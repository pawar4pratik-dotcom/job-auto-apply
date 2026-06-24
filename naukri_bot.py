"""
naukri_bot.py — Auto search + apply on Naukri.com
"""

import time
import os
from selenium.webdriver.common.by import By

from browser import create_browser, wait_for, click, fill, human_pause, scroll_down
from filter import should_apply
from tracker import log_application
from config.profile import PROFILE, SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES

APPLIED_LOG = "logs/applied_naukri.txt"


def _applied_naukri_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if active_profile and active_profile != "default":
            filename = f"logs/applied_naukri_{active_profile}.txt"
        else:
            filename = APPLIED_LOG
    except Exception:
        filename = APPLIED_LOG
    return os.path.join(script_dir, filename)


def load_applied():
    log_path = _applied_naukri_path()
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()


def save_applied(job_id):
    log_path = _applied_naukri_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(job_id + "\n")


def login(driver, log_fn=print):
    """Log into Naukri."""
    log_fn("[LOGIN] Logging into Naukri...")
    driver.get("https://www.naukri.com/nlogin/login")
    human_pause(2, 3)

    fill(driver, By.ID, "usernameField", PROFILE["naukri_email"])
    fill(driver, By.ID, "passwordField", PROFILE["naukri_password"])
    click(driver, By.XPATH, "//button[contains(text(),'Login')]")
    human_pause(3, 5)

    # Let user handle CAPTCHA if needed
    for check in range(6):
        if "naukri.com" in driver.current_url and "login" not in driver.current_url:
            log_fn("[OK] Naukri login successful")
            return True
        else:
            time.sleep(5)

    if "naukri.com" in driver.current_url and "login" not in driver.current_url:
        log_fn("[OK] Naukri login successful")
        return True

    log_fn("[FAIL] Naukri login failed. Verify credentials in config/profile.py")
    return False


def search_jobs(driver, keyword, location, log_fn=print):
    """Search for jobs on Naukri."""
    log_fn(f"\n[SEARCH] Searching: '{keyword}' in '{location}'")
    url = (
        f"https://www.naukri.com/{keyword.lower().replace(' ', '-')}-jobs-in-{location.lower()}"
        f"?experience=2&experience=5&jobAge=1"  # 2-5 yrs exp, posted today
    )
    driver.get(url)
    human_pause(1.2, 2.0)


def get_job_listings(driver):
    scroll_down(driver, 500)
    human_pause(0.4, 0.8)
    # Updated resilient selectors for modern Naukri DOM
    selectors = [
        "div[class*='jobTuple'], article[class*='jobTuple'], li[class*='jobTuple']",
        ".srp-jobtuple-wrapper",
        "[class*='jobTuple']",
        ".job-container",
        "article.jobTuple",
        "[data-job-id]",
    ]
    for sel in selectors:
        cards = driver.find_elements(By.CSS_SELECTOR, sel)
        if cards:
            return cards
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


def extract_card_metadata_naukri(card):
    """Extract (job_id, title, company, url, posted_date) directly from the card element without opening any tabs."""
    try:
        title = ""
        url = ""
        for sel in ["a.title", "a[class*='title']", "a[class*='jobTitle']", "h2 a", "[class*='job-title'] a", "a"]:
            try:
                els = card.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip()
                    href = el.get_attribute("href") or ""
                    if t and len(t) > 3 and ("naukri.com" in href or href.startswith("/")):
                        title = t
                        url = href if href.startswith("http") else ("https://www.naukri.com" + href)
                        break
                    elif t and len(t) > 3 and not url:
                        title = t
                        url = href
            except Exception:
                pass
            if title and url:
                break

        if not url:
            url = card.get_attribute("data-href") or card.get_attribute("data-url") or ""

        company = ""
        for sel in [".comp-name", "a.comp-name", "[class*='companyName']", "[class*='company-name']", "[class*='comp-name']", ".company"]:
            try:
                els = card.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    c = el.text.strip()
                    if c and len(c) > 1:
                        company = c
                        break
            except Exception:
                pass
            if company:
                break

        job_id = (
            card.get_attribute("data-job-id") or
            card.get_attribute("data-jobid") or
            card.get_attribute("data-id") or
            url
        )

        posted_date = ""
        for sel in ["[class*='date']", "span.date", "[class*='time']", "time"]:
            try:
                els = card.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip() or el.get_attribute("datetime") or ""
                    if t and any(kw in t.lower() for kw in ["day", "hour", "week", "month", "ago", "just", "minute"]):
                        posted_date = t
                        break
            except Exception:
                pass
            if posted_date:
                break

        return job_id, title, company, url, posted_date
    except Exception:
        return None, "", "", "", ""

