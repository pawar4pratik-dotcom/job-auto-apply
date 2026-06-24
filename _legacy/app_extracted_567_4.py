import time
import os
from selenium.webdriver.common.by import By
from browser import create_browser, wait_for, click, fill, human_pause, scroll_down, dom_signature
from filter import should_apply
from tracker import log_application
from config.profile import PROFILE, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES, TECH_EXPERIENCE, WORK_PREFERENCES, COVER_LETTER

APPLIED_JOBS_LOG = "logs/applied_linkedin.txt"

def load_applied_jobs():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, APPLIED_JOBS_LOG)
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()

def save_applied_job(job_id):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(script_dir, APPLIED_JOBS_LOG)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(job_id + "\n")

def login(driver):
    print("[LOGIN] Logging into LinkedIn...")
    driver.get("https://www.linkedin.com/login")
    human_pause(2, 3)
    fill(driver, By.ID, "username", PROFILE["linkedin_email"])
    fill(driver, By.ID, "password", PROFILE["linkedin_password"])
    click(driver, By.XPATH, "//button[@type='submit']")
    human_pause(3, 5)
    for _ in range(6):
        if "feed" in driver.current_url or "mynetwork" in driver.current_url:
            print("[OK] LinkedIn login successful")
            return True
        elif "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            print("[WARNING] CAPTCHA / 2FA requested. Please complete it manually.")
            time.sleep(10)
        else:
            time.sleep(5)
    print("[FAIL] LinkedIn login failed")
    return False

def search_jobs(driver, keyword, location):
    print(f"\n🔍 Searching: '{keyword}' in '{location}'")
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={keyword.replace(' ', '%20')}&location={location.replace(' ', '%20')}&f_AL=true&sortBy=DD"
    driver.get(search_url)
    human_pause(3, 5)

def get_job_cards(driver):
    scroll_down(driver, 300)
    human_pause(1, 2)
    cards = driver.find_elements(By.CSS_SELECTOR, ".job-card-container")
    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, "[data-job-id]")
    return cards

