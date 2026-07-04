"""
routes/search_routes.py — Job search result endpoints.

Routes:
  GET  /api/targeted_results  Scored jobs from latest targeted search
  GET  /api/recruiter_leads   Parsed recruiter form links from log file
  POST /api/assist_apply      Open visible Chrome for manual form filling
  GET  /api/workday_portals   List of known Workday company portals
"""
import ast
import json
import os
import time
import threading
import importlib

from flask import Blueprint, jsonify, request

from core.state import bot_log, TARGETED_SEARCH_RESULTS, _results_lock

search_bp = Blueprint("search", __name__)

@search_bp.route("/api/debug_active_page")
def api_debug_active_page():
    from routes.search_routes import _active_assist_drivers, _assist_lock
    with _assist_lock:
        if not _active_assist_drivers:
            return "No active driver found", 404
        driver = _active_assist_drivers[-1]
        try:
            return driver.page_source
        except Exception as e:
            return str(e), 500


@search_bp.route("/api/targeted_results")
def api_targeted_results():
    """Returns atomic snapshot under lock — no race conditions."""
    with _results_lock:
        return jsonify(list(TARGETED_SEARCH_RESULTS))


@search_bp.route("/api/recruiter_leads")
def api_recruiter_leads():
    """
    Reads recruiter_leads.json (preferred) or recruiter_leads.txt (fallback).
    Returns structured JSON with all form leads.
    """
    # Prefer new JSON format
    json_path = "logs/recruiter_leads.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                leads = json.load(f)
            return jsonify({"leads": leads[:100], "total": len(leads)})
        except Exception:
            pass

    # Fallback: parse TXT
    txt_path = "logs/recruiter_leads.txt"
    if not os.path.exists(txt_path):
        return jsonify({"leads": [], "total": 0})

    leads = []
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = {
                    p.split(":", 1)[0].strip(): p.split(":", 1)[1].strip()
                    for p in line.split("|") if ":" in p
                }
                date_str    = parts.get("Date", "")
                company_str = parts.get("Company", "")
                snippet     = parts.get("Post Text Snippet", "")
                links_raw   = parts.get("Links", "[]")
                try:
                    links_list = ast.literal_eval(links_raw)
                except Exception:
                    links_list = [links_raw] if links_raw else []

                for link in links_list:
                    leads.append({
                        "date":    date_str,
                        "company": company_str,
                        "snippet": snippet[:120],
                        "link":    link,
                        "type":    (
                            "Google Form" if "docs.google.com" in link or "forms.gle" in link
                            else "MS Form" if "forms.office.com" in link
                            else "Form"
                        ),
                        "source": "LinkedIn",
                    })
    except Exception as e:
        return jsonify({"leads": [], "total": 0, "error": str(e)})

    leads.reverse()  # Newest first
    return jsonify({"leads": leads, "total": len(leads)})


@search_bp.route("/api/workday_portals_list")
def api_workday_portals_list():
    """Returns list of known Workday company portals for the UI dropdown."""
    from scrapers.targeted_search import WORKDAY_PORTALS
    return jsonify({"portals": sorted(WORKDAY_PORTALS.keys())})


_active_assist_drivers = []
_assist_lock = threading.Lock()