def get_job_details_naukri(driver, card):
    """Backward compatibility helper that extracts metadata and loads the description page."""
    job_id, title, company, url, posted_date = extract_card_metadata_naukri(card)
    if not url:
        return None, None, None, None, None, ""
    try:
        driver.execute_script("window.open(arguments[0]);", url)
        driver.switch_to.window(driver.window_handles[-1])
        human_pause(1.2, 2.0)
        description = get_job_description(driver)
        return job_id, title, company, description, url, posted_date
    except Exception as e:
        print(f"  [WARN] Could not read Naukri job description: {e}")
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        return None, None, None, None, None, ""

def answer_questions_naukri(driver, log_fn=print):
    """Answers any questionnaire form elements on the current Naukri page/modal."""
    from linkedin_bot import smart_answer_for_label, smart_radio_answer, smart_dropdown_answer, get_label_for_field
    from qa_store import get_answer, record_unanswered, save_auto_answered
    from config.profile import PROFILE

    # Contact info we must always set correctly
    CONTACT_MAP = {
        "email": PROFILE.get("email", ""),
        "e-mail": PROFILE.get("email", ""),
        "mail address": PROFILE.get("email", ""),
        "phone": PROFILE.get("phone", ""),
        "mobile": PROFILE.get("phone", ""),
        "contact number": PROFILE.get("phone", ""),
    }

    try:
        # ── 1. Text/Number inputs ──
        text_fields = driver.find_elements(
            By.CSS_SELECTOR,
            "input[type='text'], input[type='number'], input[type='email'],"
            " input[type='tel'], textarea"
        )
        for field in text_fields:
            try:
                if not field.is_displayed():
                    continue
                label = get_label_for_field(driver, field)
                if not label:
                    # Try placeholder as fallback label
                    label = (field.get_attribute("placeholder") or "").strip().lower()
                if not label:
                    continue

                # ── A. Contact fields: always verify and force-fill ──
                contact_val = None
                label_lower = label.lower()
                for key, val in CONTACT_MAP.items():
                    if key in label_lower:
                        contact_val = val
                        break
                if contact_val:
                    current = (field.get_attribute("value") or "").strip()
                    if current == contact_val.strip():
                        continue  # Already correct
                    try:
                        field.clear()
                        field.send_keys(contact_val)
                        log_fn(f"  [FORM] Corrected contact '{label}' -> '{contact_val}'")
                    except Exception:
                        pass
                    continue

                # ── B. Skip already-filled non-contact fields ──
                if field.get_attribute("value"):
                    continue

                # ── C. Try persistent Q&A store first ──
                answer = get_answer(label)
                if answer == "__MANUAL__":
                    log_fn(f"  [FORM] Field '{label}' is marked as MANUAL. Skipping.")
                    continue

                # ── D. Fallback to profile smart matching ──
                if not answer:
                    answer = smart_answer_for_label(label)
                    if answer:
                        save_auto_answered(label, answer, portal="Naukri")

                # ── E. Record if still unresolved ──
                if not answer:
                    record_unanswered(label, portal="Naukri")

                if answer:
                    field.clear()
                    field.send_keys(str(answer))
                    log_fn(f"  [FORM] Filled '{label}' -> '{answer}'")
            except Exception:
                pass

        # ── 2. Radio buttons ──
        radio_groups = driver.find_elements(
            By.CSS_SELECTOR,
            "fieldset, [class*='radio-group'], [class*='question-container'],"
            " [class*='radioGroup'], [class*='RadioGroup']"
        )
        for group in radio_groups:
            try:
                if not group.is_displayed():
                    continue
                legends = group.find_elements(By.CSS_SELECTOR, "legend, label, p, span")
                legend = legends[0].text.strip() if legends else ""
                if not legend or len(legend) < 5:
                    continue

                target_answer = get_answer(legend)
                if target_answer == "__MANUAL__":
                    log_fn(f"  [FORM] Radio '{legend[:50]}' is MANUAL. Skipping.")
                    continue

                if not target_answer:
                    target_answer = smart_radio_answer(legend)
                    if target_answer:
                        save_auto_answered(legend, target_answer, portal="Naukri")

                if not target_answer:
                    log_fn(f"  [FORM] No match for radio '{legend[:50]}'. Recording.")
                    record_unanswered(legend, portal="Naukri")
                    continue

                radios = group.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                for radio in radios:
                    if radio.is_selected():
                        break
                    rid = radio.get_attribute("id")
                    label_text = ""
                    if rid:
                        lbl_els = group.find_elements(By.CSS_SELECTOR, f"label[for='{rid}']")
                        if lbl_els:
                            label_text = lbl_els[0].text.strip().lower()
                    if not label_text:
                        try:
                            label_text = radio.find_element(
                                By.XPATH, "following-sibling::*").text.strip().lower()
                        except Exception:
                            pass

                    if label_text == target_answer or target_answer in label_text:
                        driver.execute_script("arguments[0].click();", radio)
                        log_fn(f"  [FORM] Radio '{target_answer}' for '{legend[:50]}'")
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
                
                target_answer = get_answer(legend) or smart_radio_answer(legend)
                if not target_answer:
                    log_fn(f"  [FORM] No match for fallback radio group '{legend}'. Recording as unanswered.")
                    record_unanswered(legend, portal="Naukri")
                    continue
                
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
                    
                    if label_text == target_answer or target_answer in label_text:
                        driver.execute_script("arguments[0].click();", radio)
                        log_fn(f"  [FORM] Radio selected '{target_answer}' for '{legend}'")
                        break
        except Exception:
            pass

        # ── 3. Dropdowns ──
        dropdowns = driver.find_elements(By.CSS_SELECTOR, "select")
        for drop in dropdowns:
            try:
                if not drop.is_displayed():
                    continue
                label = get_label_for_field(driver, drop)
                smart_dropdown_answer(driver, drop, label, log_fn=log_fn, portal="Naukri")
            except Exception:
                pass

        # ── 4. Custom Naukri Select2 / React-select dropdowns (not native <select>) ──
        custom_selects = driver.find_elements(
            By.CSS_SELECTOR,
            "[class*='Select__control'], [class*='select__control'],"
            " [class*='Dropdown'], [class*='dropdown-container']"
        )
        for cs in custom_selects:
            try:
                if not cs.is_displayed():
                    continue
                # Get associated label
                label = ""
                try:
                    parent = driver.execute_script(
                        "return arguments[0].closest('div, li, fieldset');", cs)
                    if parent:
                        lbl_els = parent.find_elements(By.CSS_SELECTOR, "label, legend, span, p")
                        for le in lbl_els:
                            t = le.text.strip()
                            if t and 2 < len(t) < 100:
                                label = t.lower()
                                break
                except Exception:
                    pass
                if not label:
                    continue

                # Get smart answer
                answer = get_answer(label) or smart_answer_for_label(label) or smart_radio_answer(label)
                if not answer:
                    continue

                # Click to open dropdown
                driver.execute_script("arguments[0].click();", cs)
                human_pause(0.3, 0.6)

                # Try to find matching option in opened list
                options = driver.find_elements(
                    By.CSS_SELECTOR,
                    "[class*='Select__option'], [class*='select__option'],"
                    " [class*='option'], [role='option']"
                )
                for opt in options:
                    if opt.is_displayed() and answer.lower() in opt.text.strip().lower():
                        driver.execute_script("arguments[0].click();", opt)
                        log_fn(f"  [FORM] Custom select '{label}' -> '{opt.text.strip()}'")
                        break
            except Exception:
                pass

        # ── 5. Checkboxes ──
        try:
            import re
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
        log_fn(f"  [WARN] Error answering Naukri questionnaire: {e}")


