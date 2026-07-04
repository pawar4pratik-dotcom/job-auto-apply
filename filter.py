"""
filter.py — AI-matching and keyword filters to decide if a job is worth applying to.

Logic:
  1. Company whitelist check (if TARGET_COMPANIES is non-empty)
  2. Red flag keyword check (internship-only, VP-level, etc.)
  3. Experience ceiling check (skip if required years >> candidate years)
  4. Two-stage match score:
       Stage A: title-based role score (fast, no description needed)
       Stage B: skill keyword scan over full description
  5. Role alias check for Data Engineer variants
  Returns: (should_apply: bool, score: int, matched: list, reason: str)

FIXES:
  - BUG4: reason variable overwrite no longer silences AI reason
  - PERF: profile.py is NOT reloaded on every job evaluation
"""

import re
import importlib
import time
import config.profile

# ── Singleton Gemini model (Fix #12/13: avoid re-creating on every call) ──────
_gemini_model = None
_gemini_configured_key = None

def _get_gemini_model(api_key):
    global _gemini_model, _gemini_configured_key
    if _gemini_model and _gemini_configured_key == api_key:
        return _gemini_model
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    _gemini_model = genai.GenerativeModel("gemini-2.5-flash")
    _gemini_configured_key = api_key
    return _gemini_model


def _reload_profile():
    """Reload config.profile once and return it. Called explicitly when needed."""
    importlib.reload(config.profile)
    return config.profile

# ── Role alias map ────────────────────────────────────────────────────────────
# Job titles that qualify as "Data Engineer" even when named differently
ROLE_ALIASES = [
    "data engineer", "etl developer", "big data engineer",
    "cloud data engineer", "aws data engineer", "snowflake developer",
    "pyspark developer", "analytics engineer", "data platform engineer",
    "data infrastructure engineer", "pipeline engineer", "databricks engineer",
    "data architect", "ml engineer", "mlops engineer", "ai engineer",
    "backend developer", "python developer", "software engineer",
    "cloud engineer", "devops engineer", "data scientist",
    "associate data engineer", "junior data engineer", "sr data engineer",
    "senior data engineer", "lead data engineer", "principal data engineer",
    "data ops", "dataops", "data platform", "gcp data", "azure data",
    "lakehouse", "spark developer", "kafka developer",
]

# ── Red-flag compiled regex patterns — skip these roles outright ──────────────
TITLE_EXCLUDE_PATTERNS = [
    re.compile(r'\bvice\s+president\b', re.I),
    re.compile(r'\bhead\s+of\b', re.I),
    re.compile(r'\bvp\b', re.I),
    re.compile(r'\bdirector\b', re.I),
    re.compile(r'\bchief\b', re.I),
    re.compile(r'\bpresident\b', re.I),
    re.compile(r'\bc[-\s]?level\b', re.I),
    re.compile(r'\b(?:cto|ceo|cfo|cmo|cio|coo)\b', re.I),
]

DESC_EXCLUDE_PATTERNS = [
    re.compile(r'\bunpaid\b', re.I),
    re.compile(r'\binternship\s+only\b', re.I),
    re.compile(r'\bfresher\s+only\b', re.I),
]

# ── Title → base score map ────────────────────────────────────────────────────
TITLE_SCORES = {
    "data engineer":           75,
    "data platform":           70,
    "etl developer":           70,
    "pyspark":                 65,
    "databricks":              65,
    "analytics engineer":      60,
    "ml engineer":             60,
    "ai engineer":             55,
    "mlops":                   55,
    "cloud data":              60,
    "aws data":                60,
    "snowflake":               60,
    "python developer":        50,
    "software engineer":       45,
    "backend developer":       45,
    "cloud engineer":          50,
    "devops":                  45,
    "data analyst":            40,
    "data scientist":          55,
    "full stack":              40,
    "associate data":          65,
    "senior data":             75,
    "sr data":                 75,
    "lead data":               70,
    "kafka":                   50,
    "spark":                   55,
}


# ── 1. Skill keyword match ────────────────────────────────────────────────────

