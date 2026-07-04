"""
linkedin_bot.py — Auto search + apply on LinkedIn Easy Apply jobs
"""

import time
import os
import re
import json
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from browser import create_browser, wait_for, click, fill, human_pause, scroll_down, dom_signature
from filter import should_apply
from tracker import log_application
import config.profile

BLACKLISTED_MODELS = set()

# Initial placeholder globals
PROFILE = {}
SEARCH_KEYWORDS = []
SEARCH_LOCATIONS = []
TARGET_COMPANIES = []
TECH_EXPERIENCE = {}
WORK_PREFERENCES = {}
COVER_LETTER = ""
MY_SKILLS = []

def reload_profile_globals():
    global PROFILE, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES, TECH_EXPERIENCE, WORK_PREFERENCES, COVER_LETTER, MY_SKILLS
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        PROFILE = getattr(config.profile, "PROFILE", {})
        SEARCH_KEYWORDS = getattr(config.profile, "SEARCH_KEYWORDS", [])
        SEARCH_LOCATIONS = getattr(config.profile, "SEARCH_LOCATIONS", [])
        TARGET_COMPANIES = getattr(config.profile, "TARGET_COMPANIES", [])
        TECH_EXPERIENCE = getattr(config.profile, "TECH_EXPERIENCE", {})
        WORK_PREFERENCES = getattr(config.profile, "WORK_PREFERENCES", {})
        COVER_LETTER = getattr(config.profile, "COVER_LETTER", "")
        MY_SKILLS = getattr(config.profile, "MY_SKILLS", [])
    except Exception:
        pass

# Populate initial values
reload_profile_globals()

APPLIED_JOBS_LOG = "logs/applied_linkedin.txt"


def _applied_jobs_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if active_profile and active_profile != "default":
            filename = f"logs/applied_linkedin_{active_profile}.txt"
        else:
            filename = APPLIED_JOBS_LOG
    except Exception:
        filename = APPLIED_JOBS_LOG
    return os.path.join(script_dir, filename)


def load_applied_jobs():
    """Load set of already-applied job IDs so we don't apply twice."""
    log_path = _applied_jobs_path()
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()


def save_applied_job(job_id):
    log_path = _applied_jobs_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(job_id + "\n")


def _skipped_jobs_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import config.profile
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "")
        if active_profile:
            filename = f"logs/skipped_linkedin_{active_profile}.txt"
        else:
            filename = "logs/skipped_linkedin.txt"
    except Exception:
        filename = "logs/skipped_linkedin.txt"
    return os.path.join(script_dir, filename)


def load_skipped_jobs():
    """Load set of already-skipped job IDs to speed up future runs."""
    log_path = _skipped_jobs_path()
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()


def save_skipped_job(job_id):
    if not job_id:
        return
    log_path = _skipped_jobs_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        skipped = load_skipped_jobs()
        if job_id not in skipped:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(job_id + "\n")
    except Exception:
        pass


def extract_job_id_from_url(url: str) -> str:
    if not url:
        return ""
    m = re.search(r'/jobs/view/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]currentJobId=(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'(\d{9,12})', url)
    if m:
        return m.group(1)
    return ""


def login(driver, log_fn=print):
    """Log into LinkedIn."""
    email = PROFILE.get("linkedin_email", "").strip()
    password = PROFILE.get("linkedin_password", "").strip()
    if not email or not password:
        log_fn("[ERROR] LinkedIn credentials (email or password) are empty. Please configure them in the Profiles tab.")
        return False

    log_fn("[LOGIN] Logging into LinkedIn...")
    driver.get("https://www.linkedin.com/login")
    human_pause(2, 3)

    if "feed" in driver.current_url or "mynetwork" in driver.current_url or is_logged_in(driver):
        log_fn("[OK] LinkedIn already logged in via active session.")
        return True

    fill(driver, By.ID, "username", email)
    fill(driver, By.ID, "password", password)
    click(driver, By.XPATH, "//button[@type='submit']")
    human_pause(3, 5)

    # Allow users to resolve 2FA / CAPTCHA manually if prompted
    for check in range(24):
        if "feed" in driver.current_url or "mynetwork" in driver.current_url:
            log_fn("[OK] LinkedIn login successful")
            return True
        elif "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            log_fn("[WARNING] CAPTCHA / 2FA requested. Please complete it manually in the browser window.")
            time.sleep(10)
        else:
            time.sleep(5)
            
    # Final check
    if "feed" in driver.current_url or "mynetwork" in driver.current_url:
        log_fn("[OK] LinkedIn login successful")
        return True
        
    log_fn("[FAIL] LinkedIn login timed out or failed — check your credentials in config/profile.py")
    return False


def is_logged_in(driver) -> bool:
    """Helper to detect if the browser is currently logged into LinkedIn."""
    try:
        curr_url = driver.current_url.lower()
        if "feed" in curr_url or "mynetwork" in curr_url or "messaging" in curr_url:
            return True
        me_el = driver.find_elements(By.CSS_SELECTOR, ".global-nav__me, #global-nav-typeahead, button[class*='nav__button-sidebar']")
        if any(el.is_displayed() for el in me_el):
            return True
        sign_in_el = driver.find_elements(By.XPATH, "//a[contains(text(), 'Sign in') or contains(text(), 'Log in')]")
        if any(el.is_displayed() for el in sign_in_el):
            return False
        return len(me_el) > 0
    except Exception:
        return False


def search_jobs(driver, keyword, location, log_fn=print):
    """Search for jobs on LinkedIn."""
    # Anti-bot humanized pacing: wait before starting a new search
    human_pause(2.0, 4.0)
    log_fn(f"\n🔍 Searching: '{keyword}' in '{location}'")

    import urllib.parse
    search_url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={urllib.parse.quote(keyword)}"
        f"&location={urllib.parse.quote(location)}"
        f"&f_AL=true"  # Easy Apply filter ON
        f"&f_TPR=r604800"  # Past 7 days only
        f"&sortBy=DD"  # Sort by most recent
    )
    driver.get(search_url)
    human_pause(2.5, 4.0)

    # Check if we got logged out
    if not is_logged_in(driver):
        log_fn("[INFO] Detected logged-out state after search navigation. Triggering self-healing login...")
        login(driver, log_fn=log_fn)
        driver.get(search_url)
        human_pause(2.0, 4.0)

    # Challenge / verification wall detection
    for check in range(6):
        curr_url = driver.current_url.lower()
        if "challenge" in curr_url or "checkpoint" in curr_url or "security" in curr_url:
            log_fn("[WARNING] LinkedIn verification/CAPTCHA detected! Please resolve it manually in the Chrome window.")
            time.sleep(10)
        else:
            break


def get_job_cards(driver):
    """Return list of job card elements on current search page."""
    # Progressive scrolling to load lazy-loaded cards
    for _ in range(2):
        scroll_down(driver, 800)
        human_pause(0.4, 0.8)

    # Try multiple selectors in order of preference
    for selector in [
        "div[data-row-unique-id]",
        ".scaffold-layout__list-item",
        ".job-card-container",
        "[data-job-id]",
        ".jobs-search-results__list-item",
        "li.jobs-search-results__list-item",
        "div[class*='job-card-container']",
        "div[class*='job-card-list__entity-lockup']",
    ]:
        cards = driver.find_elements(By.CSS_SELECTOR, selector)
        if cards:
            return cards
    return []


