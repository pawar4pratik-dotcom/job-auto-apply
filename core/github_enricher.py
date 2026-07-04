"""
core/github_enricher.py — GitHub Profile Skill Enricher

Fetches your public GitHub repos and extracts language/technology keywords
to supplement the static resume during job matching and tailoring.

Safety design:
  - Uses only Python standard library (urllib, json) — no extra pip installs.
  - All network calls have a 5-second timeout.
  - Returns empty string gracefully if GitHub is unreachable or username is not set.
  - Results are cached in memory for the duration of a bot run (no repeated API calls).

Usage:
  from core.github_enricher import get_skill_context
  extra_skills = get_skill_context()   # Returns a markdown string of skills

CLI test:
  python core/github_enricher.py --test
"""

import json
import os
import urllib.request
import urllib.error

_CACHE: str = ""          # In-memory cache — reset each run
_CACHE_LOADED: bool = False

# Language → technology mapping (GitHub "language" → skill keyword)
_LANG_MAP = {
    "Python":     ["Python", "PySpark", "FastAPI", "Flask"],
    "SQL":        ["SQL", "PostgreSQL", "MySQL"],
    "HCL":        ["Terraform", "Infrastructure as Code"],
    "Shell":      ["Bash", "Linux", "Shell Scripting"],
    "Dockerfile": ["Docker", "Containerisation"],
    "YAML":       ["CI/CD", "GitHub Actions"],
    "Scala":      ["Scala", "Apache Spark"],
    "Java":       ["Java", "Spring Boot"],
    "JavaScript": ["JavaScript", "Node.js"],
    "TypeScript": ["TypeScript"],
    "Jupyter Notebook": ["Jupyter", "Data Science", "Machine Learning"],
    "R":          ["R", "Statistical Analysis"],
}


def _get_github_username() -> str:
    """Read GitHub username from profile config, or empty string if not set."""
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        profile = getattr(config.profile, "PROFILE", {})
        return profile.get("github_username", "").strip()
    except Exception:
        return ""


def _fetch_repos(username: str) -> list:
    """Fetch public repo metadata from GitHub API. Returns list of repo dicts."""
    url = f"https://api.github.com/users/{username}/repos?per_page=30&sort=pushed"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "job-auto-apply-bot/1.0",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, list) else []
    except Exception:
        return []


def get_skill_context(force_refresh: bool = False) -> str:
    """
    Returns a Markdown snippet of extra skills inferred from GitHub repos.
    Example return value:
        GitHub Skill Context:
        - Languages: Python, SQL, Shell
        - Technologies: PySpark, Docker, Terraform, GitHub Actions
        - Notable repos: aws-glue-pipelines (Python), snowflake-etl (SQL)

    Returns empty string if username not set or network unreachable.
    """
    global _CACHE, _CACHE_LOADED

    if _CACHE_LOADED and not force_refresh:
        return _CACHE

    _CACHE_LOADED = True
    username = _get_github_username()

    if not username:
        _CACHE = ""
        return _CACHE

    repos = _fetch_repos(username)
    if not repos:
        _CACHE = ""
        return _CACHE

    # Aggregate languages and repo names
    languages_seen: set = set()
    tech_skills: set = set()
    notable_repos: list = []

    for repo in repos:
        lang = repo.get("language") or ""
        name = repo.get("name") or ""
        if lang:
            languages_seen.add(lang)
            for tech in _LANG_MAP.get(lang, []):
                tech_skills.add(tech)
        if name and lang:
            notable_repos.append(f"{name} ({lang})")

    if not languages_seen:
        _CACHE = ""
        return _CACHE

    lines = [
        "GitHub Skill Context (auto-enriched from public repos):",
        f"- Languages: {', '.join(sorted(languages_seen))}",
        f"- Technologies: {', '.join(sorted(tech_skills))}",
    ]
    if notable_repos:
        lines.append(f"- Notable repos: {', '.join(notable_repos[:6])}")

    _CACHE = "\n".join(lines)
    return _CACHE


# ── CLI test mode ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        print("[GITHUB ENRICHER] Running test...")
        result = get_skill_context(force_refresh=True)
        if result:
            print("[OK] GitHub context retrieved:")
            print(result)
        else:
            username = _get_github_username()
            if not username:
                print("[SKIP] No 'github_username' set in config/profile.py — add it to enable enrichment.")
            else:
                print(f"[SKIP] Could not fetch repos for '{username}' — check network or GitHub username.")
