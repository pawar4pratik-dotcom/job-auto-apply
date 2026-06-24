"""
browser.py — Selenium browser factory + all page interaction helpers.

Features:
  - undetected-chromedriver (uc) with fallback to standard Selenium
  - Per-portal persistent session directories (cookies survive restarts)
  - Randomised window sizes, user agents, and human-speed typing
  - Stealth CDP injection to hide navigator.webdriver
  - wait_for / click / fill / scroll / dom_signature helpers
"""

import time
import random
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementNotInteractableException,
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)

_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_SESSION_ROOT = os.path.join(_BASE_DIR, "sessions")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]

_WINDOW_SIZES = [
    (1366, 768),
    (1440, 900),
    (1920, 1080),
    (1600, 900),
]


# ── Browser factory ───────────────────────────────────────────────────────────

def _kill_zombie_chrome(profile_name: str):
    """
    Kill any zombie chrome.exe processes locking the session profile.
    This prevents 'DevToolsActivePort file doesn't exist' and crash errors.
    """
    try:
        import subprocess
        # Search for chrome.exe containing 'sessions/profile_name' or 'sessions\profile_name' in CommandLine
        cmd = f'powershell -NonInteractive -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \\"name = \'chrome.exe\'\\" | ForEach-Object {{ if ($_.CommandLine -match \'sessions[\\\\\\\\/]+{profile_name}\') {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }} }}"'
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except subprocess.TimeoutExpired:
        print(f"[BROWSER] Warning: powershell kill chrome process timed out for profile '{profile_name}'")
    except Exception as e:
        print(f"[BROWSER] Warning: could not kill zombie Chrome for profile '{profile_name}': {e}")


def _get_chrome_main_version() -> int:
    """Query registry on Windows to get installed Chrome main version."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        main_version = int(version.split(".")[0])
        return main_version
    except Exception:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome")
            version, _ = winreg.QueryValueEx(key, "version")
            main_version = int(version.split(".")[0])
            return main_version
        except Exception:
            return None


def create_browser(headless: bool = False, profile_name: str = "default"):
    """
    Create and return a Selenium WebDriver instance.

    profile_name: "linkedin" | "naukri" | "default"
      Each profile maps to its own Chrome user-data-dir so sessions
      (cookies, saved logins) persist across bot runs.

    Tries undetected-chromedriver first; falls back to standard Selenium
    with manual anti-detection flags if uc is not installed.
    """
    session_dir = os.path.join(_SESSION_ROOT, profile_name)
    
    # Proactively kill any zombie chrome instances locking this profile directory
    _kill_zombie_chrome(profile_name)
    
    os.makedirs(session_dir, exist_ok=True)
    
    # Clean up any Chrome lock files that prevent Chrome from launching after a crash
    for lock_name in ["SingletonLock", "lock"]:
        lock_path = os.path.join(session_dir, lock_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
                print(f"[BROWSER] Proactively deleted lock file '{lock_name}' for profile '{profile_name}'")
            except Exception as le:
                pass

    width, height = random.choice(_WINDOW_SIZES)
    ua = random.choice(_USER_AGENTS)

    # ── Attempt 1: undetected-chromedriver ───────────────────────────────
    try:
        import undetected_chromedriver as uc
        options = uc.ChromeOptions()
        # NOTE: Do NOT use 'eager' — Workday and other SPAs need full JS render
        options.add_argument(f"--user-data-dir={session_dir}")
        options.add_argument(f"--window-size={width},{height}")
        options.add_argument(f"--user-agent={ua}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--lang=en-US,en;q=0.9")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--enable-javascript")
        if headless:
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
        
        version_main = _get_chrome_main_version()
        kwargs = {"options": options, "use_subprocess": True}
        if version_main:
            kwargs["version_main"] = version_main
        driver = uc.Chrome(**kwargs)
        try:
            # Comprehensive stealth: hide all automation signals
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
                """
            })
            # Set realistic viewport
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height,
                "deviceScaleFactor": 1, "mobile": False
            })
        except Exception as cdp_err:
            print(f"[BROWSER] UC CDP script injection warning: {cdp_err}")
        print(f"[BROWSER] undetected-chromedriver | profile={profile_name}")
        return driver
    except Exception as e:
        print(f"[BROWSER] undetected-chromedriver unavailable ({e}), falling back to standard Selenium...")

    # ── Attempt 2: standard Selenium with stealth flags ──────────────────
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    # NOTE: Do NOT use 'eager' — Workday and other SPAs need full JS render
    opts.add_argument(f"--user-data-dir={session_dir}")
    opts.add_argument(f"--window-size={width},{height}")
    opts.add_argument(f"--user-agent={ua}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--lang=en-US,en;q=0.9")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    except Exception:
        driver = webdriver.Chrome(options=opts)  # system chromedriver

    # Patch navigator.webdriver to undefined and fake properties
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            """
        })
    except Exception as cdp_err:
        print(f"[BROWSER] Standard Selenium CDP script injection warning: {cdp_err}")
    print(f"[BROWSER] Standard Selenium | profile={profile_name}")
    return driver


# ── Wait helpers ──────────────────────────────────────────────────────────────

def wait_for(driver, by, selector, timeout: int = 8):
    """
    Wait up to `timeout` seconds for element to be visible.
    Returns the element, or None if timed out.
    """
    try:
        return WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((by, selector))
        )
    except (TimeoutException, Exception):
        return None


def wait_clickable(driver, by, selector, timeout: int = 8):
    """Wait until element is clickable. Returns element or None."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )
    except (TimeoutException, Exception):
        return None


