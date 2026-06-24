import os
import json
import importlib
import google.generativeai as genai
import config.profile

def resolve_semantic_answer(question: str, portal: str = "") -> str:
    """
    Uses Gemini to semantically match a question against the answered QA store,
    or generate a precise answer based on the candidate's profile.
    Returns the answered string if confident, otherwise empty string.
    """
    if not question or not question.strip():
        return ""

    try:
        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return ""

        # Load Q&A store library
        from qa_store import get_all
        all_qa = get_all()
        answered_library = [
            {"q": item["question"], "a": item["answer"]}
            for item in all_qa if item.get("answered") and item.get("answer")
        ]

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

        genai.configure(api_key=api_key)
        # Use gemini-2.5-flash or fallback
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Clean up any potential markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```json"):
                text = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                text = "\n".join(lines[1:-1])
        
        data = json.loads(text.strip())
        if data.get("confident") and data.get("answer") is not None:
            ans = str(data["answer"]).strip()
            print(f"[SEMANTIC QA] Resolved '{question}' -> '{ans}' ({data.get('reason')})")
            return ans
    except Exception as e:
        print(f"[SEMANTIC QA][WARN] Gemini resolution failed: {e}")
        
    return ""