def get_job_details(driver, card, log_fn=print):
    """Click a job card and return (job_id, title, company, description, url, posted_date)."""
    try:
        # 1. Close any stuck modal first to clear the UI
        close_stuck_modal_if_any(driver, log_fn)

        job_id = card.get_attribute("data-job-id") or card.get_attribute("data-entity-urn") or ""
        if job_id.startswith("urn:li:fs_normalizedJobPosting:"):
            job_id = job_id.split(":")[-1]

        if not job_id:
            for sel in ["a.job-card-list__title", "a.job-card-container__link", "a[class*='job-card']", "a"]:
                try:
                    link = card.find_element(By.CSS_SELECTOR, sel)
                    href = link.get_attribute("href") or ""
                    extracted = extract_job_id_from_url(href)
                    if extracted:
                        job_id = extracted
                        break
                except Exception:
                    pass

        # 2. Find a specific clickable element inside the card rather than clicking the outer card itself
        click_target = None
        for sel in [
            "a.job-card-list__title",
            "a.job-card-container__link",
            "a[class*='job-card']",
            ".job-card-list__title",
            ".job-card-container__link"
        ]:
            try:
                el = card.find_element(By.CSS_SELECTOR, sel)
                if el and el.is_displayed():
                    click_target = el
                    break
            except Exception:
                pass

        if click_target is None:
            click_target = card

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", click_target)
        try:
            click_target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", click_target)
        
        # 3. Wait for the detail pane to update
        detail_loaded = False
        start_time = time.time()
        while time.time() - start_time < 4:
            title_selectors = [
                ".job-details-jobs-unified-top-card__job-title h1",
                ".job-details-jobs-unified-top-card__job-title",
                "h1.t-24",
                ".jobs-unified-top-card__job-title h1",
                ".jobs-unified-top-card__job-title",
                "h1[class*='job-title']",
                "h1[class*='title']",
                "h1"
            ]
            for sel in title_selectors:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    t = el.text.strip()
                    if t and len(t) > 3:
                        detail_loaded = True
                        break
                except Exception:
                    pass
            if detail_loaded:
                break
            time.sleep(0.15)

        # ── Title: try multiple selectors in order ──────────────────────────
        title = ""
        title_selectors = [
            ".job-details-jobs-unified-top-card__job-title h1",
            ".job-details-jobs-unified-top-card__job-title",
            "h1.t-24",
            ".jobs-unified-top-card__job-title h1",
            ".jobs-unified-top-card__job-title",
            "h1[class*='job-title']",
            "h1[class*='title']",
            ".topcard__title",
            "h1",
        ]
        for sel in title_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip()
                    if t and len(t) > 3:
                        title = t
                        break
            except Exception:
                pass
            if title:
                break

        # ── Company: try multiple selectors ────────────────────────────────
        company = ""
        company_selectors = [
            ".job-details-jobs-unified-top-card__company-name",
            ".jobs-unified-top-card__company-name",
            ".topcard__org-name-link",
            ".topcard__flavor a",
            ".jobs-unified-top-card__subtitle-primary-grouping a",
            "[data-test-employer-name]",
            ".job-details-jobs-unified-top-card__primary-description a",
            "a[class*='company']",
            ".artdeco-entity-lockup__subtitle",
        ]
        for sel in company_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    c = el.text.strip()
                    if c and len(c) > 1:
                        company = c
                        break
            except Exception:
                pass
            if company:
                break

        # ── Description ────────────────────────────────────────────────────
        description = ""
        desc_selectors = [
            "#job-details",
            ".jobs-description__content",
            ".jobs-box__html-content",
            ".description__text",
            ".jobs-description",
            "[class*='jobs-description']",
            ".job-desc",
            ".jobs-box"
        ]
        for sel in desc_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    desc_text = driver.execute_script("return (arguments[0].innerText || arguments[0].textContent || '').strip();", el)
                    if desc_text and len(desc_text) > 50:
                        description = desc_text
                        break
                if description:
                    break
            except Exception:
                pass

        # ── Posted Date ────────────────────────────────────────────────────
        posted_date = ""
        posted_selectors = [
            ".jobs-unified-top-card__posted-date",
            ".job-details-jobs-unified-top-card__primary-description-without-tagline span",
            "span[class*='posted-date']",
            "span[class*='time-ago']",
            ".topcard__flavor--metadata time",
            "time",
        ]
        for sel in posted_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip() or el.get_attribute("datetime") or ""
                    if t and any(kw in t.lower() for kw in ["day", "hour", "week", "month", "ago", "just", "minute", "2025", "2026", "2024"]):
                        posted_date = t
                        break
            except Exception:
                pass
            if posted_date:
                break

        url = driver.current_url

        if not job_id:
            job_id = extract_job_id_from_url(url)

        if job_id:
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"

        if not title:
            title = "Unknown Role"
        if not company:
            company = "Unknown Company"

        return job_id, title, company, description, url, posted_date

    except Exception as e:
        try:
            print(f"  ⚠️ Could not read job details: {str(e)}")
        except Exception:
            print("  ⚠️ Could not read job details (encoding error in exception message)")
        return None, None, None, None, None, ""


def get_label_for_field(driver, field):
    """Return the label text associated with a form input field."""
    try:
        # A. Try standard 'for' attribute
        field_id = field.get_attribute("id")
        if field_id:
            labels = driver.find_elements(By.CSS_SELECTOR, f"label[for='{field_id}']")
            if labels:
                txt = labels[0].text.strip().lower()
                if txt and txt not in ["required", "optional", "*", "required field", "optional field"]:
                    return txt
        
        # B. Check parent containers
        parent = driver.execute_script(
            "return arguments[0].closest('fieldset, div, li, td, tr, [class*=\"question\"], [class*=\"row\"], [class*=\"field\"]');", 
            field
        )
        if parent:
            # 1. Search for explicit labels, legends, or spans
            for tag in ["label", "legend", "span", "p"]:
                els = parent.find_elements(By.CSS_SELECTOR, tag)
                for el in els:
                    if el.is_displayed():
                        txt = el.text.strip()
                        txt_lower = txt.lower()
                        if txt_lower in ["required", "optional", "*", "required field", "optional field"]:
                            continue
                        if txt and 2 < len(txt) < 150:
                            return txt.lower()
            # 2. Check divs with label-like classes
            divs = parent.find_elements(By.CSS_SELECTOR, "div")
            for div in divs:
                if div.is_displayed():
                    cls = (div.get_attribute("class") or "").lower()
                    if "label" in cls or "question" in cls or "title" in cls or "text" in cls:
                        txt = div.text.strip()
                        txt_lower = txt.lower()
                        if txt_lower in ["required", "optional", "*", "required field", "optional field"]:
                            continue
                        if txt and 2 < len(txt) < 150:
                            return txt.lower()
    except Exception:
        pass
    return ""


def _has_year_keyword(label: str) -> bool:
    label_lower = label.lower()
    return any(k in label_lower for k in ["year", "yr", "yaer"])


def _has_experience_keyword(label: str) -> bool:
    label_lower = label.lower()
    for k in ["experience", "experinece", "experiance"]:
        if k in label_lower:
            return True
    if "exp" in label_lower:
        import re
        if re.search(r'\bexp\b|\bexp\.', label_lower):
            return True
        if not any(x in label_lower for x in ["expect", "expense", "export"]):
            return True
    return False


_gemini_quota_exhausted = False