# ── Interaction helpers ───────────────────────────────────────────────────────

def click(driver, by, selector, timeout: int = 8) -> bool:
    """
    Wait for an element to be clickable, scroll it into view, then click.
    Returns True if successful, False otherwise.
    Uses JS click as fallback when normal click is blocked.
    """
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'nearest'});", el)
        time.sleep(random.uniform(0.2, 0.5))
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        return True
    except (TimeoutException, NoSuchElementException):
        return False
    except Exception:
        return False


def fill(driver, by, selector, text, timeout: int = 8) -> bool:
    """
    Find an input field and type text into it character-by-character
    at a human-realistic speed (40–120 ms between keystrokes).
    Falls back to JS value injection if keyboard events are blocked.
    """
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.clear()
        time.sleep(random.uniform(0.1, 0.3))
        for ch in str(text):
            try:
                el.send_keys(ch)
            except ElementNotInteractableException:
                # JS fallback
                driver.execute_script("arguments[0].value = arguments[1];", el, text)
                break
            time.sleep(random.uniform(0.04, 0.12))
        return True
    except Exception:
        return False


def clear_and_fill(driver, element, text) -> None:
    """
    Clear an already-found element and type into it.
    Used when you already hold a reference to the element.
    """
    try:
        element.clear()
        time.sleep(0.1)
        for ch in str(text):
            element.send_keys(ch)
            time.sleep(random.uniform(0.04, 0.10))
    except Exception:
        try:
            driver.execute_script("arguments[0].value = arguments[1];", element, text)
        except Exception:
            pass


def human_pause(min_s: float = 1.0, max_s: float = 2.5) -> None:
    """Random sleep to mimic human browsing speed."""
    time.sleep(random.uniform(min_s, max_s))


def scroll_down(driver, px: int = 400) -> None:
    """Scroll down by `px` pixels."""
    driver.execute_script(f"window.scrollBy(0, {px});")
    time.sleep(random.uniform(0.4, 0.8))


def scroll_to_bottom(driver) -> None:
    """Scroll all the way to the bottom of the page."""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1.0)


def dom_signature(driver) -> int:
    """
    Cheap fingerprint of the current DOM state.
    Used to detect form stalls: two identical signatures in a row
    means clicking Next/Continue had no effect.
    """
    try:
        return len(driver.page_source)
    except Exception:
        return 0


def safe_get_text(element) -> str:
    """Get element text safely, returning empty string on failure."""
    try:
        return element.text.strip()
    except Exception:
        return ""


def safe_get_attr(element, attr: str) -> str:
    """Get element attribute safely, returning empty string on failure."""
    try:
        return element.get_attribute(attr) or ""
    except Exception:
        return ""


def is_element_visible(element) -> bool:
    """Check if a WebElement is currently displayed and enabled."""
    try:
        return element.is_displayed() and element.is_enabled()
    except Exception:
        return False


def close_extra_tabs(driver) -> None:
    """Close all tabs except the first/main one."""
    while len(driver.window_handles) > 1:
        driver.switch_to.window(driver.window_handles[-1])
        driver.close()
    if driver.window_handles:
        driver.switch_to.window(driver.window_handles[0])
