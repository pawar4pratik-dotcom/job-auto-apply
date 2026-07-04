import os
import json
import importlib
import google.generativeai as genai
import config.profile

BLACKLISTED_MODELS = set()
_gemini_quota_exhausted = False

from selenium.webdriver.common.by import By
import time

def ask_user_via_overlay(driver, question: str, timeout_s: int = 30) -> str:
    """
    Injects an interactive HTML modal directly into the active webpage DOM,
    polling for a user response for up to timeout_s seconds.
    """
    try:
        import json
        safe_q = json.dumps(question)
        
        inject_js = f"""
        (function() {{
            var existing = document.getElementById('job-bot-prompt-modal');
            if (existing) existing.remove();

            var container = document.createElement('div');
            container.id = 'job-bot-prompt-modal';
            container.style.position = 'fixed';
            container.style.top = '12%';
            container.style.right = '20px';
            container.style.width = '360px';
            container.style.zIndex = '2147483647';
            container.style.background = '#1e1e24';
            container.style.color = '#ffffff';
            container.style.padding = '18px';
            container.style.borderRadius = '10px';
            container.style.boxShadow = '0 6px 20px rgba(0, 0, 0, 0.4)';
            container.style.border = '1px solid #33333d';
            container.style.fontFamily = 'system-ui, -apple-system, sans-serif';

            var title = document.createElement('div');
            title.textContent = '🤖 JOB BOT: QUESTION DETECTED';
            title.style.fontWeight = 'bold';
            title.style.fontSize = '13px';
            title.style.marginBottom = '10px';
            title.style.color = '#4facfe';
            container.appendChild(title);

            var questionText = document.createElement('div');
            questionText.textContent = {safe_q};
            questionText.style.fontSize = '12px';
            questionText.style.marginBottom = '12px';
            questionText.style.lineHeight = '1.4';
            questionText.style.color = '#e0e0e0';
            container.appendChild(questionText);

            var input = document.createElement('input');
            input.type = 'text';
            input.placeholder = 'Type your answer here...';
            input.style.width = '100%';
            input.style.padding = '8px';
            input.style.borderRadius = '4px';
            input.style.border = '1px solid #444';
            input.style.background = '#000';
            input.style.color = '#fff';
            input.style.fontSize = '12px';
            input.style.boxSizing = 'border-box';
            input.style.marginBottom = '12px';
            input.style.outline = 'none';
            container.appendChild(input);

            var buttonContainer = document.createElement('div');
            buttonContainer.style.display = 'flex';
            buttonContainer.style.justifyContent = 'flex-end';
            buttonContainer.style.gap = '8px';

            var skipBtn = document.createElement('button');
            skipBtn.textContent = 'Skip';
            skipBtn.style.padding = '6px 12px';
            skipBtn.style.borderRadius = '4px';
            skipBtn.style.border = 'none';
            skipBtn.style.background = '#333';
            skipBtn.style.color = '#ccc';
            skipBtn.style.cursor = 'pointer';
            skipBtn.style.fontSize = '11px';
            skipBtn.onclick = function() {{
                container.setAttribute('data-answer', '__CANCEL__');
            }};
            buttonContainer.appendChild(skipBtn);

            var submitBtn = document.createElement('button');
            submitBtn.textContent = 'Submit';
            submitBtn.style.padding = '6px 12px';
            submitBtn.style.borderRadius = '4px';
            submitBtn.style.border = 'none';
            submitBtn.style.background = '#4facfe';
            submitBtn.style.color = '#fff';
            submitBtn.style.cursor = 'pointer';
            submitBtn.style.fontSize = '11px';
            submitBtn.style.fontWeight = 'bold';
            submitBtn.onclick = function() {{
                container.setAttribute('data-answer', input.value || '__EMPTY__');
            }};
            buttonContainer.appendChild(submitBtn);

            container.appendChild(buttonContainer);
            document.body.appendChild(container);

            input.focus();
        }})();
        """
        driver.execute_script(inject_js)
        
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            try:
                modal = driver.find_element(By.ID, "job-bot-prompt-modal")
                ans = modal.get_attribute("data-answer")
                if ans:
                    driver.execute_script("var m = document.getElementById('job-bot-prompt-modal'); if (m) m.remove();")
                    if ans == "__CANCEL__":
                        return ""
                    if ans == "__EMPTY__":
                        return ""
                    return ans
            except Exception:
                break
            time.sleep(1.0)
            
        try:
            driver.execute_script("var m = document.getElementById('job-bot-prompt-modal'); if (m) m.remove();")
        except Exception:
            pass
    except Exception as e:
        print(f"[SEMANTIC QA][OVERLAY][ERROR] {e}")
    return ""