@search_bp.route("/api/assist_apply", methods=["POST"])
def api_assist_apply():
    """Opens a visible (non-headless) Chrome window for manual form completion."""
    data    = request.get_json() or {}
    url     = data.get("url", "")
    company = data.get("company", "Company")
    role    = data.get("role", "Role")

    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400

    # Warn if running in non-interactive session
    import ctypes
    try:
        session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        current_session = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(
            ctypes.windll.kernel32.GetCurrentProcessId(),
            ctypes.byref(current_session)
        )
        if current_session.value == 0 and session_id != 0:
            return jsonify({"ok": False, "error": "⚠️ Server is running in a background session. Visible Chrome cannot be launched. Please stop this background process and run Start_Job_Bot_Portal.bat from your file explorer so the browser window can open on your desktop."}), 400
    except Exception:
        pass  # Not on Windows or ctypes unavailable

    def run_assist():
        # Reload configuration and modules dynamically to pick up any profile changes
        import sys
        import importlib
        import config.profile
        importlib.reload(config.profile)
        for m in ['careers_bot', 'linkedin_bot']:
            if m in sys.modules:
                try:
                    importlib.reload(sys.modules[m])
                except Exception as ex:
                    bot_log(f"[WARN] Failed to reload module {m}: {ex}")

        from browser import create_browser
        from selenium.webdriver.common.by import By
        bot_log(f"\n[ASSIST] Launching browser: {company} — {role}")

        url_lower = url.lower()
        profile_name = (
            "assist_linkedin"     if "linkedin.com" in url_lower else
            "assist_naukri"       if "naukri.com"   in url_lower else
            "assist_default"
        )
        driver = None
        try:
            driver = create_browser(headless=False, profile_name=profile_name)
            with _assist_lock:
                _active_assist_drivers.append(driver)
            
            # Setup brain context for manual assist
            brain_ctx = None
            submit_gate = None
            try:
                import config.profile
                importlib.reload(config.profile)
                resume_path = getattr(config.profile, "PROFILE", {}).get("resume_path", "")
                
                from field_resolver import QAStore
                from submit_gate import SubmitGate
                from resume_parser import parse_resume, load_cached_resume
                
                cache_path = "logs/resume_cache.json"
                parsed = load_cached_resume(cache_path)
                if parsed is None and os.path.exists(resume_path):
                    parsed = parse_resume(resume_path, cache_path=cache_path)
                    
                resume_facts = parsed.facts if parsed else {}
                resume_text = parsed.raw_text if parsed else ""
                
                qa_store = QAStore()
                submit_gate = SubmitGate()
                
                def call_gemini(system_prompt: str, user_prompt: str) -> str:
                    import google.generativeai as genai
                    import config.profile
                    importlib.reload(config.profile)
                    api_key = getattr(config.profile, "GEMINI_API_KEY", "")
                    if not api_key:
                        return "UNKNOWN"
                    prompt = f"{system_prompt}\n\nUser Question:\n{user_prompt}"
                    
                    from core.llm_cache import get_cached_response, set_cached_response
                    cached_val = get_cached_response(prompt, "gemini-2.5-flash")
                    if cached_val is not None:
                        return cached_val
                        
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel("gemini-2.5-flash")
                    response = model.generate_content(prompt)
                    text = response.text.strip()
                    set_cached_response(prompt, text, "gemini-2.5-flash")
                    return text
                    
                def ask_human_non_blocking(label: str, field_type: str, options: list) -> str:
                    from qa_store import record_unanswered
                    record_unanswered(label, portal="Workday")
                    return ""
                    
                brain_ctx = {
                    "qa_store": qa_store,
                    "resume_facts": resume_facts,
                    "resume_text": resume_text,
                    "call_llm": call_gemini,
                    "ask_human": ask_human_non_blocking
                }
                bot_log("  [ASSIST] Brain context loaded successfully for manual session.")
            except Exception as brain_ex:
                bot_log(f"  [ASSIST][WARN] Failed to load brain: {brain_ex}")
            
            driver.get(url)
            bot_log(f"  [ASSIST] Browser opened with Copilot. Navigate and use overlay buttons.")
            bot_log(f"  [ASSIST] URL: {url}")

            copilot_html = """
            if (!document.getElementById('job-bot-copilot')) {
                var div = document.createElement('div');
                div.id = 'job-bot-copilot';
                div.style.position = 'fixed';
                div.style.top = '20px';
                div.style.right = '20px';
                div.style.zIndex = '999999';
                div.style.background = 'rgba(15,23,42,0.92)';
                div.style.backdropFilter = 'blur(8px)';
                div.style.border = '1px solid rgba(255,255,255,0.15)';
                div.style.borderRadius = '12px';
                div.style.padding = '15px';
                div.style.width = '220px';
                div.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5)';
                div.style.fontFamily = 'system-ui, -apple-system, sans-serif';
                div.style.color = '#fff';
                div.style.pointerEvents = 'auto';

                div.innerHTML = `
                  <div style="font-weight:700; font-size:13px; color:#60a5fa; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                    <span>🤖 Job Bot Copilot</span>
                    <span id="copilot-badge" style="font-size:9px; background:rgba(96,165,250,0.2); padding:2px 6px; border-radius:20px; color:#93c5fd;">Active</span>
                  </div>
                  <p style="margin:0 0 10px 0; font-size:10px; color:#cbd5e1; line-height:1.4;">Click buttons to auto-fill forms on the current page step.</p>
                  <button id="copilot-btn-fill" style="width:100%; padding:8px; background:#2563eb; border:none; border-radius:6px; color:#fff; font-weight:600; font-size:11px; cursor:pointer; margin-bottom:6px; transition:all 0.2s;">⚡ Auto-Fill Fields</button>
                  <button id="copilot-btn-resume" style="width:100%; padding:8px; background:#059669; border:none; border-radius:6px; color:#fff; font-weight:600; font-size:11px; cursor:pointer; margin-bottom:6px; transition:all 0.2s;">📤 Upload Resume</button>
                  <button id="copilot-btn-next" style="width:100%; padding:8px; background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.2); border-radius:6px; color:#fff; font-weight:600; font-size:11px; cursor:pointer; transition:all 0.2s;">⏭️ Try Next Step</button>
                  <div id="copilot-status" style="margin-top:8px; font-size:9px; color:#94a3b8; text-align:center;">Idle</div>
                `;
                document.body.appendChild(div);

                window.jobBotAction = null;

                document.getElementById('copilot-btn-fill').onclick = function() {
                    window.jobBotAction = 'fill';
                    document.getElementById('copilot-status').textContent = 'Processing Fill...';
                    document.getElementById('copilot-status').style.color = '#60a5fa';
                };
                document.getElementById('copilot-btn-resume').onclick = function() {
                    window.jobBotAction = 'resume';
                    document.getElementById('copilot-status').textContent = 'Uploading Resume...';
                    document.getElementById('copilot-status').style.color = '#34d399';
                };
                document.getElementById('copilot-btn-next').onclick = function() {
                    window.jobBotAction = 'next';
                    document.getElementById('copilot-status').textContent = 'Moving Next...';
                    document.getElementById('copilot-status').style.color = '#cbd5e1';
                };
            }
            """

            js_learning_listener = """
            (function() {
                window.jobBotLearnedAnswers = window.jobBotLearnedAnswers || {};
                
                function getLabelText(el) {
                    if (el.id) {
                        var label = document.querySelector('label[for="' + el.id + '"]');
                        if (label && label.innerText.trim()) return label.innerText.trim();
                    }
                    var parentLabel = el.closest('label');
                    if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
                    
                    var prev = el.previousElementSibling;
                    if (prev && (prev.tagName === 'LABEL' || prev.tagName === 'SPAN' || prev.tagName === 'DIV')) {
                        if (prev.innerText.trim()) return prev.innerText.trim();
                    }
                    if (el.placeholder && el.placeholder.trim()) return el.placeholder.trim();
                    return el.name || el.id || '';
                }
                
                function setupListeners() {
                    var inputs = document.querySelectorAll('input, textarea, select');
                    inputs.forEach(function(input) {
                        if (input.dataset.jobBotWatched) return;
                        input.dataset.jobBotWatched = 'true';
                        
                        input.dataset.jobBotOriginalValue = input.value;
                        
                        input.addEventListener('blur', function() {
                            var label = this.getAttribute('data-bot-label') || getLabelText(this);
                            var newVal = this.type === 'checkbox' ? (this.checked ? 'yes' : 'no') : this.value;
                            if (newVal !== this.dataset.jobBotOriginalValue) {
                                window.jobBotLearnedAnswers[label] = newVal;
                                this.dataset.jobBotOriginalValue = newVal; // Avoid double learning
                            }
                        });
                    });
                }
                setupListeners();
                setInterval(setupListeners, 2000);
            })();
            """;

            while True:
                time.sleep(1)
                try:
                    # Check if browser was closed entirely
                    _ = driver.current_url
                except Exception:
                    bot_log("  [ASSIST] Browser closed by user.")
                    break

                with _assist_lock:
                    handles = list(driver.window_handles)

                triggered_action = None
                triggered_handle = None

                # Iterate through all open tabs/windows to inject overlay and scan for clicks/inputs
                for handle in handles:
                    try:
                        driver.switch_to.window(handle)
                        
                        # 1. Inject Copilot overlay and listener if missing
                        driver.execute_script(copilot_html)
                        driver.execute_script(js_learning_listener)
                        
                        # 2. Read captured learned answers from user corrections on this tab
                        learned = driver.execute_script("return window.jobBotLearnedAnswers;")
                        if learned:
                            driver.execute_script("window.jobBotLearnedAnswers = {};")
                            from qa_store import save_answer
                            for label, value in learned.items():
                                if label and value:
                                    bot_log(f"  [LEARNED] Captured user input on tab [{handle[:6]}]: '{label}' -> '{value}'")
                                    save_answer(label, value)

                        # 3. Check for button clicks on this tab
                        action = driver.execute_script("return window.jobBotAction;")
                        if action:
                            triggered_action = action
                            triggered_handle = handle
                            driver.execute_script("window.jobBotAction = null;")
                    except Exception:
                        pass

                # 4. Execute action if triggered on any tab/window
                if triggered_action and triggered_handle:
                    try:
                        driver.switch_to.window(triggered_handle)
                        
                        if triggered_action == "fill":
                            bot_log(f"  [ASSIST] Auto-Fill requested on tab [{triggered_handle[:6]}]")
                            try:
                                def fill_current_context():
                                    # Tag labels to inputs for JS listener
                                    try:
                                        driver.execute_script("""
                                            document.querySelectorAll('input, textarea, select').forEach(el => {
                                                if(!el.getAttribute('data-bot-label')) {
                                                    var label = document.querySelector('label[for="'+el.id+'"]') || el.closest('label');
                                                    if(label) el.setAttribute('data-bot-label', label.innerText.trim());
                                                }
                                            });
                                        """)
                                    except Exception:
                                        pass

                                    if "linkedin.com" in driver.current_url.lower():
                                        from linkedin_bot import answer_questions
                                        answer_questions(driver, portal="LinkedIn", log_fn=lambda m: bot_log(m, channel="bot"))
                                        return 1
                                    else:
                                        from careers_bot import (
                                            _smart_fill_standard_fields, _smart_fill_dropdowns,
                                            _smart_fill_radios, _smart_fill_checkboxes,
                                            _fill_workday_experience_blocks, _fill_workday_education_blocks,
                                            _fill_workday_languages_blocks, _fill_workday_skills_combobox,
                                            _smart_fill_remaining_unknown_fields
                                        )
                                        
                                        # Reset page metrics
                                        if submit_gate:
                                            submit_gate.reset()
                                        try:
                                            from field_resolver import clear_page_llm_cache
                                            clear_page_llm_cache()
                                        except Exception:
                                            pass
                                            
                                        fields = _smart_fill_standard_fields(driver, driver.current_url, company) or 0
                                        
                                        # Workday block fillers
                                        blocks_filled = 0
                                        if "workday" in driver.current_url.lower() or "myworkdayjobs" in driver.current_url.lower():
                                            import config.profile
                                            importlib.reload(config.profile)
                                            blocks_filled += _fill_workday_experience_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate) or 0
                                            blocks_filled += _fill_workday_education_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate) or 0
                                            blocks_filled += _fill_workday_languages_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate) or 0
                                            blocks_filled += _fill_workday_skills_combobox(driver, config.profile.PROFILE, brain_ctx, submit_gate) or 0
                                            
                                        dropdowns = _smart_fill_dropdowns(driver) or 0
                                        radios = _smart_fill_radios(driver) or 0
                                        checkboxes = _smart_fill_checkboxes(driver) or 0
                                        
                                        # Unknown batch resolved
                                        ai_filled = _smart_fill_remaining_unknown_fields(driver, brain_ctx, submit_gate) or 0
                                        
                                        return fields + blocks_filled + dropdowns + radios + checkboxes + ai_filled

                                # Fill default window
                                tot = fill_current_context() or 0
                                
                                # Traverse and fill all visible iframes
                                iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
                                for idx, iframe in enumerate(iframes):
                                    try:
                                        if iframe.is_displayed():
                                            driver.switch_to.frame(iframe)
                                            tot += fill_current_context() or 0
                                            driver.switch_to.default_content()
                                    except Exception as iframe_ex:
                                        try:
                                            driver.switch_to.default_content()
                                        except Exception:
                                            pass
                                
                                # Escalation warning highlight for low-confidence empty fields
                                try:
                                    driver.execute_script("""
                                        var missing = [];
                                        document.querySelectorAll('input[type="text"], input[type="number"], textarea, select').forEach(el => {
                                            if (el.required && !el.value && el.offsetWidth > 0 && el.offsetHeight > 0) {
                                                el.style.border = '2px solid #eab308';
                                                el.style.backgroundColor = 'rgba(234, 179, 8, 0.05)';
                                                var lbl = el.getAttribute('data-bot-label') || el.placeholder || el.name || 'unlabelled field';
                                                missing.push(lbl);
                                            }
                                        });
                                        if (missing.length > 0) {
                                            document.getElementById('copilot-status').textContent = '⚠️ Need help with: ' + missing.slice(0,2).join(', ');
                                            document.getElementById('copilot-status').style.color = '#eab308';
                                        } else {
                                            document.getElementById('copilot-status').textContent = 'Auto-filled standard fields!';
                                            document.getElementById('copilot-status').style.color = '#34d399';
                                        }
                                    """)
                                except Exception:
                                    pass

                                bot_log(f"  [ASSIST] Auto-filled {tot} fields across window and frames on tab [{triggered_handle[:6]}]!")
                            except Exception as fill_err:
                                bot_log(f"  [WARN] Auto-Fill action failed: {fill_err}")
                                try:
                                    driver.execute_script(f"document.getElementById('copilot-status').textContent = 'Error: {str(fill_err)[:30]}';")
                                    driver.execute_script("document.getElementById('copilot-status').style.color = '#f87171';")
                                except Exception:
                                    pass

                        elif triggered_action == "resume":
                            bot_log(f"  [ASSIST] Resume Upload requested via Copilot on tab [{triggered_handle[:6]}]")
                            try:
                                import config.profile
                                importlib.reload(config.profile)
                                resume_path = getattr(config.profile, "PROFILE", {}).get("resume_path", "")

                                if resume_path and os.path.exists(resume_path):
                                    from careers_bot import _upload_resume
                                    success = _upload_resume(driver, resume_path)
                                    
                                    # Try iframes if default context failed
                                    if not success:
                                        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
                                        for idx, iframe in enumerate(iframes):
                                            try:
                                                if iframe.is_displayed():
                                                    driver.switch_to.frame(iframe)
                                                    success = _upload_resume(driver, resume_path)
                                                    driver.switch_to.default_content()
                                                    if success:
                                                        break
                                            except Exception:
                                                try:
                                                    driver.switch_to.default_content()
                                                except Exception:
                                                    pass

                                    if success:
                                        msg = "Resume uploaded!"
                                        bot_log(f"  [ASSIST] {msg}")
                                        driver.execute_script(f"document.getElementById('copilot-status').textContent = '{msg}';")
                                        driver.execute_script("document.getElementById('copilot-status').style.color = '#34d399';")
                                    else:
                                        msg = "Upload failed."
                                        bot_log(f"  [ASSIST] {msg}")
                                        driver.execute_script(f"document.getElementById('copilot-status').textContent = '{msg}';")
                                        driver.execute_script("document.getElementById('copilot-status').style.color = '#f87171';")
                                else:
                                    msg = "Resume file not found!"
                                    bot_log(f"  [ASSIST] {msg}")
                                    driver.execute_script(f"document.getElementById('copilot-status').textContent = '{msg}';")
                                    driver.execute_script("document.getElementById('copilot-status').style.color = '#f87171';")
                            except Exception as resume_err:
                                bot_log(f"  [WARN] Resume Upload failed: {resume_err}")
                                try:
                                    driver.execute_script(f"document.getElementById('copilot-status').textContent = 'Error: {str(resume_err)[:30]}';")
                                    driver.execute_script("document.getElementById('copilot-status').style.color = '#f87171';")
                                except Exception:
                                    pass

                        elif triggered_action == "next":
                            bot_log(f"  [ASSIST] Next Step requested via Copilot on tab [{triggered_handle[:6]}]")
                            try:
                                from careers_bot import _click_next_or_submit
                                res = _click_next_or_submit(driver)
                                
                                # Try iframes if default context failed
                                if not res:
                                    iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
                                    for idx, iframe in enumerate(iframes):
                                        try:
                                            if iframe.is_displayed():
                                                driver.switch_to.frame(iframe)
                                                res = _click_next_or_submit(driver)
                                                driver.switch_to.default_content()
                                                if res:
                                                    break
                                        except Exception:
                                            try:
                                                driver.switch_to.default_content()
                                            except Exception:
                                                pass

                                msg = f"Action: {res}"
                                bot_log(f"  [ASSIST] {msg}")
                                driver.execute_script(f"document.getElementById('copilot-status').textContent = '{msg}';")
                                driver.execute_script("document.getElementById('copilot-status').style.color = '#93c5fd';")
                            except Exception as next_err:
                                bot_log(f"  [WARN] Next action failed: {next_err}")
                                try:
                                    driver.execute_script(f"document.getElementById('copilot-status').textContent = 'Error: {str(next_err)[:30]}';")
                                    driver.execute_script("document.getElementById('copilot-status').style.color = '#f87171';")
                                except Exception:
                                    pass
                    except Exception as ex:
                        bot_log(f"  [WARN] Copilot action execution failed on tab [{triggered_handle[:6]}]: {ex}")

        except Exception as e:
            bot_log(f"  [ERROR] Assist failed: {e}")
        finally:
            with _assist_lock:
                if driver in _active_assist_drivers:
                    _active_assist_drivers.remove(driver)
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    threading.Thread(target=run_assist, daemon=True).start()
    return jsonify({"ok": True, "message": "Manual Assist session started — check your taskbar."})