def get_job_details(driver, card):
    try:
        job_id = card.get_attribute("data-job-id") or card.get_attribute("data-entity-urn") or ""
        if job_id.startswith("urn:li:fs_normalizedJobPosting:"):
            job_id = job_id.split(":")[-1]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
        card.click()
        human_pause(1.5, 2.5)
        title_el = wait_for(driver, By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__job-title h1")
        company_el = wait_for(driver, By.CSS_SELECTOR, ".job-details-jobs-unified-top-card__company-name")
        desc_el = wait_for(driver, By.CSS_SELECTOR, "#job-details")
        title = title_el.text.strip() if title_el else "Unknown Role"
        company = company_el.text.strip() if company_el else "Unknown Company"
        description = desc_el.text.strip() if desc_el else ""
        url = driver.current_url
        return job_id, title, company, description, url
    except Exception as e:
        print(f"  ⚠️ Could not read job details: {e}")
        return None, None, None, None, None

def get_label_for_field(driver, field):
    try:
        field_id = field.get_attribute("id")
        if field_id:
            labels = driver.find_elements(By.CSS_SELECTOR, f"label[for='{field_id}']")
            if labels: return labels[0].text.lower()
        parent = driver.execute_script("return arguments[0].closest('fieldset, div.fb-form-element, li')", field)
        if parent:
            leg = parent.find_elements(By.CSS_SELECTOR, "label, legend, span")
            if leg: return leg[0].text.lower()
    except Exception:
        pass
    return ""

def smart_answer_for_label(label_text):
    label = label_text.lower()
    for tech, years in TECH_EXPERIENCE.items():
        if tech in label: return years
    if "how many years" in label or "experience" in label: return PROFILE.get("total_experience_years", "5")
    if "first name" in label: return PROFILE["first_name"]
    if "last name" in label: return PROFILE["last_name"]
    if "email" in label: return PROFILE["email"]
    if "phone" in label or "mobile" in label: return PROFILE["phone"]
    if "city" in label: return PROFILE["city"]
    if "state" in label: return PROFILE["state"]
    if "country" in label: return PROFILE["country"]
    if "linkedin" in label: return PROFILE["linkedin_url"]
    if "github" in label: return PROFILE["github_url"]
    if "notice period" in label: return PROFILE.get("notice_period", "30")
    if "current ctc" in label or "current salary" in label: return PROFILE.get("current_ctc", "")
    if "expected ctc" in label or "expected salary" in label: return PROFILE.get("expected_ctc", "")
    return None

def smart_radio_answer(legend_text):
    text = legend_text.lower()
    if "authorized to work" in text or "right to work" in text: return "yes" if WORK_PREFERENCES.get("authorized_india", True) else "no"
    if "require sponsorship" in text or "visa sponsorship" in text: return "yes" if WORK_PREFERENCES.get("require_sponsorship", False) else "no"
    if "relocate" in text or "willing to relocate" in text: return "yes" if WORK_PREFERENCES.get("open_to_relocation", True) else "no"
    return "yes"

def smart_dropdown_answer(driver, drop_element, label_text):
    from selenium.webdriver.support.ui import Select
    try:
        s = Select(drop_element)
        label = label_text.lower()
        options = [(i, opt.text.strip()) for i, opt in enumerate(s.options) if opt.text.strip()]
        if "work mode" in label or "preferred work" in label:
            pref = WORK_PREFERENCES.get("preferred_work_mode", "Hybrid").lower()
            for idx, text in options:
                if pref in text.lower(): s.select_by_index(idx); return
        if "gender" in label:
            pref = WORK_PREFERENCES.get("gender", "Prefer not to say").lower()
            for idx, text in options:
                if pref in text.lower() or "not to say" in text.lower(): s.select_by_index(idx); return
        if options: s.select_by_index(options[0][0])
    except Exception:
        pass

from qa_store import get_answer, record_unanswered
from tracker import get_today_count
from config.profile import DAILY_LIMIT

def answer_questions(driver, portal="LinkedIn"):
    try:
        text_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='number'], input[type='email'], input[type='tel'], textarea")
        for field in text_fields:
            try:
                if not field.is_displayed() or field.get_attribute("value"): continue
                label = get_label_for_field(driver, field)
                answer = smart_answer_for_label(label) or (get_answer(label) if label else None)
                if not answer and label: record_unanswered(label, portal=portal)
                if answer:
                    field.clear()
                    for ch in str(answer):
                        try: field.send_keys(ch)
                        except: driver.execute_script("arguments[0].value = arguments[1];", field, str(answer)); break
                        time.sleep(0.02)
            except Exception: pass

        radio_groups = driver.find_elements(By.CSS_SELECTOR, "fieldset[data-test-form-builder-radio-button-form-component], fieldset.fb-text-selectable__container")
        for group in radio_groups:
            try:
                legend_els = group.find_elements(By.CSS_SELECTOR, "legend, label.fb-text-selectable__option")
                legend = legend_els[0].text if legend_els else ""
                target_answer = smart_radio_answer(legend)
                radios = group.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                for radio in radios:
                    if radio.is_selected(): break
                    rid = radio.get_attribute("id")
                    if not rid: continue
                    label_els = group.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                    if label_els and (label_els[0].text.strip().lower() == target_answer or target_answer in label_els[0].text.strip().lower()):
                        driver.execute_script("arguments[0].click();", radio)
                        human_pause(0.2, 0.4)
                        break
            except Exception: pass

        dropdowns = driver.find_elements(By.CSS_SELECTOR, "select")
        for drop in dropdowns:
            try:
                if not drop.is_displayed(): continue
                label = get_label_for_field(driver, drop)
                smart_dropdown_answer(driver, drop, label)
            except Exception: pass
    except Exception as e:
        print(f"  [WARN] Error answering questions: {e}")

