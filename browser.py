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
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementNotInteractableException,
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
    InvalidSessionIdException,
    WebDriverException,
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


def create_browser(headless: bool = False, profile_name: str = "default", force_standard: bool = False):
    """
    Create and return a Selenium WebDriver instance.

    profile_name: "linkedin" | "naukri" | "default"
      Each profile maps to its own Chrome user-data-dir so sessions
      (cookies, saved logins) persist across bot runs.

    Tries undetected-chromedriver first; falls back to standard Selenium
    with manual anti-detection flags if uc is not installed.
    """
    session_dir = os.path.join(_SESSION_ROOT, profile_name)

    # Check if login email changed to prevent session pollution
    if profile_name in ["linkedin", "naukri"]:
        try:
            import config.profile
            current_email = getattr(config.profile, "PROFILE", {}).get(f"{profile_name}_email", "").strip()
            email_track_file = os.path.join(_SESSION_ROOT, f"{profile_name}_email.txt")
            last_email = ""
            if os.path.exists(email_track_file):
                try:
                    with open(email_track_file, "r", encoding="utf-8") as ef:
                        last_email = ef.read().strip()
                except Exception:
                    pass
            if current_email and last_email and current_email != last_email:
                import shutil
                shutil.rmtree(session_dir, ignore_errors=True)
                print(f"[BROWSER] Cleaned session directory for '{profile_name}' because email changed from '{last_email}' to '{current_email}'")
            if current_email:
                os.makedirs(_SESSION_ROOT, exist_ok=True)
                with open(email_track_file, "w", encoding="utf-8") as ef:
                    ef.write(current_email)
        except Exception as e:
            print(f"[BROWSER] Warning: Session change check failed: {e}")

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
    if not force_standard:
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


