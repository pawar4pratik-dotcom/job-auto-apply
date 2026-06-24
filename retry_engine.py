import csv
import os
import importlib
import time
import threading
from tracker import update_status, _tracker_path
from browser import create_browser, wait_for, click, fill, human_pause
from careers_bot import (
    detect_platform, set_log_fn,
    apply_workday, apply_greenhouse, apply_lever, apply_icims,
    apply_taleo, apply_successfactors, apply_smartrecruiters, apply_generic,
    apply_to_career_site,
)
from selenium.webdriver.common.by import By

# Global lock to prevent overlapping retry runs
_retry_lock = threading.Lock()
_active_retry_thread = None

def trigger_retry_thread(company: str, log_fn=print):
    """Start the retry worker thread for a company."""
    global _active_retry_thread
    if _active_retry_thread and _active_retry_thread.is_alive():
        log_fn("[WARN] Retry worker is already running. Please wait for the current run to finish.")
        return False
        
    _active_retry_thread = threading.Thread(
        target=retry_company_jobs,
        args=(company, log_fn),
        daemon=True
    )
    _active_retry_thread.start()
    return True

def retry_company_jobs(company: str, log_fn=print):
    """
    Find all Skipped or Manual Needed jobs in logs/job_applications.csv
    for `company` where Match % >= 20. Re-attempt application using browser.
    """
    if not _retry_lock.acquire(blocking=False):
        log_fn("[WARN] Retry worker lock active. Another thread is running.")
        return
        
    try:
        # Bind careers_bot's print to our log_fn
        set_log_fn(log_fn)
        
        # Reload config to get latest COMPANY_CREDENTIALS
        import config.profile
        importlib.reload(config.profile)
        company_credentials = getattr(config.profile, "COMPANY_CREDENTIALS", {})
        
        comp_lower = company.lower()
        creds = None
        for c, cr in company_credentials.items():
            if c.lower() in comp_lower or comp_lower in c.lower():
                creds = cr
                company = c
                comp_lower = c.lower()
                break
                
        if creds:
            log_fn(f"[INFO] Using company-specific credentials for '{company}': {creds.get('email')}")
        else:
            log_fn(f"[INFO] No company-specific credentials found for '{company}'. Fallback to default corporate profile or login-free apply.")
            
        # Read CSV log
        csv_path = _tracker_path()
        if not os.path.exists(csv_path):
            log_fn("[WARN] No job applications CSV found.")
            return
            
        jobs_to_retry = []
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("Status")
                comp_name = row.get("Company") or ""
                score_str = row.get("Match %") or "0%"
                url = row.get("URL") or ""
                
                try:
                    score = float(score_str.replace("%", "").strip())
                except ValueError:
                    score = 0
                    
                if (comp_lower in comp_name.lower() or comp_name.lower() in comp_lower) and status in ("Manual Needed", "Skipped") and score >= 20 and url:
                    jobs_to_retry.append((row.get("Role", "Unknown Role"), url))
                    
        if not jobs_to_retry:
            log_fn(f"[INFO] No skipped/stalled jobs with match >= 20% found for '{company}'.")
            return
            
        log_fn(f"\n[RETRY] Found {len(jobs_to_retry)} jobs to retry for '{company}' using custom credentials...")
        
        # Launch browser (run headfully so user can see and interact with it if needed)
        headless = False
        driver = None
        try:
            driver = create_browser(headless=headless, profile_name="retry_" + comp_lower)
        except Exception as e:
            log_fn(f"[ERROR] Failed to start browser for retry: {e}")
            return
            
        success_count = 0
        try:
            for role, url in jobs_to_retry:
                log_fn(f"\n[RETRYING] {company} -- {role}...")
                log_fn(f"  URL: {url}")
                
                try:
                    driver.get(url)
                    human_pause(2.0, 3.0)
                    
                    # Check if it is a Naukri page
                    if "naukri.com" in driver.current_url.lower():
                        log_fn("  [INFO] Naukri URL detected. Attempting to click Apply to get external redirect...")
                        # Try clicking apply button
                        applied = False
                        for sel in ["button.apply-button", ".applyBtn", ".apply-btn", "[class*='applyBtn']"]:
                            try:
                                btn = driver.find_element(By.CSS_SELECTOR, sel)
                                if btn.is_displayed():
                                    driver.execute_script("arguments[0].click();", btn)
                                    applied = True
                                    break
                            except Exception:
                                pass
                        if not applied:
                            try:
                                btn = driver.find_element(By.XPATH, "//button[contains(text(),'Apply')]")
                                if btn.is_displayed():
                                    driver.execute_script("arguments[0].click();", btn)
                                    applied = True
                            except Exception:
                                pass
                                
                        if applied:
                            human_pause(3.0, 5.0)
                            # Switch to new tab if opened
                            if len(driver.window_handles) > 1:
                                driver.switch_to.window(driver.window_handles[-1])
                                human_pause(2.0, 3.0)
                                
                    # Detect the ATS platform
                    current_url = driver.current_url
                    log_fn(f"  Current URL after load/redirect: {current_url}")
                    platform = detect_platform(current_url)
                    log_fn(f"  Platform detected: {platform.upper()}")
                    
                    applied_successfully = apply_to_career_site(
                        driver, current_url, company=company, role=role
                    )
                        
                    if applied_successfully:
                        log_fn(f"  [SUCCESS] Successfully applied to '{role}' at '{company}'!")
                        update_status(url, "Applied")
                        success_count += 1
                    else:
                        log_fn(f"  [FAIL] Failed to apply to '{role}' at '{company}'")
                        
                except Exception as ex:
                    log_fn(f"  [ERROR] Error retrying '{role}': {ex}")
                    
                # Close other tabs and switch back
                while len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    driver.close()
                driver.switch_to.window(driver.window_handles[0])
                human_pause(1.0, 2.0)
                
        finally:
            log_fn(f"\n[RETRY DONE] Completed retry run for '{company}'. Successfully applied to {success_count}/{len(jobs_to_retry)} jobs.")
            driver.quit()
            
    finally:
        # Reset careers_bot's print binding
        set_log_fn(None)
        _retry_lock.release()
