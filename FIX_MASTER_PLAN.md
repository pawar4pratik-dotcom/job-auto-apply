# Job Hunt Bot — Master Fix Plan (All Steps)

**Project:** `job auto apply`  
**Entry point:** `python app.py` → `http://localhost:5005`  
**Created:** Step 1 audit → consolidated fix roadmap for Steps 1–6  
**Purpose:** One file showing *what is wrong*, *why*, *exact fix*, and *implementation order*.

---

## How to use this document

| Phase | When | Action |
|-------|------|--------|
| **P0 Hotfix** | Do first (same day) | Section 3 — unblocks Targeted Search, Recruiter Scraper, stats, Workday |
| **P1 Data + scoring** | Day 2–3 | Section 4 — Kanban/history connect to search results |
| **Step 2 Modularize** | After P0 stable | Section 5 — split HTML/JS, archive legacy |
| **Step 3 Performance** | Section 6 | async, errors, cache, rate limits |
| **Step 4 Debug core** | Section 7 | scoring, apply, recruiter |
| **Step 5 UI/UX** | Section 8 | sidebar badge, leads UI, Glassdoor/Indeed |
| **Step 6 Advanced** | Section 9 | resume tailor, outreach, Telegram, interview prep |

Run verification checklist in **Section 10** after each phase.

---

## 1. Architecture (current vs target)

### Current data flow (broken paths in red)

```
UI (dashboard.html ~4100 lines)
  │
  ├─ POST /api/run ──► bot_routes ──► background thread
  │                         │
  │                         ├─ targeted ──► scrapers/targeted_search.py
  │                         │                    ├─ Workday / LinkedIn / Naukri / Indeed (parallel)
  │                         │                    ├─ dedup + location filter
  │                         │                    └─ filter.should_apply() + Gemini (SEQUENTIAL) ⚠ slow
  │                         │                         └─► TARGETED_SEARCH_RESULTS (RAM only) ❌ not CSV
  │                         │
  │                         ├─ recruiter_posts ──► scrapers/recruiter_scraper.py
  │                         │                         └─► logs/recruiter_leads.json + .txt
  │                         │
  │                         └─ linkedin/naukri/indeed ──► *_bot.py ──► tracker.log_application() ✅
  │
  ├─ GET /api/targeted_results ──► in-memory list
  ├─ POST /api/approve ──► apply_engine ──► Chrome ──► update_status() only ❌ no row if missing
  ├─ GET /api/stats ──► counts only ❌ missing "running" field
  └─ SSE /stream ──► core/state._log_q
```

### Target data flow (after all fixes)

```
UI (split: templates/ + static/app.js)
  │
  POST /api/run { target, company, skills, location }
       │
       ▼
  JobOrchestrator (core/orchestrator.py)
       ├─ fetch portals (ThreadPoolExecutor + rate limiter)
       ├─ dedup (URL + title fuzzy)
       ├─ score batch (Gemini pool OR keyword cache)
       ├─ log_application() for every scored job ──► CSV  ✅
       └─ TARGETED_SEARCH_RESULTS (cache, optional Redis/file backup)
       │
  POST /api/approve
       ├─ log_application(Pending Apply) if new
       ├─ resume tailor (optional LLM step)
       └─ apply_engine (semaphore, timeout, always quit driver)
```

---

## 2. Complete bug register