def skill_match_score(job_text: str) -> tuple:
    """
    Returns (score_percent: float, matched_skills: list, missing_skills: list).
    Score = % of job description technical skills that candidate possesses.
    """
    if not job_text:
        return 0.0, [], []
    job_lower = job_text.lower()
    my_skills = getattr(config.profile, "MY_SKILLS", [])
    
    # 1. Identify which of MY_SKILLS appear in the job description
    matched = [s for s in my_skills if re.search(r'\b' + re.escape(s.lower()) + r'\b', job_lower)]
    
    # 2. Tech vocabulary dictionary to identify required skills in the job description
    TECH_VOCAB = {
        "python", "sql", "aws", "gcp", "azure", "spark", "hadoop", "databricks", "snowflake",
        "pyspark", "scala", "java", "kubernetes", "docker", "airflow", "redshift", "bigquery",
        "kafka", "tableau", "powerbi", "looker", "dbt", "ml", "ai", "machine learning", "git",
        "ci/cd", "devops", "linux", "nosql", "mongodb", "postgresql", "mysql", "oracle",
        "excel", "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn"
    }
    for s in my_skills:
        TECH_VOCAB.add(s.lower())
        
    jd_skills = [s for s in TECH_VOCAB if re.search(r'\b' + re.escape(s) + r'\b', job_lower)]
    
    # 3. Missing skills (tech keywords in JD that the candidate doesn't match)
    missing = [s for s in jd_skills if s not in [m.lower() for m in matched]]
    
    if jd_skills:
        score = round(len(matched) / len(jd_skills) * 100, 1)
    else:
        score = 50.0  # Baseline if no specific tech skills are in the description
        
    score = min(score, 100.0)
    
    # Re-case missing elements for readability
    cased_missing = []
    for m in missing:
        cased_missing.append(m.title() if m not in ["sql", "aws", "gcp", "ats", "etl", "nosql"] else m.upper())
        
    return score, matched, cased_missing


# ── 2. Role alias check ───────────────────────────────────────────────────────

def is_role_relevant(job_title: str) -> bool:
    """True if the job title matches any target search keyword from the active profile, with fallback to hardcoded list."""
    title_lower = (job_title or "").lower().replace("dataengineer", "data engineer")
    try:
        import config.profile
        keywords = getattr(config.profile, "SEARCH_KEYWORDS", [])
        if isinstance(keywords, list):
            keywords = [k.lower().strip() for k in keywords if k and isinstance(k, str) and k.strip()]
            if keywords:
                return any(k in title_lower for k in keywords)
    except Exception:
        pass
    return any(alias in title_lower for alias in ROLE_ALIASES)



# ── 3. Experience ceiling ─────────────────────────────────────────────────────

def _max_required_years(text: str) -> int:
    """
    Extract the maximum years-of-experience demanded in a JD.
    Safely handles patterns like "3-5 years", "5+ years", "minimum 4 years".
    Ignores posting-age context like "posted 2 years ago".
    """
    if not text:
        return 0
    text_lower = text.lower()
    
    # Normalize spelled numbers
    num_map = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", 
               "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}
    for word, num in num_map.items():
        text_lower = re.sub(r'\b' + word + r'\b', num, text_lower)

    patterns = [
        r"(\d{1,2})\s*(?:\+|plus)\s*(?:years?|yrs?)\b",
        r"minimum\s*(\d{1,2})\s*(?:years?|yrs?)\b",
        r"at\s+least\s+(\d{1,2})\s*(?:years?|yrs?)\b",
        r"(\d{1,2})\s*-\s*(\d{1,2})\s*(?:years?|yrs?)\b",
        r"(\d{1,2})\s*to\s*(\d{1,2})\s*(?:years?|yrs?)\b",
        r"(\d{1,2})\s*(?:years?|yrs?)\s+of\s+experience\b",
        r"experience\s+of\s+(\d{1,2})\s*(?:years?|yrs?)\b",
        r"(\d{1,2})\s*(?:years?|yrs?)\s*(?:relevant)?\s*experience\b",
    ]
    max_years = 0
    for pattern in patterns:
        for m in re.finditer(pattern, text_lower):
            # Skip posting-time context: "2 years ago", "posted 3 years back"
            match_end = m.end()
            trailing = text_lower[match_end: match_end + 12]
            if "ago" in trailing or "back" in trailing:
                continue
            groups = m.groups()
            # Take the higher of a range (e.g. "3-5 years" → 5)
            if len(groups) >= 2 and groups[1] is not None:
                max_years = max(max_years, int(groups[1]))
            elif len(groups) >= 1 and groups[0] is not None:
                max_years = max(max_years, int(groups[0]))
    if max_years > 20:
        return 0
    return max_years


