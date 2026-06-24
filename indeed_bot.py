"""
indeed_bot.py — Job search via Indeed's free RSS feeds.
No API key required. Parses RSS, pulls full description via browser, filters jobs, applies via careers_bot.
"""

import feedparser
import time
import os
import importlib
from selenium.webdriver.common.by import By
from filter import should_apply
from tracker import log_application, get_today_count
from browser import create_browser, human_pause
from careers_bot import apply_to_career_site

APPLIED_LOG = "logs/applied_indeed.txt"

def _applied_indeed_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if active_profile and active_profile != "default":
            filename = f"logs/applied_indeed_{active_profile}.txt"
        else:
            filename = APPLIED_LOG
    except Exception:
        filename = APPLIED_LOG
    return os.path.join(script_dir, filename)

def load_applied() -> set:
    path = _applied_indeed_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()

def save_applied(job_url: str):
    path = _applied_indeed_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(job_url + "\n")

def build_rss_urls() -> list:
    """Build Indeed RSS feed URLs for each keyword × location combo."""
    importlib.reload(__import__("config.profile", fromlist=["profile"]))
    import config.profile
    keywords  = getattr(config.profile, "SEARCH_KEYWORDS",  ["Data Engineer"])
    locations = getattr(config.profile, "SEARCH_LOCATIONS", ["Bangalore"])
    urls = []
    for kw in keywords:
        for loc in locations:
            q = kw.replace(" ", "+")
            l = loc.replace(" ", "+")
            # fromage=1 → posted in last 1 day; sort=date → newest first
            urls.append(
                f"https://www.indeed.com/rss?q={q}&l={l}&sort=date&fromage=1"
            )
    return urls

def fetch_jobs_from_rss(rss_url: str, log_fn=print) -> list:
    """Parse an Indeed RSS feed and return list of job dicts."""
    try:
        feed = feedparser.parse(rss_url)
        jobs = []
        for entry in feed.entries:
            title   = entry.get("title", "")
            link    = entry.get("link", "")
            summary = entry.get("summary", "")
            company = ""
            if " - " in title:
                parts   = title.rsplit(" - ", 1)
                title   = parts[0].strip()
            # Try to extract company from source tag
            source = entry.get("source", {})
            if isinstance(source, dict):
                company = source.get("title", "")
            if not company and hasattr(entry, "tags"):
                for tag in entry.get("tags", []):
                    if tag.get("scheme", "").endswith("company"):
                        company = tag.get("term", "")
                        break
            jobs.append({
                "id":          link,
                "title":       title,
                "company":     company or "Unknown",
                "description": summary,
                "url":         link,
            })
        log_fn(f"[INDEED RSS] Gathered {len(jobs)} entries from feed: {rss_url[:60]}...")
        return jobs
    except Exception as e:
        log_fn(f"[INDEED RSS] Error reading feed {rss_url}: {e}")
        return []

def run_indeed_bot(max_applications: int = 15, headless: bool = False,
                   log_fn=print, stop_event=None):
    log_fn("\n" + "=" * 55 + "\n  INDEED RSS BOT RUNNER\n" + "=" * 55)

    import config.profile
    importlib.reload(config.profile)
    daily_limit = getattr(config.profile, "DAILY_LIMIT", 50)

    if get_today_count("Applied") >= daily_limit:
        log_fn(f"[STOP] Daily application limit of {daily_limit} reached.")
        return

    applied_jobs = load_applied()
    rss_urls     = build_rss_urls()
    all_jobs     = []

    for url in rss_urls:
        if stop_event and stop_event.is_set():
            break
        all_jobs.extend(fetch_jobs_from_rss(url, log_fn=log_fn))

    # Deduplicate by URL
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique_jobs.append(job)

    log_fn(f"[INDEED] Deduped down to {len(unique_jobs)} unique listings to analyze.")

    driver = None
    total_applied = 0

    try:
        for job in unique_jobs:
            if stop_event and stop_event.is_set():
                break
            if total_applied >= max_applications:
                break
            if get_today_count("Applied") >= daily_limit:
                break
            if job["url"] in applied_jobs:
                continue

            # Stage A Title-based fast filter
            do_apply, score, matched, reason, decision, missing = should_apply(
                job["title"], "", job["company"]
            )
            if not do_apply:
                log_fn(f"\n[FAST FILTER SKIP] {job['company']} — {job['title']}: {reason}")
                log_application(job["company"], job["title"], "Indeed", job["url"],
                                "Skipped", score, matched, skip_reason=reason, missing_skills=missing, decision=decision)
                continue

            # Open in browser to retrieve full job description
            if driver is None:
                driver = create_browser(headless=headless, profile_name="indeed")

            log_fn(f"\n[JOB] {job['company']} — {job['title']}...")
            try:
                driver.get(job["url"])
                human_pause(2.0, 4.0)

                # Attempt to extract full job description from Indeed layout
                description = ""
                for selector in ["div#jobDescriptionText", "div.jobsearch-JobComponent-description", "div.jobsearch-jobDescriptionText"]:
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, selector)
                        if el.is_displayed():
                            description = el.text.strip()
                            break
                    except Exception:
                        pass
                
                if not description:
                    # Fallback to general body text
                    description = driver.find_element(By.TAG_NAME, "body").text

                # Stage B Full matching score assessment
                do_apply, score, matched, reason, decision, missing = should_apply(
                    job["title"], description, job["company"]
                )

                if not do_apply or decision == "skip":
                    log_fn(f"  Skip: {reason}")
                    log_application(job["company"], job["title"], "Indeed", job["url"],
                                    "Skipped", score, matched, skip_reason=reason, missing_skills=missing, decision=decision)
                    continue

                if decision == "review":
                    log_fn(f"  [REVIEW QUEUE] {job['company']} — {job['title']} ({score:.0f}%) - Queued for review")
                    log_application(job["company"], job["title"], "Indeed", job["url"],
                                    "Review", score, matched, skip_reason=reason, missing_skills=missing, decision=decision)
                    save_applied(job["url"])
                    continue

                # Auto-apply!
                log_fn(f"  [MATCH] {score:.0f}% Match — Auto-Applying via direct ATS...")
                
                # Check redirects / final URL after page load
                current_url = driver.current_url
                success = apply_to_career_site(driver, current_url,
                                               company=job["company"], role=job["title"])
                status = "Applied" if success else "Manual Needed"
                log_application(job["company"], job["title"], "Indeed", job["url"],
                                status, score, matched, missing_skills=missing, decision=decision)
                if success:
                    save_applied(job["url"])
                    total_applied += 1
            except Exception as e:
                log_fn(f"  [ERROR] Processing job details failed: {e}")

            human_pause(1.0, 2.0)
    finally:
        if driver:
            driver.quit()
        log_fn(f"\n[INDEED DONE] Auto-applied to {total_applied} Indeed jobs.")