| ID | Sev | File | Problem | Symptom |
|----|-----|------|---------|---------|
| B01 | P0 | `templates/dashboard.html` | Duplicate `runTargetedSearch()` at L4024 overwrites L3081 | Search runs wrong bot |
| B02 | P0 | `templates/dashboard.html` | `renderTargetedResults()` called but never defined | JS crash after search |
| B03 | P0 | `templates/dashboard.html` | Sends `mode:'targeted'` not `target:'targeted'` | Backend defaults to `all` |
| B04 | P0 | `templates/dashboard.html` | Sends `mode:'recruiter_scraper'` not `target:'recruiter_posts'` | Recruiter never runs |
| B05 | P0 | `config/profile.py` | Plaintext passwords, API keys, IMAP | Security leak |
| B06 | P0 | `routes/workday_routes.py` | `get_driver` import — does not exist | Workday register crashes |
| B07 | P1 | `routes/data_routes.py` | `/api/stats` missing `running` | UI stuck IDLE, buttons stuck |
| B08 | P1 | `scrapers/targeted_search.py` | No `log_application()` after scoring | Kanban empty |
| B09 | P1 | `core/apply_engine.py` | `update_status` only, no insert | Auto Apply invisible |
| B10 | P1 | `filter.py` | Low scores still `decision=review, apply=True` | Junk in review queue |
| B11 | P1 | `scrapers/targeted_search.py` | Raw HTML as JD | Bad Gemini scores |
| B12 | P1 | `scrapers/recruiter_scraper.py` | Unauthenticated Google/LinkedIn scrape | 0 leads |
| B13 | P1 | `templates/dashboard.html` | Interview Prep = static placeholder | Fake feature |
| B14 | P2 | Root | 10+ `app_*.py`, `server.py` port 5000 | Confusion |
| B15 | P2 | `filter.py` | Sequential Gemini, no cache | 2–5 min per search |
| B16 | P2 | `routes/search_routes.py` | Assist infinite loop | Thread leak |
| B17 | P2 | `app.py` | Scheduler vs user Chrome profile conflict | Random failures |
| B18 | P2 | `tracker.py` | `run_ghosted_check()` never scheduled | Stale Applied rows |
| B19 | P2 | UI | Indeed in backend, not in quick buttons | Dead path |
| B20 | P2 | Root | `resume_tailor.py` + `core/resume_tailor.py` duplicate | Import confusion |
| B21 | P2 | Marketing | Glassdoor claimed, not implemented | Missing portal |
| B22 | P3 | `browser.py` | WMI kill every browser open | Slow Windows |
| B23 | P3 | `dashboard.html` | 900+ lines marketing above controls | UX overload |
| B24 | P3 | `sessions/` | Chrome profiles in project folder | Bloat + cookie leak risk |
| B25 | P3 | `scratch/` | Debug scripts in root | Clutter |

---

## 3. P0 Hotfixes (do these first)

### B01–B04 — Fix `templates/dashboard.html` JavaScript

**Problem:** Lines ~4023–4097 redefine functions and break the API contract.

**Approach:** Delete the entire duplicate block at the bottom. Keep only the async versions (~L3081–3160). Ensure one poll path uses `refreshTargetedResults()`.

**DELETE this entire section (approx. L4023–4097):**

```javascript
// ── Run Targeted Search (updated to use city chips) ────────────────────────────
function runTargetedSearch() { ... }   // WRONG: uses mode, not target
function pollTargetedResults() { ... renderTargetedResults(data) ... }  // WRONG: undefined fn
function runRecruiterScraper() { ... mode: 'recruiter_scraper' ... }  // WRONG
```

**KEEP and optionally improve the correct versions:**