def ask_gemini_resolver(question: str, field_type: str = "text") -> str:
    """Uses Gemini 1.5/2.0/2.5 Flash to intelligently answer screening questions."""
    global _gemini_quota_exhausted
    if _gemini_quota_exhausted:
        return ""
    import config.profile
    api_key = getattr(config.profile, "GEMINI_API_KEY", None)
    if not api_key:
        return ""
        
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # Build safe profile copy for context without exposure of login credentials
        profile_data = {
            "profile": {k: v for k, v in config.profile.PROFILE.items() if "password" not in k},
            "skills": config.profile.MY_SKILLS,
            "tech_experience": config.profile.TECH_EXPERIENCE,
            "preferences": getattr(config.profile, "WORK_PREFERENCES", {})
        }
        
        prompt = f"""
        You are an automated job application assistant representing this candidate:
        {json.dumps(profile_data, indent=2)}
        
        Answer the following question from a job recruiter form:
        Question: "{question}"
        Field Type: {field_type} (text, radio, or dropdown)
        
        Instructions:
        - Return ONLY the exact answer as a plain string. No conversational filler, introduction, or explanations.
        - If it's a numeric question (e.g., "years of experience"), return only a number (e.g., "4" or "4.6").
        - If it's yes/no, return exactly "yes" or "no".
        """
        
        import time
        models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
        
        for model_name in models_to_try:
            retries = 3
            for attempt in range(retries):
                try:
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    ans = response.text.strip()
                    if ans.startswith("`") or ans.endswith("`") or ans.startswith('"') or ans.endswith('"'):
                        ans = ans.replace("`", "").replace('"', '').strip()
                    return ans
                except Exception as e:
                    err_msg = str(e).lower()
                    is_rate_limit = any(x in err_msg for x in ["429", "quota", "resourceexhausted", "rate", "limit"])
                    if is_rate_limit:
                        if "quota" in err_msg or "limit exceeded" in err_msg or "daily" in err_msg:
                            print(f"  [AI-WARN] Gemini daily/quota limit hit. Disabling Gemini for this session to run fast.")
                            _gemini_quota_exhausted = True
                            return ""
                        sleep_time = (attempt + 1) * 5.0
                        print(f"  [AI-WARN] Model {model_name} rate-limited. Sleeping {sleep_time}s before retry... (Attempt {attempt+1}/{retries})")
                        time.sleep(sleep_time)
                        continue
                    else:
                        print(f"  [AI-WARN] Model {model_name} failed: {e}")
                        break
            if _gemini_quota_exhausted:
                return ""
        raise Exception("All Gemini models rate-limited or failed.")
    except Exception as e:
        print(f"  [AI-ERROR] Gemini resolver failed: {e}")
        return ""


def smart_answer_for_label(label_text):
    """
    Given a label string, return the best text answer value using profile data.
    Returns None if no smart match found. (Local rules only; caller handles AI fallback).
    """
    label = label_text.lower()

    # --- Technology-specific experience (e.g. "Years of Python experience" or just "Python") ---
    for tech, years in TECH_EXPERIENCE.items():
        if re.search(r'\b' + re.escape(tech) + r'\b', label):
            if _has_year_keyword(label) or _has_experience_keyword(label) or len(label.strip()) <= len(tech) + 3:
                return years

    # --- General experience ---
    if (_has_year_keyword(label) or _has_experience_keyword(label)) and any(k in label for k in ["total", "overall", "data", "work"]):
        return PROFILE.get("total_experience_years", "5")
    if _has_year_keyword(label) or _has_experience_keyword(label):
        return PROFILE.get("total_experience_years", "5")

    # --- Salary / CTC ---
    if ("expected" in label or "desired" in label) and ("salary" in label or "ctc" in label or "compensation" in label or "package" in label):
        return PROFILE.get("expected_ctc", "22")
    if ("current" in label) and ("salary" in label or "ctc" in label):
        return PROFILE.get("current_ctc", "15")
    if "salary" in label or "ctc" in label or "compensation" in label:
        return PROFILE.get("expected_ctc", "22")

    # --- Notice period / Join date / Availability ---
    if "notice" in label or "join" in label or "immediate" in label:
        return PROFILE.get("notice_period", "30")

    # --- LinkedIn / URLs ---
    if "linkedin" in label:
        return PROFILE.get("linkedin_url", "")
    if "github" in label or "portfolio" in label or "website" in label:
        return PROFILE.get("github_url", "")

    # --- Phone / Mobile ---
    if "phone" in label or "mobile" in label or "contact" in label:
        return PROFILE.get("phone", "")

    # --- Email ---
    if "email" in label or "e-mail" in label or "mail address" in label:
        return PROFILE.get("email", "")

    # --- Skills / Technology ---
    if "skill" in label or "tool" in label or "technology" in label or "technologies" in label:
        return ", ".join(MY_SKILLS[:8])

    # --- City / Location ---
    if "city" in label or "location" in label or "current location" in label:
        return PROFILE.get("city", "")

    # --- Cover letter / summary ---
    if "cover" in label or "letter" in label or "summary" in label or "about yourself" in label:
        name = f"{PROFILE.get('first_name','')} {PROFILE.get('last_name','')}"
        exp = PROFILE.get('total_experience_years', '5')
        return COVER_LETTER.format(exp=exp, name=name)

    return None


def smart_radio_answer(legend_text):
    """
    Return 'yes' or 'no' for a radio button question based on question text and WORK_PREFERENCES.
    (Local rules only; caller handles AI fallback).
    """
    q = legend_text.lower()

    # Sponsorship / Visa
    if any(k in q for k in ["sponsor", "visa sponsor", "require work permit", "work permit", "immigration"]):
        return "no" if not WORK_PREFERENCES.get("require_sponsorship") else "yes"

    # Authorization to work
    if any(k in q for k in ["authorized", "eligible to work", "right to work", "legally allowed", "work authorization"]):
        if "india" in q or "in india" in q:
            return "yes" if WORK_PREFERENCES.get("authorized_india") else "no"
        return "yes"

    # Criminal record
    if any(k in q for k in ["felony", "convicted", "criminal"]):
        return "no"

    # Consent to screenings (Background check / Drug test / Physical fitness)
    if any(k in q for k in ["drug test", "drug-test", "background check", "background screen", "willing to undergo", "physically fit"]):
        return "yes"

    # Relocation
    if any(k in q for k in ["relocat", "willing to move", "open to relocation"]):
        return "yes" if WORK_PREFERENCES.get("open_to_relocation") else "no"

    # Urgency / Start date / Availability
    if any(k in q for k in ["start immediately", "immediately", "immediate start", "can you start"]):
        return "yes"

    # 18+ age
    if any(k in q for k in ["18 years", "at least 18", "legal age"]):
        return "yes"

    # Confidentiality / NDA agreement
    if any(k in q for k in ["agree", "acknowledge", "confirm", "certify"]):
        return "yes"

    # Default: None (check QA store / record unanswered instead of guessing yes)
    return None