def exceeds_experience(job_text: str) -> tuple:
    """
    Returns (too_senior: bool, required_years: int).
    Allows up to +3 years buffer above candidate's stated experience.
    """
    if not job_text:
        return False, 0
    try:
        profile = getattr(config.profile, "PROFILE", {})
        my_years = float(profile.get("total_experience_years", "0") or 0)
    except ValueError:
        my_years = 0.0
    required = _max_required_years(job_text)
    if required and required > my_years + 3:
        return True, required
    return False, required


# ── 4. Red-flag check ─────────────────────────────────────────────────────────

def has_red_flags(job_title: str, job_description: str) -> tuple:
    """Returns (flag_found: bool, keyword: str)."""
    title = job_title or ""
    for pattern in TITLE_EXCLUDE_PATTERNS:
        match = pattern.search(title)
        if match:
            return True, f"Title: {match.group(0)}"
            
    description = job_description or ""
    for pattern in DESC_EXCLUDE_PATTERNS:
        match = pattern.search(description)
        if match:
            return True, f"Desc: {match.group(0)}"
            
    return False, ""


# ── 5. Company whitelist ──────────────────────────────────────────────────────

def matches_target_company(company_name: str) -> bool:
    """
    If TARGET_COMPANIES is non-empty, only pass companies in that list.
    Empty list = apply to everyone.
    """
    target_companies = getattr(config.profile, "TARGET_COMPANIES", [])
    if not target_companies:
        return True
    comp_lower = (company_name or "").lower()
    return any(t.lower() in comp_lower for t in target_companies)


# ── 6. Combined match score ───────────────────────────────────────────────────

def calculate_match_score(title: str, description: str) -> tuple:
    """
    Returns (final_score: float, matched_skills: list, missing_skills: list).

    Stage A: title-keyword base score (fast, no description needed).
    Stage B: skill scan across full description.
    Final    = max(title_score, skill_score) — whichever is higher.
    """
    title_lower = (title or "").lower().replace("dataengineer", "data engineer")

    # Stage A — title score
    title_score = 0

    # 1. Check dynamic SEARCH_KEYWORDS from active profile first
    try:
        import config.profile
        keywords = getattr(config.profile, "SEARCH_KEYWORDS", [])
        if isinstance(keywords, list):
            keywords = [k.lower().strip() for k in keywords if k and isinstance(k, str) and k.strip()]
            for kw in keywords:
                if kw in title_lower:
                    title_score = max(title_score, 75)
    except Exception:
        pass


    # 2. Check hardcoded data engineering aliases as fallback
    for role_kw, pts in TITLE_SCORES.items():
        if role_kw in title_lower:
            title_score = max(title_score, pts)

    # Short or missing description — return title score as-is (no forced 20% penalty)
    if not description or len(description.strip()) < 50:
        if title_score > 0:
            return float(title_score), [f"Title match: {title[:40]}"], []
        # Generic fallback: give any job a baseline of 20% so it's not auto-rejected
        return 20.0, ["No description available"], []

    # Stage B — skill keyword scan
    skill_score, matched, missing = skill_match_score(description)
    return max(skill_score, float(title_score)), matched, missing


# ── 7. Master decision ────────────────────────────────────────────────────────