```javascript
// ── Bot Controls (CORRECT — keep these) ─────────────────────────────
let _botRunning = false;

async function runTargetedSearch() {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    const company  = document.getElementById('target-company-input').value.trim();
    const skills   = document.getElementById('target-skills-input').value.trim();
    const location = document.getElementById('target-location-input').value.trim()
                  || [...(_selectedCities || [])].join(', ');

    if (!skills) {
        showToast("⚠️ Please enter Skills / Role for Targeted Search!");
        return;
    }
    // company + location optional when using city chips

    const headless = document.getElementById('headless-checkbox').checked;
    const maxApps  = parseInt(document.getElementById('max-apps-input').value) || 15;

    const btn = document.getElementById('targeted-search-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Searching...'; }

    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target: 'targeted',          // ✅ NOT "mode"
            headless,
            max_applications: maxApps,   // ✅ NOT "max_apps"
            company,
            skills,
            location: location || 'Pune'
        })
    });

    const d = await res.json();
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Search Jobs (4 Portals)'; }

    if (d.error) {
        showToast(`Error: ${d.error}`);
        return;
    }

    _botRunning = true;
    showToast(`🚀 Targeted Search started${company ? ' for ' + company : ''}!`);
    pollTargetedResults(0);
    refreshStats();
}

async function runRecruiterScraper() {
    if (_botRunning) {
        showToast("Bot is already running! Please wait...");
        return;
    }
    const company  = document.getElementById('target-company-input').value.trim();
    const skills   = document.getElementById('target-skills-input').value.trim() || 'Data Engineer';
    const location = document.getElementById('target-location-input').value.trim()
                  || [...(_selectedCities || [])].join(', ') || 'Pune';

    const btn = document.getElementById('recruiter-btn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning...'; }

    const res = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            target: 'recruiter_posts',   // ✅ NOT "recruiter_scraper"
            company,
            skills,
            location
        })
    });

    const d = await res.json();
    if (btn) { btn.disabled = false; btn.textContent = '📬 Find Recruiter Forms'; }

    if (d.error) {
        showToast(`Error: ${d.error}`);
        return;
    }

    _botRunning = true;
    showToast('🚀 Recruiter scanner started!');
    setTimeout(() => { refreshRecruiterLeads(); refreshStats(); }, 8000);
}

function pollTargetedResults(attempt) {
    if (attempt > 36) return;  // ~3 min
    fetch('/api/targeted_results')
        .then(r => r.json())
        .then(jobs => {
            if (jobs && jobs.length > 0) {
                refreshTargetedResults();  // ✅ existing function — NOT renderTargetedResults
            } else {
                setTimeout(() => pollTargetedResults(attempt + 1), 5000);
            }
        })
        .catch(() => setTimeout(() => pollTargetedResults(attempt + 1), 6000));
}
```

---

### B05 — Secrets: move to `.env`

**Problem:** `config/profile.py` stores live passwords and API keys.

**Approach:**

1. Create `.env` (gitignored):

```env
GEMINI_API_KEY=your_key_here
LINKEDIN_EMAIL=...
LINKEDIN_PASSWORD=...
NAUKRI_EMAIL=...
NAUKRI_PASSWORD=...
IMAP_EMAIL=...
IMAP_PASSWORD=...
CORP_EMAIL=...
CORP_PASSWORD=...
```

2. Add to `requirements.txt`:

```
python-dotenv>=1.0.0
```

3. Create `config/secrets.py`:

```python
import os
from dotenv import load_dotenv

load_dotenv()

def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()
```

4. Change `config/profile.py` to read secrets from env:

```python
from config.secrets import env

PROFILE = {
    "linkedin_email": env("LINKEDIN_EMAIL"),
    "linkedin_password": env("LINKEDIN_PASSWORD"),
    # ... non-secret fields stay inline ...
}
GEMINI_API_KEY = env("GEMINI_API_KEY")
IMAP_PASSWORD = env("IMAP_PASSWORD")
```

5. Change `routes/profile_routes.py` POST handler: **never write passwords back to profile.py** — write to `.env` or a local `config/secrets.local.json` (gitignored).

6. **Rotate all keys/passwords** that were ever in plaintext profile.py.

7. Add `.gitignore`:

```
.env
config/secrets.local.json
sessions/
logs/*.csv
logs/applied_*.txt
__pycache__/
*.pyc
google_search*.html
ddg_search.html
```

---

### B06 — Fix Workday routes browser import

**File:** `routes/workday_routes.py`

**Replace:**

```python
from browser import get_driver
driver = get_driver(headless=False)
```

**With:**

```python
from browser import create_browser
driver = create_browser(headless=False, profile_name="approve_apply")
```

---

### B07 — Fix `/api/stats` running indicator

**File:** `routes/data_routes.py`

```python
import core.state as state

@data_bp.route("/api/stats")
def api_stats():
    running = bool(state._bot_thread and state._bot_thread.is_alive())
    return jsonify({
        "applied": get_today_count("Applied"),
        "skipped": get_today_count("Skipped"),
        "manual":  get_today_count("Manual Needed"),
        "total":   get_today_count(None),
        "running": running,   # ✅ UI reads this at dashboard.html L2398
    })
```

---

## 4. P1 Fixes — connect search ↔ tracker ↔ apply