def smart_dropdown_answer(driver, dropdown_el, label_text, log_fn=print, portal="LinkedIn"):
    """
    Select the most appropriate option from a dropdown based on the label context.
    """
    from selenium.webdriver.support.ui import Select
    try:
        s = Select(dropdown_el)
        options = [(i, o.text.strip()) for i, o in enumerate(s.options) if o.text.strip() and o.text.strip() != 'Select an option']
        label = label_text.lower()

        def select_and_log(idx, txt, is_auto_rule=False):
            s.select_by_index(idx)
            log_fn(f"  [FORM] Selected dropdown '{label_text}' -> '{txt}'")
            if is_auto_rule:
                save_auto_answered(label_text, txt, portal=portal)

        # 1. Check Q&A store first (user overrides take precedence)
        qa_ans = get_answer(label_text, driver=driver)
        if qa_ans == "__MANUAL__":
            log_fn(f"  [FORM] Dropdown '{label_text}' is marked as MANUAL. Skipping auto-fill.")
            return
        if qa_ans:
            for i, text in options:
                if qa_ans.lower() in text.lower() or text.lower() in qa_ans.lower():
                    select_and_log(i, text)
                    return

        # 2. Try standard rules FIRST (fast, no API calls)
        # Work mode preference
        if "work mode" in label or "work type" in label or "remote" in label:
            pref = WORK_PREFERENCES.get("preferred_work_mode", "Hybrid").lower()
            for i, text in options:
                if pref in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Gender
        if "gender" in label:
            target = WORK_PREFERENCES.get("gender", "Prefer not to say").lower()
            for i, text in options:
                if "prefer not" in text.lower() or "decline" in text.lower() or target in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Ethnicity / Race
        if "ethnic" in label or "race" in label:
            for i, text in options:
                if "decline" in text.lower() or "prefer not" in text.lower() or "not specified" in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Disability
        if "disab" in label:
            for i, text in options:
                if "no" in text.lower() or "not" in text.lower() or "decline" in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Veteran
        if "veteran" in label:
            for i, text in options:
                if "not" in text.lower() or "no" in text.lower() or "decline" in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Country
        if "country" in label:
            for i, text in options:
                if "india" in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Relocation
        if "relocat" in label or "willing to move" in label:
            target = "yes" if WORK_PREFERENCES.get("open_to_relocation") else "no"
            if "assistance" in label or "help" in label or "reimbursement" in label:
                target = "no"
            for i, text in options:
                if target in text.lower():
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # Salary (pick range closest to expected)
        if "salary" in label or "ctc" in label or "compensation" in label:
            expected_val = PROFILE.get("expected_ctc", "18")
            try:
                expected_num = float(expected_val)
                for i, text in options:
                    import re
                    nums = [float(n.replace(',', '')) for n in re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', text)]
                    if not nums:
                        continue
                    norm_nums = [n / 100000.0 if n >= 100000 else n for n in nums]
                    if len(norm_nums) == 1:
                        if abs(norm_nums[0] - expected_num) <= 2:
                            select_and_log(i, text, is_auto_rule=True)
                            return
                    elif len(norm_nums) >= 2:
                        if norm_nums[0] <= expected_num <= norm_nums[1]:
                            select_and_log(i, text, is_auto_rule=True)
                            return
            except Exception:
                pass
            
            expected = int(PROFILE.get("expected_ctc", "18"))
            for i, text in options:
                for kw in [str(expected), str(expected - 1), str(expected + 1)]:
                    if kw in text:
                        select_and_log(i, text, is_auto_rule=True)
                        return

        # Dates (From / To / Start / End)
        if "from" in label or "start" in label:
            if "year" in label:
                for i, text in options:
                    if "2022" in text or "2021" in text or "2020" in text:
                        select_and_log(i, text, is_auto_rule=True)
                        return
            elif "month" in label:
                for i, text in options:
                    if "june" in text.lower() or "06" in text or "jun" in text.lower():
                        select_and_log(i, text, is_auto_rule=True)
                        return
                        
        if "to" in label or "end" in label:
            if "year" in label:
                for i, text in options:
                    if "present" in text.lower() or "current" in text.lower() or "2026" in text or "2025" in text:
                        select_and_log(i, text, is_auto_rule=True)
                        return
            elif "month" in label:
                for i, text in options:
                    if "present" in text.lower() or "current" in text.lower() or "june" in text.lower() or "06" in text or "jun" in text.lower():
                        select_and_log(i, text, is_auto_rule=True)
                        return

        # Experience / Years of experience general rule
        if "experience" in label and ("year" in label or "yrs" in label):
            years_val = str(PROFILE.get("total_experience_years", "4"))
            for i, text in options:
                import re
                nums = re.findall(r'\d+', text)
                if nums and str(years_val) in nums:
                    select_and_log(i, text, is_auto_rule=True)
                    return

        # ── AI Fallback (LAST resort — only if no rule matched) ──
        import config.profile
        if getattr(config.profile, "GEMINI_API_KEY", None):
            opts_str = ", ".join(f"'{txt}'" for _, txt in options)
            prompt = f"Given the dropdown question '{label_text}' and options [{opts_str}], which option is the best fit?"
            ai_ans = ask_gemini_resolver(prompt, "dropdown")
            if ai_ans:
                ai_ans_lower = ai_ans.lower().strip()
                for i, text in options:
                    t_lower = text.lower()
                    if ai_ans_lower in t_lower or t_lower in ai_ans_lower:
                        select_and_log(i, text, is_auto_rule=True)
                        return

        # Yes/No dropdowns — pick Yes
        for i, text in options:
            if text.lower() in ["yes", "true", "agree"]:
                select_and_log(i, text, is_auto_rule=True)
                return

        # Record unanswered dropdown (no smart fallback chosen)
        log_fn(f"  [FORM] No match for dropdown '{label_text}'. Recording as unanswered.")
        record_unanswered(label_text, portal=portal)
    except Exception:
        pass


from qa_store import get_answer, record_unanswered, save_auto_answered
from tracker import get_today_count
from config.profile import DAILY_LIMIT


def answer_questions(driver, portal="LinkedIn", log_fn=print):
    """Intelligently fills all form fields, radio groups, and dropdowns on the current step."""
    try:
        # ── 1. TEXT / NUMBER INPUTS ──────────────────────────
        text_fields = driver.find_elements(
            By.CSS_SELECTOR, 
            "input[type='text'], input[type='number'], input[type='email'], input[type='tel'], textarea"
        )
        for field in text_fields:
            try:
                if not field.is_displayed():
                    continue

                label = get_label_for_field(driver, field)
                if not label:
                    label = (field.get_attribute("placeholder") or "").strip().lower()
                
                # -- Contact fields (email / phone): always verify and force correct value --
                contact_targets = {
                    "email": PROFILE.get("email", ""),
                    "e-mail": PROFILE.get("email", ""),
                    "mail address": PROFILE.get("email", ""),
                    "phone": PROFILE.get("phone", ""),
                    "mobile": PROFILE.get("phone", ""),
                    "contact number": PROFILE.get("phone", ""),
                }
                contact_val = None
                if label:
                    for key, val in contact_targets.items():
                        if key in label:
                            contact_val = val
                            break
                if contact_val:
                    current = (field.get_attribute("value") or "").strip()
                    if current != contact_val.strip():
                        try:
                            field.clear()
                            field.send_keys(contact_val)
                            log_fn(f"  [FORM] Set contact '{label}' -> '{contact_val}'")
                        except Exception:
                            pass
                    continue  # Done with this contact field

                # -- Skip already-filled non-contact fields --
                if field.get_attribute("value"):
                    continue
                
                # A. Try persistent Q&A store first (user overrides take precedence)
                answer = get_answer(label, driver=driver) if label else ""

                if answer == "__MANUAL__":
                    log_fn(f"  [FORM] Field '{label}' is marked as MANUAL. Skipping auto-fill.")
                    continue

                # B. Fallback to profile smart matching
                if not answer and label:
                    answer = smart_answer_for_label(label)
                    # Record the auto-answered question in Q&A database for review/correction
                    if answer:
                        save_auto_answered(label, answer, portal=portal)

                # C. Fallback to Gemini AI resolver (expensive/slow)
                if not answer and label:
                    from core.semantic_qa import resolve_semantic_answer
                    answer = resolve_semantic_answer(label, portal=portal, driver=driver)
                    if answer:
                        save_auto_answered(label, answer, portal=portal)

                # D. Record unanswered question if still unresolved
                if not answer and label:
                    record_unanswered(label, portal=portal)

                if answer:
                    field.clear()
                    field.send_keys(str(answer))
                    log_fn(f"  [FORM] Filled field '{label}' -> '{answer}'")
            except Exception:
                pass

        # ── 2. RADIO BUTTONS (Yes/No, Authorized, Sponsorship, etc.) ──
        # LinkedIn uses fieldset with data-test attribute; Naukri/other use different selectors
        radio_groups = driver.find_elements(
            By.CSS_SELECTOR,
            "fieldset[data-test-form-builder-radio-button-form-component],"
            " fieldset.fb-text-selectable__container,"
            " fieldset, [class*='radio-group'], [class*='radioGroup'],"
            " [class*='question-container']"
        )
        for group in radio_groups:
            try:
                legend_els = group.find_elements(By.CSS_SELECTOR, "legend, label.fb-text-selectable__option")
                legend = legend_els[0].text if legend_els else ""
                if not legend:
                    try:
                        legend = group.get_attribute("aria-label") or ""
                    except Exception:
                        pass
                if not legend:
                    try:
                        spans = group.find_elements(By.CSS_SELECTOR, "span, p")
                        for sp in spans:
                            t = sp.text.strip()
                            if t and len(t) > 3:
                                legend = t
                                break
                    except Exception:
                        pass
                legend = legend.strip()
                
                # Check Q&A store first (user overrides take precedence)
                target_answer = get_answer(legend, driver=driver) if legend else ""
                
                if target_answer == "__MANUAL__":
                    log_fn(f"  [FORM] Radio group '{legend}' is marked as MANUAL. Skipping select.")
                    continue
                
                # Fallback to smart profile matching
                if not target_answer and legend:
                    target_answer = smart_radio_answer(legend)
                    if target_answer:
                        save_auto_answered(legend, target_answer, portal=portal)

                # Fallback to Gemini AI resolver
                if not target_answer and legend:
                    from core.semantic_qa import resolve_semantic_answer
                    target_answer = resolve_semantic_answer(legend, portal=portal, driver=driver)
                    if target_answer:
                        save_auto_answered(legend, target_answer, portal=portal)
                    
                # If still no answer, record it to Q&A store and skip
                if not target_answer:
                    if legend:
                        log_fn(f"  [FORM] No match for radio group '{legend}'. Recording as unanswered.")
                        record_unanswered(legend, portal=portal)
                    continue

                target_lower = target_answer.lower().strip()
                radios = group.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                for radio in radios:
                    if radio.is_selected():
                        break  # Group already answered
                    rid = radio.get_attribute("id")
                    if not rid:
                        continue
                    label_els = group.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                    if not label_els:
                        continue
                    label_text = label_els[0].text.strip().lower()
                    
                    matched = False
                    if label_text == target_lower:
                        matched = True
                    elif target_lower in label_text:
                        if target_lower in ["yes", "no"]:
                            import re
                            if re.search(r'\b' + re.escape(target_lower) + r'\b', label_text):
                                matched = True
                        else:
                            matched = True
                            
                    if matched:
                        driver.execute_script("arguments[0].click();", radio)
                        human_pause(0.2, 0.4)
                        log_fn(f"  [FORM] Radio selected '{target_answer}' for '{legend}'")
                        break
            except Exception:
                pass

        # ── 2b. Fallback: Find any ungrouped radio buttons ──
        try:
            all_radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            radio_groups_by_name = {}
            for r in all_radios:
                if not r.is_displayed():
                    continue
                name = r.get_attribute("name")
                if name:
                    if name not in radio_groups_by_name:
                        radio_groups_by_name[name] = []
                    radio_groups_by_name[name].append(r)
            
            for name, radios in radio_groups_by_name.items():
                if any(r.is_selected() for r in radios):
                    continue
                
                legend = ""
                try:
                    parent = driver.execute_script(
                        "let r = arguments[0]; return r.closest('fieldset, div, li, [class*=\"row\"], [class*=\"field\"]');", 
                        radios[0]
                    )
                    if parent:
                        for tag in ["legend", "label", "p", "span", "div"]:
                            els = parent.find_elements(By.CSS_SELECTOR, tag)
                            for el in els:
                                if el.is_displayed():
                                    t = el.text.strip()
                                    if t and 3 < len(t) < 150:
                                        if not any(t.lower() == r_opt.text.strip().lower() for r_opt in radios):
                                            legend = t
                                            break
                            if legend:
                                break
                except Exception:
                    pass
                
                if not legend:
                    continue
                
                target_answer = get_answer(legend, driver=driver) or smart_radio_answer(legend)
                if not target_answer:
                    from core.semantic_qa import resolve_semantic_answer
                    target_answer = resolve_semantic_answer(legend, portal=portal, driver=driver)
                    if target_answer:
                        save_auto_answered(legend, target_answer, portal=portal)

                if not target_answer:
                    log_fn(f"  [FORM] No match for fallback radio group '{legend}'. Recording as unanswered.")
                    record_unanswered(legend, portal=portal)
                    continue
                
                target_lower = target_answer.lower().strip()
                for radio in radios:
                    rid = radio.get_attribute("id")
                    label_text = ""
                    if rid:
                        lbl_els = driver.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                        if lbl_els:
                            label_text = lbl_els[0].text.strip().lower()
                    if not label_text:
                        try:
                            label_text = radio.find_element(By.XPATH, "following-sibling::*").text.strip().lower()
                        except Exception:
                            pass
                    
                    matched = False
                    if label_text == target_lower:
                        matched = True
                    elif target_lower in label_text:
                        if target_lower in ["yes", "no"]:
                            import re
                            if re.search(r'\b' + re.escape(target_lower) + r'\b', label_text):
                                matched = True
                        else:
                            matched = True
                    
                    if matched:
                        driver.execute_script("arguments[0].click();", radio)
                        human_pause(0.2, 0.4)
                        log_fn(f"  [FORM] Radio selected '{target_answer}' for '{legend}'")
                        break
        except Exception:
            pass

        # ── 3. SELECT / DROPDOWN ──────────────────────────────
        dropdowns = driver.find_elements(By.CSS_SELECTOR, "select")
        for drop in dropdowns:
            try:
                if not drop.is_displayed():
                    continue
                label = get_label_for_field(driver, drop)
                smart_dropdown_answer(driver, drop, label, log_fn=log_fn)
            except Exception:
                pass

        # ── 4. Checkboxes ──
        try:
            import re
            import config.profile
            checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            for cb in checkboxes:
                try:
                    if not cb.is_displayed() or cb.is_selected():
                        continue
                    
                    # Get label text for the checkbox
                    label_text = ""
                    cb_id = cb.get_attribute("id")
                    if cb_id:
                        lbl_els = driver.find_elements(By.CSS_SELECTOR, f"label[for='{cb_id}']")
                        if lbl_els:
                            label_text = lbl_els[0].text.strip()
                    if not label_text:
                        try:
                            label_text = cb.find_element(By.XPATH, "following-sibling::*").text.strip()
                        except Exception:
                            pass
                    if not label_text:
                        try:
                            parent = driver.execute_script("return arguments[0].parentElement;", cb)
                            label_text = parent.text.strip()
                        except Exception:
                            pass
                            
                    if not label_text:
                        continue
                        
                    label_lower = label_text.lower()
                    
                    # Check if this checkbox matches a skill or preference
                    should_check = False
                    
                    # Relocation / Agreement / Confirmation / Work Authorization
                    if any(k in label_lower for k in [
                        "agree", "confirm", "accept", "consent", "willing", "relocate",
                        "authorized", "eligible", "citizen", "permanent resident"
                    ]):
                        should_check = True
                        
                    # Skills matching
                    my_skills = getattr(config.profile, "MY_SKILLS", [])
                    for skill in my_skills:
                        s_lower = skill.lower()
                        # Match exact word or boundary to avoid partial matches
                        if re.search(r'\b' + re.escape(s_lower) + r'\b', label_lower):
                            should_check = True
                            break
                            
                    if should_check:
                        driver.execute_script("arguments[0].click();", cb)
                        log_fn(f"  [FORM] Checked box '{label_text}'")
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        print(f"  [WARN] Error answering questions: {e}")

def discard_current_application(driver, log_fn=print):
    """Robustly closes and discards any open Easy Apply modal."""
    try:
        # Check if modal is present
        modal_selectors = [
            ".jobs-easy-apply-modal",
            ".artdeco-modal",
            "[data-test-modal]",
            "[role='dialog']"
        ]
        modal_open = False
        for sel in modal_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if any(el.is_displayed() for el in els):
                    modal_open = True
                    break
            except Exception:
                pass
                
        if not modal_open:
            return True

        log_fn("  [FORM] Dismissing stuck Easy Apply modal...")
        
        # 1. Click the Close/Dismiss button
        dismissed = False
        dismiss_selectors = [
            "button.artdeco-modal__dismiss",
            "button[aria-label='Dismiss']",
            "button[data-test-modal-close-btn]",
            ".artdeco-modal__dismiss",
            "[aria-label='Close']"
        ]
        for sel in dismiss_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        dismissed = True
                        break
                if dismissed:
                    break
            except Exception:
                pass
                
        if not dismissed:
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                dismissed = True
            except Exception:
                pass
                
        human_pause(0.8, 1.5)
        
        # 2. Click the Discard button in the confirmation modal
        discarded = False
        discard_selectors = [
            "button[data-test-dialog-primary-btn]",
            "button[data-control-name='discard_application_confirm_btn']",
            "button.artdeco-modal__confirm-dialog-btn",
            "//button[contains(., 'Discard')]",
            "//span[contains(text(), 'Discard')]/.."
        ]
        for sel in discard_selectors:
            try:
                if sel.startswith("//"):
                    els = driver.find_elements(By.XPATH, sel)
                else:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        try:
                            el.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", el)
                        discarded = True
                        break
                if discarded:
                    break
            except Exception:
                pass
                
        human_pause(0.5, 1.0)
        return True
    except Exception as e:
        log_fn(f"  [WARN] Error discarding application: {e}")
        return False

def close_stuck_modal_if_any(driver, log_fn=print):
    """Closes any open/stuck modal before processing a job card."""
    modal_selectors = [
        ".jobs-easy-apply-modal",
        ".artdeco-modal",
        "[data-test-modal]",
        "[role='dialog']"
    ]
    for sel in modal_selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if any(el.is_displayed() for el in els):
                discard_current_application(driver, log_fn)
                break
        except Exception:
            pass


def correct_validation_errors(driver, log_fn=print):
    """
    Scan the form for active validation errors and correct the inputs.
    e.g. if error is 'Enter a whole number', round decimal values to integers.
    if error is 'Enter a decimal number', convert text like '15 days' to '15'.
    """
    errors_corrected = False
    try:
        error_selectors = [
            ".artdeco-inline-feedback--error",
            ".fb-form-element__error",
            "[class*='error']",
            "[class*='feedback'][class*='error']"
        ]
        for sel in error_selectors:
            errors = driver.find_elements(By.CSS_SELECTOR, sel)
            for err in errors:
                try:
                    if not err.is_displayed():
                        continue
                    err_text = err.text.lower()
                    
                    # Traverse up to 4 parent elements to locate the input field
                    field = None
                    curr = err
                    for _ in range(4):
                        try:
                            curr = driver.execute_script("return arguments[0].parentElement;", curr)
                            if not curr: break
                            fields = curr.find_elements(By.CSS_SELECTOR, "input, textarea, select")
                            if fields:
                                # Find the first displayed input
                                for f in fields:
                                    if f.is_displayed():
                                        field = f
                                        break
                                if field: break
                        except Exception:
                            pass
                    if not field or not field.is_displayed():
                        continue
                        
                    val = (field.get_attribute("value") or "").strip()
                    if not val:
                        continue
                        
                    def force_set_value(el, new_val):
                        try:
                            el.click()
                            time.sleep(0.1)
                            el.send_keys(Keys.CONTROL + "a")
                            el.send_keys(Keys.BACKSPACE)
                            time.sleep(0.1)
                            el.send_keys(str(new_val))
                            time.sleep(0.1)
                        except Exception:
                            pass
                        try:
                            driver.execute_script(
                                "arguments[0].value = arguments[1];"
                                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
                                "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                                el, str(new_val)
                            )
                        except Exception:
                            pass

                    # 1. Whole number error: "whole number" or "integer"
                    if "whole number" in err_text or "integer" in err_text:
                        import re
                        num_match = re.search(r'\d+(?:\.\d+)?', val)
                        if num_match:
                            num_val = float(num_match.group(0))
                            rounded = str(round(num_val))
                            force_set_value(field, rounded)
                            log_fn(f"  [FORM-FIX] Rounded decimal value '{val}' -> '{rounded}' due to whole number validation error.")
                            errors_corrected = True
                            
                    # 2. Decimal number error: "decimal number"
                    elif any(w in err_text for w in ["decimal", "number", "numeric", "larger than"]):
                        import re
                        num_match = re.search(r'\d+(?:\.\d+)?', val)
                        if num_match:
                            num_val = num_match.group(0)
                            force_set_value(field, num_val)
                            log_fn(f"  [FORM-FIX] Extracted numeric value '{val}' -> '{num_val}' due to numeric validation error.")
                            errors_corrected = True
                except Exception:
                    pass
    except Exception:
        pass
    return errors_corrected


def fill_easy_apply_form(driver, job_description="", company="", role="", log_fn=print):
    try:
        # Find the button first
        btn = None
        for btn_selector in [
            ".jobs-apply-button--top-card button",
            "button[class*='jobs-apply-button']",
            "button.jobs-apply-button",
            ".jobs-s-apply button",
        ]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, btn_selector)
                if el.is_displayed():
                    btn = el
                    break
            except Exception:
                pass
        
        if not btn:
            try:
                el = driver.find_element(By.XPATH, "//button[contains(., 'Easy Apply') or contains(@aria-label, 'Easy Apply')]")
                if el.is_displayed():
                    btn = el
            except Exception:
                pass

        if not btn:
            return False

        # Verify it is indeed an Easy Apply button (avoiding standard Apply redirect buttons)
        text = (btn.text or "").strip().lower()
        label = (btn.get_attribute("aria-label") or "").strip().lower()
        if "easy apply" not in text and "easy apply" not in label:
            log_fn("  [SKIP] Not an Easy Apply job (regular Apply button detected).")
            return False

        # Click the Easy Apply button
        applied = False
        try:
            btn.click()
            applied = True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", btn)
                applied = True
            except Exception:
                pass

        if not applied:
            return False

        human_pause(0.5, 1.0)

        last_sig, stall = None, 0
        for step in range(20):
            answer_questions(driver, log_fn=log_fn)
            errors_fixed = correct_validation_errors(driver, log_fn=log_fn)
            if errors_fixed:
                human_pause(0.3, 0.5)

            # Auto-fill Cover Letter if present
            try:
                for cover_sel in ["textarea[aria-label*='cover letter']", "textarea[name*='coverLetter']", "textarea[class*='cover']"]:
                    cover_letter_area = wait_for(driver, By.CSS_SELECTOR, cover_sel, timeout=1)
                    if cover_letter_area and not cover_letter_area.get_attribute("value"):
                        # Extract matched skills for cover letter
                        matched_skills = []
                        jd_lower = job_description.lower()
                        for skill in MY_SKILLS:
                            if skill.lower() in jd_lower:
                                matched_skills.append(skill)
                        if not matched_skills:
                            matched_skills = MY_SKILLS[:3]
                        skills_str = ", ".join(matched_skills[:3])
                        
                        # Dynamically adapt cover letter to applicant's primary background role
                        current_title = "Data Engineering"
                        work_exp = PROFILE.get("work_experience", [])
                        if work_exp and isinstance(work_exp, list):
                            first_job = work_exp[0]
                            if isinstance(first_job, dict) and first_job.get("job_title"):
                                current_title = first_job["job_title"]

                        cover_text = (
                            f"Dear Hiring Manager,\n\n"
                            f"I am writing to express my strong interest in the {role} position at {company}. "
                            f"With {PROFILE.get('total_experience_years', '4.6')} years of experience as a {current_title}, "
                            f"I have built scalable pipelines and data architectures. I noticed your team leverages "
                            f"technologies like {skills_str}, which directly aligns with my hands-on expertise with "
                            f"AWS, Snowflake, and Python.\n\n"
                            f"I would love the opportunity to discuss how my background matches your needs.\n\n"
                            f"Best regards,\n"
                            f"{PROFILE.get('first_name', '')} {PROFILE.get('last_name', '')}"
                        )
                        cover_letter_area.clear()
                        cover_letter_area.send_keys(cover_text)
                        break
            except Exception:
                pass

            # Handle Resume Upload / Selection
            saved_resume_selected = False
            saved_resume_name = PROFILE.get("linkedin_resume_name", "").strip()
            if saved_resume_name:
                try:
                    # Look for elements matching the name case-insensitively
                    xpath_lbl = f"//label[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{saved_resume_name.lower()}')]"
                    elements = driver.find_elements(By.XPATH, xpath_lbl)
                    if not elements:
                        xpath_span = f"//span[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{saved_resume_name.lower()}')]"
                        elements = driver.find_elements(By.XPATH, xpath_span)
                        
                    if elements:
                        # Click the label or span to select the radio button
                        elements[0].click()
                        log_fn(f"  [RESUME] Selected pre-uploaded LinkedIn resume: '{saved_resume_name}'")
                        saved_resume_selected = True
                        human_pause(0.5, 1.0)
                except Exception as ex:
                    log_fn(f"  [RESUME][WARN] Failed to select pre-uploaded resume: {ex}")

            if not saved_resume_selected:
                resume_input = wait_for(driver, By.CSS_SELECTOR, "input[type='file']", timeout=1)
                res_path = PROFILE.get("linkedin_resume_path") or PROFILE.get("resume_path")
                if resume_input and res_path:
                    abs_path = os.path.abspath(res_path)
                    if os.path.exists(abs_path):
                        # Call resume tailor helper
                        try:
                            from resume_tailor import generate_tailored_resume
                            log_fn(f"  [ATS TAILOR] Appending role-specific matched skills page for {company}...")
                            upload_path = generate_tailored_resume(abs_path, job_description, company, role)
                        except Exception as e:
                            log_fn(f"  [ATS TAILOR][WARN] Tailoring failed ({e}), using default resume.")
                            upload_path = abs_path
                            
                        resume_input.send_keys(upload_path)
                        human_pause(0.5, 1.0)

            # Check for Submit button
            submit_clicked = (
                click(driver, By.CSS_SELECTOR, "button[aria-label='Submit application']", timeout=1) or
                click(driver, By.XPATH, "//button[contains(., 'Submit application')]", timeout=1) or
                click(driver, By.XPATH, "//button[text()='Submit']", timeout=1)
            )
            if submit_clicked:
                human_pause(1.2, 2.0)
                # Verify that the form modal is gone or has transitioned to the success screen
                success = False
                form_present = False
                for sel in [".jobs-easy-apply-modal", "[role='dialog']"]:
                    try:
                        els = driver.find_elements(By.CSS_SELECTOR, sel)
                        if any(el.is_displayed() for el in els):
                            form_present = True
                            break
                    except Exception:
                        pass
                
                # If a modal is still present, look for the 'Done' or success dismiss button to confirm success
                try:
                    done_btn = driver.find_elements(By.XPATH, "//button[contains(.,'Done')]")
                    dismiss_btn = driver.find_elements(By.CSS_SELECTOR, "button[aria-label='Dismiss']")
                    if any(b.is_displayed() for b in done_btn) or any(b.is_displayed() for b in dismiss_btn):
                        success = True
                except Exception:
                    pass
                
                # If the modal closed completely, it's also a success
                if not form_present:
                    success = True
                    
                if success:
                    # Dismiss the success confirmation modal
                    click(driver, By.CSS_SELECTOR, "button[aria-label='Dismiss']", timeout=1)
                    click(driver, By.XPATH, "//button[contains(.,'Done')]", timeout=1)
                    return True
                else:
                    log_fn("  [WARN] Submit clicked but success modal did not appear (validation error?). Discarding.")
                    discard_current_application(driver, log_fn=log_fn)
                    return False

            # Click Next / Continue / Review using a fast, combined visible element checks to avoid sequential timeouts
            next_btn = None
            for sel in [
                "button[aria-label='Continue to next step']",
                "button[aria-label='Review your application']",
                "button[aria-label='Next step']",
                "button[class*='button-next']",
                "button[class*='button-continue']"
            ]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed() and el.is_enabled():
                        next_btn = el
                        break
                except Exception:
                    pass
            
            if not next_btn:
                try:
                    xpath_queries = [
                        "//button[contains(translate(text(), 'NEXT', 'next'), 'next')]",
                        "//button[contains(translate(text(), 'CONTINUE', 'continue'), 'continue')]",
                        "//button[contains(translate(text(), 'REVIEW', 'review'), 'review')]",
                        "//button[contains(translate(., 'NEXT', 'next'), 'next')]",
                        "//button[contains(translate(., 'CONTINUE', 'continue'), 'continue')]",
                        "//button[contains(translate(., 'REVIEW', 'review'), 'review')]"
                    ]
                    for x in xpath_queries:
                        els = driver.find_elements(By.XPATH, x)
                        for el in els:
                            if el.is_displayed() and el.is_enabled():
                                next_btn = el
                                break
                        if next_btn:
                            break
                except Exception:
                    pass

            advanced = False
            if next_btn:
                try:
                    next_btn.click()
                    advanced = True
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", next_btn)
                        advanced = True
                    except Exception:
                        pass

            # Transition wait to let DOM change settle if we clicked Next
            if advanced:
                human_pause(0.3, 0.6)

            new_sig = dom_signature(driver)
            
            # Increment stall mutually exclusively
            if not advanced or new_sig == last_sig:
                stall += 1
                if not advanced:
                    log_fn("  [FORM] Next button not found or could not click")
                else:
                    log_fn("  [FORM] Form DOM did not change after clicking Next")
            else:
                stall = 0
            
            last_sig = new_sig

            if stall >= 3:
                log_fn("  [WARN] Form stalled — could not advance or signature unchanged")
                discard_current_application(driver, log_fn=log_fn)
                return False

            human_pause(0.2, 0.4)

        return False
    except Exception as e:
        log_fn(f"  [WARN] Easy Apply error: {e}")
        return False