class SelfHealingDriver:
    def __init__(self, headless: bool = False, profile_name: str = "default"):
        self.headless = headless
        self.profile_name = profile_name
        self.driver = None
        self._consecutive_failures = 0
        self.init_driver()

    def init_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

        _kill_zombie_chrome(self.profile_name)

        attempt_count = 0
        while attempt_count < 3:
            try:
                # If we've failed twice, force standard Selenium fallback
                force_standard = (self._consecutive_failures >= 2)
                if force_standard:
                    print(f"[RECOVERY] Spawning browser in standard Selenium fallback mode for stability.")
                
                self.driver = create_browser(
                    headless=self.headless,
                    profile_name=self.profile_name,
                    force_standard=force_standard
                )
                self._consecutive_failures = 0
                return
            except Exception as e:
                attempt_count += 1
                self._consecutive_failures += 1
                print(f"[ERROR] Failed to start Chrome browser (attempt {attempt_count}/3): {e}")
                time.sleep(2)
        
        raise WebDriverException("Failed to launch Chrome browser after multiple self-healing attempts.")

    def execute_with_retry(self, name, *args, **kwargs):
        for attempt in range(3):
            try:
                if not self.driver:
                    self.init_driver()
                
                attr = getattr(self.driver, name)
                if callable(attr):
                    return attr(*args, **kwargs)
                return attr
            except (InvalidSessionIdException, WebDriverException, Exception) as e:
                if isinstance(e, (TimeoutException, NoSuchElementException)):
                    raise e
                err_msg = str(e).lower()
                is_session_lost = (
                    isinstance(e, InvalidSessionIdException) or
                    any(phrase in err_msg for phrase in [
                        "session id", "connection refused", "not connected to devtools", 
                        "chrome not reachable", "disconnected", "invalid session id"
                    ])
                )
                if not is_session_lost:
                    raise e
                
                print(f"[RECOVERY] Browser session crashed/disconnected: {e}. Re-initializing Chrome (attempt {attempt+1}/3)...")
                self._consecutive_failures += 1
                time.sleep(2.5)
                self.init_driver()
        
        raise WebDriverException("Failed to execute WebDriver command after 3 recovery attempts.")

    def __getattr__(self, name):
        # Prevent infinite recursion on special attributes
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        
        if not self.driver:
            self.init_driver()

        attr = getattr(self.driver, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                return self.execute_with_retry(name, *args, **kwargs)
            return wrapper
        return attr

    def __setattr__(self, name, value):
        if name in ["headless", "profile_name", "driver", "_consecutive_failures"]:
            super().__setattr__(name, value)
        else:
            if not self.driver:
                self.init_driver()
            setattr(self.driver, name, value)


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

def move_to_element_with_curve(driver, element) -> None:
    """
    Simulates a human-like curved mouse movement to hover/move to an element using ActionChains.
    Uses randomized offsets to trace a curve and avoid straight-line telemetry detection.
    """
    try:
        # Move to a slightly offset location first to simulate curved path arrival
        offset_x = random.randint(-12, 12)
        offset_y = random.randint(-12, 12)
        ActionChains(driver).move_to_element_with_offset(element, offset_x, offset_y).perform()
        
        # Micro-pause simulating dynamic targeting
        mu = 0.08
        sigma = 0.02
        time.sleep(max(0.04, random.gauss(mu, sigma)))
        
        # Settle to the final destination
        ActionChains(driver).move_to_element(element).perform()
    except Exception:
        try:
            ActionChains(driver).move_to_element(element).perform()
        except Exception:
            pass


def click(driver, by, selector, timeout: int = 8) -> bool:
    """
    Wait for an element to be clickable, scroll it into view, then click.
    Simulates a human curved hover before clicking.
    """
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'nearest'});", el)
        human_pause(0.2, 0.4)
        try:
            move_to_element_with_curve(driver, el)
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
    Find an input field and type text into it efficiently.
    Sends the entire string at once for speed, falling back to JS value injection.
    """
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.clear()
        
        # Gaussian delay before typing
        time.sleep(max(0.05, random.gauss(0.1, 0.02)))
        
        try:
            el.send_keys(str(text))
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", el, text)
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
        time.sleep(0.05)
        try:
            element.send_keys(str(text))
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", element, text)
    except Exception:
        try:
            driver.execute_script("arguments[0].value = arguments[1];", element, text)
        except Exception:
            pass


def human_pause(min_s: float = 1.0, max_s: float = 2.5) -> None:
    """Random sleep utilizing a Gaussian distribution to mimic human browsing speed."""
    mu = (min_s + max_s) / 2.0
    sigma = (max_s - min_s) / 6.0
    val = random.gauss(mu, sigma)
    time.sleep(max(min_s, min(val, max_s)))


def scroll_down(driver, px: int = 400) -> None:
    """Scroll down by `px` pixels with Gaussian timing."""
    driver.execute_script(f"window.scrollBy(0, {px});")
    human_pause(0.4, 0.8)


def scroll_to_bottom(driver) -> None:
    """Scroll all the way to the bottom of the page."""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1.0)


def dom_signature(driver) -> int:
    """
    Cheap fingerprint of the current form/modal DOM state.
    Used to detect form stalls: two identical signatures in a row
    means clicking Next/Continue had no effect.
    """
    try:
        # Target the Easy Apply modal or any dialog if present
        for sel in [".jobs-easy-apply-modal", "[role='dialog']", ".modal-container", "form"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    return len(el.get_attribute("innerHTML") or "")
            except Exception:
                pass
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


def wait_for_ajax_transition(driver, timeout: int = 10) -> None:
    """
    Transition guard that blocks execution while active loading indicators, 
    spinners, or progress bars are visible on the page.
    """
    spinners_css = (
        "div[class*='loading'], div[class*='spinner'], "
        "[data-automation-id='loading-spinner'], [class*='loading-spinner'], "
        ".spinner, .loader, [class*='progress-bar'], .loading-overlay"
    )
    start = time.time()
    while time.time() - start < timeout:
        try:
            spinners = driver.find_elements(By.CSS_SELECTOR, spinners_css)
            visible = [s for s in spinners if s.is_displayed()]
            if not visible:
                break
        except Exception:
            break
        time.sleep(0.5)