### B08 — Log targeted search results to CSV

**File:** `scrapers/targeted_search.py` — after scoring loop, before final sort:

```python
from tracker import log_application

for job in batch_results:
    status = "Review" if job["decision"] in ("auto", "review") else "Skipped"
    log_application(
        company=job["company"],
        role=job["title"],
        portal=job["portal"],
        url=job["url"],
        status=status,
        score=job["score"],
        matched_skills=job.get("matched", []),
        skip_reason=job.get("reason", "") if status == "Skipped" else "",
        posted_date=job.get("posted", ""),
        missing_skills=job.get("missing", []),
        decision=job.get("decision", ""),
    )
```

---

### B09 — Ensure apply creates a row before updating

**File:** `core/apply_engine.py` — at start of `run_apply_for_url`:

```python
from tracker import log_application, get_all_rows, update_status

def _ensure_tracker_row(url, company, role, portal="Unknown", score=0):
    urls = {r.get("URL", "").strip() for r in get_all_rows()}
    if url.strip() not in urls:
        log_application(
            company, role, portal, url,
            "Pending Apply", score, [], decision="auto"
        )

def run_apply_for_url(url: str, company: str, role: str) -> bool:
    portal = "LinkedIn" if "linkedin.com" in url.lower() else \
             "Naukri" if "naukri.com" in url.lower() else "Career Site"
    _ensure_tracker_row(url, company, role, portal)
    # ... rest unchanged ...
```

---

### B10 — Fix scoring decision logic

**File:** `filter.py` — replace bottom decision block (~L324–337):

```python
    reason_suffix = f" — {ai_reason}" if ai_reason else ""

    if score >= auto_threshold:
        return True, score, matched, f"High match ({score:.0f}%){reason_suffix}", "auto", missing
    if score >= review_threshold:
        return True, score, matched, f"Medium match ({score:.0f}%){reason_suffix}", "review", missing

    # Below review threshold — skip (was incorrectly still "review")
    return False, score, matched, f"Low match ({score:.0f}%){reason_suffix}", "skip", missing
```

---

### B11 — Better job description extraction

**Create:** `scrapers/jd_extract.py`

```python
import re
import requests

def fetch_job_description(url: str, portal: str, fallback_title: str, skills: str) -> str:
    """Portal-aware JD fetch. Returns clean text or synthetic fallback."""
    if not url:
        return f"{fallback_title} requiring skills: {skills}"

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if not r.ok:
            raise ValueError(f"HTTP {r.status_code}")

        html = r.text

        if portal == "Naukri":
            m = re.search(r'"jobDescription"\s*:\s*"([^"]+)"', html)
            if m:
                return m.group(1).encode().decode("unicode_escape")[:4000]

        if portal == "LinkedIn":
            m = re.search(r'"description"\s*:\s*\{[^}]*"text"\s*:\s*"([^"]+)"', html)
            if m:
                return m.group(1).encode().decode("unicode_escape")[:4000]

        # Generic: strip tags
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000] if len(text) >= 80 else f"{fallback_title} requiring skills: {skills}"

    except Exception:
        return f"{fallback_title} requiring skills: {skills}"
```

**Use in** `targeted_search.py` scoring loop:

```python
from scrapers.jd_extract import fetch_job_description

desc_text = fetch_job_description(job["url"], job["portal"], job["title"], skills)
```

---

### B12 — Recruiter scraper reliability (Step 4 preview)

**Short-term:** Add Selenium fallback using existing LinkedIn session profile.

**Medium-term:** Google Custom Search JSON API (100 free queries/day) with key in `.env`:

```python
GOOGLE_CSE_API_KEY=...
GOOGLE_CSE_CX=...
```

**File:** `scrapers/recruiter_scraper.py` — add `_google_cse_search()` when env keys present; keep urllib as fallback.

---

## 5. Step 2 — Modularization plan (block-by-block)

Backend is **already modular** (`app.py` is 98 lines). Focus on frontend + legacy cleanup.

### 5.1 Target folder structure

