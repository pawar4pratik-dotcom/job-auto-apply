"""
routes/workday_routes.py — Phase 6: Workday Auto-Register & Profile Automation

Endpoints:
  POST /api/workday/register          Launches Playwright to auto-register on a Workday portal
  POST /api/workday/test_login        Tests login with stored credentials
  GET  /api/workday/status            Returns current auto-register job status (SSE-friendly)
  GET  /api/workday/saved_portals     Lists all saved Workday portals from profile.py
  POST /api/workday/save_portal       Saves a new portal + credentials to COMPANY_CREDENTIALS
"""

import os
import re
import time
import threading
import importlib
from flask import Blueprint, jsonify, request, Response
from core.state import bot_log

workday_bp = Blueprint("workday_bp", __name__)

# ── Job state for auto-register tasks ────────────────────────────────────────
_register_lock = threading.Lock()
_register_status = {
    "running": False,
    "phase": "idle",
    "log": [],
    "success": False,
    "error": None,
    "portal_url": "",
    "credentials_saved": False,
}


def _log(msg: str):
    """Append to register log and to global bot_log."""
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    _register_status["log"].append(entry)
    if len(_register_status["log"]) > 200:
        _register_status["log"] = _register_status["log"][-100:]
    try:
        bot_log(f"[WORKDAY] {msg}")
    except Exception:
        pass