@search_bp.route("/api/search_profiles", methods=["GET", "POST"])
def api_search_profiles():
    profiles_path = "logs/search_profiles.json"
    if request.method == "GET":
        if not os.path.exists(profiles_path):
            return jsonify({})
        try:
            with open(profiles_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # POST - save or delete
    try:
        data = request.get_json() or {}
        action = data.get("action")
        name = data.get("name")
        if not name:
            return jsonify({"error": "Profile name required"}), 400

        profiles = {}
        if os.path.exists(profiles_path):
            try:
                with open(profiles_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                pass

        if action == "save":
            profile_data = data.get("profile", {})
            profiles[name] = profile_data
        elif action == "delete":
            if name in profiles:
                del profiles[name]
        else:
            return jsonify({"error": f"Invalid action: {action}"}), 400

        with open(profiles_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@search_bp.route("/api/generate_outreach", methods=["POST"])
def api_generate_outreach():
    """Generates a professional, personalized recruiter outreach message using Gemini."""
    data = request.get_json() or {}
    company = data.get("company", "")
    role = data.get("role", "")
    snippet = data.get("snippet", "")

    import importlib
    import config.profile
    importlib.reload(config.profile)

    api_key = getattr(config.profile, "GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "Gemini API Key is missing. Please add it in Settings."}), 400

    profile = getattr(config.profile, "PROFILE", {})
    skills = getattr(config.profile, "MY_SKILLS", [])

    first_name = profile.get("first_name", "Pratik")
    last_name = profile.get("last_name", "Pawar")
    email = profile.get("email", "")
    phone = profile.get("phone", "")
    total_exp = profile.get("total_experience_years", "4.6")

    prompt = f"""You are an expert career advisor. Draft a highly personalized, compelling, and professional cold outreach message (for LinkedIn or email) to a recruiter/hiring manager at {company} for the role of "{role}".

Candidate Info:
- Name: {first_name} {last_name}
- Email: {email}
- Phone: {phone}
- Experience: {total_exp} years
- Key Skills: {', '.join(skills[:8])}

Target Job Details:
- Company: {company}
- Position: {role}
- Job Snippet: {snippet}

Draft a message that:
1. Is extremely concise (under 150 words).
2. Explains briefly how the candidate's skills directly map to this role.
3. Ends with a clear call to action (e.g. requesting a brief chat).

Respond ONLY with a JSON block in this exact schema, without markdown formatting:
{{
  "subject": "Clear, professional email subject line",
  "message": "The complete personalized outreach message"
}}
"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Clean up code blocks if any
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```json"):
                text = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                text = "\n".join(lines[1:-1])

        res_data = json.loads(text.strip())
        return jsonify({
            "ok": True,
            "subject": res_data.get("subject", f"Interested in {role} at {company}"),
            "message": res_data.get("message", "")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