```
job auto apply/
├── app.py                          # entry only
├── .env                            # secrets (gitignored)
├── requirements.txt
├── config/
│   ├── profile.py                  # non-secret settings
│   └── secrets.py                  # env loader
├── core/
│   ├── state.py
│   ├── apply_engine.py
│   ├── orchestrator.py             # NEW: wraps run flows
│   ├── scoring/
│   │   └── filter.py               # move from root
│   └── resume_tailor.py
├── routes/                         # keep as-is
├── scrapers/
│   ├── targeted_search.py
│   ├── recruiter_scraper.py
│   └── jd_extract.py               # NEW
├── bots/                           # NEW — move from root
│   ├── linkedin_bot.py
│   ├── naukri_bot.py
│   ├── indeed_bot.py
│   └── careers_bot.py
├── templates/
│   ├── base.html                   # shell, nav, SSE console
│   ├── tabs/
│   │   ├── feed.html
│   │   ├── tracker.html
│   │   ├── review.html
│   │   ├── resume.html
│   │   ├── prep.html
│   │   ├── analytics.html
│   │   └── settings.html
│   └── dashboard.html              # {% include tabs %} only
├── static/
│   ├── css/dashboard.css
│   └── js/
│       ├── app.js                  # tabs, toast, SSE
│       ├── bot-controls.js
│       ├── targeted-search.js
│       └── kanban.js
├── _legacy/                        # archive, do not import
│   ├── app_v2_monolith.py
│   ├── server.py
│   └── app_extracted_*.py
└── logs/
```

### 5.2 Migration order (nothing breaks)

| Block | Move | Test after |
|-------|------|------------|
| 1 | Create `_legacy/`, move all `app_extracted_*.py`, `app_v2_monolith.py`, `server.py` | `python app.py` still starts |
| 2 | Extract CSS from `dashboard.html` → `static/css/dashboard.css` | Page looks same |
| 3 | Extract JS → `static/js/*.js` (one file at a time) | Buttons still work |
| 4 | Remove marketing sections (L983–1015 hero stats, L1889–2270 docs) OR move to `docs/LANDING.md` | Dashboard at top |
| 5 | Split tab HTML into `templates/tabs/` | All 7 tabs render |
| 6 | Move `filter.py` → `core/scoring/filter.py`, update imports | Targeted search scores |
| 7 | Move bots → `bots/`, update imports in routes | Run All Bots works |

### 5.3 Import update pattern

```python
# Before
from linkedin_bot import run_linkedin_bot

# After
from bots.linkedin_bot import run_linkedin_bot
```

Use project-wide search-replace once per module.

---

## 6. Step 3 — Performance & reliability

### 6.1 Async / background processing

**Create:** `core/orchestrator.py`

```python
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

class JobOrchestrator:
    def __init__(self, log_fn, stop_event):
        self.log_fn = log_fn
        self.stop_event = stop_event

    def run_targeted(self, company, skills, location, max_apps, headless):
        t = threading.Thread(
            target=self._targeted_wrapper,
            args=(company, skills, location, max_apps, headless),
            daemon=True,
        )
        t.start()
        return t

    def _targeted_wrapper(self, *args):
        try:
            from scrapers.targeted_search import run_targeted_search_flow
            run_targeted_search_flow(*args, self.log_fn, self.stop_event)
        except Exception as e:
            self.log_fn(f"[ERROR] Targeted search: {e}")
```

**Scoring parallelism** — in `targeted_search.py`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _score_one(job, skills):
    from filter import should_apply
    from scrapers.jd_extract import fetch_job_description
    desc = fetch_job_description(job["url"], job["portal"], job["title"], skills)
    apply, score, matched, reason, decision, missing = should_apply(
        job["title"], desc, job["company"], _reload=False
    )
    return {**job, "score": round(score, 1), "decision": decision,
            "reason": reason, "matched": matched, "missing": missing}

# Replace sequential for-loop with:
with ThreadPoolExecutor(max_workers=3) as pool:  # cap Gemini concurrency
    futures = [pool.submit(_score_one, j, skills) for j in unique_jobs]
    for fut in as_completed(futures):
        if stop_event.is_set():
            break
        batch_results.append(fut.result())