def resolve_semantic_answer(question: str, portal: str = "", driver = None) -> str:
    """
    Uses a local similarity matcher or Gemini to match questions against the QA store,
    or generate a precise answer based on the profile.
    """
    if not question or not question.strip():
        return ""

    try:
        # Load Q&A store library
        from qa_store import get_all
        all_qa = get_all()
        answered_library = [
            {"q": item["question"], "a": item["answer"]}
            for item in all_qa if item.get("answered") and item.get("answer")
        ]

        # ── Local Semantic Jaccard Matcher ──
        STOP_WORDS = {"how", "many", "do", "you", "have", "the", "a", "an", "is", "are", "what", "your", "of", "to", "in", "for", "and", "or", "with"}
        def get_tokens(text: str):
            import re
            text = text.lower().strip()
            text = re.sub(r'[^\w\s]', '', text)
            tokens = set(text.split())
            return tokens - STOP_WORDS

        q_tokens = get_tokens(question)
        if q_tokens:
            best_match = None
            best_score = 0.0
            for item in answered_library:
                cached_q = item.get("q", "")
                cached_tokens = get_tokens(cached_q)
                if not cached_tokens:
                    continue
                intersection = q_tokens.intersection(cached_tokens)
                union = q_tokens.union(cached_tokens)
                score = len(intersection) / float(len(union))
                if score > best_score:
                    best_score = score
                    best_match = item.get("a", "")
            if best_score >= 0.65:
                print(f"[SEMANTIC QA][LOCAL] High-confidence match (Jaccard: {best_score:.2f}) -> '{best_match}'")
                return str(best_match).strip()

        global _gemini_quota_exhausted
        if _gemini_quota_exhausted:
            return ""

        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return ""

        # Load profile configurations
        profile = getattr(config.profile, "PROFILE", {})
        skills = getattr(config.profile, "MY_SKILLS", [])
        tech_exp = getattr(config.profile, "TECH_EXPERIENCE", {})
        work_prefs = getattr(config.profile, "WORK_PREFERENCES", {})

        # Format profile data for prompt
        profile_text = json.dumps(profile, indent=2)
        tech_exp_text = json.dumps({
            "skills_list": skills,
            "skills_experience_years": tech_exp
        }, indent=2)
        work_prefs_text = json.dumps(work_prefs, indent=2)
        qa_library_text = json.dumps(answered_library, indent=2)

        prompt = f"""You are an AI assistant helping a job candidate auto-fill job application forms.
Here is the candidate's Profile Details:
{profile_text}

Here is the candidate's Technical Skills and Experience (in years):
{tech_exp_text}

Here are the candidate's Work Preferences:
{work_prefs_text}

Here is a list of previously answered questions for context:
{qa_library_text}

New Question: "{question}"
Portal context: "{portal}"

Your task:
Can you answer this question accurately on behalf of the candidate?
1. Try to match it to a previously answered question in the library. If there is a semantic match (e.g. "Do you have experience with PySpark?" vs "Do you know PySpark?"), reuse that answer exactly.
2. If there is no semantic match in the library, try to answer it using the candidate's profile, technical experience, and work preferences.
   - If asked about years of experience with a skill NOT listed in the skills list, the answer is "0" (e.g. "years of experience with palantir" -> "0" because Palantir is not listed). Do NOT guess a non-zero value.
   - If asked about commuting comfortability or hybrid work, refer to work preferences (e.g. "preferred_work_mode": "Hybrid", "open_to_relocation": true, so commuting/relocation comfort is "Yes").
3. If the question requires highly specific custom input, personal statement, or portal-specific essay that cannot be derived from the profile, set "confident" to false.

Respond ONLY with a JSON block in this exact schema, without markdown formatting:
{{
  "confident": true,
  "answer": "the answer string or yes/no/number",
  "reason": "short explanation of how you derived the answer"
}}
"""

        # Cache lookup using the full prompt text (automatically invalidates if profile/QA store changes)
        from core.llm_cache import get_cached_response, set_cached_response
        cached_val = get_cached_response(prompt, "gemini-2.5-flash")
        if cached_val is not None:
            text = cached_val
        else:
            genai.configure(api_key=api_key)
            import time
            global BLACKLISTED_MODELS
            models_to_try = [m for m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest", "gemini-pro-latest"] if m not in BLACKLISTED_MODELS]
            if not models_to_try:
                # If all models are rate-limited, clear blacklist to allow retry fallbacks
                BLACKLISTED_MODELS.clear()
                models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-flash-latest", "gemini-pro-latest"]

            text = ""
            for model_name in models_to_try:
                retries = 2
                backoff = 1.5
                for attempt in range(retries):
                    try:
                        model = genai.GenerativeModel(model_name)
                        response = model.generate_content(prompt)
                        text = response.text.strip()
                        set_cached_response(prompt, text, "gemini-2.5-flash")
                        break
                    except Exception as e:
                        err_msg = str(e)
                        if "429" in err_msg or "quota" in err_msg.lower() or "resourceexhausted" in err_msg.lower() or "rate" in err_msg.lower():
                            if "quota" in err_msg.lower() or "limit exceeded" in err_msg.lower() or "daily" in err_msg.lower():
                                print(f"  [SEMANTIC QA][WARN] Gemini daily/quota limit hit. Disabling Gemini for this session to run fast.")
                                global _gemini_quota_exhausted
                                _gemini_quota_exhausted = True
                                break
                            if attempt < retries - 1:
                                sleep_time = backoff ** (attempt + 1) + 1
                                print(f"  [SEMANTIC QA][WARN] Model {model_name} rate-limited. Retrying in {sleep_time}s... (Attempt {attempt+1}/{retries})")
                                time.sleep(sleep_time)
                                continue
                            else:
                                print(f"  [SEMANTIC QA][WARN] Model {model_name} exhausted. Blacklisting model for this run...")
                                BLACKLISTED_MODELS.add(model_name)
                                break
                        raise e
                if text:
                    break
            if not text:
                raise Exception("All Gemini models exhausted or rate-limited in Semantic QA.")
        
        # Clean up any potential markdown code blocks and extract JSON
        import re
        json_match = re.search(r'\{.*\}', text.strip(), re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if data.get("confident") and data.get("answer") is not None:
                    ans = str(data["answer"]).strip()
                    print(f"[SEMANTIC QA] Resolved '{question}' -> '{ans}' ({data.get('reason')})")
                    return ans
            except Exception as json_err:
                print(f"[SEMANTIC QA][WARN] JSON parsing failed: {json_err}. Text was: {text}")
    except Exception as e:
        print(f"[SEMANTIC QA][WARN] Gemini resolution failed: {e}")
        
    # Injected HTML modal prompt fallback
    if driver:
        user_ans = ask_user_via_overlay(driver, question)
        if user_ans:
            print(f"[SEMANTIC QA][OVERLAY] User provided answer: '{user_ans}'")
            try:
                from qa_store import save_answer
                save_answer(question, user_ans)
            except Exception as ex:
                print(f"[SEMANTIC QA][OVERLAY] Failed to auto-save answer to store: {ex}")
            return user_ans

    return ""
