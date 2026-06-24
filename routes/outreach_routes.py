"""
routes/outreach_routes.py — Email outreach API endpoints (Blueprint: outreach_bp)

Routes:
  POST /api/outreach/craft       Craft personalized outreach email via Gemini
  POST /api/outreach/send        Send outreach emails to list of recipients
  GET  /api/outreach/history     Get outreach history
  GET  /api/outreach/templates   List saved email templates
  POST /api/outreach/templates   Save/delete email template
"""

import os
import json
import importlib

from flask import Blueprint, jsonify, request

import config.profile

outreach_bp = Blueprint("outreach", __name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_BASE_DIR, "logs")
_TEMPLATES_FILE = os.path.join(_LOGS_DIR, "outreach_templates.json")


# ── POST /api/outreach/craft ─────────────────────────────────────────────────
@outreach_bp.route("/api/outreach/craft", methods=["POST"])
def craft_outreach():
    """
    Craft a personalized outreach email using Gemini.

    Request JSON:
      { "jd": str, "role": str, "company": str }

    Response JSON:
      { "subject": str, "body": str }
    """
    data = request.get_json(force=True, silent=True) or {}
    jd = data.get("jd", "").strip()
    role = data.get("role", "").strip()
    company = data.get("company", "").strip()

    if not jd:
        return jsonify({"error": "jd (job description) is required"}), 400
    if not role:
        return jsonify({"error": "role is required"}), 400

    try:
        importlib.reload(config.profile)
        from config.profile import PROFILE, MY_SKILLS, GEMINI_API_KEY
        tech_exp = getattr(config.profile, "TECH_EXPERIENCE", {})

        if not GEMINI_API_KEY:
            return jsonify({"error": "GEMINI_API_KEY is not configured in Settings."}), 400

        candidate_profile = {
            "profile": PROFILE,
            "skills": MY_SKILLS,
            "tech_experience": tech_exp,
        }

        from core.outreach_engine import craft_outreach_email
        result = craft_outreach_email(jd, role, company, candidate_profile, GEMINI_API_KEY)
        return jsonify(result)

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Email crafting failed: {e}"}), 500


# ── POST /api/outreach/send ──────────────────────────────────────────────────
@outreach_bp.route("/api/outreach/send", methods=["POST"])
def send_outreach():
    """
    Send outreach emails to a list of recipients.

    Request JSON:
      {
        "emails": [str],
        "subject": str,
        "body": str,
        "attach_resume": bool,
        "role": str,           (optional, for history)
        "company": str,        (optional, for history)
        "tailor_resume": bool, (optional, generate tailored resume first)
        "jd": str,             (optional, needed if tailor_resume is true)
      }

    Response JSON:
      { "results": [...], "summary": { "total": int, "sent": int, "failed": int } }
    """
    data = request.get_json(force=True, silent=True) or {}
    emails = data.get("emails", [])
    subject = data.get("subject", "").strip()
    body = data.get("body", "").strip()
    attach_resume = data.get("attach_resume", False)
    role = data.get("role", "").strip()
    company = data.get("company", "").strip()
    tailor_resume = data.get("tailor_resume", False)
    jd = data.get("jd", "").strip()

    if not emails:
        return jsonify({"error": "emails list is required"}), 400
    if not subject:
        return jsonify({"error": "subject is required"}), 400
    if not body:
        return jsonify({"error": "body is required"}), 400

    try:
        importlib.reload(config.profile)
        from config.profile import IMAP_EMAIL, IMAP_PASSWORD, PROFILE

        if not IMAP_EMAIL or not IMAP_PASSWORD:
            return jsonify({"error": "IMAP_EMAIL / IMAP_PASSWORD not configured in Settings."}), 400

        smtp_host = "smtp.gmail.com"
        smtp_port = 465
        resume_path = None

        # Optionally tailor resume first
        if tailor_resume and jd and role:
            try:
                from core.resume_tailor import generate_tailored_resume
                resume_path = generate_tailored_resume(jd, role, company)
            except Exception:
                # Fall back to default resume if tailoring fails
                pass

        # Attach default resume if requested and no tailored resume was generated
        if attach_resume and not resume_path:
            default_resume = PROFILE.get("resume_path", "")
            if default_resume and os.path.exists(default_resume):
                resume_path = default_resume

        from core.outreach_engine import send_bulk_outreach, save_outreach_history
        results = send_bulk_outreach(
            smtp_host, smtp_port, IMAP_EMAIL, IMAP_PASSWORD,
            emails, subject, body, resume_path
        )

        # Save to history
        save_outreach_history(results, role, company)

        total = len(results)
        sent = sum(1 for r in results if r["status"] == "sent")
        failed = total - sent

        return jsonify({
            "results": results,
            "summary": {"total": total, "sent": sent, "failed": failed},
        })

    except Exception as e:
        return jsonify({"error": f"Sending failed: {e}"}), 500