def should_apply(job_title: str, job_description: str, company_name: str = "",
                 _reload: bool = False, url: str = "") -> tuple:
    """
    Master entry point.
    Returns: (apply: bool, score: float, matched: list, reason: str, decision: str, missing: list)
    decision = "auto" | "review" | "skip"

    _reload=True forces a fresh reload of config.profile (use once per batch, not per job).
    """
    if url:
        from core.cache import get_scored
        cached = get_scored(url)
        if cached is not None:
            return cached

    # BUG-FIX PERF: Only reload profile when explicitly requested (e.g. once per search batch)
    # Previously this reloaded profile.py for EVERY single job evaluated (50+ disk reads per scan)
    if _reload:
        importlib.reload(config.profile)

    auto_threshold   = getattr(config.profile, "AUTO_THRESHOLD", 75)
    review_threshold = getattr(config.profile, "REVIEW_THRESHOLD", 55)
    min_match_score  = getattr(config.profile, "MIN_MATCH_SCORE", 30)

    # Gate 1: Company whitelist
    if company_name and not matches_target_company(company_name):
        return False, 0, [], f"Company '{company_name}' not in target list", "skip", []

    # Gate 2: Red flags
    flag_found, flag_word = has_red_flags(job_title, job_description)
    if flag_found:
        return False, 0, [], f"Red flag keyword: '{flag_word}'", "skip", []

    # Gate 3: Experience ceiling
    over_exp, req_years = exceeds_experience(job_description)
    if over_exp:
        profile_data = getattr(config.profile, "PROFILE", {})
        my_years = profile_data.get("total_experience_years", "?")
        return False, 0, [], f"Requires {req_years} yrs (candidate has {my_years} yrs)", "skip", []

    # Gate 4: Keyword score (baseline)
    score, matched, missing = calculate_match_score(job_title, job_description)

    # Pre-filtering (title-only) stage bypass check
    is_prefilter = (not job_description or len(job_description.strip()) < 50)
    role_ok = is_role_relevant(job_title)
    if is_prefilter:
        title_lower = (job_title or "").lower()
        if score >= 40 or role_ok:
            return True, score, matched, f"Title pre-pass ({score:.0f}%)", "auto", missing
        elif score >= 20 and any(kw in title_lower for kw in ["engineer", "developer", "data", "cloud", "python", "analyst"]):
            return True, score, matched, f"Title pre-pass ({score:.0f}%)", "auto", missing
        else:
            return False, score, matched, f"Low title match ({score:.0f}%)", "skip", missing

    # BUG-FIX BUG4: ai_reason is now preserved — reason variable is NOT reset after AI block
    # Previously: reason = "" at L297 silently discarded the Gemini AI reason
    ai_reason = ""  # Track AI reason separately

    # AI Suitability scoring via Gemini (only run for inconclusive keyword scores to save quota and speed up)
    api_key = getattr(config.profile, "GEMINI_API_KEY", "")
    if api_key and job_description and len(job_description.strip()) > 100 and (35 <= score <= 75):
        try:
            import json
            model = _get_gemini_model(api_key)

            profile_data = getattr(config.profile, "PROFILE", {})
            my_skills = getattr(config.profile, "MY_SKILLS", [])
            my_exp = profile_data.get("total_experience_years", "4.6")

            # ── GitHub skill enrichment (additive, non-blocking) ────────────────
            github_context = ""
            try:
                from core.github_enricher import get_skill_context
                github_context = get_skill_context()
            except Exception:
                pass

            prompt = f"""
You are an expert recruiter evaluating candidate suitability for a job.
Candidate details:
- Experience: {my_exp} years
- Key Skills: {', '.join(my_skills)}
{github_context}
Job Posting:
- Title: {job_title}
- Description: {job_description[:3000]}

Evaluate this job post and return a JSON object with:
1. "score": a number from 0 to 100 representing match suitability.
2. "matched_skills": list of skills from the candidate's key skills that are relevant for this job.
3. "missing_skills": list of skills from the candidate's key skills that are missing but highly relevant/demanded in the job description.
4. "reason": a concise, 1-sentence explanation of the score.

Response must be valid raw JSON only, e.g.
{{"score": 85, "matched_skills": ["AWS", "SQL"], "missing_skills": ["Spark"], "reason": "Excellent alignment with AWS Data Engineer requirements."}}
"""
            # Fix #11: Retry once on Gemini failure
            resp_text = None
            for _attempt in range(2):
                try:
                    response = model.generate_content(prompt)
                    resp_text = response.text.strip()
                    break
                except Exception as retry_err:
                    if _attempt == 0:
                        time.sleep(2)
                    else:
                        raise retry_err
            if resp_text.startswith("```"):
                resp_text = re.sub(r"^```(?:json)?\n|```$", "", resp_text, flags=re.MULTILINE).strip()

            res = json.loads(resp_text)
            ai_score  = float(res.get("score", score))
            ai_matched = res.get("matched_skills", matched)
            ai_missing = res.get("missing_skills", missing)
            ai_reason  = res.get("reason", "")  # ← preserved in dedicated var, NOT overwritten below

            print(f"  [AI MATCH SCORE] {ai_score}% — {ai_reason}")
            score   = ai_score
            matched = ai_matched
            missing = ai_missing
        except Exception as e:
            print(f"  [AI MATCH SCORE][WARN] Gemini failed: {e}. Using keyword score.")

    role_ok = is_role_relevant(job_title)

    # Master custom auto-apply thresholds (User rules: 60% standard, 40% priority titles, or 3+ core skills match)
    title_lower = (job_title or "").lower()
    priority_titles = ["cloud engineer", "clod enginer", "aws data engineer", "data engineer", "data analyst"]
    is_priority_role = any(p in title_lower for p in priority_titles)
    local_auto_threshold = 40 if is_priority_role else auto_threshold

    # Core skills and their common aliases (e.g. AWS or Amazon Web Services or SQL or MySQL)
    core_skills_aliases = {
        "aws": ["aws", "amazon web services", "amazon web service"],
        "snowflake": ["snowflake"],
        "sql": ["sql", "mysql", "postgresql", "oracle sql", "pl/sql", "tsql", "t-sql"],
        "python": ["python", "py"],
        "pyspark": ["pyspark", "py-spark", "spark"]
    }
    
    matched_lower = [m.lower() for m in matched]
    core_matches = []
    job_desc_lower = (job_description or "").lower()
    for skill_name, aliases in core_skills_aliases.items():
        # Check if any alias exists in matched skills or is mentioned in the job description
        for alias in aliases:
            if alias in matched_lower or re.search(r'\b' + re.escape(alias) + r'\b', job_desc_lower):
                core_matches.append(skill_name)
                # Ensure the primary skill gets marked as matched
                primary_cased = skill_name.upper() if skill_name in ["aws", "sql"] else skill_name.title()
                if primary_cased not in matched:
                    matched.append(primary_cased)
                break
                
    force_auto = (len(core_matches) >= 3)

    # Hard floor check (bypassed if force_auto is triggered)
    if not force_auto and score < min_match_score and not (role_ok and score >= max(10, min_match_score / 2)):
        top_missing = missing[:3]
        floor_reason = (
            f"Low match ({score:.0f}% < {min_match_score}% threshold)"
            + (f" — missing: {', '.join(top_missing)}" if top_missing else "")
        )
        return False, score, matched, floor_reason, "skip", missing

    # Three-tier decision routing — ai_reason is included in reason when available
    reason_suffix = f" — {ai_reason}" if ai_reason else ""
    if score >= local_auto_threshold or force_auto:
        reason_lbl = f"High match ({score:.0f}%)"
        if force_auto:
            reason_lbl = f"Core skills match ({len(core_matches)}/5 core: {', '.join(core_matches)})"
        ret = (True, score, matched, f"{reason_lbl}{reason_suffix}", "auto", missing)
    elif score >= review_threshold:
        ret = (True, score, matched, f"Medium match ({score:.0f}%){reason_suffix}", "review", missing)
    else:
        ret = (False, score, matched, f"Low match ({score:.0f}%){reason_suffix}", "skip", missing)

    if url:
        from core.cache import set_scored
        set_scored(url, ret)
    return ret