def _update_company_credentials(portal_name: str, email: str, password: str):
    """
    Save/update COMPANY_CREDENTIALS in config/profile.py.
    Reads the current file, patches the COMPANY_CREDENTIALS dict, rewrites.
    """
    import config.profile
    importlib.reload(config.profile)

    profile_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "profile.py"
    )
    with open(profile_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Update the in-memory dict
    creds = dict(getattr(config.profile, "COMPANY_CREDENTIALS", {}))
    creds[portal_name] = {"email": email, "password": password}

    # Re-serialize COMPANY_CREDENTIALS line
    creds_repr = repr(creds)
    new_line = f"COMPANY_CREDENTIALS = {creds_repr}"

    # Replace existing line
    content_new = re.sub(
        r"^COMPANY_CREDENTIALS\s*=\s*\{.*?\}",
        new_line,
        content,
        flags=re.MULTILINE | re.DOTALL
    )

    with open(profile_path, "w", encoding="utf-8") as f:
        f.write(content_new)

    importlib.reload(config.profile)
    return creds


def _do_workday_register(portal_url: str, portal_name: str):
    """
    Background thread: launch Selenium, navigate to the Workday portal,
    detect login/register page, auto-register or login, save credentials.
    """
    import config.profile
    importlib.reload(config.profile)

    profile_data = getattr(config.profile, "PROFILE", {})
    creds_map    = getattr(config.profile, "COMPANY_CREDENTIALS", {})

    corp_email    = creds_map.get(portal_name, {}).get("email") or profile_data.get("corp_email", "")
    corp_password = creds_map.get(portal_name, {}).get("password") or profile_data.get("corp_password", "")

    _register_status.update({
        "running": True, "phase": "launching",
        "log": [], "success": False, "error": None,
        "portal_url": portal_url, "credentials_saved": False
    })

    try:
        from browser import create_browser
        _log(f"Launching browser for: {portal_url}")
        driver = create_browser(headless=False, profile_name="workday")  # Visible so user can verify

        try:
            _update_register_phase("navigating")
            _log(f"Navigating to portal...")
            driver.get(portal_url)
            time.sleep(5)

            # Import the existing _handle_login_or_register FSM from careers_bot
            try:
                from careers_bot import _handle_login_or_register, force_set_value
                _update_register_phase("authenticating")
                _log("Running authentication FSM (login/register/OTP)...")
                result = _handle_login_or_register(driver, portal_url)
                if result:
                    _log("✅ Authentication wall cleared")
                    _register_status["success"] = True
                    _update_register_phase("saving_credentials")
                    # Save the credentials that worked
                    _update_company_credentials(portal_name, corp_email, corp_password)
                    _register_status["credentials_saved"] = True
                    _log(f"✅ Credentials saved for '{portal_name}'")
                    _update_register_phase("done")
                else:
                    _log("⚠️ Could not clear authentication wall")
                    _register_status["error"] = "Authentication wall could not be bypassed"
                    _update_register_phase("failed")
            except ImportError as ie:
                _log(f"⚠️ careers_bot not available: {ie}")
                # Fallback: manual register detection
                _update_register_phase("detecting")
                _do_manual_register_attempt(driver, corp_email, corp_password, portal_url, portal_name)

        finally:
            time.sleep(3)
            try:
                driver.quit()
            except Exception:
                pass

    except Exception as e:
        _log(f"❌ Register failed: {e}")
        _register_status["error"] = str(e)
        _register_status["success"] = False
        _update_register_phase("failed")
    finally:
        _register_status["running"] = False


def _do_manual_register_attempt(driver, corp_email, corp_password, portal_url, portal_name):
    """Fallback minimal register attempt without full careers_bot dependency."""
    from selenium.webdriver.common.by import By
    import time

    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        page_text = ""

    # Detect state
    email_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[name*='email']")
    pw_inputs    = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    visible_email = [el for el in email_inputs if el.is_displayed()]
    visible_pw    = [el for el in pw_inputs if el.is_displayed()]

    if not visible_email:
        _log("No login wall detected — portal may be open")
        _register_status["success"] = True
        _update_register_phase("done")
        return

    _log(f"Detected {'registration' if len(visible_pw) >= 2 else 'login'} form")

    # Fill email
    try:
        driver.execute_script(
            "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            visible_email[0], corp_email
        )
    except Exception:
        pass

    # Fill password(s)
    for pw_el in visible_pw[:2]:
        try:
            driver.execute_script(
                "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
                pw_el, corp_password
            )
        except Exception:
            pass

    # Submit
    for sel in ["button[type='submit']", "button[data-automation-id='signInSubmitButton']"]:
        btns = driver.find_elements(By.CSS_SELECTOR, sel)
        for btn in btns:
            if btn.is_displayed():
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    _log("Clicked submit button")
                    time.sleep(6)
                    break
                except Exception:
                    pass

    # Check result
    remaining = driver.find_elements(By.CSS_SELECTOR, "input[type='email']")
    still_visible = [el for el in remaining if el.is_displayed()]
    if not still_visible:
        _register_status["success"] = True
        _update_company_credentials(portal_name, corp_email, corp_password)
        _register_status["credentials_saved"] = True
        _log(f"✅ Auth cleared. Credentials saved for '{portal_name}'")
        _update_register_phase("done")
    else:
        _log("⚠️ Auth form still visible after submit")
        _register_status["error"] = "Form did not advance after submit"
        _update_register_phase("failed")


def _update_register_phase(phase: str):
    _register_status["phase"] = phase


# ── POST /api/workday/register ────────────────────────────────────────────────
@workday_bp.route("/api/workday/register", methods=["POST"])
def workday_register():
    """
    Body: {portal_url: str, portal_name: str}
    Launches background register thread.
    """
    if _register_status["running"]:
        return jsonify({"error": "A registration task is already running. Wait for it to complete."}), 409

    data = request.get_json(force=True, silent=True) or {}
    portal_url  = data.get("portal_url", "").strip()
    portal_name = data.get("portal_name", "").strip()

    if not portal_url:
        return jsonify({"error": "portal_url is required"}), 400
    if not portal_url.startswith("http"):
        return jsonify({"error": "Invalid URL — must start with http"}), 400
    if not portal_name:
        # Derive name from URL
        portal_name = re.sub(r"https?://", "", portal_url).split("/")[0].replace(".", "_")

    t = threading.Thread(target=_do_workday_register, args=(portal_url, portal_name), daemon=True)
    t.start()

    return jsonify({"ok": True, "portal_name": portal_name, "message": f"Auto-register started for '{portal_name}'"})


# ── POST /api/workday/test_login ──────────────────────────────────────────────
@workday_bp.route("/api/workday/test_login", methods=["POST"])
def workday_test_login():
    """
    Body: {portal_name: str}
    Checks if credentials are stored for this portal.
    """
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("portal_name", "").strip()
    if not name:
        return jsonify({"error": "portal_name required"}), 400

    import config.profile
    importlib.reload(config.profile)
    creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
    if name in creds and creds[name].get("email"):
        return jsonify({"ok": True, "has_credentials": True,
                        "email": creds[name]["email"],
                        "message": f"Credentials found for '{name}'"})
    return jsonify({"ok": True, "has_credentials": False,
                    "message": f"No credentials saved for '{name}' yet"})


# ── GET /api/workday/status ───────────────────────────────────────────────────
@workday_bp.route("/api/workday/status", methods=["GET"])
def workday_status():
    """Returns current auto-register task status."""
    return jsonify({
        "running":             _register_status["running"],
        "phase":               _register_status["phase"],
        "log":                 _register_status["log"][-30:],  # last 30 lines
        "success":             _register_status["success"],
        "error":               _register_status["error"],
        "portal_url":          _register_status["portal_url"],
        "credentials_saved":   _register_status["credentials_saved"],
    })


# ── GET /api/workday/saved_portals ────────────────────────────────────────────
@workday_bp.route("/api/workday/saved_portals", methods=["GET"])
def saved_portals():
    """Lists all saved Workday portals from COMPANY_CREDENTIALS."""
    import config.profile
    importlib.reload(config.profile)
    creds = getattr(config.profile, "COMPANY_CREDENTIALS", {})
    portals = []
    for name, c in creds.items():
        portals.append({
            "name":     name,
            "email":    c.get("email", ""),
            "has_pass": bool(c.get("password", "")),
        })
    return jsonify({"portals": portals})


# ── POST /api/workday/save_portal ─────────────────────────────────────────────
@workday_bp.route("/api/workday/save_portal", methods=["POST"])
def save_portal():
    """
    Manually save/update credentials for a portal.
    Body: {portal_name: str, email: str, password: str}
    """
    data = request.get_json(force=True, silent=True) or {}
    name  = data.get("portal_name", "").strip()
    email = data.get("email", "").strip()
    pw    = data.get("password", "").strip()
    if not name or not email:
        return jsonify({"error": "portal_name and email are required"}), 400
    try:
        updated = _update_company_credentials(name, email, pw)
        return jsonify({"ok": True, "total_portals": len(updated),
                        "message": f"Saved credentials for '{name}'"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