```

### 6.2 Robust error handling wrapper

**Create:** `core/retry.py`:

```python
import time
import functools

def with_retry(max_attempts=3, delay=2.0, exceptions=(Exception,)):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for i in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last = e
                    time.sleep(delay * (i + 1))
            raise last
        return wrapper
    return decorator
```

Wrap all `_fetch_*` functions and browser `driver.get()` calls.

### 6.3 Caching & rate limiting

**Create:** `core/rate_limit.py`:

```python
import time
import threading

class RateLimiter:
    def __init__(self, min_interval_sec: float):
        self.min_interval = min_interval_sec
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.time()

LINKEDIN_LIMITER = RateLimiter(3.0)   # 3s between LinkedIn requests
NAUKRI_LIMITER   = RateLimiter(1.5)
GOOGLE_LIMITER   = RateLimiter(5.0)
```

**Create:** `core/cache.py` — TTL dict for scored URLs (30 min):

```python
import time

_cache = {}

def get_scored(url: str):
    entry = _cache.get(url)
    if entry and time.time() - entry["ts"] < 1800:
        return entry["data"]
    return None

def set_scored(url: str, data: dict):
    _cache[url] = {"ts": time.time(), "data": data}
```

Use in `filter.should_apply()` before calling Gemini.

### 6.4 Assist apply — stop thread leak

**File:** `routes/search_routes.py`

```python
_active_assist_drivers = []
_assist_lock = threading.Lock()

def run_assist():
    driver = None
    try:
        driver = create_browser(headless=False, profile_name=profile_name)
        with _assist_lock:
            _active_assist_drivers.append(driver)
        driver.get(url)
        # ... wait for close ...
    finally:
        with _assist_lock:
            if driver in _active_assist_drivers:
                _active_assist_drivers.remove(driver)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
```

---

## 7. Step 4 — Debug core features

### 7.1 AI scoring test script

**Create:** `tools/test_scoring.py`

```python
"""Run: python tools/test_scoring.py"""
from filter import should_apply

SAMPLE = [
    ("Senior Data Engineer", "AWS PySpark Snowflake ETL pipeline Python SQL 4 years", "PwC"),
    ("VP of Engineering", "15 years leadership", "BigCorp"),
    ("Intern Data Analyst", "0-1 year fresher only unpaid", "Startup"),
]

for title, desc, company in SAMPLE:
    apply, score, matched, reason, decision, missing = should_apply(title, desc, company)
    print(f"{score:5.1f}% {decision:6s} apply={apply} | {title} @ {company}")
    print(f"       {reason}\n")
```

### 7.2 Auto Apply timeout fix

**File:** `core/apply_engine.py` — wrap apply in timeout:

```python
import concurrent.futures

APPLY_TIMEOUT_SEC = 180  # 3 min max per job