# ── GET /api/outreach/history ─────────────────────────────────────────────────
@outreach_bp.route("/api/outreach/history", methods=["GET"])
def outreach_history():
    """Return outreach history from logs/outreach_history.json."""
    try:
        from core.outreach_engine import load_outreach_history
        history = load_outreach_history()
        return jsonify(history)
    except Exception as e:
        return jsonify({"error": f"Failed to load history: {e}"}), 500


# ── GET /api/outreach/templates ───────────────────────────────────────────────
@outreach_bp.route("/api/outreach/templates", methods=["GET"])
def get_templates():
    """Return saved email templates from logs/outreach_templates.json."""
    try:
        if not os.path.exists(_TEMPLATES_FILE):
            return jsonify([])
        with open(_TEMPLATES_FILE, "r", encoding="utf-8") as f:
            templates = json.load(f)
        return jsonify(templates if isinstance(templates, list) else [])
    except (json.JSONDecodeError, IOError):
        return jsonify([])
    except Exception as e:
        return jsonify({"error": f"Failed to load templates: {e}"}), 500


# ── POST /api/outreach/templates ──────────────────────────────────────────────
@outreach_bp.route("/api/outreach/templates", methods=["POST"])
def save_template():
    """
    Save or delete an email template.

    To save:
      { "name": str, "subject": str, "body": str }

    To delete:
      { "delete": str (template name) }
    """
    data = request.get_json(force=True, silent=True) or {}

    try:
        os.makedirs(_LOGS_DIR, exist_ok=True)

        # Load existing templates
        templates = []
        if os.path.exists(_TEMPLATES_FILE):
            with open(_TEMPLATES_FILE, "r", encoding="utf-8") as f:
                templates = json.load(f)
            if not isinstance(templates, list):
                templates = []

        # Delete operation
        delete_name = data.get("delete", "").strip()
        if delete_name:
            original_len = len(templates)
            templates = [t for t in templates if t.get("name") != delete_name]
            if len(templates) == original_len:
                return jsonify({"error": f"Template '{delete_name}' not found"}), 404
            with open(_TEMPLATES_FILE, "w", encoding="utf-8") as f:
                json.dump(templates, f, indent=2, ensure_ascii=False)
            return jsonify({"ok": True, "message": f"Template '{delete_name}' deleted"})

        # Save operation
        name = data.get("name", "").strip()
        subject = data.get("subject", "").strip()
        body = data.get("body", "").strip()

        if not name:
            return jsonify({"error": "Template name is required"}), 400
        if not subject and not body:
            return jsonify({"error": "subject or body is required"}), 400

        # Update existing or append new
        updated = False
        for t in templates:
            if t.get("name") == name:
                t["subject"] = subject
                t["body"] = body
                updated = True
                break

        if not updated:
            templates.append({
                "name": name,
                "subject": subject,
                "body": body,
            })

        with open(_TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(templates, f, indent=2, ensure_ascii=False)

        action = "updated" if updated else "saved"
        return jsonify({"ok": True, "message": f"Template '{name}' {action}"})

    except Exception as e:
        return jsonify({"error": f"Template operation failed: {e}"}), 500


# ── POST /api/outreach/bulk_craft ─────────────────────────────────────────────
@outreach_bp.route("/api/outreach/bulk_craft", methods=["POST"])
def bulk_craft_outreach():
    """
    Accept multiple JDs, auto-extract role/company/requirements, craft emails for all.

    Request JSON:
      { "jds": [str, str, ...], "emails_per_jd": {"0": "hr@x.com,hr2@x.com", ...} }

    Response JSON:
      { "drafts": [ { "jd_index": int, "role": str, "company": str, "requirements": [str],
                       "matched_skills": [str], "subject": str, "body": str, "emails": [str] }, ... ] }
    """
    data = request.get_json(force=True, silent=True) or {}
    jds = data.get("jds", [])
    emails_map = data.get("emails_per_jd", {})

    if not jds:
        return jsonify({"error": "jds list is required"}), 400

    try:
        importlib.reload(config.profile)
        from config.profile import PROFILE, MY_SKILLS, GEMINI_API_KEY, TECH_EXPERIENCE

        if not GEMINI_API_KEY:
            return jsonify({"error": "GEMINI_API_KEY not configured"}), 400

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        candidate_profile = {
            "name": f"{PROFILE.get('first_name','')} {PROFILE.get('last_name','')}",
            "email": PROFILE.get("email", ""),
            "phone": PROFILE.get("phone", ""),
            "experience": PROFILE.get("total_experience_years", "4.6"),
            "skills": MY_SKILLS,
            "tech_exp": TECH_EXPERIENCE,
        }

        drafts = []
        for idx, jd in enumerate(jds):
            jd = jd.strip()
            if not jd:
                continue

            emails_str = emails_map.get(str(idx), "")
            email_list = [e.strip() for e in emails_str.replace(";", ",").replace("\n", ",").split(",") if e.strip() and "@" in e.strip()]

            # Fallback: extract emails from JD using regex
            if not email_list:
                import re
                found_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', jd)
                email_list = list(set([e.strip() for e in found_emails if e.strip()]))

            prompt = f"""You are an expert job application assistant.

Given this JD:
---
{jd[:4000]}
---

And this candidate:
- Name: {candidate_profile['name']}
- Experience: {candidate_profile['experience']} years
- Skills: {', '.join(candidate_profile['skills'][:12])}

Do ALL of the following:
1. Extract: role title, company name, top 5 key requirements from the JD
2. Match: which of the candidate's skills align with the JD requirements
3. Draft: a professional cold email (under 180 words) highlighting matched skills, experience, and requesting an opportunity to discuss
4. Create: a compelling subject line

Return ONLY valid JSON:
{{"role": "...", "company": "...", "requirements": ["req1","req2","req3","req4","req5"], "matched_skills": ["skill1","skill2"], "subject": "...", "body": "..."}}"""

            try:
                import re
                response = model.generate_content(prompt)
                resp_text = response.text.strip()
                if resp_text.startswith("```"):
                    resp_text = re.sub(r"^```(?:json)?\n|```$", "", resp_text, flags=re.MULTILINE).strip()
                result = json.loads(resp_text)
                drafts.append({
                    "jd_index": idx,
                    "role": result.get("role", "Unknown Role"),
                    "company": result.get("company", "Unknown"),
                    "requirements": result.get("requirements", []),
                    "matched_skills": result.get("matched_skills", []),
                    "subject": result.get("subject", ""),
                    "body": result.get("body", ""),
                    "emails": email_list,
                    "jd_preview": jd[:150] + "..." if len(jd) > 150 else jd,
                })
            except Exception as e:
                drafts.append({
                    "jd_index": idx,
                    "role": "Parse Error",
                    "company": "",
                    "requirements": [],
                    "matched_skills": [],
                    "subject": "",
                    "body": "",
                    "emails": email_list,
                    "error": str(e),
                    "jd_preview": jd[:150] + "..." if len(jd) > 150 else jd,
                })

        return jsonify({"drafts": drafts})

    except Exception as e:
        return jsonify({"error": f"Bulk craft failed: {e}"}), 500


@outreach_bp.route("/api/outreach/smart_split_craft", methods=["POST"])
def smart_split_craft_outreach():
    """
    Accept a single block of raw text, split it into separate JDs, auto-extract emails,
    and draft email outreach templates for all using Gemini.
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_text = data.get("raw_text", "").strip()

    if not raw_text:
        return jsonify({"error": "raw_text is required"}), 400

    try:
        importlib.reload(config.profile)
        from config.profile import PROFILE, MY_SKILLS, GEMINI_API_KEY, TECH_EXPERIENCE

        if not GEMINI_API_KEY:
            return jsonify({"error": "GEMINI_API_KEY not configured"}), 400

        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        candidate_profile = {
            "name": f"{PROFILE.get('first_name','')} {PROFILE.get('last_name','')}",
            "email": PROFILE.get("email", ""),
            "phone": PROFILE.get("phone", ""),
            "experience": PROFILE.get("total_experience_years", "4.6"),
            "skills": MY_SKILLS,
            "tech_exp": TECH_EXPERIENCE,
        }

        prompt = f"""You are an expert job application assistant.

The user has pasted a block of text containing one or more job descriptions (JDs) or recruiter posts.
Please split this block of text into individual job postings.

CANDIDATE PROFILE:
- Name: {candidate_profile['name']}
- Experience: {candidate_profile['experience']} years
- Skills: {', '.join(candidate_profile['skills'][:15])}

RAW PASTED TEXT:
---
{raw_text[:8000]}
---

For EACH individual job posting found in the raw text:
1. Extract the text of the job description.
2. Extract any email addresses mentioned in that posting (specifically recruiters, HR, or hiring managers). If none are found, return an empty list.
3. Extract the role title and company name.
4. List the top 5 key requirements.
5. Identify which of the candidate's skills match the requirements.
6. Draft a professional cold email (under 180 words) highlighting matched skills, experience, and requesting an opportunity.
7. Create a subject line.

Return ONLY a valid JSON object matching this structure (no markdown code blocks, no extra text, no conversation):
{{
  "postings": [
    {{
      "jd": "extracted JD text",
      "emails": ["email1@company.com"],
      "role": "extracted role title",
      "company": "extracted company name",
      "requirements": ["req1", "req2", "req3", "req4", "req5"],
      "matched_skills": ["skill1", "skill2"],
      "subject": "email subject",
      "body": "email body text with proper line breaks using \\n"
    }}
  ]
}}"""

        import re
        response = model.generate_content(prompt)
        resp_text = response.text.strip()
        if resp_text.startswith("```"):
            resp_text = re.sub(r"^```(?:json)?\n|```$", "", resp_text, flags=re.MULTILINE).strip()
        
        result = json.loads(resp_text)
        postings = result.get("postings", [])
        
        drafts = []
        for idx, post in enumerate(postings):
            jd_text = post.get("jd", "")
            emails = post.get("emails", [])
            
            # Fallback regex email extraction if list is empty
            if not emails and jd_text:
                found_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', jd_text)
                emails = list(set([e.strip() for e in found_emails if e.strip()]))

            drafts.append({
                "jd_index": idx,
                "role": post.get("role", "Unknown Role"),
                "company": post.get("company", "Unknown"),
                "requirements": post.get("requirements", []),
                "matched_skills": post.get("matched_skills", []),
                "subject": post.get("subject", ""),
                "body": post.get("body", ""),
                "emails": emails,
                "jd_preview": jd_text[:150] + "..." if len(jd_text) > 150 else jd_text,
            })

        return jsonify({"drafts": drafts})

    except Exception as e:
        return jsonify({"error": f"Smart split and craft failed: {e}"}), 500