def apply_naukri(driver, log_fn=print, company="Company", role="Data Engineer"):
    """Apply to a Naukri job. Returns True on confirmed success."""
    try:
        # ── 0. Already applied check ──────────────────────────────────────────
        already_applied = False
        check_selectors = [
            ".already-applied", "[class*='applied-status']", "[class*='apply-status']"
        ]
        for sel in check_selectors:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and any(
                    x in el.text.lower() for x in ["applied", "already"]
                ):
                    already_applied = True
                    break
            if already_applied:
                break

        if not already_applied:
            for el in driver.find_elements(
                By.XPATH,
                "//*[self::button or self::a or contains(@class,'btn') or contains(@class,'status')]"
                "[not(ancestor::header)][not(ancestor::nav)]"
            ):
                try:
                    if el.is_displayed() and el.text.strip().lower() in [
                        "applied", "already applied", "applied directly"
                    ]:
                        already_applied = True
                        break
                except Exception:
                    continue

        if already_applied:
            log_fn("  [SKIP] Already applied on Naukri.")
            return True

        # ── 1. Click Apply button ─────────────────────────────────────────────
        initial_handles = set(driver.window_handles)
        applied_clicked = click(
            driver, By.CSS_SELECTOR,
            "button.apply-button, .applyBtn, .apply-btn, [class*='applyBtn']"
        )
        if not applied_clicked:
            applied_clicked = click(
                driver, By.XPATH,
                "//button[contains(text(),'Apply') or contains(text(),'Apply on')]"
            )
        if not applied_clicked:
            log_fn("  [FAIL] Could not find Apply button.")
            return False

        human_pause(1.5, 2.5)

        # ── 2. Tailored resume generation ─────────────────────────────────────
        abs_path = os.path.abspath(PROFILE.get("resume_path", ""))
        tailored_resume_path = abs_path
        if os.path.exists(abs_path):
            try:
                from resume_tailor import generate_tailored_resume
                page_body = driver.find_element(By.TAG_NAME, "body").text
                log_fn(f"  [ATS TAILOR] Generating tailored resume for {company}...")
                tailored_resume_path = generate_tailored_resume(
                    abs_path, page_body, company, role
                )
            except Exception as te:
                log_fn(f"  [ATS TAILOR][WARN] Tailoring failed: {te}")

        # ── 3. Handle new tab (external ATS) ─────────────────────────────────
        current_handles = set(driver.window_handles)
        if current_handles - initial_handles:
            new_tab = list(current_handles - initial_handles)[0]
            log_fn("  [INFO] External ATS tab opened. Attempting to fill form...")
            driver.switch_to.window(new_tab)
            human_pause(1.5, 2.5)
            # Try answering the external form
            try:
                answer_questions_naukri(driver, log_fn=log_fn)
                human_pause(0.5, 1.0)
                # Try submitting
                for sel in [
                    "button[type='submit']",
                    "//button[contains(text(),'Submit') or contains(text(),'Apply')]"
                ]:
                    try:
                        if sel.startswith("//"):
                            btn = driver.find_element(By.XPATH, sel)
                        else:
                            btn = driver.find_element(By.CSS_SELECTOR, sel)
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            human_pause(1.0, 2.0)
                            break
                    except Exception:
                        pass
            except Exception as ext_err:
                log_fn(f"  [WARN] External ATS fill error: {ext_err}")
            finally:
                driver.close()
                driver.switch_to.window(list(initial_handles)[-1])
            return False  # Can't confirm success on external ATS

        # ── 4. Redirect check ─────────────────────────────────────────────────
        if "naukri.com" not in driver.current_url.lower():
            log_fn(f"  [INFO] Redirected to: {driver.current_url}")
            driver.back()
            human_pause(1.0, 1.5)
            return False

        # ── 5. Dismiss chatbot / cookie popups ────────────────────────────────
        for close_sel in [".botCloseIcon", "[class*='chatbot'] [class*='close']",
                          "[class*='chatbot'] [aria-label='Close']", ".cookieAccept"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, close_sel)
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    human_pause(0.3, 0.6)
            except Exception:
                pass

        # ── 6. Multi-page questionnaire loop ──────────────────────────────────
        # Naukri questionnaires can span multiple pages; loop until modal closes
        # or we exhaust attempts.
        def _modal_has_form(driver):
            """True if a visible modal or form contains at least one form input."""
            modal_css = (
                "form, .modal-body, .chatbot-container, [class*='modal'],"
                " [class*='popup'], .apply-questionnaire, [class*='questionnaire'],"
                " [class*='overlay'], [class*='dialog'], [class*='apply-container']"
            )
            inputs_css = "input:not([type='hidden']), select, textarea"
            for el in driver.find_elements(By.CSS_SELECTOR, modal_css):
                try:
                    if not el.is_displayed():
                        continue
                    # Skip if inside header or nav
                    parent_tags = driver.execute_script(
                        "let p = arguments[0]; let tags = []; while(p) { tags.push(p.tagName); p = p.parentElement; } return tags;", el
                    )
                    if any(t in ["HEADER", "NAV"] for t in parent_tags):
                        continue
                    text = el.text.lower()
                    if "success" in text or "applied" in text:
                        continue
                    inputs = el.find_elements(By.CSS_SELECTOR, inputs_css)
                    # Filter out hidden or non-interactive inputs
                    visible_inputs = [inp for inp in inputs if inp.is_displayed()]
                    if visible_inputs:
                        return True, el
                except Exception:
                    pass
            return False, None

        max_form_pages = 6  # Safety: never loop more than 6 pages
        for page_num in range(max_form_pages):
            has_form, modal_el = _modal_has_form(driver)
            if not has_form:
                break  # No questionnaire modal → done

            log_fn(f"  [FORM] Questionnaire page {page_num + 1} detected. Filling...")
            answer_questions_naukri(driver, log_fn=log_fn)

            # Upload resume if file input visible
            try:
                for ri in driver.find_elements(By.CSS_SELECTOR, "input[type='file']"):
                    if ri.is_displayed() and os.path.exists(tailored_resume_path):
                        ri.send_keys(tailored_resume_path)
                        log_fn("  [ATS TAILOR] Uploaded tailored resume.")
                        human_pause(0.8, 1.2)
                        break
            except Exception:
                pass

            human_pause(0.5, 1.0)

            # Click next/submit button
            btn_clicked = False
            for sel in [
                "button[type='submit']",
                ".submit-btn", ".confirm-btn", ".save-btn", ".next-btn",
                "//button[contains(text(),'Next') or contains(text(),'Continue')]",
                "//button[contains(text(),'Confirm') or contains(text(),'Apply')]",
                "//button[contains(text(),'Save') or contains(text(),'Submit')]",
            ]:
                try:
                    if sel.startswith("//"):
                        btn = driver.find_element(By.XPATH, sel)
                    else:
                        btn = driver.find_element(By.CSS_SELECTOR, sel)
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        btn_clicked = True
                        log_fn(f"  [FORM] Clicked submit/next on page {page_num + 1}")
                        break
                except Exception:
                    pass

            if not btn_clicked:
                log_fn("  [WARN] No submit button found on form page.")
                break

            human_pause(1.0, 2.0)  # Wait for page transition

        else:
            # Loop exhausted — questionnaire still open
            log_fn("  [WARN] Questionnaire still open after max attempts.")

        # ── 7. Non-questionnaire confirm (simple Apply confirmation) ──────────
        try:
            btn = driver.find_element(
                By.XPATH,
                "//button[contains(text(),'Confirm') or contains(text(),'Apply')]"
            )
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                human_pause(1.0, 1.8)
        except Exception:
            pass

        # ── 8. Verify success (extended window) ───────────────────────────────
        success = False
        start_time = time.time()
        while time.time() - start_time < 10:  # 10-second window
            try:
                # Check for applied button text
                for btn in driver.find_elements(
                    By.CSS_SELECTOR,
                    "button, a, .apply-button, .applyBtn, .apply-btn, [class*='apply']"
                ):
                    if btn.is_displayed() and btn.text.strip().lower() in [
                        "applied", "already applied", "applied directly", "application sent"
                    ]:
                        success = True
                        break
                if success:
                    break

                # Check page body text
                body_text = driver.execute_script(
                    "return document.body.innerText;"
                ).lower()
                if any(x in body_text for x in [
                    "applied successfully", "application sent",
                    "applied to this job", "your application has been",
                    "thank you for applying"
                ]):
                    success = True
                    break

                # Check URL params
                if "applied" in driver.current_url.lower():
                    success = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        return success
    except Exception as e:
        log_fn(f"  [WARN] Naukri apply error: {e}")
        return False


