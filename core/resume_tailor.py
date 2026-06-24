"""
core/resume_tailor.py — LLM-powered resume tailoring and cover letter generation.

SPEED OPTIMIZATIONS (v2):
  - Parallel Gemini calls: tailor + cover letter run concurrently via ThreadPoolExecutor
  - Model pre-configured once per process (singleton pattern)
  - JD URL caching with TTL=300s (don't re-fetch same URL within 5 minutes)
  - Trimmed prompts for faster token throughput
  - generation_config: temperature=0.4 for deterministic fast output

Called by routes/resume_routes.py
"""

import json
import re
import importlib
import config.profile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# ── Singleton model (configured once, reused) ────────────────────────────────
_model = None
_model_lock = threading.Lock()
_last_api_key = None

# ── URL fetch cache (url → (text, expiry)) ───────────────────────────────────
_url_cache: dict = {}
_URL_CACHE_TTL = 300  # 5 minutes


def _get_api_key() -> str:
    importlib.reload(config.profile)
    return getattr(config.profile, "GEMINI_API_KEY", "")


def _get_profile():
    importlib.reload(config.profile)
    return config.profile


def _get_model():
    """Return singleton Gemini model, reconfiguring only if API key changed."""
    global _model, _last_api_key
    if not _GENAI_AVAILABLE:
        raise RuntimeError("google-generativeai not installed. Run: pip install google-generativeai")
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in config/profile.py")
    with _model_lock:
        if _model is None or api_key != _last_api_key:
            genai.configure(api_key=api_key)
            _model = genai.GenerativeModel(
                "gemini-2.5-flash",
                generation_config=genai.GenerationConfig(
                    temperature=0.4,
                    top_p=0.9,
                    max_output_tokens=2048,
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


def _call_tailor(model, tailor_prompt: str) -> dict:
    """Internal: call Gemini for resume tailoring JSON."""
    response = model.generate_content(tailor_prompt)
    return _extract_json(response.text)


def _call_cover(model, cover_prompt: str) -> str:
    """Internal: call Gemini for cover letter text."""
    response = model.generate_content(cover_prompt)
    return response.text.strip()


def tailor_resume(master_resume_text: str, job_description: str, profile=None) -> dict:
    """
    Call Gemini to tailor the resume for a specific job description.
    OPTIMIZED: Both Gemini calls run in parallel via ThreadPoolExecutor.

    Returns dict with keys:
      tailored_summary    — rewritten professional summary (str)
      tailored_skills     — reordered/filtered skills section (str)
      tailored_bullets    — list of rewritten experience bullets (list[str])
      keyword_matches     — keywords from JD present in resume (list[str])
      keyword_gaps        — keywords from JD missing from resume (list[str])
      match_score         — 0-100 match percentage (int)
      cover_letter        — personalized cover letter (str)
    """
    if profile is None:
        profile = _get_profile()

    p = getattr(profile, "PROFILE", {})
    name = f"{p.get('first_name', 'Candidate')} {p.get('last_name', '')}".strip()
    exp  = p.get("total_experience_years", "4+")
    skills_list = ", ".join(getattr(profile, "MY_SKILLS", []))

    model = _get_model()

    # Trim JD to key section (first 3000 chars) for speed without losing signal
    jd_trimmed = job_description[:3000]

    tailor_prompt = f"""You are an expert ATS resume writer for Data Engineering roles.

CANDIDATE: {name} | {exp} years | Skills: {skills_list}

MASTER RESUME:
{master_resume_text[:3000]}

JOB DESCRIPTION:
{jd_trimmed}

Return ONLY valid JSON (no markdown, no extra text):
{{
  "tailored_summary": "2-3 sentence summary using JD keywords",
  "tailored_skills": "comma-separated skills ordered by JD relevance",
  "tailored_bullets": ["action-verb bullet with metric 1", "bullet 2", "bullet 3", "bullet 4", "bullet 5", "bullet 6"],
  "keyword_matches": ["kw1", "kw2"],
  "keyword_gaps": ["missing1", "missing2"],
  "match_score": 85
}}
Rules: 6-8 bullets with action verbs + metrics. No fictional experience. JSON only."""

    cover_prompt = f"""Write a 3-paragraph professional cover letter for {name} ({exp}yr Data Engineer).

Skills: {skills_list}
JD excerpt: {jd_trimmed[:600]}

Requirements: 3 paragraphs, 150-200 words, paragraph 1=hook, paragraph 2=achievements matching JD, paragraph 3=CTA.
Use JD keywords. Do NOT start with "I am writing to apply". Return ONLY the letter text."""

    # ── PARALLEL EXECUTION ────────────────────────────────────────────────────
    result = {}
    cover_letter = ""
    errors = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_tailor = executor.submit(_call_tailor, model, tailor_prompt)
        fut_cover  = executor.submit(_call_cover,  model, cover_prompt)

        for fut in as_completed([fut_tailor, fut_cover]):
            try:
                if fut is fut_tailor:
                    result = fut.result()
                else:
                    cover_letter = fut.result()
            except Exception as e:
                errors.append(str(e))

    if not result and errors:
        raise RuntimeError(f"Gemini tailoring failed: {'; '.join(errors)}")

    result["cover_letter"] = cover_letter
    return result


def generate_cover_letter_only(profile, job_description: str, company: str = "", role: str = "") -> str:
    """
    Generate only a cover letter (lighter call, no full resume analysis).
    Used by /api/cover_letter endpoint.
    """
    p = getattr(profile, "PROFILE", {})
    name = f"{p.get('first_name', 'Candidate')} {p.get('last_name', '')}".strip()
    exp  = p.get("total_experience_years", "4+")
    skills_list = ", ".join(getattr(profile, "MY_SKILLS", []))

    model = _get_model()

    prompt = f"""Write a 3-paragraph cover letter for {name} applying to {role or 'Data Engineer'} at {company or 'the company'}.

Candidate: {name}, {exp}yr Senior Data Engineer. Skills: {skills_list}
JD: {job_description[:800]}

3 paragraphs, 150-200 words. Paragraph 1: hook specific to company/role.
Paragraph 2: 2-3 quantified achievements matching JD. Paragraph 3: confident CTA.
Use JD keywords. Do NOT start with "I am writing to apply". Letter text only."""

    response = model.generate_content(prompt)
    return response.text.strip()


def fetch_jd_from_url(url: str) -> str:
    """
    Fetch job description text from a URL.
    Uses TTL cache to avoid re-fetching same URL within 5 minutes.
    """
    now = time.time()
    if url in _url_cache:
        cached_text, expiry = _url_cache[url]
        if now < expiry:
            return cached_text

    try:
        import urllib.request
        import html as html_lib
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        # Strip HTML tags
        clean = re.sub(r"<[^>]+>", " ", raw)
        # Collapse whitespace
        clean = re.sub(r"\s+", " ", clean)
        # Remove HTML entities
        clean = html_lib.unescape(clean)
        # First 4000 chars
        result = clean[:4000].strip()
        _url_cache[url] = (result, now + _URL_CACHE_TTL)
        return result
    except Exception as e:
        return f"[Error fetching URL: {e}]"
