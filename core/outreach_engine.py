"""
core/outreach_engine.py — Email outreach engine for cold emailing recruiters/hiring managers.

Functions:
  craft_outreach_email()   — LLM-generated personalized cold email via Gemini 2.5 Flash
  send_email()             — Send single email via SMTP_SSL (Gmail)
  send_bulk_outreach()     — Send to multiple recipients with delay
  save_outreach_history()  — Append results to logs/outreach_history.json
  load_outreach_history()  — Read outreach history

Called by routes/outreach_routes.py
"""

import json
import os
import re
import smtplib
import time
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# ── Singleton model (configured once, reused) ────────────────────────────────
_model = None
_model_lock = threading.Lock()
_last_api_key = None

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_BASE_DIR, "logs")
_HISTORY_FILE = os.path.join(_LOGS_DIR, "outreach_history.json")
_TEMPLATES_FILE = os.path.join(_LOGS_DIR, "outreach_templates.json")


def _get_model(api_key: str):
    """Return singleton Gemini model, reconfiguring only if API key changed."""
    global _model, _last_api_key
    if not _GENAI_AVAILABLE:
        raise RuntimeError("google-generativeai not installed. Run: pip install google-generativeai")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in config/profile.py")
    with _model_lock:
        if _model is None or api_key != _last_api_key:
            genai.configure(api_key=api_key)
            _model = genai.GenerativeModel(
                "gemini-2.5-flash",
                generation_config=genai.GenerationConfig(
                    temperature=0.5,
                    top_p=0.9,
                    max_output_tokens=1024,
                )
            )
            _last_api_key = api_key
    return _model


def _extract_json(text: str) -> dict:
    """Extract first JSON object from a Gemini response that may have markdown fencing."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in Gemini response")
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return json.loads(text[start:end + 1])


# ── 1. Craft Outreach Email ──────────────────────────────────────────────────

def craft_outreach_email(jd: str, role: str, company: str,
                         candidate_profile: dict, gemini_api_key: str) -> dict:
    """
    Use Gemini 2.5 Flash to generate a personalized cold outreach email.

    Args:
        jd:                Job description text
        role:              Target role name
        company:           Company name
        candidate_profile: Dict with keys 'profile' (PROFILE dict),
                           'skills' (MY_SKILLS list), 'tech_experience' (TECH_EXPERIENCE dict)
        gemini_api_key:    Gemini API key string

    Returns:
        { "subject": str, "body": str }
    """
    model = _get_model(gemini_api_key)

    profile = candidate_profile.get("profile", {})
    skills = candidate_profile.get("skills", [])
    name = f"{profile.get('first_name', 'Candidate')} {profile.get('last_name', '')}".strip()
    exp = profile.get("total_experience_years", "4+")
    skills_str = ", ".join(skills[:15])  # Top 15 skills

    jd_trimmed = jd[:3000]

    prompt = f"""You are an expert career email copywriter.

Write a professional cold outreach email for a job candidate reaching out about a specific role.

CANDIDATE: {name} | {exp} years of experience | Skills: {skills_str}
ROLE: {role}
COMPANY: {company}
JOB DESCRIPTION:
{jd_trimmed}

INSTRUCTIONS:
- Write a concise, professional cold email (under 200 words for the body)
- Open by referencing the specific role name at the company
- Highlight 3-4 skills from the candidate that match the JD keywords
- Mention years of relevant experience
- Keep the tone confident but not arrogant
- End with a clear call to action (e.g., request a brief call or meeting)
- Do NOT use generic filler phrases like "I believe I would be a great fit"

Return ONLY valid JSON (no markdown, no extra text):
{{
  "subject": "concise professional email subject line",
  "body": "full email body text with proper line breaks using \\n"
}}
"""

    response = model.generate_content(prompt)
    result = _extract_json(response.text)

    if "subject" not in result or "body" not in result:
        raise ValueError("Gemini response missing 'subject' or 'body' keys")

    return {"subject": result["subject"], "body": result["body"]}


# ── 2. Send Email ─────────────────────────────────────────────────────────────

def send_email(smtp_host: str, smtp_port: int, from_addr: str, password: str,
               to_addr: str, subject: str, body: str,
               attachments: list = None) -> dict:
    """
    Send a single email via SMTP_SSL (Gmail).

    Args:
        smtp_host:    SMTP server hostname (e.g., 'smtp.gmail.com')
        smtp_port:    SMTP port (e.g., 465 for SSL)
        from_addr:    Sender email address
        password:     Sender email password / app password
        to_addr:      Recipient email address
        subject:      Email subject line
        body:         Email body text
        attachments:  Optional list of file paths (PDF) to attach

    Returns:
        { "success": bool, "error": str|None }
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Attach files if provided
        if attachments:
            for filepath in attachments:
                if not os.path.exists(filepath):
                    continue
                filename = os.path.basename(filepath)
                with open(filepath, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"'
                )
                msg.attach(part)

        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())

        return {"success": True, "error": None}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 3. Send Bulk Outreach ────────────────────────────────────────────────────

def send_bulk_outreach(smtp_host: str, smtp_port: int, from_addr: str,
                       password: str, emails: list, subject: str, body: str,
                       resume_path: str = None, delay: float = 2.0) -> list:
    """
    Send outreach email to multiple recipients with delay between sends.

    Args:
        smtp_host:    SMTP server hostname
        smtp_port:    SMTP port
        from_addr:    Sender email address
        password:     Sender password
        emails:       List of recipient email addresses
        subject:      Email subject
        body:         Email body
        resume_path:  Optional path to resume PDF to attach
        delay:        Seconds to wait between sends (default 2.0)

    Returns:
        List of { "email": str, "status": str, "error": str|None, "sent_at": str }
    """
    results = []
    attachments = [resume_path] if resume_path and os.path.exists(resume_path) else None

    for i, to_addr in enumerate(emails):
        to_addr = to_addr.strip()
        if not to_addr:
            continue

        result = send_email(smtp_host, smtp_port, from_addr, password,
                            to_addr, subject, body, attachments)

        results.append({
            "email": to_addr,
            "status": "sent" if result["success"] else "failed",
            "error": result["error"],
            "sent_at": datetime.now().isoformat(),
        })

        # Delay between sends to avoid spam detection (skip after last email)
        if i < len(emails) - 1 and delay > 0:
            time.sleep(delay)

    return results


# ── 4. Save Outreach History ─────────────────────────────────────────────────

def save_outreach_history(results: list, role: str, company: str) -> None:
    """
    Append outreach results to logs/outreach_history.json.

    Each entry: { role, company, emails: [...results], crafted_at, sent_at }
    """
    os.makedirs(_LOGS_DIR, exist_ok=True)

    history = load_outreach_history()

    entry = {
        "role": role,
        "company": company,
        "emails": results,
        "crafted_at": datetime.now().isoformat(),
        "sent_at": datetime.now().isoformat(),
    }
    history.append(entry)

    with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ── 5. Load Outreach History ─────────────────────────────────────────────────

def load_outreach_history() -> list:
    """Read logs/outreach_history.json, returns list or empty list."""
    if not os.path.exists(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []
