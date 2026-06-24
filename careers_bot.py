"""
careers_bot.py — Auto-fill job applications on company career sites (Workday, Greenhouse, Lever,
                  iCIMS, Taleo, SuccessFactors, SmartRecruiters, and generic sites).

SCENARIO TRAINING MAP:
  - Account already exists (login form)  → Fill email + password → click Sign In
  - Account does not exist               → Click "Create Account/Sign Up" → Register → Continue
  - Email/OTP verification gating        → Poll IMAP inbox, extract OTP code, paste it in, click Verify
  - Multi-step form (1-4 pages)          → Iterative page loop: fill → next → detect stall → self-heal
  - Validation errors on page            → force_set_value + JS event dispatcher to clear and resubmit
  - Resume already uploaded              → Skip upload step
  - Cover letter field present           → Generate via Gemini AI, fallback to template
  - Dropdown (country/phone/yoe)         → Smart text selection from Select element
  - Radio buttons (yes/no/agree)         → Match label text, click correct option
  - Checkboxes (agreement/skills)        → Auto-check consent/agreement boxes
  - File upload (resume)                 → Send absolute path via input[type='file']
  - LinkedIn / Github URL fields         → Fill from PROFILE
  - Notice period / Current CTC / Expected CTC → Fill from PROFILE dictionary
  - Any unrecognised field               → Ask Gemini resolver for value, log in QA store
"""

import os
import time
import re
import importlib
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from browser import wait_for, click, fill, human_pause
from config.profile import PROFILE
try:
    from config.profile import COMPANY_CREDENTIALS
except ImportError:
    COMPANY_CREDENTIALS = {}

# ─── Logging relay ───────────────────────────────────────────────────────────
_log_fn = None

def set_log_fn(log_fn):
    global _log_fn
    _log_fn = log_fn

def print(*args, **kwargs):
    try:
        if _log_fn:
            msg = " ".join(str(a) for a in args)
            _log_fn(msg)
        else:
            import builtins
            builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        import builtins
        msg = " ".join(str(a) for a in args)
        safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
        if _log_fn:
            _log_fn(safe_msg)
        else:
            builtins.print(safe_msg, **kwargs)

# ─── Profile shorthand ───────────────────────────────────────────────────────
RESUME_PATH = os.path.abspath(PROFILE.get("resume_path", ""))

# ─── Workday standard data-automation-id field mapping ───────────────────────
WORKDAY_FIELDS = {
    "legalNameSection_firstName":  PROFILE.get("first_name", ""),
    "legalNameSection_lastName":   PROFILE.get("last_name", ""),
    "email":                       PROFILE.get("email", ""),
    "phone":                       PROFILE.get("phone", ""),
    "addressSection_city":         PROFILE.get("city", ""),
    "addressSection_countryRegion": PROFILE.get("country", "India"),
    "linkedin":                    PROFILE.get("linkedin_url", ""),
}


# ─── Utilities ───────────────────────────────────────────────────────────────

def get_custom_email_for_company(url: str) -> str:
    """Find company-specific email or fall back to profile email."""
    url_lower = url.lower()
    for c_name, c_creds in COMPANY_CREDENTIALS.items():
        if c_name.lower() in url_lower:
            c_email = c_creds.get("email")
            if c_email:
                return c_email
    return PROFILE.get("email", "")


def get_corp_credentials(url: str):
    """Return (email, password) for this URL — company-specific first, then default."""
    url_lower = url.lower()
    for c_name, c_creds in COMPANY_CREDENTIALS.items():
        if c_name.lower() in url_lower:
            return c_creds.get("email"), c_creds.get("password")
    return PROFILE.get("corp_email"), PROFILE.get("corp_password")


def get_tailored_resume_path(driver, company: str, role: str) -> str:
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    original_path = os.path.abspath(PROFILE.get("resume_path", ""))
    if not os.path.exists(original_path):
        return original_path
    try:
        from resume_tailor import generate_tailored_resume
        print(f"  [ATS TAILOR] Appending matched skills for {company}...")
        return generate_tailored_resume(original_path, body_text, company, role)
    except Exception as e:
        print(f"  [ATS TAILOR][WARN] Resume tailoring failed ({e}), using default.")
        return original_path


def get_personalized_cover_letter(body_text: str, company: str, role: str) -> str:
    from config.profile import MY_SKILLS, PROFILE
    matched_skills = [s for s in MY_SKILLS if s.lower() in body_text.lower()]
    if not matched_skills:
        matched_skills = MY_SKILLS[:3]
    skills_str = ", ".join(matched_skills[:3])
    name = f"{PROFILE.get('first_name', '')} {PROFILE.get('last_name', '')}".strip()
    exp  = PROFILE.get("total_experience_years", "4.6")
    return (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to express my strong interest in the {role} position at {company}. "
        f"With {exp} years of experience in data engineering, "
        f"I have built scalable pipelines and data architectures leveraging "
        f"technologies like {skills_str}, which directly aligns with your requirements.\n\n"
        f"I would love the opportunity to discuss how my background matches your needs.\n\n"
        f"Best regards,\n{name}"
    )


def _gemini_cover_letter(body_text: str, company: str, role: str) -> str:
    """
    Generate a tailored cover letter using Gemini 1.5 Flash.
    Falls back to the template cover letter if Gemini is not configured.
    """
    import config.profile
    importlib.reload(config.profile)
    api_key = getattr(config.profile, "GEMINI_API_KEY", "")
    if not api_key:
        return get_personalized_cover_letter(body_text, company, role)
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        profile = config.profile.PROFILE
        skills  = config.profile.MY_SKILLS[:8]
        exp     = profile.get("total_experience_years", "4.6")
        name    = f"{profile.get('first_name','')} {profile.get('last_name','')}".strip()
        prompt  = f"""
Write a concise 3-paragraph job application cover letter.
Candidate: {name}, {exp} years experience, skills: {', '.join(skills)}.
Company: {company}. Role: {role}.
Job description (excerpt): {body_text[:800]}
Rules:
- Paragraph 1: Express genuine interest, mention ONE specific thing about the company from the JD.
- Paragraph 2: Cite 2-3 directly relevant skills with a brief concrete achievement.
- Paragraph 3: Short confident close, mention availability for interview.
- Formal but warm tone. Under 200 words total. Do NOT include salutation or sign-off lines.
"""
        model    = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)
        body     = response.text.strip()
        return (
            f"Dear Hiring Manager,\n\n{body}\n\n"
            f"Best regards,\n{name}"
        )
    except Exception as e:
        print(f"  [GEMINI COVER] Failed ({e}), using template.")
        return get_personalized_cover_letter(body_text, company, role)


def _gemini_field_answer(question_text: str, field_type: str = "text") -> str:
    """Ask Gemini to answer an unknown screening question using candidate profile."""
    try:
        import config.profile
        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return ""
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        profile = config.profile.PROFILE
        skills  = ", ".join(config.profile.MY_SKILLS[:8])
        name    = f"{profile.get('first_name','')} {profile.get('last_name','')}".strip()
        exp     = profile.get("total_experience_years", "4.6")
        notice  = profile.get("notice_period", "15")
        ctc     = profile.get("current_ctc", "15")
        ectc    = profile.get("expected_ctc", "18")
        prompt  = f"""
You are answering a job application form field for candidate:
Name: {name}, Experience: {exp} years, Skills: {skills},
Notice Period: {notice} days, Current CTC: {ctc} LPA, Expected CTC: {ectc} LPA.

Question/Field Label: "{question_text}"
Field type: {field_type} (text/number/radio/dropdown)

Rules:
- Return ONLY the answer value, no extra words.
- For yes/no questions: return "Yes" or "No".
- For number fields: return only the number (e.g. 4 or 15).
- For text fields: return a concise professional answer.
- For dropdown/radio: return the most appropriate option text.
"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp  = model.generate_content(prompt)
        return resp.text.strip()
    except Exception:
        return ""


def force_set_value(driver, element, value: str):
    """
    Force-set a form input value, triggering React/Angular/Vue validation hooks.
    Uses direct JS injection and dispatches native browser event listeners to guarantee state sync.
    """
    try:
        driver.execute_script(
            "arguments[0].value = '';"
            "arguments[0].dispatchEvent(new Event('focus', { bubbles: true }));"
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
            "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));"
            "arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));",
            element, str(value)
        )
        time.sleep(0.1)
    except Exception:
        pass


def _wait_for_otp_in_email(timeout: int = 60) -> str:
    """
    Poll the IMAP inbox for a recent OTP verification email.
    Returns the 4-8 digit OTP code as a string, or "" if not found.
    """
    try:
        import imaplib, email as email_lib
        import config.profile
        importlib.reload(config.profile)
        host     = getattr(config.profile, "IMAP_HOST",     "imap.gmail.com")
        email_   = getattr(config.profile, "IMAP_EMAIL",    "")
        password = getattr(config.profile, "IMAP_PASSWORD", "")
        if not email_ or not password:
            return ""
        start = time.time()
        while time.time() - start < timeout:
            try:
                mail = imaplib.IMAP4_SSL(host, timeout=10)
                mail.login(email_, password)
                mail.select("INBOX")
                _, data = mail.search(None, "ALL")
                ids = data[0].split()
                for mid in reversed(ids[-10:]):  # Check last 10 unseen
                    _, msg_data = mail.fetch(mid, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                    # Extract OTP: 4-8 digit standalone number
                    otp_match = re.search(r'\b(\d{4,8})\b', body)
                    if otp_match:
                        mail.logout()
                        return otp_match.group(1)
                    # Extract activation link
                    link_match = re.search(r'https?://[^\s"<>]+(?:verify|confirm|activate|token)[^\s"<>]*', body, re.I)
                    if link_match:
                        mail.logout()
                        return link_match.group(0)
                mail.logout()
            except Exception:
                pass
            time.sleep(8)
    except Exception:
        pass
    return ""


def _wait_for_password_reset_link(email_addr: str, timeout: int = 120) -> str:
    """
    Poll the IMAP inbox for a recent password reset link.
    Returns the link as a string, or "" if not found.
    """
    try:
        import imaplib, email as email_lib, re
        import config.profile
        importlib.reload(config.profile)
        host     = getattr(config.profile, "IMAP_HOST",     "imap.gmail.com")
        email_   = getattr(config.profile, "IMAP_EMAIL",    "")
        password = getattr(config.profile, "IMAP_PASSWORD", "")
        if not email_ or not password:
            return ""
        start = time.time()
        while time.time() - start < timeout:
            try:
                mail = imaplib.IMAP4_SSL(host, timeout=10)
                mail.login(email_, password)
                mail.select("INBOX")
                _, data = mail.search(None, "ALL")
                ids = data[0].split()
                for mid in reversed(ids[-10:]):  # Check last 10 unseen
                    _, msg_data = mail.fetch(mid, "(RFC822)")
                    raw = msg_data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                    subject = msg.get("Subject", "")
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                try:
                                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                    # If email subject or body mentions password or reset
                    if "password" in subject.lower() or "reset" in subject.lower() or "password" in body.lower():
                        link_match = re.search(r'https?://[^\s"<>]+(?:reset|password|wday)[^\s"<>]*', body, re.I)
                        if link_match:
                            mail.logout()
                            return link_match.group(0)
                mail.logout()
            except Exception:
                pass
            time.sleep(8)
    except Exception:
        pass
    return ""


def _trigger_forgot_password(driver, email_addr: str) -> bool:
    """Clicks 'Forgot Password?', fills email, submits, retrieves reset link from Gmail, and resets password."""
    print("  [FORGOT PASSWORD] Initiating password reset...")
    forgot_btns = driver.find_elements(By.XPATH, "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'forgot password') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'forgot your password') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'reset password')]")
    forgot_btns += driver.find_elements(By.CSS_SELECTOR, "a[data-automation-id='forgotPasswordLink'], [data-automation-id='forgotPassword']")
    forgot_btns += driver.find_elements(By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'forgot password') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'forgot your password')]")
    clicked = False
    for btn in forgot_btns:
        if btn.is_displayed():
            try:
                btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
            clicked = True
            human_pause(4, 6)
            break
    if not clicked:
        print("  [FORGOT PASSWORD] Could not find 'Forgot Password' link.")
        return False

    # Now we should be on the Forgot Password page
    email_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[data-automation-id='email']")
    if not email_inputs:
        print("  [FORGOT PASSWORD] Email input field not found on reset page.")
        return False
    
    force_set_value(driver, email_inputs[0], email_addr)
    human_pause(0.5, 1.0)

    # Click Submit/Reset
    submit_btns = driver.find_elements(By.CSS_SELECTOR, "button[data-automation-id='forgotPasswordSubmitButton'], button[type='submit']")
    submit_btns += driver.find_elements(By.XPATH, "//button[contains(.,'Submit') or contains(.,'Reset')]")
    submitted = False
    for btn in submit_btns:
        if btn.is_displayed():
            driver.execute_script("arguments[0].click();", btn)
            submitted = True
            human_pause(5, 8)
            break
            
    if not submitted:
        print("  [FORGOT PASSWORD] Could not find submit button on reset page.")
        return False

    print("  [FORGOT PASSWORD] Password reset request submitted. Checking email for reset link...")
    reset_link = _wait_for_password_reset_link(email_addr, timeout=120)
    if not reset_link:
        print("  [FORGOT PASSWORD] Could not retrieve password reset link from email.")
        return False
        
    print(f"  [FORGOT PASSWORD] Reset link retrieved. Navigating...")
    driver.get(reset_link)
    human_pause(6, 8)
    
    # Fill in new password
    pw_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password'], input[data-automation-id='newPassword']")
    confirm_inputs = driver.find_elements(By.CSS_SELECTOR, "input[data-automation-id='confirmPassword']")
    
    new_pw = "Megamind@9595" 
    
    if len(pw_inputs) >= 1:
        force_set_value(driver, pw_inputs[0], new_pw)
    if len(confirm_inputs) >= 1:
        force_set_value(driver, confirm_inputs[0], new_pw)
    elif len(pw_inputs) >= 2:
        force_set_value(driver, pw_inputs[1], new_pw)
        
    human_pause(1, 2)
    submit_change = driver.find_elements(By.CSS_SELECTOR, "button[data-automation-id='resetPasswordSubmitButton'], button[type='submit']")
    for btn in submit_change:
        if btn.is_displayed():
            driver.execute_script("arguments[0].click();", btn)
            print("  [FORGOT PASSWORD] Password updated successfully.")
            human_pause(5, 8)
            return True
            
    return False


def _handle_otp_wall(driver) -> bool:
    """
    Detect OTP / email verification walls and auto-fill the OTP or click activation links.
    Returns True if wall was bypassed, False if failed.
    """
    # Detect 4-8 digit OTP input fields
    otp_inputs = driver.find_elements(By.CSS_SELECTOR,
        "input[type='number'][maxlength='6'], input[type='text'][maxlength='6'], "
        "input[type='text'][maxlength='4'], input[type='text'][maxlength='8'], "
        "input[placeholder*='code'], input[placeholder*='OTP'], input[placeholder*='verify'], "
        "input[name*='otp'], input[name*='code'], input[id*='otp'], input[id*='code']"
    )
    if not otp_inputs:
        return False
    visible_otp = [el for el in otp_inputs if el.is_displayed()]
    if not visible_otp:
        return False
    print("  [OTP WALL] OTP verification field detected. Polling inbox for code (60s)...")
    otp_or_link = _wait_for_otp_in_email(timeout=60)
    if not otp_or_link:
        print("  [OTP WALL] Could not retrieve OTP from inbox. Waiting up to 120s for manual entry...")
        for _ in range(24):
            time.sleep(5)
            otp_walls = driver.find_elements(By.CSS_SELECTOR,
                "input[placeholder*='code'], input[placeholder*='OTP'], input[name*='otp']")
            if not any(el.is_displayed() for el in otp_walls):
                print("  [OTP WALL] OTP cleared (likely manual). Continuing...")
                return True
        return False
    if otp_or_link.startswith("http"):
        print(f"  [OTP WALL] Activation link detected. Opening in browser...")
        driver.get(otp_or_link)
        human_pause(4, 6)
        return True
    print(f"  [OTP WALL] OTP code found: {otp_or_link}. Filling in...")
    for el in visible_otp:
        try:
            force_set_value(driver, el, otp_or_link)
            time.sleep(0.3)
        except Exception:
            pass
    # Click submit/verify button
    for sel in ["button[type='submit']", "button[id*='verify']", "button[id*='submit']",
                "//button[contains(.,'Verify')]", "//button[contains(.,'Submit')]",
                "//button[contains(.,'Confirm')]"]:
        try:
            if sel.startswith("//"):
                btns = driver.find_elements(By.XPATH, sel)
            else:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    human_pause(3, 5)
                    return True
        except Exception:
            pass
    return True


def _handle_login_or_register(driver, url: str) -> bool:
    """
    Unified FSM to handle Workday/iCIMS/Taleo/SmartRecruiters sign-in walls.
    State machine:
      A → Login form visible → Try login → if fails → go to B
      B → Create Account form visible → Fill + submit → go to C  
      C → OTP/Email verification wall → Auto-fill OTP → go to D
      D → Application form accessible → Done
    Returns True when application form is accessible.
    """
    corp_email, corp_password = get_corp_credentials(url)
    if not corp_email or not corp_password:
        print("  [LOGIN] No corporate credentials found. Skipping login attempt.")
        return True

    for attempt in range(3):
        # Detect current state
        email_inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[type='email'], input[data-automation-id='email'], "
            "input[name*='email'], input[id*='email'], input[name*='Email'], input[id*='Email']")
        pw_inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[type='password'], input[data-automation-id='password'], "
            "input[name*='password'], input[id*='password']")
        visible_email = [el for el in email_inputs if el.is_displayed() or (el.get_attribute("type") != "hidden" and "display: none" not in (el.get_attribute("style") or ""))]
        visible_pw    = [el for el in pw_inputs if el.is_displayed() or (el.get_attribute("type") != "hidden" and "display: none" not in (el.get_attribute("style") or ""))]

        if not visible_email:
            # No wall — application form is accessible
            return True

        is_registration_page = False
        if len(visible_pw) >= 2:
            is_registration_page = True
        else:
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "create account" in page_text and "verify new password" in page_text:
                    is_registration_page = True
            except Exception:
                pass

        # State A: Login form (email + password present, and NOT a registration page)
        if visible_email and visible_pw and not is_registration_page:
            print(f"  [STATE A] Login wall. Attempting sign-in with: {corp_email}")
            try:
                force_set_value(driver, visible_email[0], corp_email)
                force_set_value(driver, visible_pw[0], corp_password)
                # Dispatch blur events to trigger React framework validations on login inputs
                driver.execute_script(
                    "arguments[0].dispatchEvent(new Event('focus', { bubbles: true }));"
                    "arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));"
                    "arguments[1].dispatchEvent(new Event('focus', { bubbles: true }));"
                    "arguments[1].dispatchEvent(new Event('blur', { bubbles: true }));",
                    visible_email[0], visible_pw[0]
                )
                human_pause(0.5, 1.0)
                # Click Sign In
                for sel in [
                    "button[data-automation-id='signInSubmitButton']",
                    "button[type='submit']",
                    "//button[contains(.,'Sign In') or contains(.,'Log In') or contains(.,'Login')]"
                ]:
                    try:
                        btns = driver.find_elements(
                            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                        for btn in btns:
                            if btn.is_displayed():
                                try:
                                    btn.click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", btn)
                                break
                    except Exception:
                        pass
                human_pause(6, 10)
                # Check for errors after login submission
                error_elements = driver.find_elements(By.CSS_SELECTOR, "[data-automation-id='errorBanner'], .wd-error-banner, [role='alert'], .alert-danger")
                error_text = ""
                for err in error_elements:
                    if err.is_displayed():
                        error_text += err.text + " "
                if error_text:
                    print(f"  [LOGIN] Login failed: {error_text.strip()}")
                    if "password" in error_text.lower() or "incorrect" in error_text.lower() or "invalid" in error_text.lower() or "user name" in error_text.lower():
                        if _trigger_forgot_password(driver, corp_email):
                            print("  [LOGIN] Password reset completed successfully. Retrying login...")
                            continue
                        else:
                            print("  [LOGIN] Password reset failed/timed out. Email might not be registered. Switching to Register/Create Account...")
                            create_btns = driver.find_elements(By.CSS_SELECTOR, "a[data-automation-id='createAccountLink'], button[data-automation-id='createAccountLink']")
                            create_btns += driver.find_elements(By.XPATH, "//a[contains(.,'Create Account')] | //button[contains(.,'Create Account')]")
                            for btn in create_btns:
                                if btn.is_displayed():
                                    driver.execute_script("arguments[0].click();", btn)
                                    human_pause(4, 6)
                                    break
                            continue
                # Check for OTP after login
                if _handle_otp_wall(driver):
                    human_pause(2, 4)
                
                # Verify if login wall is cleared
                time.sleep(2)
                email_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[data-automation-id='email']")
                visible_email_after = [el for el in email_inputs if el.is_displayed()]
                if not visible_email_after:
                    print("  [LOGIN] Initial login wall cleared successfully.")
                    return True
                else:
                    # Let's inspect the page error banners or form-specific error attributes
                    page_errors = driver.find_elements(By.CSS_SELECTOR, "[data-automation-id='errorBanner'], .wd-error-banner, [role='alert'], .alert-danger, .wd-validation-error")
                    errors = [err.text for err in page_errors if err.is_displayed()]
                    if errors:
                        print(f"  [LOGIN] Login stuck. Visible page errors: {errors}")
                    else:
                        print("  [LOGIN] Login form did not advance and no error banners were found. Triggering password reset as fallback...")
                    
                    if _trigger_forgot_password(driver, corp_email):
                        print("  [LOGIN] Password reset completed successfully via fallback. Retrying login...")
                        continue
                    else:
                        print("  [LOGIN] Password reset fallback failed/timed out. Switching to registration...")
                        create_btns = driver.find_elements(By.CSS_SELECTOR, "a[data-automation-id='createAccountLink'], button[data-automation-id='createAccountLink']")
                        create_btns += driver.find_elements(By.XPATH, "//a[contains(.,'Create Account')] | //button[contains(.,'Create Account')]")
                        for btn in create_btns:
                            if btn.is_displayed():
                                driver.execute_script("arguments[0].click();", btn)
                                human_pause(4, 6)
                                break
                        continue
                continue
            except Exception as e:
                print(f"  [STATE A] Login attempt exception: {e}")

        # State B: Registration page or email-only signup screen
        if is_registration_page or (visible_email and not visible_pw):
            if not is_registration_page:
                # Check if there's a Create Account button to click
                create_btns = driver.find_elements(By.XPATH,
                    "//button[contains(.,'Create Account') or contains(.,'Sign Up') or contains(.,'Register')] | "
                    "//a[contains(.,'Create Account') or contains(.,'Sign Up') or contains(.,'Register')]")
                create_btns += driver.find_elements(By.CSS_SELECTOR,
                    "button[data-automation-id='createAccountLink'], a[data-automation-id='createAccountLink']")
                for btn in create_btns:
                    if btn.is_displayed():
                        print("  [STATE B] Clicking Create Account / Sign Up...")
                        driver.execute_script("arguments[0].click();", btn)
                        human_pause(3, 5)
                        break
                else:
                    # Try submitting the email to proceed to next step
                    print(f"  [STATE B] Submitting email: {corp_email}")
                    try:
                        force_set_value(driver, visible_email[0], corp_email)
                        submit_btns = driver.find_elements(By.XPATH,
                            "//button[contains(.,'Next') or contains(.,'Continue') or contains(.,'Submit')]")
                        for btn in submit_btns:
                            if btn.is_displayed():
                                driver.execute_script("arguments[0].click();", btn)
                                human_pause(3, 5)
                                break
                    except Exception:
                        pass

            # Try filling registration form
            human_pause(2, 4)
            reg_email_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[data-automation-id='email'], input[type='email'], input[name*='email']")
            reg_pw_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[type='password'], input[data-automation-id='password']")
            reg_confirm_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[data-automation-id='confirmPassword'], input[name*='confirm']")
            fn_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[data-automation-id='firstName'], input[name*='firstName'], input[name*='first_name']")
            ln_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[data-automation-id='lastName'], input[name*='lastName'], input[name*='last_name']")

            visible_reg_email = [el for el in reg_email_inputs if el.is_displayed()]
            visible_reg_pw    = [el for el in reg_pw_inputs if el.is_displayed()]
            visible_confirm   = [el for el in reg_confirm_inputs if el.is_displayed()]
            visible_fn        = [el for el in fn_inputs if el.is_displayed()]
            visible_ln        = [el for el in ln_inputs if el.is_displayed()]

            if visible_reg_email:
                force_set_value(driver, visible_reg_email[0], corp_email)
            if visible_reg_pw:
                force_set_value(driver, visible_reg_pw[0], corp_password)
                if len(visible_reg_pw) >= 2 and not visible_confirm:
                    force_set_value(driver, visible_reg_pw[1], corp_password)
            if visible_confirm:
                force_set_value(driver, visible_confirm[0], corp_password)
            if visible_fn:
                force_set_value(driver, visible_fn[0], PROFILE.get("first_name", ""))
            if visible_ln:
                force_set_value(driver, visible_ln[0], PROFILE.get("last_name", ""))

            # Check agreement checkboxes
            terms_chks = driver.find_elements(By.CSS_SELECTOR,
                "input[type='checkbox'], [data-automation-id='agreementCheckbox']")
            for chk in terms_chks:
                try:
                    if not chk.is_selected():
                        # Try finding and clicking label/parent to trigger React onChange
                        cid = chk.get_attribute("id")
                        clicked = False
                        if cid:
                            lbls = driver.find_elements(By.CSS_SELECTOR, f"label[for='{cid}'], [for='{cid}']")
                            for lbl in lbls:
                                driver.execute_script("arguments[0].click();", lbl)
                                clicked = True
                                break
                        if not clicked:
                            parent = driver.execute_script("return arguments[0].parentNode;", chk)
                            driver.execute_script("arguments[0].click();", parent)
                        print("  [STATE B] Clicked agreement checkbox (via label/parent).")
                except Exception:
                    pass

            # Fire blur events on password inputs to ensure Workday validation evaluates them
            for pw_el in visible_reg_pw + visible_confirm:
                try:
                    driver.execute_script("arguments[0].focus(); arguments[0].blur(); arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", pw_el)
                except Exception:
                    pass

            human_pause(1.0, 2.0)
            # Submit registration
            reg_submitted = False
            for sel in [
                "button[data-automation-id='createAccountSubmitButton']",
                "button[type='submit']",
                "//button[contains(.,'Create Account') or contains(.,'Register') or contains(.,'Submit')]"
            ]:
                try:
                    btns = driver.find_elements(
                        By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
                    for btn in btns:
                        if btn.is_displayed():
                            print("  [STATE B] Submitting registration form...")
                            try:
                                btn.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", btn)
                            reg_submitted = True
                            human_pause(6, 10)
                            break
                except Exception:
                    pass
                if reg_submitted:
                    break

            # Detect if "account already exists" error is shown after submitting registration
            error_elements = driver.find_elements(By.CSS_SELECTOR, "[data-automation-id='errorBanner'], .wd-error-banner, [role='alert'], .alert-danger")
            error_text = ""
            for err in error_elements:
                if err.is_displayed():
                    error_text += err.text + " "
            
            # Check if password fields are still displayed/visible after submission (indicating stuck registration)
            stuck_on_reg = False
            for pw_el in visible_reg_pw:
                try:
                    if pw_el.is_displayed():
                        stuck_on_reg = True
                except Exception:
                    pass

            if error_text and "already exists" in error_text.lower():
                print("  [STATE B] Email already registered. Switching to Login page...")
                signin_links = driver.find_elements(By.XPATH, "//a[contains(.,'Sign In') or contains(.,'Log In') or contains(.,'Login')]")
                signin_links += driver.find_elements(By.CSS_SELECTOR, "a[data-automation-id='signInLink']")
                for link in signin_links:
                    if link.is_displayed():
                        driver.execute_script("arguments[0].click();", link)
                        human_pause(4, 6)
                        break
                continue
            elif reg_submitted and stuck_on_reg:
                print("  [STATE B] Form submission did not advance (inputs still visible). Email likely exists. Navigating directly to login URL...")
                # Derive login URL from the main job URL
                # Example: https://pwc.wd3.myworkdayjobs.com/en-US/Global_Experienced_Careers/job/Hyderabad...
                # Workday login URL is generally: https://pwc.wd3.myworkdayjobs.com/en-US/Global_Experienced_Careers/login
                login_url = url
                match = re.match(r'(https?://[^/]+/en-US/[^/]+)/job/', url)
                if match:
                    login_url = match.group(1) + "/login"
                print(f"  [STATE B] Derived login URL: {login_url}")
                driver.get(login_url)
                human_pause(6, 8)
                continue
            elif reg_submitted and not error_text:
                print("  [STATE B] Registration submitted successfully without immediate errors.")
                # State C: OTP/Email verification
                _handle_otp_wall(driver)
                return True

            # State C: OTP/Email verification
            if _handle_otp_wall(driver):
                human_pause(3, 5)
            continue

    # Final fallback: manual wait
    email_inputs = driver.find_elements(By.CSS_SELECTOR,
        "input[type='email'], input[data-automation-id='email'], "
        "input[name*='email'], input[id*='email']")
    still_walled = [el for el in email_inputs if el.is_displayed()]
    if still_walled:
        print("  [LOGIN] Still walled. Waiting up to 90s for manual completion...")
        for _ in range(18):
            time.sleep(5)
            email_inputs = driver.find_elements(By.CSS_SELECTOR,
                "input[type='email'], input[data-automation-id='email'], "
                "input[name*='email'], input[id*='email']")
            still_walled = [el for el in email_inputs if el.is_displayed()]
            if not still_walled:
                print("  [LOGIN] Wall cleared! Continuing...")
                return True
        return False
    return True


def _gemini_select_option(question_text: str, options: list) -> str:
    """Ask Gemini to select the best option from a dropdown list for the candidate."""
    try:
        import config.profile
        importlib.reload(config.profile)
        api_key = getattr(config.profile, "GEMINI_API_KEY", "")
        if not api_key:
            return ""
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        profile = config.profile.PROFILE
        skills  = ", ".join(config.profile.MY_SKILLS[:8])
        name    = f"{profile.get('first_name','')} {profile.get('last_name','')}".strip()
        exp     = profile.get("total_experience_years", "4.6")
        work_prefs = str(getattr(config.profile, "WORK_PREFERENCES", {}))
        
        options_str = "\n".join(f"- {opt}" for opt in options)
        
        prompt = f"""
You are helping a candidate auto-fill a job application dropdown question.
Candidate: {name}, Experience: {exp} years, Skills: {skills}.
Work preferences & eligibility: {work_prefs}

Dropdown/Question Label: "{question_text}"
Available Options to choose from:
{options_str}

Rules:
- Choose the single most appropriate option for the candidate from the list.
- Return ONLY the exact text of the selected option, matching character-for-character with one of the options in the list.
- Do NOT add any introductory text, explanation, quotes, or markdown formatting. Just the raw selected option text.
"""
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp  = model.generate_content(prompt)
        ans = resp.text.strip().strip('"').strip("'").strip()
        
        for opt in options:
            if opt.lower() == ans.lower():
                return opt
        return ""
    except Exception as e:
        print(f"  [GEMINI SELECT ERROR] {e}")
        return ""


def _get_workday_dropdown_label(driver, trigger_el) -> str:
    try:
        parent = driver.execute_script(
            "let el = arguments[0]; while(el && el.tagName !== 'FORM') {"
            "  let lbl = el.querySelector('label');"
            "  if(lbl && lbl.innerText.trim()) return lbl.innerText.trim();"
            "  el = el.parentElement;"
            "}"
            "return '';", trigger_el
        )
        if parent:
            return parent
            
        lbl_id = trigger_el.get_attribute("aria-labelledby")
        if lbl_id:
            lbl = driver.find_element(By.ID, lbl_id)
            if lbl:
                return lbl.text.strip()
    except Exception:
        pass
    return "Dropdown option"


def _fill_workday_dropdown(driver, trigger_el, label_text: str) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger_el)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", trigger_el)
        time.sleep(0.8)
        
        option_els = driver.find_elements(By.CSS_SELECTOR, "[data-automation-id='searchResultItem'], [role='option'], div[id*='select-option'], li[role='option']")
        if not option_els:
            try:
                driver.execute_script("arguments[0].click();", trigger_el)
            except Exception:
                pass
            return False
            
        options = []
        option_map = {}
        for op in option_els:
            txt = op.text.strip()
            if txt and txt not in options:
                options.append(txt)
                option_map[txt] = op
                
        if not options:
            try:
                driver.execute_script("arguments[0].click();", trigger_el)
            except Exception:
                pass
            return False
            
        target_option = None
        label_lower = label_text.lower()
        
        import config.profile
        importlib.reload(config.profile)
        work_prefs = getattr(config.profile, "WORK_PREFERENCES", {})
        
        if "prefix" in label_lower or "salutation" in label_lower:
            gender = work_prefs.get("gender", "").lower()
            if "female" in gender:
                target_option = next((o for o in options if "ms" in o.lower() or "mrs" in o.lower()), None)
            else:
                target_option = next((o for o in options if "mr" in o.lower() or "mr." in o.lower()), None)
        elif "device" in label_lower or "phone type" in label_lower:
            target_option = next((o for o in options if "mobile" in o.lower() or "cell" in o.lower() or "smartphone" in o.lower()), None)
            if not target_option:
                target_option = next((o for o in options if "home" in o.lower() or "work" in o.lower()), None)
        elif "country" in label_lower:
            target_option = next((o for o in options if "india" in o.lower() or "united states" in o.lower() or "us" in o.lower()), None)
        elif "hear" in label_lower or "source" in label_lower:
            keywords = ["linkedin", "social media", "company website", "career site", "website", "indeed", "job board", "glassdoor"]
            for kw in keywords:
                target_option = next((o for o in options if kw in o.lower()), None)
                if target_option:
                    break
            if not target_option:
                target_option = next((o for o in options if "other" in o.lower()), options[0])
        elif "gender" in label_lower:
            gender = work_prefs.get("gender", "")
            target_option = next((o for o in options if gender.lower() in o.lower() or "say" in o.lower()), None)
        elif "disability" in label_lower:
            target_option = next((o for o in options if "no" in o.lower() or "not" in o.lower()), None)
        elif "veteran" in label_lower:
            target_option = next((o for o in options if "not" in o.lower() or "no" in o.lower()), None)
            
        if not target_option:
            target_option = _gemini_select_option(label_text, options)
            
        if target_option and target_option in option_map:
            opt_el = option_map[target_option]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", opt_el)
            time.sleep(0.2)
            driver.execute_script("arguments[0].click();", opt_el)
            time.sleep(0.5)
            print(f"  [WORKDAY SELECT] Selected '{target_option}' for '{label_text}'")
            return True
        else:
            try:
                driver.execute_script("arguments[0].click();", trigger_el)
            except Exception:
                pass
            return False
    except Exception as e:
        print(f"  [WORKDAY SELECT ERROR] {e}")
        try:
            driver.execute_script("arguments[0].click();", trigger_el)
        except Exception:
            pass
        return False


def _fill_workday_custom_dropdowns(driver) -> int:
    filled = 0
    blacklist = set()
    for attempt in range(15):
        triggers = driver.find_elements(By.CSS_SELECTOR, 
            "[data-automation-id='dropdownActiveOption'], [data-automation-id='selectSelectedOption']")
        
        target_trigger = None
        target_label = ""
        
        for trigger in triggers:
            try:
                if trigger.is_displayed():
                    txt = trigger.text.strip()
                    if txt.lower() in ["select one", "select...", "select", ""]:
                        lbl = _get_workday_dropdown_label(driver, trigger)
                        if lbl and lbl not in blacklist:
                            target_trigger = trigger
                            target_label = lbl
                            break
            except Exception:
                pass
                
        if not target_trigger:
            break
            
        success = _fill_workday_dropdown(driver, target_trigger, target_label)
        if success:
            filled += 1
            time.sleep(0.5)
        else:
            blacklist.add(target_label)
    return filled


def _smart_fill_standard_fields(driver, url: str, company: str) -> int:
    """
    Universally fill common fields (first name, last name, email, phone, city, notice period,
    current CTC, expected CTC, LinkedIn URL, GitHub URL).
    Returns count of fields filled.
    """
    import config.profile
    importlib.reload(config.profile)
    profile = config.profile.PROFILE

    field_map = [
        # (CSS selector, value, label_hint)
        ("input[name='first_name'], input[id='first_name'], input[data-automation-id='legalNameSection_firstName'], input[name*='firstName'], input[id*='firstName']",
         profile.get("first_name", ""), "first name"),
        ("input[name='last_name'], input[id='last_name'], input[data-automation-id='legalNameSection_lastName'], input[name*='lastName'], input[id*='lastName']",
         profile.get("last_name", ""), "last name"),
        ("input[name='email'], input[id='email'], input[type='email'], input[data-automation-id='email'], input[name*='Email'], input[id*='email']",
         get_custom_email_for_company(url), "email"),
        ("input[name='phone'], input[id='phone'], input[type='tel'], input[name*='phone'], input[id*='phone'], input[name*='mobile'], input[id*='mobile']",
         profile.get("phone", ""), "phone"),
        ("input[name='location'], input[id='location'], input[name*='city'], input[id*='city'], input[name*='location'], input[data-automation-id='addressSection_city']",
         profile.get("city", ""), "city"),
        ("input[name*='linkedin'], input[id*='linkedin'], input[placeholder*='linkedin'], input[data-automation-id*='linkedin']",
         profile.get("linkedin_url", ""), "linkedin"),
        ("input[name*='github'], input[id*='github'], input[placeholder*='github']",
         profile.get("github_url", ""), "github"),
        ("input[name*='notice'], input[id*='notice'], input[placeholder*='notice'], input[name*='Notice']",
         profile.get("notice_period", "15"), "notice period"),
        ("input[name*='currentCtc'], input[name*='current_ctc'], input[id*='currentCtc'], input[name*='CurrentSalary'], input[placeholder*='current salary'], input[placeholder*='current ctc']",
         profile.get("current_ctc", "15"), "current ctc"),
        ("input[name*='expectedCtc'], input[name*='expected_ctc'], input[id*='expectedCtc'], input[name*='ExpectedSalary'], input[placeholder*='expected salary'], input[placeholder*='expected ctc']",
         profile.get("expected_ctc", "18"), "expected ctc"),
    ]

    filled = 0

    # Workday-specific fill using legacy data-automation-id mapping
    if "myworkdayjobs" in url.lower() or "workday" in url.lower():
        workday_map = {
            "legalNameSection_firstName":  profile.get("first_name", ""),
            "legalNameSection_lastName":   profile.get("last_name", ""),
            "email":                       get_custom_email_for_company(url),
            "phone":                       profile.get("phone", ""),
            "addressSection_city":         profile.get("city", ""),
            "addressSection_countryRegion": profile.get("country", "India"),
            "linkedin":                    profile.get("linkedin_url", ""),
            "github":                      profile.get("github_url", ""),
        }
        
        for field_id, val in workday_map.items():
            if not val:
                continue
            inputs = driver.find_elements(By.CSS_SELECTOR, f"input[data-automation-id*='{field_id}'], textarea[data-automation-id*='{field_id}']")
            for inp in inputs:
                try:
                    if inp.is_displayed() and not (inp.get_attribute("value") or "").strip():
                        force_set_value(driver, inp, str(val))
                        print(f"  [FILL WORKDAY] {field_id}: {val}")
                        filled += 1
                except Exception:
                    pass

    for selector, value, label in field_map:
        if not value:
            continue
        for sel in selector.split(","):
            sel = sel.strip()
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                try:
                    if el.is_displayed() and not (el.get_attribute("value") or "").strip():
                        force_set_value(driver, el, str(value))
                        print(f"  [FILL] {label}: {value}")
                        filled += 1
                        break
                except Exception:
                    pass
    return filled


def _smart_fill_dropdowns(driver) -> int:
    """Auto-fill country, phone code, year of experience dropdowns."""
    filled = 0
    
    # 1. Custom Workday dropdown handler
    url = driver.current_url.lower()
    if "myworkdayjobs" in url or "workday" in url:
        filled += _fill_workday_custom_dropdowns(driver)

    # 2. Standard HTML select elements handler
    selects = driver.find_elements(By.CSS_SELECTOR, "select")
    for sel_el in selects:
        try:
            if not sel_el.is_displayed():
                continue
            s = Select(sel_el)
            name = (sel_el.get_attribute("name") or "").lower()
            label_text = ""
            try:
                label_id = sel_el.get_attribute("id")
                if label_id:
                    lbl = driver.find_elements(By.CSS_SELECTOR, f"label[for='{label_id}']")
                    if lbl:
                        label_text = lbl[0].text.lower()
            except Exception:
                pass
            context = name + label_text

            options = [o.text.strip() for o in s.options if o.text.strip()]
            if not options:
                continue

            current_val = (s.first_selected_option.text or "").strip()

            if "country" in context:
                for opt in ["India", "United States", "US"]:
                    if opt in options:
                        s.select_by_visible_text(opt)
                        filled += 1
                        break
            elif "phone" in context or "code" in context:
                for opt in ["+91", "+1"]:
                    if opt in options:
                        s.select_by_visible_text(opt)
                        filled += 1
                        break
            elif ("year" in context or "experience" in context) and not current_val:
                exp_str = PROFILE.get("total_experience_years", "4")
                try:
                    exp_num = round(float(exp_str))
                    for opt in options:
                        num_m = re.search(r'\d+', opt)
                        if num_m and int(num_m.group()) == exp_num:
                            s.select_by_visible_text(opt)
                            filled += 1
                            break
                except Exception:
                    pass
            elif ("notice" in context or "joining" in context) and not current_val:
                notice = PROFILE.get("notice_period", "15")
                for opt in options:
                    if notice in opt or opt.startswith(notice):
                        s.select_by_visible_text(opt)
                        filled += 1
                        break
        except Exception:
            pass
    return filled


def _smart_fill_radios(driver) -> int:
    """Answer yes/no and agreement radio button groups."""
    filled = 0
    try:
        radio_groups = {}
        radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for r in radios:
            name = r.get_attribute("name") or ""
            if name not in radio_groups:
                radio_groups[name] = []
            radio_groups[name].append(r)

        for name, radios_list in radio_groups.items():
            if any(r.is_selected() for r in radios_list):
                continue
            group_label = ""
            try:
                parent = driver.execute_script(
                    "let el = arguments[0]; while(el && el.tagName !== 'FIELDSET' && "
                    "el.tagName !== 'DIV' && el.tagName !== 'FORM') el = el.parentElement; return el;",
                    radios_list[0])
                if parent:
                    group_label = parent.text.lower()
            except Exception:
                pass

            for r in radios_list:
                try:
                    val = (r.get_attribute("value") or "").lower()
                    label_text = ""
                    try:
                        rid = r.get_attribute("id")
                        if rid:
                            lbl = driver.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                            if lbl:
                                label_text = lbl[0].text.lower()
                    except Exception:
                        pass
                    context = group_label + " " + label_text

                    should_select = False
                    if val in ("yes", "true", "1"):
                        if any(k in context for k in ["authoriz", "eligible", "willing", "consent",
                                                        "agree", "legal", "available", "current"]):
                            should_select = True
                    if val in ("no", "false", "0"):
                        if any(k in context for k in ["sponsor", "visa required", "criminal"]):
                            should_select = True

                    if should_select and r.is_displayed():
                        driver.execute_script("arguments[0].click();", r)
                        print(f"  [RADIO] Set '{label_text or val}' for group '{name}'")
                        filled += 1
                        break
                except Exception:
                    pass
    except Exception:
        pass
    return filled


def _smart_fill_checkboxes(driver) -> int:
    """Auto-check agreement/consent checkboxes."""
    filled = 0
    try:
        checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        for chk in checkboxes:
            if not chk.is_displayed() or chk.is_selected():
                continue
            label_text = ""
            try:
                cid = chk.get_attribute("id")
                if cid:
                    lbls = driver.find_elements(By.CSS_SELECTOR, f"label[for='{cid}']")
                    if lbls:
                        label_text = lbls[0].text.lower()
            except Exception:
                pass
            if any(k in label_text for k in ["agree", "accept", "consent", "authoriz",
                                               "terms", "policy", "privacy", "confirm"]):
                try:
                    driver.execute_script("arguments[0].click();", chk)
                    print(f"  [CHECK] Checked: '{label_text[:50]}'")
                    filled += 1
                except Exception:
                    pass
    except Exception:
        pass
    return filled


def _upload_resume(driver, resume_path: str) -> bool:
    """Upload resume to any file input field."""
    if not os.path.exists(resume_path):
        return False
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    for fi in file_inputs:
        try:
            current = fi.get_attribute("value") or ""
            if not current:
                fi.send_keys(resume_path)
                human_pause(2, 3)
                print("  [RESUME] Uploaded resume.")
                return True
        except Exception:
            pass
    return False


def _fill_cover_letter(driver, body_text: str, company: str, role: str):
    """Fill cover letter textareas if present."""
    try:
        cover_selectors = [
            "textarea[name*='cover']", "textarea[id*='cover']", "textarea[class*='cover']",
            "textarea[aria-label*='cover']", "textarea[placeholder*='cover']",
            "textarea[name*='letter']", "textarea[id*='letter']",
        ]
        for sel in cover_selectors:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and not (el.get_attribute("value") or "").strip():
                    cover = _gemini_cover_letter(body_text, company, role)
                    el.clear()
                    el.send_keys(cover)
                    print("  [COVER] Cover letter filled.")
                    return
    except Exception:
        pass


def _fill_unknown_fields_via_ai(driver) -> int:
    """
    Scan for any visible, empty text/textarea inputs that haven't been filled.
    Use Gemini to determine and fill values for unrecognised fields.
    """
    filled = 0
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[type='text'], input[type='number'], input[type='tel'], input[type='email'], textarea")
        for el in inputs:
            try:
                if not el.is_displayed():
                    continue
                val = (el.get_attribute("value") or "").strip()
                if val:
                    continue  # Already filled
                # Get label
                label = ""
                try:
                    eid = el.get_attribute("id")
                    ph  = el.get_attribute("placeholder") or ""
                    aria = el.get_attribute("aria-label") or ""
                    name = el.get_attribute("name") or ""
                    if eid:
                        lbls = driver.find_elements(By.CSS_SELECTOR, f"label[for='{eid}']")
                        if lbls:
                            label = lbls[0].text.strip()
                    if not label:
                        label = ph or aria or name
                except Exception:
                    pass
                if not label or len(label) < 3:
                    continue
                answer = _gemini_field_answer(label, el.get_attribute("type") or "text")
                if answer:
                    force_set_value(driver, el, answer)
                    print(f"  [AI FILL] '{label}' -> '{answer}'")
                    filled += 1
            except Exception:
                pass
    except Exception:
        pass
    return filled


def _click_next_or_submit(driver) -> str:
    """
    Try to click Next/Continue/Review/Submit button.
    Returns 'submitted', 'advanced', or 'stuck'.
    """
    # Check for Submit
    for sel in [
        "button[data-automation-id='bottom-navigation-next-button'][aria-label*='Submit']",
        "button[data-automation-id*='submit']",
        "button[type='submit']",
        "input[type='submit']",
        "//button[contains(.,'Submit Application')]",
        "//button[contains(.,'Submit')]",
        "//input[@type='submit']",
    ]:
        try:
            btns = driver.find_elements(
                By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for btn in btns:
                # Avoid clicking login or registration submit buttons again on the application pages
                btn_id = btn.get_attribute("data-automation-id") or ""
                btn_text = btn.text.lower()
                if "signin" in btn_id.lower() or "createaccount" in btn_id.lower() or "create account" in btn_text or "sign in" in btn_text:
                    continue
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    return "submitted"
        except Exception:
            pass

    # Check for Next/Continue
    for sel in [
        "button[data-automation-id='bottom-navigation-next-button']",
        "button[data-automation-id*='next-button']",
        "//button[contains(.,'Next')]",
        "//button[contains(.,'Continue')]",
        "//button[contains(.,'Save and Continue')]",
        "//button[contains(.,'Review')]",
        "//a[contains(.,'Next')]",
    ]:
        try:
            btns = driver.find_elements(
                By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for btn in btns:
                btn_id = btn.get_attribute("data-automation-id") or ""
                btn_text = btn.text.lower()
                if "signin" in btn_id.lower() or "createaccount" in btn_id.lower() or "create account" in btn_text or "sign in" in btn_text:
                    continue
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    return "advanced"
        except Exception:
            pass

    return "stuck"


def _check_success(driver) -> bool:
    """Detect success/confirmation screen."""
    success_indicators = [
        "div[data-automation-id='confirmationMessage']",
        ".application-success", ".success-page", ".confirmation",
        "//h1[contains(.,'Application Submitted')]",
        "//h1[contains(.,'Thank you')]",
        "//h2[contains(.,'successfully submitted')]",
        "//p[contains(.,'application has been submitted')]",
    ]
    for sel in success_indicators:
        try:
            els = driver.find_elements(
                By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            if any(el.is_displayed() for el in els):
                return True
        except Exception:
            pass
    return False


def _fill_workday_experience_blocks(driver, profile: dict, brain_ctx: dict, submit_gate) -> int:
    """Automates Workday Work Experience blocks (Screenshots 1 & 5)."""
    work_history = profile.get("work_experience", [])
    if not work_history:
        # Fallback: check profile main data or look for config profiles
        return 0

    filled = 0
    try:
        container = driver.find_element(By.CSS_SELECTOR, "[data-automation-id='workExperienceSection'], fieldset")
    except Exception:
        container = driver

    blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='workExperience']")
    needed = len(work_history)
    for _ in range(needed - len(blocks)):
        try:
            add_btn = container.find_element(By.XPATH, "//button[contains(.,'Add another') or contains(.,'Add Work Experience') or contains(.,'Add')]")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_btn)
            driver.execute_script("arguments[0].click();", add_btn)
            time.sleep(1.0)
            blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='workExperience']")
        except Exception:
            break

    for idx, exp in enumerate(work_history):
        if idx >= len(blocks):
            break
        block = blocks[idx]
        context_prefix = f"Work Experience {idx + 1}"
        print(f"  [WORKDAY BLOCK] Filling Work Experience {idx + 1}: {exp.get('job_title')} at {exp.get('company')}")

        # Scroll the block into view to ensure elements are active and visible
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", block)
            time.sleep(0.5)
        except Exception:
            pass

        def resolve_and_set(label, field_type, selector_or_el, val, options=None):
            nonlocal filled
            try:
                if isinstance(selector_or_el, str):
                    el = block.find_element(By.CSS_SELECTOR, selector_or_el)
                else:
                    el = selector_or_el
                if el.is_displayed():
                    from field_resolver import resolve_field_value
                    ans = resolve_field_value(
                        label=label,
                        field_type=field_type,
                        options=options,
                        qa_store=brain_ctx.get("qa_store") if brain_ctx else None,
                        resume_facts=brain_ctx.get("resume_facts") if brain_ctx else None,
                        resume_text=brain_ctx.get("resume_text") if brain_ctx else None,
                        call_llm=brain_ctx.get("call_llm") if brain_ctx else None,
                        ask_human=brain_ctx.get("ask_human") if brain_ctx else None,
                        context_prefix=context_prefix
                    )
                    if submit_gate:
                        submit_gate.record(ans)
                    value_to_use = ans.value if ans.value else val
                    if value_to_use:
                        force_set_value(driver, el, value_to_use)
                        filled += 1
            except Exception:
                pass

        resolve_and_set("Job Title", "text", "input[data-automation-id='jobTitle'], input[name*='jobTitle']", exp.get("job_title", ""))
        resolve_and_set("Company", "text", "input[data-automation-id='company'], input[name*='company']", exp.get("company", ""))
        resolve_and_set("Location", "text", "input[data-automation-id='location'], input[name*='location']", exp.get("location", ""))
        
        try:
            chk = block.find_element(By.CSS_SELECTOR, "input[type='checkbox'], [data-automation-id='currentlyWorkHere']")
            is_checked = chk.is_selected()
            should_check = exp.get("currently_work_here", False)
            if is_checked != should_check:
                driver.execute_script("arguments[0].click();", chk)
                filled += 1
        except Exception:
            pass

        # Unified vs Separate Start Date
        unified_start_selectors = [
            "input[data-automation-id='dateSection_startDate-input']",
            "input[placeholder='MM/YYYY']",
            "div[data-automation-id='dateSection_startDate'] input"
        ]
        unified_start_el = None
        for sel in unified_start_selectors:
            try:
                el = block.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    unified_start_el = el
                    break
            except Exception:
                pass

        if unified_start_el:
            start_date_val = f"{exp.get('start_month', '')}/{exp.get('start_year', '')}"
            if start_date_val.strip() != "/":
                resolve_and_set("From Date", "text", unified_start_el, start_date_val)
        else:
            resolve_and_set("From Month", "text", "input[data-automation-id='dateSection_startDate-month'], input[placeholder='MM']", exp.get("start_month", ""))
            resolve_and_set("From Year", "text", "input[data-automation-id='dateSection_startDate-year'], input[placeholder='YYYY']", exp.get("start_year", ""))

        # Unified vs Separate End Date
        if not exp.get("currently_work_here", False):
            unified_end_selectors = [
                "input[data-automation-id='dateSection_endDate-input']",
                "div[data-automation-id='dateSection_endDate'] input"
            ]
            unified_end_el = None
            for sel in unified_end_selectors:
                try:
                    el = block.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        unified_end_el = el
                        break
                except Exception:
                    pass
            if not unified_end_el:
                try:
                    mm_yyyy_inputs = block.find_elements(By.CSS_SELECTOR, "input[placeholder='MM/YYYY']")
                    visible_mm_yyyy = [el for el in mm_yyyy_inputs if el.is_displayed() and el != unified_start_el]
                    if visible_mm_yyyy:
                        unified_end_el = visible_mm_yyyy[0]
                except Exception:
                    pass

            if unified_end_el:
                end_date_val = f"{exp.get('end_month', '')}/{exp.get('end_year', '')}"
                if end_date_val.strip() != "/":
                    resolve_and_set("To Date", "text", unified_end_el, end_date_val)
            else:
                resolve_and_set("To Month", "text", "input[data-automation-id='dateSection_endDate-month'], input[placeholder='MM']", exp.get("end_month", ""))
                resolve_and_set("To Year", "text", "input[data-automation-id='dateSection_endDate-year'], input[placeholder='YYYY']", exp.get("end_year", ""))
            
        resolve_and_set("Role Description", "textarea", "textarea[data-automation-id='description'], textarea[name*='description'], textarea", exp.get("description", ""))

    return filled


def _fill_workday_education_blocks(driver, profile: dict, brain_ctx: dict, submit_gate) -> int:
    """Automates Workday Education blocks (Screenshot 2)."""
    edu_history = profile.get("education", [])
    if not edu_history:
        return 0

    filled = 0
    try:
        container = driver.find_element(By.CSS_SELECTOR, "[data-automation-id='educationSection'], fieldset")
    except Exception:
        container = driver

    blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='education']")
    needed = len(edu_history)
    for _ in range(needed - len(blocks)):
        try:
            add_btn = container.find_element(By.XPATH, "//button[contains(.,'Add another') or contains(.,'Add Education') or contains(.,'Add')]")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_btn)
            driver.execute_script("arguments[0].click();", add_btn)
            time.sleep(1.0)
            blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='education']")
        except Exception:
            break

    for idx, edu in enumerate(edu_history):
        if idx >= len(blocks):
            break
        block = blocks[idx]
        context_prefix = f"Education {idx + 1}"
        print(f"  [WORKDAY BLOCK] Filling Education {idx + 1}: {edu.get('school')}")

        # Scroll the block into view to ensure elements are active and visible
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", block)
            time.sleep(0.5)
        except Exception:
            pass

        def resolve_and_set(label, field_type, selector_or_el, val, options=None):
            nonlocal filled
            try:
                if isinstance(selector_or_el, str):
                    el = block.find_element(By.CSS_SELECTOR, selector_or_el)
                else:
                    el = selector_or_el
                if el.is_displayed():
                    from field_resolver import resolve_field_value
                    ans = resolve_field_value(
                        label=label,
                        field_type=field_type,
                        options=options,
                        qa_store=brain_ctx.get("qa_store") if brain_ctx else None,
                        resume_facts=brain_ctx.get("resume_facts") if brain_ctx else None,
                        resume_text=brain_ctx.get("resume_text") if brain_ctx else None,
                        call_llm=brain_ctx.get("call_llm") if brain_ctx else None,
                        ask_human=brain_ctx.get("ask_human") if brain_ctx else None,
                        context_prefix=context_prefix
                    )
                    if submit_gate:
                        submit_gate.record(ans)
                    value_to_use = ans.value if ans.value else val
                    if value_to_use:
                        force_set_value(driver, el, value_to_use)
                        filled += 1
            except Exception:
                pass

        resolve_and_set("School or University", "text", "input[data-automation-id='school'], input[name*='school']", edu.get("school", ""))
        resolve_and_set("Field of Study", "text", "input[data-automation-id='fieldOfStudy'], input[name*='fieldOfStudy']", edu.get("field_of_study", ""))
        resolve_and_set("GPA", "text", "input[data-automation-id='gpa'], input[name*='gpa']", edu.get("gpa", ""))
        resolve_and_set("From Year", "text", "input[data-automation-id='dateSection_startDate-year'], input[placeholder='YYYY']", edu.get("start_year", ""))
        resolve_and_set("To Year", "text", "input[data-automation-id='dateSection_endDate-year'], input[placeholder='YYYY']", edu.get("end_year", ""))

        try:
            degree_dropdown = block.find_element(By.CSS_SELECTOR, "[data-automation-id='dropdownActiveOption']")
            _fill_workday_dropdown(driver, degree_dropdown, f"Degree {idx+1}")
            filled += 1
        except Exception:
            pass

    return filled


def _fill_workday_languages_blocks(driver, profile: dict, brain_ctx: dict, submit_gate) -> int:
    """Automates Workday Languages blocks (Screenshot 4)."""
    languages = profile.get("languages", [])
    if not languages:
        return 0

    filled = 0
    try:
        container = driver.find_element(By.CSS_SELECTOR, "[data-automation-id='languagesSection'], fieldset")
    except Exception:
        container = driver

    blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='language']")
    needed = len(languages)
    for _ in range(needed - len(blocks)):
        try:
            add_btn = container.find_element(By.XPATH, "//button[contains(.,'Add another') or contains(.,'Add Language') or contains(.,'Add')]")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_btn)
            driver.execute_script("arguments[0].click();", add_btn)
            time.sleep(1.0)
            blocks = container.find_elements(By.CSS_SELECTOR, "[data-automation-id='panel'], .wd-panel, div[id*='language']")
        except Exception:
            break

    for idx, lang in enumerate(languages):
        if idx >= len(blocks):
            break
        block = blocks[idx]
        print(f"  [WORKDAY BLOCK] Filling Language {idx + 1}: {lang.get('language')}")

        try:
            lang_dropdown = block.find_element(By.CSS_SELECTOR, "[data-automation-id='dropdownActiveOption']")
            _fill_workday_dropdown(driver, lang_dropdown, f"Language {idx+1}")
            filled += 1
        except Exception:
            pass

        try:
            chk = block.find_element(By.CSS_SELECTOR, "input[type='checkbox'], [data-automation-id='fluent']")
            is_checked = chk.is_selected()
            should_check = lang.get("fluent", False)
            if is_checked != should_check:
                driver.execute_script("arguments[0].click();", chk)
                filled += 1
        except Exception:
            pass

        try:
            prof_dropdowns = block.find_elements(By.CSS_SELECTOR, "[data-automation-id='dropdownActiveOption']")
            if len(prof_dropdowns) > 1:
                _fill_workday_dropdown(driver, prof_dropdowns[1], f"Proficiency {idx+1}")
                filled += 1
        except Exception:
            pass

    return filled


def _fill_workday_skills_combobox(driver, profile: dict, brain_ctx: dict, submit_gate) -> int:
    """Automates Workday dynamic search-and-select multiselect combobox for Skills (Screenshot 3)."""
    skills = profile.get("skills", [])
    if not skills:
        import config.profile
        skills = getattr(config.profile, "MY_SKILLS", [])
        
    filled = 0
    try:
        search_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='Search'], input[placeholder*='Skills'], [role='combobox'] input")
        
        for search_input in search_inputs:
            if not search_input.is_displayed():
                continue
            
            try:
                parent_text = driver.execute_script("return arguments[0].parentElement.innerText;", search_input).lower()
                if "skill" not in parent_text and "languages" not in parent_text:
                    continue
            except Exception:
                pass

            print(f"  [WORKDAY SKILLS] Automating Skills Combobox...")

            for skill in skills[:10]:
                try:
                    driver.execute_script("arguments[0].focus();", search_input)
                    search_input.send_keys(Keys.CONTROL + "a")
                    search_input.send_keys(Keys.BACKSPACE)
                    time.sleep(0.1)
                    
                    search_input.send_keys(skill)
                    time.sleep(1.0)
                    
                    options = driver.find_elements(By.CSS_SELECTOR, "[role='option'], [data-automation-id='searchResultItem'], div.searchResultItem")
                    
                    match_el = None
                    for opt in options:
                        if skill.lower() in opt.text.lower():
                            match_el = opt
                            break
                    
                    if not match_el and options:
                        match_el = options[0]
                        
                    if match_el:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", match_el)
                        time.sleep(0.2)
                        driver.execute_script("arguments[0].click();", match_el)
                        time.sleep(0.5)
                        filled += 1
                except Exception:
                    pass
    except Exception:
        pass
    return filled


def _smart_fill_remaining_unknown_fields(driver, brain_ctx: dict, submit_gate) -> int:
    """Scans all remaining empty visible inputs and batch resolves them using Gemini."""
    if not brain_ctx:
        return 0
        
    filled = 0
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='number'], input[type='tel'], input[type='email'], textarea")
        empty_fields = []
        
        for el in inputs:
            try:
                if not el.is_displayed():
                    continue
                val = (el.get_attribute("value") or "").strip()
                if val:
                    continue
                
                label = ""
                eid = el.get_attribute("id")
                ph = el.get_attribute("placeholder") or ""
                aria = el.get_attribute("aria-label") or ""
                name = el.get_attribute("name") or ""
                if eid:
                    lbls = driver.find_elements(By.CSS_SELECTOR, f"label[for='{eid}']")
                    if lbls:
                        label = lbls[0].text.strip()
                if not label:
                    label = ph or aria or name
                
                if label and len(label) >= 3:
                    empty_fields.append({
                        "label": label,
                        "type": el.get_attribute("type") or "text",
                        "element": el
                    })
            except Exception:
                pass
                
        if not empty_fields:
            return 0
            
        print(f"  [BRAIN BATCH] Batch-resolving {len(empty_fields)} empty fields via Gemini...")
        
        from field_resolver import resolve_field_value
        for item in empty_fields:
            try:
                ans = resolve_field_value(
                    label=item["label"],
                    field_type=item["type"],
                    qa_store=brain_ctx["qa_store"],
                    resume_facts=brain_ctx["resume_facts"],
                    resume_text=brain_ctx["resume_text"],
                    call_llm=brain_ctx["call_llm"],
                    ask_human=brain_ctx["ask_human"]
                )
                if submit_gate:
                    submit_gate.record(ans)
                if ans.value:
                    force_set_value(driver, item["element"], ans.value)
                    print(f"    [RESOLVED] '{item['label']}' -> '{ans.value}' (conf={ans.confidence:.2f})")
                    filled += 1
            except Exception:
                pass
    except Exception as e:
        print(f"  [BRAIN BATCH ERROR] Batch execution failed: {e}")
        
    return filled


def _universal_multi_page_apply(driver, url: str, company: str, role: str,
                                  max_steps: int = 15) -> bool:
    """
    Universal multi-page form filler. Works across all ATS platforms.
    Iteratively:
      1. Fills all standard fields on visible form
      2. Uploads resume if not already uploaded
      3. Fills cover letter if present
      4. Fills dropdowns, radios, checkboxes
      5. Fills unknown fields via Gemini AI
      6. Evaluates confidence via SubmitGate
      7. Clicks Next/Submit
      8. Detects stalls and self-heals validation errors
      9. Detects success screen
    """
    resume_path = get_tailored_resume_path(driver, company, role)
    body_text = ""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        pass

    # Initialize resolver brain
    brain_ctx = None
    submit_gate = None
    try:
        from field_resolver import QAStore, clear_page_llm_cache
        from submit_gate import SubmitGate
        from resume_parser import parse_resume, load_cached_resume
        
        cache_path = "logs/resume_cache.json"
        parsed = load_cached_resume(cache_path)
        if parsed is None and os.path.exists(resume_path):
            parsed = parse_resume(resume_path, cache_path=cache_path)
            
        resume_facts = parsed.facts if parsed else {}
        resume_text = parsed.raw_text if parsed else ""
        
        qa_store = QAStore()
        submit_gate = SubmitGate()
        
        # LLM Caller via Gemini
        def call_gemini(system_prompt: str, user_prompt: str) -> str:
            import google.generativeai as genai
            import config.profile
            importlib.reload(config.profile)
            api_key = getattr(config.profile, "GEMINI_API_KEY", "")
            if not api_key:
                return "UNKNOWN"
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            prompt = f"{system_prompt}\n\nUser Question:\n{user_prompt}"
            response = model.generate_content(prompt)
            return response.text.strip()
            
        # Non-blocking Human Asker callback
        def ask_human_non_blocking(label: str, field_type: str, options: list) -> str:
            from qa_store import record_unanswered
            record_unanswered(label, portal="Workday")
            return ""
            
        brain_ctx = {
            "qa_store": qa_store,
            "resume_facts": resume_facts,
            "resume_text": resume_text,
            "call_llm": call_gemini,
            "ask_human": ask_human_non_blocking
        }
        print("  [BRAIN] Gated resolution brain initialized.")
    except Exception as brain_ex:
        print(f"  [BRAIN][WARN] Failed to initialize resolver brain: {brain_ex}")

    resume_uploaded = False
    last_url = ""
    stall_count = 0

    for step in range(max_steps):
        current_url = driver.current_url
        print(f"  [PAGE {step + 1}] URL: {current_url[:80]}...")

        # Reset page metrics
        if submit_gate:
            submit_gate.reset()
        try:
            from field_resolver import clear_page_llm_cache
            clear_page_llm_cache()
        except Exception:
            pass

        # Check success
        if _check_success(driver):
            print(f"  [SUCCESS] Application success screen detected!")
            return True

        # Check OTP/verification wall
        _handle_otp_wall(driver)
        human_pause(0.5, 1.0)

        # Fill standard fields
        _smart_fill_standard_fields(driver, url, company)

        # Workday block autofills
        if "workday" in driver.current_url.lower() or "myworkdayjobs" in driver.current_url.lower():
            try:
                import config.profile
                importlib.reload(config.profile)
                _fill_workday_experience_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate)
                _fill_workday_education_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate)
                _fill_workday_languages_blocks(driver, config.profile.PROFILE, brain_ctx, submit_gate)
                _fill_workday_skills_combobox(driver, config.profile.PROFILE, brain_ctx, submit_gate)
            except Exception as wd_blocks_ex:
                print(f"  [WORKDAY][WARN] Workday blocks fill error: {wd_blocks_ex}")

        # Upload resume
        if not resume_uploaded:
            resume_uploaded = _upload_resume(driver, resume_path)

        # Fill cover letter
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            pass
        _fill_cover_letter(driver, body_text, company, role)

        # Fill dropdowns, radios, checkboxes
        _smart_fill_dropdowns(driver)
        _smart_fill_radios(driver)
        _smart_fill_checkboxes(driver)

        # Fill unknown fields via AI Batch Resolver
        _smart_fill_remaining_unknown_fields(driver, brain_ctx, submit_gate)

        human_pause(0.5, 1.0)

        # Evaluate gating policy
        can_proceed = True
        if submit_gate:
            gate_res = submit_gate.evaluate()
            if not gate_res.can_auto_submit:
                can_proceed = False
                print(f"  [GATE] Pausing submit/next: {gate_res.reason}")
                try:
                    # Highlight low-confidence fields in yellow on page
                    driver.execute_script("""
                        var fields = arguments[0];
                        fields.forEach(f => {
                            document.querySelectorAll('input, select, textarea').forEach(el => {
                                var lbl = el.getAttribute('data-bot-label') || el.placeholder || el.name || '';
                                if(lbl.toLowerCase().includes(f.toLowerCase())) {
                                    el.style.border = '2px dashed #eab308';
                                    el.style.backgroundColor = 'rgba(234, 179, 8, 0.05)';
                                }
                            });
                        });
                        
                        var status = document.getElementById('copilot-status');
                        if (status) {
                            status.innerHTML = '⚠️ <b>Gated:</b> Review highlighted fields on page.';
                            status.style.color = '#eab308';
                        }
                    """, [a.field_label for a in gate_res.low_confidence_fields])
                except Exception:
                    pass

        if not can_proceed:
            # Sleep and continue the loop without clicking next.
            # This returns control to the user's manual chrome instance immediately!
            human_pause(2, 3)
            stall_count += 1
            if stall_count >= 5:
                print("  [FAIL] Form stalled at review gate for too long.")
                return False
            continue

        # Try to advance
        action = _click_next_or_submit(driver)
        human_pause(2, 4)

        if action == "submitted":
            human_pause(2, 3)
            if _check_success(driver):
                print(f"  [SUCCESS] Application submitted successfully!")
                return True
            print("  [WARN] Submit clicked but success not confirmed. Checking for errors...")
            stall_count += 1
            if stall_count >= 3:
                screenshot_filename = f"validation_error_page_{step+1}.png"
                logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(logs_dir, exist_ok=True)
                screenshot_path = os.path.join(logs_dir, screenshot_filename)
                artifact_path = os.path.join(r"C:\Users\Pratik\.gemini\antigravity\brain\ea2d3941-8ecf-4346-ae66-07af174ae292", screenshot_filename)
                try:
                    driver.save_screenshot(screenshot_path)
                    import shutil
                    shutil.copy2(screenshot_path, artifact_path)
                    print(f"  [DEBUG] Saved screenshot of validation errors at: {artifact_path}")
                except Exception as e:
                    print(f"  [DEBUG] Could not save validation error screenshot: {e}")
                print("  [FAIL] Could not clear validation errors after 3 attempts.")
                return False
        elif action == "advanced":
            if current_url == last_url:
                stall_count += 1
            else:
                stall_count = 0
            last_url = driver.current_url
        elif action == "stuck":
            stall_count += 1
            if stall_count >= 3:
                screenshot_filename = f"stuck_page_{step+1}.png"
                logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
                os.makedirs(logs_dir, exist_ok=True)
                screenshot_path = os.path.join(logs_dir, screenshot_filename)
                artifact_path = os.path.join(r"C:\Users\Pratik\.gemini\antigravity\brain\ea2d3941-8ecf-4346-ae66-07af174ae292", screenshot_filename)
                try:
                    driver.save_screenshot(screenshot_path)
                    import shutil
                    shutil.copy2(screenshot_path, artifact_path)
                    print(f"  [DEBUG] Saved screenshot of stuck form at: {artifact_path}")
                except Exception as e:
                    print(f"  [DEBUG] Could not save screenshot: {e}")
                print("  [WARN] Form stuck — no navigation button found.")
                return False

        if stall_count >= 5:
            print("  [FAIL] Form stalled for too long. Giving up.")
            return False

    return False


# ─── Platform Detection ───────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    """Detect which ATS platform the URL belongs to."""
    url_lower = url.lower()
    if "myworkdayjobs" in url_lower or "wd1.myworkday" in url_lower or "workday" in url_lower:
        return "workday"
    elif "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
        return "greenhouse"
    elif "jobs.lever.co" in url_lower:
        return "lever"
    elif "icims.com" in url_lower or "careers.icims" in url_lower:
        return "icims"
    elif "taleo.net" in url_lower or "tbe.taleo.net" in url_lower:
        return "taleo"
    elif "successfactors.com" in url_lower or "sap.com/hiring" in url_lower:
        return "successfactors"
    elif "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    else:
        return "generic"


# ─── Platform Appliers ────────────────────────────────────────────────────────

def apply_workday(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Full Workday application handler: login/register → multi-step form → OTP → submit."""
    print(f"  [WORKDAY] Loading page...")
    driver.get(url)

    # Wait for full SPA render — Workday uses heavy JavaScript
    human_pause(5, 8)

    # ── Detect Workday bot-block / redirect ───────────────────────────────────
    current_url = driver.current_url
    if "invalid-url" in current_url or "community.workday.com" in current_url:
        print(f"  [WORKDAY] Redirect detected ({current_url}). Clearing cookies and retrying...")
        driver.delete_all_cookies()
        human_pause(2, 3)
        driver.get(url)
        human_pause(6, 10)
        current_url = driver.current_url
        if "invalid-url" in current_url or "community.workday.com" in current_url:
            print(f"  [WORKDAY][FAIL] Still redirected after cookie clear. URL may be expired or geo-blocked.")
            return False

    # Check page actually loaded something useful
    page_title = driver.title
    if "page not found" in page_title.lower() or "404" in page_title.lower():
        print(f"  [WORKDAY][FAIL] Job page returned 404/Not Found: {page_title}")
        return False

    print(f"  [WORKDAY] Page loaded: {page_title[:60]}")

    # ── Wait for job page content to appear ───────────────────────────────────
    # Workday renders everything via React — wait for job title or apply button
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                "[data-automation-id='jobPostingHeader'], [data-automation-id='applyNowButton'], "
                "h1, .WGDC, [data-automation-id='jobTitle']"
            ))
        )
        print(f"  [WORKDAY] Job content rendered.")
    except TimeoutException:
        print(f"  [WORKDAY][WARN] Job content render timed out, proceeding anyway...")

    # ── Dismiss Cookie Banner ─────────────────────────────────────────────────
    try:
        cookie_btns = driver.find_elements(By.XPATH,
            "//button[contains(.,'Accept Cookies') or contains(.,'Accept') or contains(.,'Agree') or contains(.,'Decline')] | "
            "//a[contains(.,'Accept Cookies') or contains(.,'Accept') or contains(.,'Agree') or contains(.,'Decline')]"
        )
        for btn in cookie_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                print("  [WORKDAY] Cookie banner dismissed.")
                human_pause(1, 2)
                break
    except Exception:
        pass

    # ── Click Apply / Apply Now button ────────────────────────────────────────
    apply_clicked = False
    for sel in [
        "[data-automation-id='applyNowButton']",
        "[data-automation-id='applyButton']",
        "[data-automation-id*='apply']",
        "//a[text()='Apply']",
        "//a[contains(.,'Apply Now')]",
        "//a[contains(.,'Apply for Job')]",
        "//a[contains(.,'Apply')]",
        "//button[contains(.,'Apply Now')]",
        "//button[contains(.,'Apply')]",
        "//a[contains(@href,'apply')]",
    ]:
        try:
            btns = driver.find_elements(
                By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    print(f"  [WORKDAY] Clicking Apply button: '{btn.text[:40]}'")
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    human_pause(0.5, 1.0)
                    driver.execute_script("arguments[0].click();", btn)
                    apply_clicked = True
                    human_pause(4, 7)
                    break
        except Exception:
            pass
        if apply_clicked:
            break

    if not apply_clicked:
        print(f"  [WORKDAY][WARN] No Apply button found. Page may already be on application form.")

    # ── Handle Start Your Application popup if present ────────────────────────
    human_pause(2, 3)
    popup_clicked = False
    for sel in [
        "[data-automation-id='applyManually']",
        "[data-automation-id='autofillWithResume']",
        "//button[contains(.,'Apply Manually')]",
        "//button[contains(.,'Autofill with Resume')]",
    ]:
        try:
            btns = driver.find_elements(
                By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    print(f"  [WORKDAY] Popup detected. Clicking: '{btn.text[:45]}'")
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    human_pause(0.5, 1.0)
                    driver.execute_script("arguments[0].click();", btn)
                    popup_clicked = True
                    human_pause(5, 8)
                    break
        except Exception:
            pass
        if popup_clicked:
            break

    # ── Check again for redirect after clicking Apply (auth wall) ─────────────
    human_pause(2, 3)
    current_url = driver.current_url
    if "invalid-url" in current_url or "community.workday.com" in current_url:
        print(f"  [WORKDAY][FAIL] Redirected after Apply click — likely requires prior login.")
        return False

    # ── Handle login/register/OTP wall ────────────────────────────────────────
    if not _handle_login_or_register(driver, url):
        print("  [WORKDAY][FAIL] Login or Registration wall could not be cleared.")
        return False
    human_pause(2, 3)

    return _universal_multi_page_apply(driver, url, company, role)




def apply_greenhouse(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Full Greenhouse application handler."""
    print(f"  [GREENHOUSE] Loading form...")
    driver.get(url)
    human_pause(3, 4)

    resume_path = get_tailored_resume_path(driver, company, role)
    _smart_fill_standard_fields(driver, url, company)

    # Greenhouse-specific: LinkedIn URL
    for sel in ["input[name='job_application[urls][LinkedIn]']", "input[name*='linkedin']", "input[id*='linkedin']"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els:
            if el.is_displayed() and not el.get_attribute("value"):
                force_set_value(driver, el, PROFILE.get("linkedin_url", ""))
                break

    _upload_resume(driver, resume_path)
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    _fill_cover_letter(driver, body_text, company, role)
    _smart_fill_dropdowns(driver)
    _smart_fill_radios(driver)
    _smart_fill_checkboxes(driver)
    _fill_unknown_fields_via_ai(driver)

    # Submit
    submitted = False
    for sel in ["button#submit_app", "input[type='submit']", "//button[contains(.,'Submit')]"]:
        btns = driver.find_elements(
            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
        for btn in btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                submitted = True
                break
        if submitted:
            break

    if submitted:
        human_pause(3, 4)
        if _check_success(driver):
            print("  [SUCCESS] Greenhouse application submitted!")
            return True
    return False


def apply_lever(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Full Lever application handler."""
    print(f"  [LEVER] Loading form...")
    driver.get(url)
    human_pause(3, 4)

    resume_path = get_tailored_resume_path(driver, company, role)

    # Lever-specific full name field
    for sel in ["input[name='name']", "input[id='name']"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els:
            if el.is_displayed() and not el.get_attribute("value"):
                force_set_value(driver, el,
                    f"{PROFILE.get('first_name', '')} {PROFILE.get('last_name', '')}".strip())
                break

    _smart_fill_standard_fields(driver, url, company)

    # Lever URL fields
    for name_attr, val in [("urls[LinkedIn]", PROFILE.get("linkedin_url", "")),
                            ("urls[GitHub]",   PROFILE.get("github_url", ""))]:
        els = driver.find_elements(By.CSS_SELECTOR, f"input[name='{name_attr}']")
        for el in els:
            if el.is_displayed() and not el.get_attribute("value"):
                force_set_value(driver, el, val)

    _upload_resume(driver, resume_path)
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        body_text = ""
    _fill_cover_letter(driver, body_text, company, role)
    _smart_fill_dropdowns(driver)
    _smart_fill_radios(driver)
    _smart_fill_checkboxes(driver)
    _fill_unknown_fields_via_ai(driver)

    # Lever submit
    submitted = False
    for sel in [
        "button[type='submit'].template-btn-submit",
        "button[type='submit']",
        "//button[contains(.,'Submit Application')]",
        "//button[contains(.,'Apply')]"
    ]:
        btns = driver.find_elements(
            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
        for btn in btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                submitted = True
                break
        if submitted:
            break

    if submitted:
        human_pause(3, 4)
        if _check_success(driver):
            print("  [SUCCESS] Lever application submitted!")
            return True
    return False


def apply_icims(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Full iCIMS application handler."""
    print(f"  [ICIMS] Loading page...")
    driver.get(url)
    human_pause(3, 5)

    _handle_login_or_register(driver, url)
    human_pause(2, 3)

    return _universal_multi_page_apply(driver, url, company, role)


def apply_taleo(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """
    Full Taleo ATS application handler.
    Taleo is login-required. It uses standard HTML form inputs with
    descriptive name/id patterns (e.g. FlexFieldWidget, rsrCandidateProfile).
    """
    print(f"  [TALEO] Loading page...")
    driver.get(url)
    human_pause(3, 5)

    # Taleo login
    _handle_login_or_register(driver, url)
    human_pause(2, 3)

    # Click Apply Now if visible
    for sel in ["a.applyNow", "//a[contains(.,'Apply')]", "//button[contains(.,'Apply')]"]:
        btns = driver.find_elements(
            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
        for btn in btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                human_pause(2, 4)
                break

    return _universal_multi_page_apply(driver, url, company, role, max_steps=12)


def apply_successfactors(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """
    Full SAP SuccessFactors application handler.
    SuccessFactors is login-required. Uses internal SAP field naming conventions.
    """
    print(f"  [SUCCESSFACTORS] Loading page...")
    driver.get(url)
    human_pause(3, 5)

    _handle_login_or_register(driver, url)
    human_pause(2, 3)

    # Click Apply button
    for sel in [
        "button[title='Apply']",
        "//button[contains(.,'Apply for Job')]",
        "//button[contains(.,'Apply Now')]"
    ]:
        btns = driver.find_elements(
            By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel)
        for btn in btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                human_pause(2, 4)
                break

    return _universal_multi_page_apply(driver, url, company, role, max_steps=12)


def apply_smartrecruiters(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """
    Full SmartRecruiters application handler.
    SmartRecruiters is login-optional (can apply as guest or logged in).
    Standard HTML form with clear naming conventions.
    """
    print(f"  [SMARTRECRUITERS] Loading form...")
    driver.get(url)
    human_pause(3, 4)

    # SmartRecruiters may show a "Continue as Guest" button
    for sel in [
        "//button[contains(.,'Continue as Guest')]",
        "//button[contains(.,'Apply without account')]",
        "//a[contains(.,'Guest')]"
    ]:
        btns = driver.find_elements(By.XPATH, sel)
        for btn in btns:
            if btn.is_displayed():
                print("  [SMARTRECRUITERS] Applying as guest...")
                driver.execute_script("arguments[0].click();", btn)
                human_pause(2, 3)
                break

    # If login required
    _handle_login_or_register(driver, url)
    human_pause(1, 2)

    return _universal_multi_page_apply(driver, url, company, role, max_steps=10)


def apply_generic(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Fallback universal form filler for unknown ATS platforms."""
    print(f"  [GENERIC] Loading site and attempting universal form fill...")
    driver.get(url)
    human_pause(3, 4)

    # Attempt login if login form detected
    _handle_login_or_register(driver, url)
    human_pause(1, 2)

    # Try clicking Apply button
    for sel in [
        "//button[contains(.,'Apply') or contains(.,'Apply Now')]",
        "//a[contains(.,'Apply') or contains(.,'Apply Now')]",
    ]:
        btns = driver.find_elements(By.XPATH, sel)
        for btn in btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                human_pause(2, 4)
                break

    return _universal_multi_page_apply(driver, url, company, role)


# ─── Main dispatcher ──────────────────────────────────────────────────────────

def apply_to_career_site(driver, url: str, company: str = "Company", role: str = "Role") -> bool:
    """Auto-detect ATS platform and run matching filling procedure."""
    platform = detect_platform(url)
    print(f"  [PLATFORM] Detected: {platform.upper()} for {company} — {role}")

    if platform == "workday":
        return apply_workday(driver, url, company=company, role=role)
    elif platform == "greenhouse":
        return apply_greenhouse(driver, url, company=company, role=role)
    elif platform == "lever":
        return apply_lever(driver, url, company=company, role=role)
    elif platform == "icims":
        return apply_icims(driver, url, company=company, role=role)
    elif platform == "taleo":
        return apply_taleo(driver, url, company=company, role=role)
    elif platform == "successfactors":
        return apply_successfactors(driver, url, company=company, role=role)
    elif platform == "smartrecruiters":
        return apply_smartrecruiters(driver, url, company=company, role=role)
    else:
        return apply_generic(driver, url, company=company, role=role)


# List mode support (kept for backward compatibility)
CAREER_URLS = []


def run_careers_bot(headless: bool = False, urls=None, log_fn=None):
    """Apply to a list of company career site URLs."""
    from browser import create_browser
    from tracker import log_application

    if log_fn:
        set_log_fn(log_fn)

    target_urls = urls if urls else CAREER_URLS
    if not target_urls:
        print("No career URLs provided. Pass urls=[...] or add entries to CAREER_URLS.")
        return

    driver = create_browser(headless=headless)
    success_count = 0

    for url in target_urls:
        print(f"\n[CAREERS BOT] Applying: {url}")
        try:
            url_parts = url.rstrip("/").split("/")
            company = url_parts[2].replace("www.", "").split(".")[0].title() if len(url_parts) > 2 else "Company"
            role = url_parts[-1].replace("-", " ").title() if len(url_parts) > 3 else "Data Engineer"
            success = apply_to_career_site(driver, url, company=company, role=role)
            status  = "Applied" if success else "Manual Needed"
            log_application(company, role, "Career Site", url, status, 0, [])
            if success:
                success_count += 1
        except Exception as e:
            print(f"  [ERROR] Error applying to {url}: {e}")

    driver.quit()
    print(f"\n[CAREERS BOT DONE] Applied to {success_count}/{len(target_urls)} jobs.")
