"""
core/apply_engine.py — Unified browser-based job application engine.

Replaces the duplicated 60-line apply blocks that previously existed
in both api_approve() and api_review_bulk_approve().

Key design:
  - Single _run_apply_for_url() handles LinkedIn / Naukri / ATS portals
  - Acquires _MAX_BROWSER_SEM before opening Chrome (max 3 concurrent)
  - Always quits driver in finally block (no leaked browser processes)
  - Updates tracker status on success/failure
"""
import time

from core.state import bot_log, _MAX_BROWSER_SEM


def _ensure_tracker_row(url, company, role, portal="Unknown", score=0):
    from tracker import get_all_rows, log_application
    urls = {r.get("URL", "").strip() for r in get_all_rows()}
    if url.strip() not in urls:
        log_application(
            company=company,
            role=role,
            portal=portal,
            url=url,
            status="Pending Apply",
            score=score,
            matched_skills=[],
            decision="auto"
        )


import concurrent.futures

APPLY_TIMEOUT_SEC = 180  # 3 min max per job


def run_apply_for_url(url: str, company: str, role: str) -> bool:
    """
    Execute an automated browser application for a single job URL with a 3-minute timeout.
    """
    portal = "LinkedIn" if "linkedin.com" in url.lower() else \
             "Naukri" if "naukri.com" in url.lower() else "Career Site"
    _ensure_tracker_row(url, company, role, portal)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run_apply_inner, url, company, role)
        try:
            return fut.result(timeout=APPLY_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            bot_log(f"  [ERROR] Apply timed out after {APPLY_TIMEOUT_SEC}s")
            from tracker import update_status
            update_status(url, "Manual Needed")
            return False


def _run_apply_inner(url: str, company: str, role: str) -> bool:
    """
    Execute an automated browser application for a single job URL.

    Portal detection:
      linkedin.com  → LinkedIn Easy Apply flow
      naukri.com    → Naukri Apply flow
      anything else → careers_bot ATS/Workday flow

    Returns True on successful application, False on failure.
    Thread-safe: uses semaphore to cap concurrent Chrome instances to 3.
    """
    from browser import create_browser
    from tracker import update_status

    bot_log(f"\n[APPLY ENGINE] {company} — {role}")
    bot_log(f"  URL: {url}")

    driver = None
    with _MAX_BROWSER_SEM:
        try:
            import config.profile as cp
            headless = getattr(cp, "HEADLESS_DEFAULT", True)
            url_lower = url.lower()

            if "linkedin.com" in url_lower:
                bot_log("  [PORTAL] LinkedIn Easy Apply")
                driver = create_browser(headless=headless, profile_name="linkedin")
                from linkedin_bot import login as linkedin_login, fill_easy_apply_form
                from selenium.webdriver.common.by import By
                linkedin_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                try:
                    desc = driver.find_element(By.TAG_NAME, "body").text
                except Exception:
                    desc = ""
                success = fill_easy_apply_form(
                    driver, job_description=desc, company=company, role=role, log_fn=bot_log
                )

            elif "naukri.com" in url_lower:
                bot_log("  [PORTAL] Naukri Apply")
                driver = create_browser(headless=headless, profile_name="naukri")
                from naukri_bot import login as naukri_login, apply_naukri
                naukri_login(driver, log_fn=bot_log)
                driver.get(url)
                time.sleep(3)
                success = apply_naukri(driver, log_fn=bot_log, company=company, role=role)

            else:
                bot_log("  [PORTAL] ATS/Careers portal")
                driver = create_browser(headless=headless, profile_name="approve_apply")
                driver.get(url)
                time.sleep(4)
                current_url = driver.current_url
                bot_log(f"  Loaded: {current_url}")
                from careers_bot import apply_to_career_site
                success = apply_to_career_site(driver, current_url, company=company, role=role)

            if success:
                bot_log(f"  [SUCCESS] Applied to '{role}' at '{company}'!")
                update_status(url, "Applied")
            else:
                bot_log(f"  [FAIL] Could not complete apply for '{role}' at '{company}'")
                update_status(url, "Manual Needed")

            return success

        except Exception as ex:
            import traceback
            bot_log(f"  [ERROR] Apply failed: {ex}\n{traceback.format_exc()[:400]}")
            update_status(url, "Manual Needed")
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
