import time
import os
from selenium.webdriver.common.by import By
from browser import create_browser, wait_for, click, fill, human_pause, scroll_down
from filter import should_apply
from tracker import log_application
from config.profile import PROFILE, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES

APPLIED_LOG = "logs/applied_naukri.txt"

def load_applied():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, APPLIED_LOG)
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()

def save_applied(job_id):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, APPLIED_LOG)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(job_id + "\n")

def login(driver):
    print("[LOGIN] Logging into Naukri...")
    driver.get("https://www.naukri.com/nlogin/login")
    human_pause(2, 3)
    fill(driver, By.ID, "usernameField", PROFILE["naukri_email"])
    fill(driver, By.ID, "passwordField", PROFILE["naukri_password"])
    click(driver, By.XPATH, "//button[contains(text(),'Login')]")
    human_pause(3, 5)
    for _ in range(6):
        if "naukri.com" in driver.current_url and "login" not in driver.current_url:
            print("[OK] Naukri login successful")
            return True
        time.sleep(5)
    print("[FAIL] Naukri login failed. Verify credentials.")
    return False

def search_jobs(driver, keyword, location):
    print(f"\n[SEARCH] Searching: '{keyword}' in '{location}'")
    url = f"https://www.naukri.com/{keyword.lower().replace(' ', '-')}-jobs-in-{location.lower()}?experience=2&experience=5&jobAge1=1"
    driver.get(url)
    human_pause(3, 4)

def get_job_listings(driver):
    scroll_down(driver, 500)
    # Updated resilient selectors for modern Naukri DOM
    selectors = [
        "div[class*='jobTuple'], article[class*='jobTuple'], li[class*='jobTuple']",
        ".srp-jobtuple-wrapper",
        "[class*='jobTuple']"
    ]
    for sel in selectors:
        cards = driver.find_elements(By.CSS_SELECTOR, sel)
        if cards: return cards
    return []

def get_job_description(driver):
    selectors = [".dang-inner-html", ".job-desc", "[class*='description']", "[class*='jobDescription']", ".jd-container", "article"]
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                text = el.text.strip()
                if len(text) > 100: return text
        except Exception: continue
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        noise = ["naukri.com", "login", "register", "similar jobs", "recruiters", "©", "privacy policy"]
        lines = [line for line in body_text.split('\n') if len(line) > 20 and not any(n in line.lower() for n in noise)]
        return '\n'.join(lines[:50])
    except Exception:
        return ""

def get_job_details_naukri(driver, card):
    try:
        title_el = card.find_element(By.CSS_SELECTOR, "a.title")
        company_el = card.find_element(By.CSS_SELECTOR, ".comp-name, a.comp-name")
        url = title_el.get_attribute("href")
        job_id = card.get_attribute("data-job-id") or url
        title = title_el.text.strip()
        company = company_el.text.strip()
        
        # Safe tab management
        driver.execute_script("window.open(arguments[0]);", url)
        driver.switch_to.window(driver.window_handles[-1])
        human_pause(2, 3)
        description = get_job_description(driver)
        return job_id, title, company, description, url
    except Exception as e:
        print(f"  [WARN] Could not read Naukri job: {e}")
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        return None, None, None, None, None

def apply_naukri(driver):
    try:
        already_applied = driver.find_elements(By.XPATH, "//span[contains(text(), 'Applied') or contains(text(), 'Already Applied')]")
        if already_applied:
            print("  [SKIP] Already applied directly on Naukri.")
            return True
        
        applied = click(driver, By.CSS_SELECTOR, "button.apply-button, .applyBtn, .apply-btn, [class*='applyBtn']")
        if not applied:
            applied = click(driver, By.XPATH, "//button[contains(text(),'Apply') or contains(text(),'Apply on')]")
        
        human_pause(2.5, 4.0)
        
        # Close chatbot popup if it appears
        click(driver, By.CSS_SELECTOR, ".botCloseIcon, [class*='close'], [aria-label='Close']", timeout=2)
        
        # Confirm application
        confirm_btn = click(driver, By.XPATH, "//button[contains(text(),'Apply') or contains(text(),'Confirm')]", timeout=2)
        if confirm_btn:
            human_pause(1, 2)
            return True
    except Exception as e:
        print(f"  [WARN] Naukri apply error: {e}")
        return False
    return False

from tracker import get_today_count
from config.profile import DAILY_LIMIT

def run_naukri_bot(max_applications=20, headless=False, log_fn=print, stop_event=None):
    log_fn("\n" + "="*55 + "\n  NAUKRI AUTO-APPLY BOT\n" + "="*55)
    if get_today_count("Applied") >= DAILY_LIMIT:
        log_fn(f"[STOP] Daily limit of {DAILY_LIMIT} applications reached. Stopping.")
        return

    driver = create_browser(headless=headless, profile_name="naukri")
    applied_jobs = load_applied()
    total_applied = 0
    try:
        if not login(driver): return
        
        for keyword in SEARCH_KEYWORDS:
            if stop_event and stop_event.is_set():
                log_fn("[INFO] Stop signal received. Halting Naukri bot.")
                break
            for location in SEARCH_LOCATIONS:
                if stop_event and stop_event.is_set(): break
                if total_applied >= max_applications: break
                
                search_jobs(driver, keyword, location)
                cards = get_job_listings(driver)
                log_fn(f"  Found {len(cards)} jobs on search page")
                
                for card in cards:
                    if stop_event and stop_event.is_set(): break
                    if total_applied >= max_applications: break
                    
                    job_id, title, company, description, url = get_job_details_naukri(driver, card)
                    if not job_id: continue
                    
                    if job_id in applied_jobs:
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        continue
                    
                    log_fn(f"\n[JOB] {company} -- {title}")
                    do_apply, score, matched, reason = should_apply(title, description, company)
                    
                    if not do_apply:
                        log_fn(f"  Skip: {reason}")
                        log_application(company, title, "Naukri", url, "Skipped", score, matched, skip_reason=reason)
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        continue
                    
                    log_fn(f"  [MATCH] {score}% -- Applying...")
                    success = apply_naukri(driver)
                    if success:
                        log_fn("  [SUCCESS] Applied!")
                        log_application(company, title, "Naukri", url, "Applied", score, matched)
                        save_applied(job_id)
                        total_applied += 1
                    else:
                        log_fn("  [FAIL] Apply failed")
                        log_application(company, title, "Naukri", url, "Manual Needed", score, matched, skip_reason="Apply button click failed")
                    
                    # Safe tab cleanup
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    human_pause(2, 4)
    except KeyboardInterrupt:
        log_fn("\n[STOP] Naukri Bot stopped by user.")
    finally:
        log_fn(f"\n[DONE] Completed! Applied to {total_applied} jobs on Naukri.")
        driver.quit()