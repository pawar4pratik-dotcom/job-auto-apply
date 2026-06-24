"""
routes/profile_routes.py — User profile and settings management.

Routes:
  GET/POST /api/profile              Read/write config/profile.py
  GET      /api/notifications        Company credential suggestions (BUG7-FIX: 30s TTL cache)
  POST     /api/company-credentials  Add company login credentials
  POST     /api/company-credentials/delete  Remove company credentials
"""
import csv
import importlib
import json
import os
import time

import config.profile
import config.secrets
from flask import Blueprint, jsonify, request

from core.state import _notifications_cache, _NOTIF_CACHE_TTL

profile_bp = Blueprint("profile", __name__)

_PROFILE_PATH = "config/profile.py"


@profile_bp.route("/api/profile", methods=["GET", "POST"])
def api_profile_settings():
    if request.method == "GET":
        try:
            importlib.reload(config.profile)
            from config.profile import (
                PROFILE, MY_SKILLS, SEARCH_KEYWORDS, SEARCH_LOCATIONS,
                TARGET_COMPANIES, COVER_LETTER, MIN_MATCH_SCORE, DAILY_LIMIT,
            )
            return jsonify({
                "profile":              PROFILE,
                "skills":               MY_SKILLS,
                "keywords":             SEARCH_KEYWORDS,
                "locations":            SEARCH_LOCATIONS,
                "companies":            TARGET_COMPANIES,
                "cover_letter":         COVER_LETTER,
                "min_match_score":      MIN_MATCH_SCORE,
                "daily_limit":          DAILY_LIMIT,
                "company_credentials":  getattr(config.profile, "COMPANY_CREDENTIALS", {}),
                "tech_experience":      getattr(config.profile, "TECH_EXPERIENCE", {}),
                "gemini_api_key":       getattr(config.profile, "GEMINI_API_KEY", ""),
                "auto_threshold":       getattr(config.profile, "AUTO_THRESHOLD", 75),
                "review_threshold":     getattr(config.profile, "REVIEW_THRESHOLD", 55),
                "imap_host":            getattr(config.profile, "IMAP_HOST", "imap.gmail.com"),
                "imap_email":           getattr(config.profile, "IMAP_EMAIL", ""),
                "imap_password":        getattr(config.profile, "IMAP_PASSWORD", ""),
                "telegram_bot_token":   getattr(config.profile, "TELEGRAM_BOT_TOKEN", ""),
                "telegram_chat_id":     getattr(config.profile, "TELEGRAM_CHAT_ID", ""),
                "notification_channels": getattr(config.profile, "NOTIFICATION_CHANNELS", ["email"]),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # POST — write new profile.py
    try:
        data = request.get_json() or {}
        profile_dict    = data.get("profile", {})
        skills_list     = data.get("skills", [])
        keywords_list   = data.get("keywords", [])
        locations_list  = data.get("locations", [])
        companies_list  = data.get("companies", [])
        cover_letter    = data.get("cover_letter", "")
        daily_limit     = int(data.get("daily_limit", 50))
        min_match_score = int(data.get("min_match_score", 30))
        auto_threshold  = int(data.get("auto_threshold", 75))
        review_threshold = int(data.get("review_threshold", 55))
        tech_experience_dict = data.get("tech_experience", {})
        gemini_api_key  = data.get("gemini_api_key", "")
        imap_host       = data.get("imap_host", "imap.gmail.com")
        imap_email      = data.get("imap_email", "")
        imap_password   = data.get("imap_password", "")
        telegram_bot_token = data.get("telegram_bot_token", "")
        telegram_chat_id   = data.get("telegram_chat_id", "")
        notification_channels = data.get("notification_channels", ["email"])

        # Update .env file with secrets
        env_updates = {
            "GEMINI_API_KEY": gemini_api_key,
            "LINKEDIN_EMAIL": profile_dict.get("linkedin_email", ""),
            "LINKEDIN_PASSWORD": profile_dict.get("linkedin_password", ""),
            "NAUKRI_EMAIL": profile_dict.get("naukri_email", ""),
            "NAUKRI_PASSWORD": profile_dict.get("naukri_password", ""),
            "IMAP_EMAIL": imap_email,
            "IMAP_PASSWORD": imap_password,
            "CORP_EMAIL": profile_dict.get("corp_email", ""),
            "CORP_PASSWORD": profile_dict.get("corp_password", ""),
            "TELEGRAM_BOT_TOKEN": telegram_bot_token,
            "TELEGRAM_CHAT_ID": telegram_chat_id
        }
        _update_env_file(env_updates)

        # Reload secrets to pick up changes
        importlib.reload(config.secrets)
        importlib.reload(config.profile)

        company_credentials_dict = data.get("company_credentials") or getattr(config.profile, "COMPANY_CREDENTIALS", {})

        # ISSUE15-FIX: Preserve WORK_PREFERENCES/SCHEDULED_RUNS from current profile
        current_work_prefs = getattr(config.profile, "WORK_PREFERENCES", {
            "preferred_work_mode": "Hybrid", "open_to_relocation": True,
            "authorized_india": True, "require_sponsorship": False, "gender": "Prefer not to say",
        })
        current_scheduled_runs = getattr(config.profile, "SCHEDULED_RUNS", ["09:00", "14:00", "19:00"])
        current_headless       = getattr(config.profile, "HEADLESS_DEFAULT", True)
        current_per_run        = getattr(config.profile, "PER_RUN_LIMIT", 15)

        tech_exp = {
            skill.lower(): tech_experience_dict.get(skill.lower(), profile_dict.get("total_experience_years", "5"))
            for skill in skills_list
        }

        # Generate profile.py content with secrets references
        content = _generate_profile_file_content(
            company_credentials_dict, profile_dict, skills_list, tech_exp,
            current_work_prefs, daily_limit, current_per_run, current_scheduled_runs,
            current_headless, min_match_score, auto_threshold, review_threshold,
            keywords_list, locations_list, companies_list, cover_letter, imap_host,
            notification_channels
        )

        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        content += f"\nACTIVE_PROFILE_NAME = {repr(active_profile)}\n"

        with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        importlib.reload(config.profile)

        # Invalidate notifications cache after profile save
        global _notifications_cache
        _notifications_cache.update({"data": [], "ts": 0})

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@profile_bp.route("/api/notifications")
def api_notifications():
    """
    BUG7-FIX: 30-second TTL cache — no CSV scan on every 10s poll.
    Only re-scans when cache expires or profile is saved.
    """
    global _notifications_cache
    now = time.time()
    if now - _notifications_cache["ts"] < _NOTIF_CACHE_TTL:
        return jsonify({"notifications": _notifications_cache["data"]})

    try:
        importlib.reload(config.profile)
        company_creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
        csv_path = "logs/job_applications.csv"

        if not os.path.exists(csv_path):
            _notifications_cache.update({"data": [], "ts": now})
            return jsonify({"notifications": []})

        skipped_groups: dict = {}
        with open(csv_path, mode="r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                status    = row.get("Status")
                comp      = row.get("Company") or ""
                score_raw = row.get("Match %") or "0%"
                role      = row.get("Role") or "Unknown"
                url       = row.get("URL") or ""
                try:
                    score = float(score_raw.replace("%", "").strip())
                except ValueError:
                    score = 0
                if status in ("Manual Needed", "Skipped") and score >= 20 and comp:
                    k = comp.strip()
                    if k not in skipped_groups:
                        skipped_groups[k] = {"count": 0, "roles": set(), "urls": []}
                    skipped_groups[k]["count"] += 1
                    skipped_groups[k]["roles"].add(role.strip())
                    skipped_groups[k]["urls"].append(url)

        from careers_bot import detect_platform
        notifications = []
        for comp_name, group in skipped_groups.items():
            if group["count"] >= 2:
                has_creds = any(
                    c.lower() in comp_name.lower() or comp_name.lower() in c.lower()
                    for c in company_creds
                )
                if not has_creds:
                    platform = "unknown"
                    requires_login = False
                    if group["urls"]:
                        platform = detect_platform(group["urls"][0])
                        requires_login = platform in ("workday", "icims", "taleo", "successfactors")

                    roles_str = ", ".join(list(group["roles"])[:3]) + ("..." if len(group["roles"]) > 3 else "")
                    if requires_login:
                        msg = (f"<strong>{comp_name}</strong> has {group['count']} high-match jobs "
                               f"({roles_str}) on {platform.upper()} — login credentials needed.")
                    elif platform in ("greenhouse", "lever", "smartrecruiters"):
                        msg = (f"<strong>{comp_name}</strong> has {group['count']} jobs ({roles_str}) "
                               f"on {platform.upper()} — bot can apply without credentials!")
                    else:
                        msg = (f"<strong>{comp_name}</strong> has {group['count']} stalled jobs "
                               f"({roles_str}). Try Assist mode or add credentials.")

                    notifications.append({
                        "company": comp_name, "count": group["count"],
                        "roles": list(group["roles"])[:3], "message": msg,
                    })

        _notifications_cache.update({"data": notifications, "ts": now})
        return jsonify({"notifications": notifications})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/company-credentials", methods=["POST"])
def api_company_credentials():
    try:
        data     = request.get_json() or {}
        comp     = data.get("company", "").strip()
        email    = data.get("email", "").strip()
        password = data.get("password", "").strip()
        if not comp or not email:
            return jsonify({"ok": False, "error": "company and email required"}), 400

        importlib.reload(config.profile)
        creds = dict(getattr(config.profile, "COMPANY_CREDENTIALS", {}))
        creds[comp] = {"email": email, "password": password}

        _patch_credentials(creds)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/company-credentials/delete", methods=["POST"])
def api_company_credentials_delete():
    try:
        data = request.get_json() or {}
        comp = data.get("company", "").strip()
        if not comp:
            return jsonify({"ok": False, "error": "company required"}), 400

        importlib.reload(config.profile)
        creds = dict(getattr(config.profile, "COMPANY_CREDENTIALS", {}))
        creds.pop(comp, None)
        _patch_credentials(creds)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _update_env_file(updates: dict):
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Error reading .env: {e}")
    
    env_data = {}
    for line in lines:
        line_str = line.strip()
        if line_str and not line_str.startswith("#") and "=" in line_str:
            k, v = line_str.split("=", 1)
            env_data[k.strip()] = v.strip()
            
    for k, v in updates.items():
        env_data[k] = str(v)
        
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in env_data.items():
                f.write(f"{k}={v}\n")
    except Exception as e:
        print(f"Error writing .env: {e}")

def _generate_profile_file_content(company_creds, profile_dict, skills_list, tech_exp, work_prefs, daily_limit, per_run, scheduled_runs, headless, min_match_score, auto_th, rev_th, keywords_list, locations_list, companies_list, cover_letter, imap_h, notif_channels=None):
    # Filter secret keys out of profile_dict to prevent them from being dumped in the file
    profile_non_secret = {k: v for k, v in profile_dict.items() if k not in [
        "linkedin_email", "linkedin_password", "naukri_email", "naukri_password",
        "corp_email", "corp_password", "imap_email", "imap_password"
    ]}
    
    # Format the PROFILE dict as python code referencing config.secrets
    profile_lines = []
    for k, v in profile_non_secret.items():
        profile_lines.append(f"    {repr(k)}: {repr(v)},")
    profile_lines.append("    'linkedin_email': config.secrets.LINKEDIN_EMAIL,")
    profile_lines.append("    'linkedin_password': config.secrets.LINKEDIN_PASSWORD,")
    profile_lines.append("    'naukri_email': config.secrets.NAUKRI_EMAIL,")
    profile_lines.append("    'naukri_password': config.secrets.NAUKRI_PASSWORD,")
    profile_lines.append("    'corp_email': config.secrets.CORP_EMAIL,")
    profile_lines.append("    'corp_password': config.secrets.CORP_PASSWORD,")
    profile_lines.append("    'imap_email': config.secrets.IMAP_EMAIL,")
    profile_lines.append("    'imap_password': config.secrets.IMAP_PASSWORD,")
    
    profile_str = "{\n" + "\n".join(profile_lines) + "\n}"
    if notif_channels is None:
        notif_channels = ["email"]
    
    return f"""# Auto-generated by Job Bot Portal — do not edit manually
import config.secrets

COMPANY_CREDENTIALS = {repr(company_creds)}
PROFILE = {profile_str}

MY_SKILLS = {repr(skills_list)}
TECH_EXPERIENCE = {repr(tech_exp)}
WORK_PREFERENCES = {repr(work_prefs)}

DAILY_LIMIT        = {daily_limit}
PER_RUN_LIMIT      = {per_run}
SCHEDULED_RUNS     = {repr(scheduled_runs)}
HEADLESS_DEFAULT   = {headless}

MIN_MATCH_SCORE  = {min_match_score}
AUTO_THRESHOLD   = {auto_th}
REVIEW_THRESHOLD = {rev_th}

SEARCH_KEYWORDS  = {repr(keywords_list)}
SEARCH_LOCATIONS = {repr(locations_list)}
TARGET_COMPANIES = {repr(companies_list)}

COVER_LETTER = {repr(cover_letter.strip())}

GEMINI_API_KEY = config.secrets.GEMINI_API_KEY
IMAP_HOST      = {repr(imap_h)}
IMAP_EMAIL     = config.secrets.IMAP_EMAIL
IMAP_PASSWORD  = config.secrets.IMAP_PASSWORD

TELEGRAM_BOT_TOKEN = getattr(config.secrets, "TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = getattr(config.secrets, "TELEGRAM_CHAT_ID", "")
NOTIFICATION_CHANNELS = {repr(notif_channels)}
"""

def _patch_credentials(new_creds: dict):
    """Patch only the COMPANY_CREDENTIALS line in profile.py (safe in-place update)."""
    importlib.reload(config.profile)
    from config.profile import (
        PROFILE, MY_SKILLS, TECH_EXPERIENCE, WORK_PREFERENCES,
        DAILY_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT, PER_RUN_LIMIT,
        MIN_MATCH_SCORE, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES,
        COVER_LETTER,
    )
    auto_th  = getattr(config.profile, "AUTO_THRESHOLD", 75)
    rev_th   = getattr(config.profile, "REVIEW_THRESHOLD", 55)
    imap_h   = getattr(config.profile, "IMAP_HOST", "imap.gmail.com")
    notif_ch = getattr(config.profile, "NOTIFICATION_CHANNELS", ["email"])

    content = _generate_profile_file_content(
        new_creds, PROFILE, MY_SKILLS, TECH_EXPERIENCE, WORK_PREFERENCES,
        DAILY_LIMIT, PER_RUN_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT,
        MIN_MATCH_SCORE, auto_th, rev_th, SEARCH_KEYWORDS, SEARCH_LOCATIONS,
        TARGET_COMPANIES, COVER_LETTER, imap_h, notif_ch
    )
    active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
    content += f"\nACTIVE_PROFILE_NAME = {repr(active_profile)}\n"

    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    importlib.reload(config.profile)


# ── Profiles Management APIs (JobBot v4.0) ──────────────────────────────────
_PROFILES_DIR = "config/profiles"
_RESUMES_DIR = os.path.join(_PROFILES_DIR, "resumes")
os.makedirs(_PROFILES_DIR, exist_ok=True)
os.makedirs(_RESUMES_DIR, exist_ok=True)

@profile_bp.route("/api/profiles/upload-resume", methods=["POST"])
def upload_resume():
    """Upload a PDF resume, parse it, and return its absolute path plus candidate info."""
    try:
        if 'resume' not in request.files:
            return jsonify({"error": "No resume file in request"}), 400
            
        file = request.files['resume']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400
            
        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "Only PDF files are allowed"}), 400
            
        import re
        safe_base = re.sub(r'[^a-zA-Z0-9_\-.]', '_', file.filename)
        filename = f"{int(time.time())}_{safe_base}"
        filepath = os.path.abspath(os.path.join(_RESUMES_DIR, filename))
        
        file.save(filepath)
        
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return jsonify({"error": "Failed to save file"}), 500

        # Parse resume text & extract candidate info
        from resume_parser import parse_resume
        parsed = parse_resume(filepath)
        facts = parsed.facts

        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        
        candidate_info = {
            "name": "",
            "email": "",
            "phone": "",
            "city": "",
            "skills": [],
            "experience_years": ""
        }
        
        if api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-2.5-flash")
                prompt = f"""
                You are a highly accurate ATS resume parser. Extract the following candidate details from the resume text:
                1. Candidate's Full Name (e.g. Pratik Pawar)
                2. Email Address
                3. Phone Number
                4. Location / City (e.g. Pune, Remote)
                5. Core Skills (as a list of strings)
                6. Total Experience (in Years as a decimal or integer)
                
                Format the output strictly as a JSON object with these keys:
                "name", "email", "phone", "city", "skills", "experience_years"
                
                Do not include any code block formatting (like ```json or ```). Return ONLY the raw JSON string.
                
                Resume text:
                {parsed.raw_text[:12000]}
                """
                response = model.generate_content(prompt)
                text = response.text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                import json
                candidate_info = json.loads(text)
            except Exception as ex:
                print(f"[WARN] Gemini resume extraction failed: {ex}")
                
        # Fallbacks using regex facts
        if not candidate_info.get("email") and facts.get("email"):
            candidate_info["email"] = facts["email"]
        if not candidate_info.get("phone") and facts.get("phone"):
            candidate_info["phone"] = facts["phone"]
        if not candidate_info.get("experience_years") and facts.get("years_of_experience"):
            candidate_info["experience_years"] = facts["years_of_experience"]
        if not candidate_info.get("skills") and facts.get("skills"):
            candidate_info["skills"] = facts["skills"]
        if not candidate_info.get("name"):
            base_name = os.path.basename(filepath)
            cleaned_name = re.sub(r'^\d+_', '', base_name).split(".")[0].replace("_", " ").title()
            candidate_info["name"] = cleaned_name

        return jsonify({
            "ok": True, 
            "path": filepath, 
            "candidate_info": candidate_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@profile_bp.route("/api/profiles/list", methods=["GET"])
def list_profiles():
    """List all saved profiles in the config/profiles folder."""
    try:
        profiles = []
        for filename in os.listdir(_PROFILES_DIR):
            if filename.endswith(".json"):
                path = os.path.join(_PROFILES_DIR, filename)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profiles.append({
                    "id": filename[:-5],
                    "name": data.get("name", filename[:-5]),
                    "naukri_email": data.get("profile", {}).get("naukri_email", ""),
                    "resume_path": data.get("profile", {}).get("resume_path", ""),
                    "data": data
                })
        return jsonify(profiles)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _sync_profile_to_system(profile_id, profile_data):
    """Sync the profile data to .env and config/profile.py securely."""
    # 1. Sync credentials to .env file first
    profile_dict = profile_data.get("profile", {})
    custom_imap_email = profile_dict.get("imap_email", "")
    custom_imap_pass = profile_dict.get("imap_password", "")

    env_updates = {
        "LINKEDIN_EMAIL": profile_dict.get("linkedin_email", ""),
        "LINKEDIN_PASSWORD": profile_dict.get("linkedin_password", ""),
        "NAUKRI_EMAIL": profile_dict.get("naukri_email", ""),
        "NAUKRI_PASSWORD": profile_dict.get("naukri_password", ""),
        "IMAP_EMAIL": custom_imap_email or profile_dict.get("naukri_email", "") or profile_dict.get("linkedin_email", ""),
        "IMAP_PASSWORD": custom_imap_pass or profile_dict.get("naukri_password", "") or profile_dict.get("linkedin_password", ""),
    }
    _update_env_file(env_updates)
    importlib.reload(config.secrets)

    # 2. Generate config/profile.py safely using helper (filters plain credentials to secrets references)
    content = _generate_profile_file_content(
        profile_data.get("company_credentials", {}),
        profile_data.get("profile", {}),
        profile_data.get("skills", []),
        profile_data.get("tech_experience", {}),
        profile_data.get("work_preferences", {}),
        profile_data.get("daily_limit", 50),
        15,  # per-run limit
        ['09:00', '14:00', '19:00'],
        profile_data.get("headless", True),
        profile_data.get("min_match_score", 30),
        profile_data.get("auto_threshold", 75),
        profile_data.get("review_threshold", 55),
        profile_data.get("keywords", []),
        profile_data.get("locations", []),
        profile_data.get("companies", []),
        profile_data.get("cover_letter", ""),
        profile_data.get("imap_host", "imap.gmail.com"),
        profile_data.get("notification_channels", ["email"])
    )
    
    # 3. Append the active profile name parameter
    content += f"\nACTIVE_PROFILE_NAME = {repr(profile_id)}\n"
    
    with open("config/profile.py", "w", encoding="utf-8") as f:
        f.write(content)
        
    importlib.reload(config.profile)


@profile_bp.route("/api/profiles/save", methods=["POST"])
def save_profile():
    """Create or update a profile JSON template."""
    try:
        data = request.get_json() or {}
        profile_name = data.get("name", "default").strip()
        if not profile_name:
            return jsonify({"error": "Profile name is required"}), 400
            
        safe_name = "".join([c for c in profile_name if c.isalnum() or c in (" ", "_", "-")]).strip().replace(" ", "_").lower()
        if not safe_name:
            safe_name = "profile_" + str(int(time.time()))
            
        filepath = os.path.join(_PROFILES_DIR, f"{safe_name}.json")
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        # Delete old file if renamed
        old_id = data.get("old_id", "").strip()
        if old_id and old_id != safe_name:
            old_path = os.path.join(_PROFILES_DIR, f"{old_id}.json")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception as ex:
                    print(f"[WARN] Failed to delete old profile file {old_path}: {ex}")

        # If the saved profile is active, sync it immediately to config/profile.py
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if safe_name == active_profile or (old_id and old_id == active_profile):
            _sync_profile_to_system(safe_name, data)
            
        return jsonify({"ok": True, "id": safe_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/profiles/select", methods=["POST"])
def select_profile():
    """Switch to a specific profile, rewriting config/profile.py securely."""
    try:
        data = request.get_json() or {}
        profile_id = data.get("id", "").strip()
        filepath = os.path.join(_PROFILES_DIR, f"{profile_id}.json")
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Profile not found"}), 404
            
        with open(filepath, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
            
        _sync_profile_to_system(profile_id, profile_data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@profile_bp.route("/api/profiles/delete", methods=["POST"])
def delete_profile():
    """Delete a profile JSON template."""
    try:
        data = request.get_json() or {}
        profile_id = data.get("id", "").strip()
        if not profile_id:
            return jsonify({"error": "Profile ID is required"}), 400
            
        if profile_id == "default":
            return jsonify({"error": "Cannot delete default profile"}), 400
            
        filepath = os.path.join(_PROFILES_DIR, f"{profile_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            
        # If the deleted profile was active, switch active back to default
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if active_profile == profile_id:
            if os.path.exists(os.path.join(_PROFILES_DIR, "default.json")):
                with open(os.path.join(_PROFILES_DIR, "default.json"), "r", encoding="utf-8") as f:
                    default_data = json.load(f)
                _sync_profile_to_system("default", default_data)
            else:
                with open("config/profile.py", "w", encoding="utf-8") as f:
                    f.write("ACTIVE_PROFILE_NAME = 'default'\n")
                    
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


