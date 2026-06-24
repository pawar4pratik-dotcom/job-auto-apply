import re
from config.profile import MY_SKILLS, MIN_MATCH_SCORE, TARGET_COMPANIES, PROFILE

ROLE_ALIASES = [
    "data engineer", "etl developer", "big data engineer",
    "cloud data engineer", "aws data engineer", "snowflake developer",
    "pyspark developer", "analytics engineer", "data platform engineer",
    "data infrastructure engineer", "pipeline engineer", "databricks engineer",
]

EXCLUDE_KEYWORDS = [
    "unpaid", "internship only", "fresher only",
    "vice president", "head of", " vp ", "director of",
]

def skill_match_score(job_text: str):
    if not job_text:
        return 0, []
    job_lower = job_text.lower()
    matched = [s for s in MY_SKILLS if s.lower() in job_lower]
    score = round(len(matched) / len(MY_SKILLS) * 100, 1) if MY_SKILLS else 0
    return score, matched

def is_role_relevant(job_title: str) -> bool:
    return any(alias in (job_title or "").lower() for alias in ROLE_ALIASES)

def _max_required_years(text: str) -> int:
    """Improved regex to catch '3-5 years', '5+ years', 'minimum 3 years', etc."""
    if not text:
        return 0
    text_lower = text.lower()
    patterns = [
        r"(\d{1,2})\s*(?:\+|plus)\s*years?",
        r"minimum\s*(\d{1,2})\s*years?",
        r"(\d{1,2})\s*-\s*(\d{1,2})\s*years?",
        r"(\d{1,2})\s*to\s*(\d{1,2})\s*years?",
        r"(\d{1,2})\s*years?"
    ]
    max_years = 0
    for pattern in patterns:
        for m in re.finditer(pattern, text_lower):
            if m.group(2):
                max_years = max(max_years, int(m.group(2)))
            else:
                max_years = max(max_years, int(m.group(1)))
    return max_years

def exceeds_experience(job_text: str):
    if not job_text:
        return False, 0
    try:
        my_years = float(PROFILE.get("total_experience_years", "0") or 0)
    except ValueError:
        my_years = 0.0
    required = _max_required_years(job_text)
    if required and required > my_years + 3:
        return True, required
    return False, required

def has_red_flags(job_text: str):
    if not job_text:
        return False, ""
    job_lower = job_text.lower()
    for flag in EXCLUDE_KEYWORDS:
        if flag in job_lower:
            return True, flag.strip()
    return False, ""

def matches_target_company(company_name: str) -> bool:
    if not TARGET_COMPANIES:
        return True
    comp_lower = (company_name or "").lower()
    return any(t.lower() in comp_lower for t in TARGET_COMPANIES)

def calculate_match_score(title: str, description: str):
    title_lower = title.lower()
    role_keywords = {
        'data engineer': 50, 'data platform': 50, 'software engineer': 40,
        'python developer': 45, 'ml engineer': 50, 'ai engineer': 50,
        'data analyst': 35, 'data scientist': 50, 'backend developer': 40,
        'full stack': 35, 'devops': 40, 'cloud engineer': 45
    }
    title_score = 0
    for role, points in role_keywords.items():
        if role in title_lower:
            title_score = max(title_score, points)
            break
    
    if not description or len(description.strip()) < 50:
        total_score = max(title_score, 20)
        matched = [f"Title match: {title[:30]}"] if title_score > 0 else ["No description available"]
        return total_score, matched
        
    score, matched = skill_match_score(description)
    return max(score, title_score), matched

def should_apply(job_title: str, job_description: str, company_name: str = "") -> tuple:
    if company_name and not matches_target_company(company_name):
        return False, 0, [], f"Company '{company_name}' not in target list"
    
    flag_found, flag_word = has_red_flags(job_description)
    if flag_found:
        return False, 0, [], f"Red flag keyword: '{flag_word}'"
    
    over_exp, req_years = exceeds_experience(job_description)
    if over_exp:
        my_years = PROFILE.get("total_experience_years", "?")
        return False, 0, [], f"Requires {req_years} yrs experience (you have {my_years} yrs)"
    
    score, matched = calculate_match_score(job_title, job_description)
    role_ok = is_role_relevant(job_title)
    
    if score >= MIN_MATCH_SCORE or (role_ok and score >= max(10, MIN_MATCH_SCORE / 2)):
        return True, score, matched, "Skill match"
    else:
        top_missing = [s for s in MY_SKILLS if s.lower() not in (job_description or "").lower()][:3]
        return False, score, matched, (
            f"Low match score ({score}% < {MIN_MATCH_SCORE}% required)"
            + (f" — missing: {', '.join(top_missing)}" if top_missing else "")
        )