def fill_easy_apply_form(driver, log_fn=print):
    try:
        applied = click(driver, By.CSS_SELECTOR, ".jobs-apply-button--top-card button") or click(driver, By.XPATH, "//button[contains(., 'Easy Apply')]")
        if not applied: return False
        human_pause(2, 3)
        
        last_sig, stall = None, 0
        for step in range(15): # Increased max steps slightly for complex forms
            answer_questions(driver)
            
            # Auto-fill Cover Letter if present
            try:
                cover_letter_area = wait_for(driver, By.CSS_SELECTOR, "textarea[aria-label*='cover letter']", timeout=1)
                if cover_letter_area and not cover_letter_area.get_attribute("value"):
                    cover_text = COVER_LETTER.format(exp=PROFILE["total_experience_years"], name=f"{PROFILE['first_name']} {PROFILE['last_name']}")
                    cover_letter_area.clear()
                    for ch in cover_text:
                        cover_letter_area.send_keys(ch)
                        time.sleep(0.01)
            except Exception: pass

            # Handle Resume Upload
            resume_input = wait_for(driver, By.CSS_SELECTOR, "input[type='file']", timeout=1)
            if resume_input and PROFILE.get("resume_path"):
                abs_path = os.path.abspath(PROFILE["resume_path"])
                if os.path.exists(abs_path):
                    resume_input.send_keys(abs_path)
                    human_pause(2, 3)

            # Check for Submit button
            if click(driver, By.CSS_SELECTOR, "button[aria-label='Submit application']", timeout=1) or \
               click(driver, By.XPATH, "//button[contains(., 'Submit application')]", timeout=1) or \
               click(driver, By.XPATH, "//button[contains(., 'Submit')]", timeout=1):
                human_pause(3, 4)
                click(driver, By.CSS_SELECTOR, "button[aria-label='Dismiss']")
                return True

            # Otherwise, click Next/Continue
            advanced = (
                click(driver, By.CSS_SELECTOR, "button[aria-label='Continue to next step']", timeout=1) or
                click(driver, By.CSS_SELECTOR, "button[aria-label='Next step']", timeout=1) or
                click(driver, By.XPATH, "//button[contains(., 'Next')]", timeout=1) or
                click(driver, By.XPATH, "//button[contains(., 'Continue')]", timeout=1) or
                click(driver, By.XPATH, "//button[contains(., 'Review')]", timeout=1)
            )
            
            sig = dom_signature(driver)
            if sig == last_sig:
                stall += 1
            else:
                stall = 0
            last_sig = sig
            
            if not advanced or stall >= 2:
                log_fn("  [WARN] Form stalled on an unanswered question — needs manual completion")
                click(driver, By.CSS_SELECTOR, "button[aria-label='Dismiss']")
                human_pause(1, 2)
                click(driver, By.XPATH, "//span[contains(text(), 'Discard')]/..")
                return False
            human_pause(1.5, 2.5)
            click(driver, By.CSS_SELECTOR, "button[aria-label='Dismiss']") # Dismiss completion modal if it pops up early
        return False
    except Exception as e:
        log_fn(f"  [WARN] Easy Apply error: {e}")
        return False

def run_linkedin_bot(max_applications=20, headless=False, log_fn=print, stop_event=None):
    log_fn("\n" + "="*55 + "\n  LINKEDIN AUTO-APPLY BOT\n" + "="*55)
    if get_today_count("Applied") >= DAILY_LIMIT:
        log_fn(f"[STOP] Daily limit of {DAILY_LIMIT} applications reached. Stopping.")
        return

    driver = create_browser(headless=headless, profile_name="linkedin")
    applied_jobs = load_applied_jobs()
    total_applied = 0
    try:
        if not login(driver): return
        
        for keyword in SEARCH_KEYWORDS:
            if stop_event and stop_event.is_set():
                log_fn("[INFO] Stop signal received. Halting LinkedIn bot.")
                break
            for location in SEARCH_LOCATIONS:
                if stop_event and stop_event.is_set(): break
                if total_applied >= max_applications: break
                
                search_jobs(driver, keyword, location)
                cards = get_job_cards(driver)
                log_fn(f"  Found {len(cards)} job listings")
                
                for card in cards:
                    if stop_event and stop_event.is_set(): break
                    if total_applied >= max_applications: break
                    
                    job_id, title, company, description, url = get_job_details(driver, card)
                    if not job_id or job_id in applied_jobs: continue
                    
                    log_fn(f"\n[JOB] {company} -- {title}")
                    do_apply, score, matched, reason = should_apply(title, description, company)
                    
                    if not do_apply:
                        log_fn(f"  Skip: {reason}")
                        log_application(company, title, "LinkedIn", url, "Skipped", score, matched, skip_reason=reason)
                        continue
                    
                    log_fn(f"  [MATCH] {score}% -- Auto-Applying...")
                    success = fill_easy_apply_form(driver, log_fn=log_fn)
                    if success:
                        log_fn("  [SUCCESS] Successfully Applied!")
                        log_application(company, title, "LinkedIn", url, "Applied", score, matched)
                        save_applied_job(job_id)
                        total_applied += 1
                        human_pause(3, 6)
                    else:
                        log_fn("  [FAIL] Apply failed (requires manual completion)")
                        log_application(company, title, "LinkedIn", url, "Manual Needed", score, matched, skip_reason="Form stalled")
    except KeyboardInterrupt:
        log_fn("\n[STOP] LinkedIn Bot stopped by user.")
    finally:
        log_fn(f"\n[DONE] Completed! Applied to {total_applied} jobs on LinkedIn.")
        driver.quit()