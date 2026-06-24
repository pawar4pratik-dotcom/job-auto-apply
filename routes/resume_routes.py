"""
routes/resume_routes.py — Resume & Cover Letter API endpoints (Blueprint: resume_bp)

Endpoints:
  GET  /api/master_resume          Read config/master_resume.txt
  POST /api/master_resume          Save config/master_resume.txt
  POST /api/tailor                 Tailor resume + generate cover letter via Gemini
  POST /api/cover_letter           Generate cover letter only via Gemini
"""

import os
import importlib
from flask import Blueprint, jsonify, request

resume_bp = Blueprint("resume_bp", __name__)

MASTER_RESUME_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "master_resume.txt"
)


def _load_master_resume() -> str:
    """Read master_resume.txt, return empty string if not found."""
    if os.path.exists(MASTER_RESUME_PATH):
        with open(MASTER_RESUME_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _save_master_resume(text: str):
    """Write text to master_resume.txt (creates file if needed)."""
    os.makedirs(os.path.dirname(MASTER_RESUME_PATH), exist_ok=True)
    with open(MASTER_RESUME_PATH, "w", encoding="utf-8") as f:
        f.write(text)


# ── GET /api/master_resume ────────────────────────────────────────────────────
@resume_bp.route("/api/master_resume", methods=["GET"])
def get_master_resume():
    text = _load_master_resume()
    return jsonify({"text": text, "exists": bool(text)})


# ── POST /api/master_resume ───────────────────────────────────────────────────
@resume_bp.route("/api/master_resume", methods=["POST"])
def save_master_resume():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    _save_master_resume(text)
    word_count = len(text.split())
    return jsonify({"ok": True, "word_count": word_count,
                    "message": f"Saved ({word_count} words)"})


# ── POST /api/tailor ──────────────────────────────────────────────────────────
@resume_bp.route("/api/tailor", methods=["POST"])
def tailor_resume_endpoint():
    """
    Body (JSON):
      job_description: str   (paste raw JD text)
      job_url:         str   (optional, fetches JD automatically)

    Response:
      tailored_summary, tailored_skills, tailored_bullets[],
      keyword_matches[], keyword_gaps[], match_score, cover_letter
    """
    data = request.get_json(force=True, silent=True) or {}
    job_url = data.get("job_url", "").strip()
    job_description = data.get("job_description", "").strip()

    # If URL given but no JD text, fetch from URL
    if job_url and not job_description:
        try:
            from core.resume_tailor import fetch_jd_from_url
            job_description = fetch_jd_from_url(job_url)
            if job_description.startswith("[Error"):
                return jsonify({"error": job_description}), 502
        except Exception as e:
            return jsonify({"error": f"URL fetch failed: {e}"}), 502

    if not job_description:
        return jsonify({"error": "Provide job_description text or a job_url"}), 400

    master_resume = _load_master_resume()
    if not master_resume:
        return jsonify({"error": "Master resume is empty. Please paste your resume in the left panel and save first."}), 400

    try:
        from core.resume_tailor import tailor_resume
        import config.profile
        importlib.reload(config.profile)
        result = tailor_resume(master_resume, job_description, config.profile)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Tailoring failed: {e}"}), 500


# ── POST /api/cover_letter ────────────────────────────────────────────────────
@resume_bp.route("/api/cover_letter", methods=["POST"])
def cover_letter_endpoint():
    """
    Body (JSON):
      job_description: str
      company:         str   (optional)
      role:            str   (optional)
    """
    data = request.get_json(force=True, silent=True) or {}
    job_description = data.get("job_description", "").strip()
    company = data.get("company", "").strip()
    role = data.get("role", "").strip()

    if not job_description:
        return jsonify({"error": "job_description is required"}), 400

    try:
        from core.resume_tailor import generate_cover_letter_only
        import config.profile
        importlib.reload(config.profile)
        letter = generate_cover_letter_only(config.profile, job_description, company, role)
        return jsonify({"cover_letter": letter})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Cover letter generation failed: {e}"}), 500


# ── POST /api/parse_resume ───────────────────────────────────────────────────
@resume_bp.route("/api/parse_resume", methods=["POST"])
def parse_resume_endpoint():
    """
    Accepts an uploaded PDF resume file.
    Extracts text using pypdf, structures it using Gemini, and returns JSON.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
        
    file = request.files["file"]
    if not file or not file.filename.endswith(".pdf"):
        return jsonify({"ok": False, "error": "Only PDF files are supported"}), 400

    try:
        import pypdf
        reader = pypdf.PdfReader(file.stream)
        text_parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
        resume_text = "\n".join(text_parts).strip()
        
        if not resume_text:
            return jsonify({"ok": False, "error": "No text could be extracted from PDF (is it scanned or empty?)"}), 400

        # Load API key
        import config.profile
        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return jsonify({"ok": False, "error": "Gemini API key is not configured in Settings."}), 400

        prompt = f"""You are an AI assistant specialized in parsing candidate resumes.
Extract structural data from the candidate's Resume Text below.

Resume Text:
\"\"\"
{resume_text}
\"\"\"

Your task is to extract the following details precisely:
1. First Name and Last Name
2. Email address
3. Phone number
4. Current City
5. Total years of professional experience as a numeric string (e.g., "4.6", "5.0", "3.0")
6. Key skill tags/names (as a flat array of unique skills, e.g., ["Python", "SQL", "AWS"])
7. Specific technical skills experience in years (as a key-value dictionary, matching the skills list, mapping skill names in lowercase to years of experience as a numeric string, e.g. {{"python": "4.6", "aws": "3.0"}})

Respond ONLY with a JSON block in this exact schema, without markdown formatting:
{{
  "first_name": "...",
  "last_name": "...",
  "email": "...",
  "phone": "...",
  "city": "...",
  "total_experience_years": "...",
  "skills": ["...", "..."],
  "tech_experience": {{
    "skill_name_1": "years",
    "skill_name_2": "years"
  }}
}}
"""

        import google.generativeai as genai
        import json
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```json"):
                text = "\n".join(lines[1:-1])
            elif lines[0].startswith("```"):
                text = "\n".join(lines[1:-1])
                
        data = json.loads(text.strip())
        return jsonify({
            "ok": True,
            "parsed": data
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