from tracker import get_today_count
from config.profile import DAILY_LIMIT


def run_naukri_bot(max_applications=20, headless=False, log_fn=print, stop_event=None, keywords=None, locations=None):
    log_fn("\n" + "="*55 + "\n  NAUKRI AUTO-APPLY BOT\n" + "="*55)
    if get_today_count("Applied") >= DAILY_LIMIT:
        log_fn(f"[STOP] Daily limit of {DAILY_LIMIT} applications reached. Stopping.")
        return

    driver = create_browser(headless=headless, profile_name="naukri")
    applied_jobs = load_applied()
    processed_urls_this_run = set()
    total_applied = 0
    
    target_keywords = keywords if keywords is not None else SEARCH_KEYWORDS
    target_locations = locations if locations is not None else SEARCH_LOCATIONS

    try:
        if not login(driver, log_fn=log_fn): return

        for keyword in target_keywords:
            if stop_event and stop_event.is_set():
                log_fn("[INFO] Stop signal received. Halting Naukri bot.")
                break
            for location in target_locations:
                if stop_event and stop_event.is_set(): break
                if total_applied >= max_applications: break

                search_jobs(driver, keyword, location, log_fn=log_fn)
                cards = get_job_listings(driver)
                log_fn(f"  Found {len(cards)} jobs on search page")

                for card in cards:
                    if stop_event and stop_event.is_set(): break
                    if total_applied >= max_applications: break

                    # ── Early card-level pre-filtering (Stage A) ──────────────
                    try:
                        job_id, title, company, url, posted_date = extract_card_metadata_naukri(card)
                    except Exception:
                        continue
                        
                    if not job_id or not url:
                        continue

                    if job_id in applied_jobs or url in applied_jobs or url in processed_urls_this_run:
                        continue

                    # Check for applied badge text on the search card itself
                    try:
                        badges = card.find_elements(By.XPATH, ".//*[contains(text(), 'Applied') or contains(text(), 'applied')]")
                        if any("applied" in b.text.strip().lower() for b in badges):
                            continue
                    except Exception:
                        pass

                    if url:
                        processed_urls_this_run.add(url)

                    # Fast Stage A filter
                    do_apply, score, matched, reason, decision, missing = should_apply(title, "", company)
                    if not do_apply:
                        log_fn(f"\n[FAST FILTER SKIP] {company} -- {title}")
                        log_fn(f"  Skip: {reason}")
                        log_application(company, title, "Naukri", url, "Skipped", score, matched, skip_reason=reason, posted_date=posted_date, missing_skills=missing, decision=decision)
                        continue

                    # Only open tab and load description if it passes Stage A
                    log_fn(f"\n[JOB] {company} -- {title}{' (Posted: ' + posted_date + ')' if posted_date else ''}")
                    try:
                        driver.execute_script("window.open(arguments[0]);", url)
                        driver.switch_to.window(driver.window_handles[-1])
                        human_pause(1.5, 2.5)
                        description = get_job_description(driver)
                        # Retry once if description is empty (page may still be loading)
                        if not description or len(description.strip()) < 50:
                            human_pause(1.5, 2.5)
                            description = get_job_description(driver)
                    except Exception as e:
                        log_fn(f"  [WARN] Failed to load job page: {e}")
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        continue

                    # Stage B full description filter
                    do_apply, score, matched, reason, decision, missing = should_apply(title, description, company)

                    if not do_apply or decision == "skip":
                        log_fn(f"  Skip: {reason}")
                        log_application(company, title, "Naukri", url, "Skipped", score, matched, skip_reason=reason, posted_date=posted_date, missing_skills=missing, decision=decision)
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        continue

                    if decision == "review":
                        log_fn(f"  [REVIEW QUEUE] {company} -- {title} ({score}%) - Queued for review")
                        log_application(company, title, "Naukri", url, "Review", score, matched, skip_reason=reason, posted_date=posted_date, missing_skills=missing, decision=decision)
                        save_applied(job_id)
                        if len(driver.window_handles) > 1:
                            driver.close()
                            driver.switch_to.window(driver.window_handles[0])
                        continue

                    log_fn(f"  [MATCH] {score}% -- Applying...")
                    success = apply_naukri(driver, log_fn=log_fn, company=company, role=title)
                    if success:
                        log_fn("  [SUCCESS] Applied!")
                        log_application(company, title, "Naukri", url, "Applied", score, matched, posted_date=posted_date)
                        save_applied(job_id)
                        total_applied += 1
                    else:
                        log_fn("  [FAIL] Apply failed")
                        log_application(company, title, "Naukri", url, "Manual Needed", score, matched, skip_reason="Apply verification failed, redirected, or stalled", posted_date=posted_date)

                    # Safe tab cleanup
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    human_pause(0.5, 1.2)
    except KeyboardInterrupt:
        log_fn("\n[STOP] Naukri Bot stopped by user.")
    finally:
        log_fn(f"\n[DONE] Completed! Applied to {total_applied} jobs on Naukri.")
        driver.quit()