def run_apply_for_url(url, company, role):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_run_apply_inner, url, company, role)
        try:
            return fut.result(timeout=APPLY_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            bot_log(f"  [ERROR] Apply timed out after {APPLY_TIMEOUT_SEC}s")
            update_status(url, "Manual Needed")
            return False
```

Move current body to `_run_apply_inner()`.

### 7.3 Recruiter scraper test

```powershell
python -c "from scrapers.recruiter_scraper import run_recruiter_scraper_flow; from threading import Event; run_recruiter_scraper_flow('PwC','Data Engineer','Pune', print, Event())"
```

Check `logs/recruiter_leads.json` for new entries.

---

## 8. Step 5 — UI/UX upgrades

### 8.1 Credentials → sidebar badge (not banner)

**Remove intrusive banner** — `dashboard.html` L1040 `display:none !important` is a hack. Replace with:

```html
<!-- In tab-bar, after Settings button -->
<button class="tab-btn cred-badge" id="cred-status-badge" onclick="switchTab('settings'); switchSettingsTab('settings-company-creds');">
  🔑 <span id="cred-badge-text">Credentials</span>
  <span id="cred-alert-dot" class="alert-dot" style="display:none;"></span>
</button>
```

**JS:** On load, fetch `/api/notifications`. If any notification, show red dot on badge — not full-width yellow banner.

### 8.2 Recruiter leads — Apply button in UI

**In** `refreshRecruiterLeads()` add Assist button per row:

```javascript
<button class="mock-btn" onclick="assistApply('${encodeURIComponent(lead.link)}', '${encodeURIComponent(lead.company)}', 'Recruiter Form')">
  🧑‍💻 Apply
</button>
```

### 8.3 Glassdoor + Indeed async (targeted search)

**Add to** `scrapers/targeted_search.py`:

```python
def _fetch_glassdoor_rss(skills, location, log_fn):
    """Glassdoor has no stable public API — use job board RSS mirrors or Selenium fallback."""
    # Phase 1: skip if blocked
    # Phase 2: Playwright with stealth + linkedin profile cookies
    log_fn("    Glassdoor: not yet implemented (Step 5)")
    return []
```

Indeed RSS already exists — ensure it stays in parallel pool.

### 8.4 Simplified dashboard layout

**Remove from live dashboard:**
- Hero marketing block (or collapse to 80px header)
- "What the bot actually does" pipeline section
- "16-week implementation plan" section
- Duplicate architecture diagrams below tabs

**Keep:**
- Tab bar + active tab content
- SSE console (dock bottom or sidebar)
- Targeted search card + results tables

---

## 9. Step 6 — Advanced features

### 9.1 Dynamic resume tailoring before Auto Apply

**Hook in** `core/apply_engine.py` before form fill:

```python
from core.resume_tailor import tailor_and_export_pdf

def _maybe_tailor_resume(driver, company, role):
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
        pdf_path = tailor_and_export_pdf(body, company, role)
        if pdf_path and os.path.exists(pdf_path):
            bot_log(f"  [ATS] Using tailored resume: {pdf_path}")
            return pdf_path
    except Exception as e:
        bot_log(f"  [ATS][WARN] Tailor skipped: {e}")
    return PROFILE.get("resume_path")
```

Implement `tailor_and_export_pdf()` in `core/resume_tailor.py` using existing Gemini logic + reportlab/pypdf.

### 9.2 Cold outreach generator

**New route:** `routes/outreach_routes.py`

```
POST /api/outreach/generate
Body: { lead_id, type: "linkedin"|"email", tone: "professional" }
```

**Logic:**
1. Read lead from `recruiter_leads.json`
2. Extract company + snippet + form context
3. Gemini prompt → 300-char LinkedIn note OR 150-word email
4. Return draft for user copy/paste (do not auto-send — ToS risk)

### 9.3 Scheduled daily digest (8 AM)

**Extend** `app.py` scheduler:

```python
def _run_morning_digest():
    from scrapers.targeted_search import run_targeted_search_flow
    from threading import Event
    from config.profile import SEARCH_KEYWORDS, SEARCH_LOCATIONS, TARGET_COMPANIES

    ev = Event()
    company = TARGET_COMPANIES[0] if TARGET_COMPANIES else ""
    skills  = SEARCH_KEYWORDS[0] if SEARCH_KEYWORDS else "Data Engineer"
    loc     = SEARCH_LOCATIONS[0] if SEARCH_LOCATIONS else "Pune"

    run_targeted_search_flow(company, skills, loc, 15, True, bot_log, ev)

    from core.state import TARGETED_SEARCH_RESULTS
    hot = [j for j in TARGETED_SEARCH_RESULTS if j.get("score", 0) >= 80]

    if hot:
        _send_telegram_digest(hot)  # or email via smtplib

scheduler.add_job(_run_morning_digest, "cron", hour=8, minute=0)
```

**Telegram** — add to `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

```python
def _send_telegram_digest(jobs):
    import requests
    token = env("TELEGRAM_BOT_TOKEN")
    chat  = env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    lines = [f"🌅 Morning digest — {len(jobs)} jobs ≥80%\n"]
    for j in jobs[:10]:
        lines.append(f"• {j['score']}% {j['title']} @ {j['company']}\n  {j['url']}")
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": "\n".join(lines)},
        timeout=15,
    )
```

### 9.4 Contextual interview prep (Kanban-connected)

**New route:**

```
POST /api/interview_prep
Body: { url: "job listing url from Kanban card" }
```

**Logic:**
1. Find row in CSV by URL
2. Re-fetch or use cached JD
3. Gemini: generate 5 technical + 3 behavioral questions + STAR hints
4. Return JSON → populate Interview Prep tab dynamically

**Replace static placeholder** in `tab-prep` with empty state + "Select a job from Kanban" + generated Q&A list.

---

## 10. Verification checklist

### After P0

- [ ] DevTools Console: zero JS errors on page load
- [ ] Network: `POST /api/run` body contains `"target":"targeted"` (not `"mode"`)
- [ ] Log shows `[TARGETED SEARCH]` not `[LOGIN] LinkedIn` when clicking Search Jobs
- [ ] Recruiter button sends `"target":"recruiter_posts"`
- [ ] `/api/stats` returns `"running": true|false`
- [ ] Workday register does not crash on `get_driver`

### After P1

- [ ] After targeted search, `logs/job_applications.csv` has new rows
- [ ] Kanban shows Review/Skipped jobs from search
- [ ] Auto Apply creates row then updates to Applied/Manual Needed
- [ ] Jobs below 55% show decision `skip` not `review`

### After Step 2

- [ ] `python app.py` works from clean terminal
- [ ] No imports from `_legacy/`
- [ ] `dashboard.html` under 500 lines (includes only)

### After Step 3

- [ ] 20-job search completes faster (parallel scoring)
- [ ] Repeated same URL uses cache (no second Gemini call)
- [ ] Apply kills Chrome after 180s timeout

### After Step 5–6

- [ ] Credentials show as sidebar dot, not banner
- [ ] Recruiter leads have Apply button
- [ ] 8 AM digest message on Telegram (if configured)
- [ ] Interview Prep generates questions for Kanban Interview card

---

## 11. Implementation schedule (recommended)

| Day | Work | Files touched |
|-----|------|---------------|
| 1 AM | P0 hotfixes B01–B07 | `dashboard.html`, `data_routes.py`, `workday_routes.py` |
| 1 PM | Secrets to `.env` B05 | `config/`, `.gitignore`, rotate keys |
| 2 | P1 B08–B11 | `targeted_search.py`, `apply_engine.py`, `filter.py`, `jd_extract.py` |
| 3 | Step 2 extract JS/CSS | `static/`, `templates/tabs/` |
| 4 | Step 3 rate limit + cache | `core/rate_limit.py`, `core/cache.py` |
| 5 | Step 4 test scripts + apply timeout | `tools/`, `apply_engine.py` |
| 6–7 | Step 5 UI simplify + recruiter Apply btn | `dashboard` or `static/js` |
| 8–10 | Step 6 tailor hook + Telegram + interview API | new routes |

---

## 12. What NOT to do

1. **Do not** keep two `runTargetedSearch` functions — one file, one definition.
2. **Do not** store secrets in `profile.py` after migration — UI save must write `.env`.
3. **Do not** run `server.py` and `app.py` together — pick port 5005 only.
4. **Do not** commit `sessions/` — contains live LinkedIn cookies.
5. **Do not** auto-send LinkedIn connection requests — generate text only (account ban risk).
6. **Do not** skip rotating credentials that were in plaintext profile.py.

---

## 13. Quick reference — API contract (correct)

### POST `/api/run`

```json
{
  "target": "all | linkedin | naukri | indeed | targeted | recruiter_posts",
  "headless": true,
  "max_applications": 15,
  "company": "pwc",
  "skills": "Data Engineer AWS",
  "location": "Pune"
}
```

### POST `/api/approve` (Auto Apply)

```json
{
  "url": "https://...",
  "company": "PwC",
  "role": "Senior Data Engineer"
}
```

### POST `/api/assist_apply`

```json
{
  "url": "https://...",
  "company": "PwC",
  "role": "Senior Data Engineer"
}
```

---

*End of master plan. Say **"fix P0 now"** to apply Section 3 patches automatically, or **"green light Step 2"** to start modularization.*