def run_linkedin_bot(max_applications=20, headless=False, log_fn=print, stop_event=None, keywords=None, locations=None):
    log_fn("\n" + "="*55 + "\n  LINKEDIN AUTO-APPLY BOT\n" + "="*55)
    
    reload_profile_globals()
    daily_limit = getattr(config.profile, "DAILY_LIMIT", 50)
    if get_today_count("Applied") >= daily_limit:
        log_fn(f"[STOP] Daily limit of {daily_limit} applications reached. Stopping.")
        return

    # Clear any stale stop signal from a previous run
    if stop_event:
        stop_event.clear()

    log_fn("[INFO] Step 1/4: Launching Chrome browser... (this takes ~15-20 seconds)")
    try:
        from browser import SelfHealingDriver
        driver = SelfHealingDriver(headless=headless, profile_name="linkedin")
    except Exception as e:
        log_fn(f"[ERROR] Failed to launch Chrome: {e}")
        return

    log_fn("[OK] Chrome browser launched successfully!")
    applied_jobs = load_applied_jobs()
    skipped_jobs = load_skipped_jobs()
    total_applied = 0
    processed_urls_this_run = set()  # Dedup across keyword×location combos
    
    target_keywords = keywords if keywords is not None else SEARCH_KEYWORDS
    target_locations = locations if locations is not None else SEARCH_LOCATIONS

    try:
        log_fn("[INFO] Step 2/4: Logging into LinkedIn...")
        if not login(driver, log_fn=log_fn): return

        log_fn("[INFO] Step 3/4: Starting job search...")
        search_count = 0
        max_searches = 40  # Cap combinations to avoid LinkedIn rate-limit blocks
        break_all_searches = False
        
        for keyword in target_keywords:
            if break_all_searches:
                break
            for location in target_locations:
                if stop_event and stop_event.is_set():
                    log_fn("[STOP] Stop signal received. Halting LinkedIn bot.")
                    break_all_searches = True
                    break
                if total_applied >= max_applications:
                    break_all_searches = True
                    break
                    
                if search_count >= max_searches:
                    log_fn(f"[INFO] Capped at {max_searches} search combinations per session to avoid LinkedIn query rate limits.")
                    break_all_searches = True
                    break
                
                search_count += 1
                search_jobs(driver, keyword, location, log_fn=log_fn)
                
                # Pagination: scan up to 3 pages per search
                for page_num in range(1, 4):
                    if stop_event and stop_event.is_set(): break
                    if total_applied >= max_applications: break
                    
                    if page_num > 1:
                        # Try to click next page
                        next_clicked = False
                        try:
                            next_btns = driver.find_elements(By.CSS_SELECTOR, f"button[aria-label='Page {page_num}']")
                            if not next_btns:
                                next_btns = driver.find_elements(By.XPATH, f"//button[contains(@aria-label, 'Page {page_num}')]")
                            if next_btns and next_btns[0].is_displayed():
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btns[0])
                                human_pause(0.3, 0.5)
                                next_btns[0].click()
                                human_pause(2, 3)
                                next_clicked = True
                                log_fn(f"  [PAGE] Navigated to page {page_num}")
                        except Exception:
                            pass
                        if not next_clicked:
                            break  # No more pages

                    log_fn(f"[INFO] Step 4/4: Scanning job listings (page {page_num})...")
                    cards = get_job_cards(driver)
                    log_fn(f"  Found {len(cards)} job listings")
                    if not cards:
                        try:
                            os.makedirs("logs", exist_ok=True)
                            screenshot_path = "logs/linkedin_zero_listings.png"
                            driver.save_screenshot(screenshot_path)
                            log_fn(f"  [DEBUG] Saved screenshot to {screenshot_path}")
                        except Exception as e:
                            log_fn(f"  [DEBUG] Failed to save screenshot: {e}")

                    for card_idx in range(len(cards)):
                        if stop_event and stop_event.is_set(): break
                        if total_applied >= max_applications: break

                        # Re-locate card list to prevent stale element exceptions
                        try:
                            cards = get_job_cards(driver)
                            if card_idx >= len(cards):
                                break
                            card = cards[card_idx]
                        except Exception:
                            continue

                        # ── Early duplicate check without clicking ────────────────
                        try:
                            job_id = card.get_attribute("data-job-id") or card.get_attribute("data-entity-urn") or ""
                            if job_id.startswith("urn:li:fs_normalizedJobPosting:"):
                                job_id = job_id.split(":")[-1]

                            if not job_id:
                                for sel in ["a.job-card-list__title", "a.job-card-container__link", "a[class*='job-card']", ".job-card-list__title", "a"]:
                                    try:
                                        link = card.find_element(By.CSS_SELECTOR, sel)
                                        href = link.get_attribute("href") or ""
                                        extracted = extract_job_id_from_url(href)
                                        if extracted:
                                            job_id = extracted
                                            break
                                    except Exception:
                                        pass
                                
                            if job_id and (job_id in applied_jobs or job_id in skipped_jobs):
                                continue
                            if job_id and job_id in processed_urls_this_run:
                                continue
                        except Exception:
                            pass

                        # ── Early Title & Company Pre-filtering ──────────────────
                        card_title = ""
                        card_company = ""
                        try:
                            for sel in ["a.job-card-list__title", "a.job-card-container__link", "a[class*='job-card']", ".job-card-list__title"]:
                                try:
                                    el = card.find_element(By.CSS_SELECTOR, sel)
                                    t = el.text.strip()
                                    if t:
                                        card_title = t
                                        break
                                except Exception:
                                    pass
                            for sel in ["span.job-card-container__primary-description", "span.job-card-list__normal-corp-name", ".artdeco-entity-lockup__subtitle", "span[class*='company']", "a[class*='company']"]:
                                try:
                                    el = card.find_element(By.CSS_SELECTOR, sel)
                                    c = el.text.strip()
                                    if c:
                                        card_company = c
                                        break
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        if card_title:
                            do_apply, score, matched, reason, decision, missing = should_apply(card_title, "", card_company)
                            if not do_apply:
                                # Extract card URL if possible for logging
                                card_url = ""
                                try:
                                    for sel in ["a.job-card-list__title", "a.job-card-container__link", "a[class*='job-card']"]:
                                        el = card.find_element(By.CSS_SELECTOR, sel)
                                        href = el.get_attribute("href")
                                        if href:
                                            card_url = href.split("?")[0]
                                            break
                                except Exception:
                                    pass
                                log_fn(f"\n[FAST FILTER SKIP] {card_company or 'Unknown'} -- {card_title}")
                                log_fn(f"  Skip: {reason}")
                                log_application(card_company, card_title, "LinkedIn", card_url, "Skipped", score, matched, skip_reason=reason, missing_skills=missing, decision=decision)
                                if job_id:
                                    save_skipped_job(job_id)
                                continue

                        job_id, title, company, description, url, posted_date = get_job_details(driver, card, log_fn=log_fn)
                        if not job_id:
                            continue
                        if job_id in applied_jobs:
                            continue
                        if url in processed_urls_this_run:
                            continue
                        processed_urls_this_run.add(url)
                        if job_id:
                            processed_urls_this_run.add(job_id)

                        log_fn(f"\n[JOB] {company} -- {title}{' (Posted: ' + posted_date + ')' if posted_date else ''}")
                        do_apply, score, matched, reason, decision, missing = should_apply(title, description, company)

                        if not do_apply or decision == "skip":
                            log_fn(f"  Skip: {reason}")
                            log_application(company, title, "LinkedIn", url, "Skipped", score, matched, skip_reason=reason, posted_date=posted_date, missing_skills=missing, decision=decision)
                            if job_id:
                                save_skipped_job(job_id)
                            continue

                        if decision == "review":
                            # For LinkedIn Easy Apply, auto-apply to review-threshold jobs too (low friction/no cost)
                            log_fn(f"  [REVIEW -> AUTO] {score}% -- Auto-Applying...")
                            success = fill_easy_apply_form(driver, job_description=description, company=company, role=title, log_fn=log_fn)
                            if success:
                                log_fn("  [SUCCESS] Successfully Applied!")
                                log_application(company, title, "LinkedIn", url, "Applied", score, matched, posted_date=posted_date)
                                save_applied_job(job_id)
                                total_applied += 1
                                human_pause(1.0, 2.0)
                            else:
                                log_fn("  [FAIL] Apply failed (requires manual completion)")
                                log_application(company, title, "LinkedIn", url, "Manual Needed", score, matched, skip_reason="Form stalled", posted_date=posted_date)
                                if job_id:
                                    save_skipped_job(job_id)
                            continue

                        log_fn(f"  [MATCH] {score}% -- Auto-Applying...")
                        success = fill_easy_apply_form(driver, job_description=description, company=company, role=title, log_fn=log_fn)
                        if success:
                            log_fn("  [SUCCESS] Successfully Applied!")
                            log_application(company, title, "LinkedIn", url, "Applied", score, matched, posted_date=posted_date)
                            save_applied_job(job_id)
                            total_applied += 1
                            human_pause(1.0, 2.0)
                        else:
                            log_fn("  [FAIL] Apply failed (requires manual completion)")
                            log_application(company, title, "LinkedIn", url, "Manual Needed", score, matched, skip_reason="Form stalled", posted_date=posted_date)
                            if job_id:
                                save_skipped_job(job_id)
    except KeyboardInterrupt:
        log_fn("\n[STOP] LinkedIn Bot stopped by user.")
    finally:
        log_fn(f"\n[DONE] Completed! Applied to {total_applied} jobs on LinkedIn.")
        driver.quit()


