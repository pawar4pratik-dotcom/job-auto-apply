"""
scrapers/targeted_search.py — Multi-portal targeted job search (v2 - improved).

Changes v2:
  - Generic Workday API: works for ANY company, not just PwC
  - Direct LinkedIn RSS/API: no browser login needed for public search
  - Naukri API: direct API call instead of browser session
  - Parallel portal fetching via ThreadPoolExecutor for speed
  - Better deduplication + location filtering
  - Graceful fallback if any portal fails
  - Progress streaming via log_fn for live UI feedback
"""
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.state import bot_log, TARGETED_SEARCH_RESULTS, _results_lock

# ── Known Workday company portals ────────────────────────────────────────────
WORKDAY_PORTALS = {
    "pwc":         ("https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/{site}/jobs",
                    ["Global_Experienced_Careers", "Catalyst"]),
    "accenture":   ("https://accenture.wd3.myworkdayjobs.com/wday/cxs/AccentureCareers/Accenture_Experienced_Professionals_Global/jobs",
                    ["Accenture_Experienced_Professionals_Global"]),
    "deloitte":    ("https://deloitte.wd5.myworkdayjobs.com/wday/cxs/External_Careers/DeloitteCareers/jobs",
                    ["DeloitteCareers"]),
    "tcs":         ("https://tcs.wd3.myworkdayjobs.com/wday/cxs/TCS/TCS_Jobs/jobs",
                    ["TCS_Jobs"]),
    "wipro":       ("https://wipro.wd3.myworkdayjobs.com/wday/cxs/Wipro/WiproCareers/jobs",
                    ["WiproCareers"]),
    "infosys":     ("https://infosys.wd3.myworkdayjobs.com/wday/cxs/Infosys/Careers/jobs",
                    ["Careers"]),
    "cognizant":   ("https://cognizant.wd5.myworkdayjobs.com/wday/cxs/Cognizant/Careers/jobs",
                    ["Careers"]),
    "capgemini":   ("https://capgemini.wd3.myworkdayjobs.com/wday/cxs/Capgemini/Capgemini_Careers/jobs",
                    ["Capgemini_Careers"]),
    "microsoft":   ("https://gdc.wd3.myworkdayjobs.com/wday/cxs/MSFT/myCareersite/jobs",
                    ["myCareersite"]),
    "google":      ("https://google.wd3.myworkdayjobs.com/wday/cxs/Google/google/jobs",
                    ["google"]),
}


_LOCATION_ALIASES = {
    "bangalore": ["bengaluru", "bangalore", "benglore"],
    "bengaluru": ["bengaluru", "bangalore", "benglore"],
    "benglore": ["bengaluru", "bangalore", "benglore"],
    "gurgaon": ["gurugram", "gurgaon"],
    "gurugram": ["gurugram", "gurgaon"],
    "mumbai": ["mumbai", "bombay", "navi mumbai"],
    "bombay": ["mumbai", "bombay", "navi mumbai"],
    "calcutta": ["kolkata", "calcutta"],
    "kolkata": ["kolkata", "calcutta"],
}

def _location_matches(job_loc: str, target_locs: list) -> bool:
    job_loc_lower = job_loc.lower()
    for t in target_locs:
        t_clean = t.strip().lower()
        if not t_clean:
            continue
        # Check standard substring match first
        if t_clean in job_loc_lower:
            return True
        # Check aliases
        aliases = _LOCATION_ALIASES.get(t_clean, [t_clean])
        if any(alias in job_loc_lower for alias in aliases):
            return True
    return False


def _score_one(job, skills):
    from filter import should_apply
    from scrapers.jd_extract import fetch_job_description
    desc = fetch_job_description(job["url"], job["portal"], job["title"], skills)
    try:
        apply, score, matched, reason, decision, missing = should_apply(
            job["title"], desc, job["company"], _reload=False, url=job["url"]
        )
    except Exception as e:
        apply, score, matched, reason, decision, missing = False, 0, [], str(e), "skip", []
    return {
        "company":  job["company"],   "title":    job["title"],
        "url":      job["url"],       "location": job["location"],
        "portal":   job["portal"],    "posted":   job.get("posted", ""),
        "score":    round(score, 1),  "decision": decision,
        "reason":   reason,           "matched":  matched,
        "missing":  missing,
    }


def _fetch_workday_portal(company_key: str, url_template: str, sites: list,
                          skills: str, location: str, log_fn) -> list:
    """Fetch jobs from a Workday portal via direct JSON API."""
    results = []
    search_terms = [s.strip() for s in re.split(r"[,/]", skills) if s.strip()][:3]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        import requests as _req
        for site in sites:
            api_url = url_template.format(site=site) if "{site}" in url_template else url_template
            for term in (search_terms if search_terms else ["Data Engineer"]):
                payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term}
                try:
                    r = _req.post(api_url, json=payload, headers=headers, timeout=12)
                    if r.status_code == 200:
                        jobs = r.json().get("jobPostings", [])
                        for j in jobs:
                            locs = j.get("locationsText", "")
                            loc_str = ", ".join(
                                [l.get("descriptor", str(l)) if isinstance(l, dict) else str(l)
                                 for l in locs] if isinstance(locs, list) else [str(locs)]
                            )
                            path = j.get("externalPath", "")
                            base = re.match(r"(https://[^/]+)", api_url)
                            base_url = base.group(1) if base else ""
                            full_url = f"{base_url}/en-US/{site}{path}" if path else ""
                            if full_url:
                                results.append({
                                    "company": company_key.title(), "title": j.get("title", ""),
                                    "url": full_url, "location": loc_str,
                                    "portal": "Workday", "posted": j.get("postedOn", ""), "description": "",
                                })
                except Exception:
                    pass
    except Exception:
        pass
    log_fn(f"    Workday/{company_key.title()}: {len(results)} results")
    return results


def _fetch_linkedin_public(skills: str, location: str, company: str, log_fn) -> list:
    """Fetch jobs via LinkedIn public job search API (no login required)."""
    results = []
    try:
        import requests as _req
        from bs4 import BeautifulSoup
        keywords = f"{skills} {company}".strip()
        # LinkedIn job search public endpoint
        params = {
            "keywords": keywords,
            "location": location,
            "f_TPR": "r86400",  # Last 24h
            "count": 25,
            "start": 0,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        url = "https://www.linkedin.com/jobs/search"
        r = _req.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for card in soup.select('.job-search-card'):
                title_el = card.select_one('.base-search-card__title')
                title = title_el.text.strip() if title_el else ""
                
                comp_el = card.select_one('.base-search-card__subtitle')
                comp = comp_el.text.strip() if comp_el else ""
                
                loc_el = card.select_one('.job-search-card__location')
                loc = loc_el.text.strip() if loc_el else ""
                
                urn = card.get('data-entity-urn', '')
                jid = urn.split(':')[-1] if urn else ''
                
                if jid and title:
                    results.append({
                        "company": comp, "title": title,
                        "url": f"https://www.linkedin.com/jobs/view/{jid}",
                        "location": loc, "portal": "LinkedIn",
                        "posted": "", "description": "",
                    })
    except Exception as e:
        log_fn(f"    [WARN] LinkedIn public fetch: {e}")

    log_fn(f"    LinkedIn: {len(results)} results")
    return results


def _fetch_naukri_browser(skills: str, location: str, company: str, log_fn) -> list:
    """Fallback to browser search for Naukri if public API gets blocked."""
    results = []
    try:
        from browser import create_browser
        import naukri_bot
        log_fn("    [INFO] Launching headless Naukri browser for targeted search...")
        driver = create_browser(headless=True, profile_name="naukri")
        try:
            kw = f"{company + ' ' if company else ''}{skills}".strip()
            naukri_bot.search_jobs(driver, kw, location, page=1, log_fn=lambda x: None)
            time.sleep(3.5)
            
            cards = naukri_bot.get_job_listings(driver)
            for card in cards[:20]:
                job_id, title, comp, url, posted_date = naukri_bot.extract_card_metadata_naukri(card)
                if url and title:
                    results.append({
                        "company": comp, "title": title, "url": url,
                        "location": location, "portal": "Naukri",
                        "posted": posted_date, "description": "",
                    })
        finally:
            driver.quit()
    except Exception as e:
        log_fn(f"    [WARN] Naukri browser fetch failed: {e}")
    return results


def _fetch_naukri_public(skills: str, location: str, company: str, log_fn) -> list:
    """Fetch jobs via Naukri public API."""
    results = []
    try:
        import requests as _req
        keywords = f"{skills} {company}".strip()
        loc_encoded = location.replace(" ", "%20")
        kw_encoded  = keywords.replace(" ", "%20").replace("/", "%2C")
        url = (
            f"https://www.naukri.com/jobapi/v3/search?noOfResults=20&urlType=search_by_keyword"
            f"&searchType=adv&keyword={kw_encoded}&location={loc_encoded}&pageNo=1&mode=o"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Appid": "109",
            "Systemid": "Naukri",
            "Content-Type": "application/json",
        }
        r = _req.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()
            jobs = data.get("jobDetails", [])
            for j in jobs:
                job_url = j.get("jdURL", "") or j.get("jobUrl", "")
                title   = j.get("title", "")
                comp    = j.get("companyName", company)
                locs_list = j.get("placeholders", [])
                loc = location
                for ph in locs_list:
                    if ph.get("type") == "location":
                        loc = ph.get("label", location)
                        break
                if job_url and title:
                    if not job_url.startswith("http"):
                        job_url = "https://www.naukri.com" + job_url
                    results.append({
                        "company": comp, "title": title, "url": job_url,
                        "location": loc, "portal": "Naukri",
                        "posted": j.get("footerPlaceholderLabel", ""), "description": "",
                    })
    except Exception as e:
        log_fn(f"    [WARN] Naukri API: {e}")

    if not results:
        results = _fetch_naukri_browser(skills, location, company, log_fn)

    log_fn(f"    Naukri: {len(results)} results")
    return results


def _fetch_indeed_rss(skills: str, location: str, log_fn) -> list:
    """Fetch jobs via Indeed RSS (no auth needed)."""
    results = []
    try:
        import urllib.request, xml.etree.ElementTree as ET
        q = skills.replace(" ", "+").replace("/", "+")
        l = location.replace(" ", "+")
        url = f"https://in.indeed.com/rss?q={q}&l={l}&sort=date&limit=20"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:20]:
            title   = item.findtext("title", "").strip()
            link    = item.findtext("link", "").strip()
            comp    = ""
            src_el  = item.find("source")
            if src_el is not None:
                comp = src_el.text or ""
            pub     = item.findtext("pubDate", "")
            if link and title:
                results.append({
                    "company": comp, "title": title, "url": link,
                    "location": location, "portal": "Indeed",
                    "posted": pub[:16] if pub else "", "description": "",
                })
    except Exception as e:
        log_fn(f"    [WARN] Indeed RSS: {e}")
    log_fn(f"    Indeed: {len(results)} results")
    return results


def run_targeted_search_flow(
    company: str,
    skills: str,
    location: str,
    max_apps: int,
    headless: bool,
    log_fn,
    stop_event,
):
    """Execute the full multi-portal targeted search and score pipeline."""
    with _results_lock:
        TARGETED_SEARCH_RESULTS.clear()

    company_lower = company.strip().lower()
    log_fn(f"\n[TARGETED SEARCH] Company: {company or 'Any'} | Skills: {skills} | Location: {location}")
    log_fn("[TARGETED SEARCH] Fetching from: Workday API → LinkedIn → Naukri → Indeed (parallel)")

    discovered_raw = []
    fetch_tasks = []

    # ── Determine which portals to hit ───────────────────────────────────────
    with ThreadPoolExecutor(max_workers=6) as pool:

        # 1. Workday portals
        if company_lower in WORKDAY_PORTALS:
            url_tmpl, sites = WORKDAY_PORTALS[company_lower]
            fetch_tasks.append(pool.submit(
                _fetch_workday_portal, company_lower, url_tmpl, sites, skills, location, log_fn
            ))
        elif not company_lower:
            # No specific company — hit top 3 workday portals
            for ck in ["pwc", "accenture", "deloitte"]:
                url_tmpl, sites = WORKDAY_PORTALS[ck]
                fetch_tasks.append(pool.submit(
                    _fetch_workday_portal, ck, url_tmpl, sites, skills, location, log_fn
                ))

        # 2. LinkedIn public
        fetch_tasks.append(pool.submit(_fetch_linkedin_public, skills, location, company, log_fn))

        # 3. Naukri API
        fetch_tasks.append(pool.submit(_fetch_naukri_public, skills, location, company, log_fn))

        # 4. Indeed RSS
        fetch_tasks.append(pool.submit(_fetch_indeed_rss, skills, location, log_fn))

        for fut in as_completed(fetch_tasks):
            if stop_event.is_set():
                break
            try:
                batch = fut.result()
                discovered_raw.extend(batch)
            except Exception as e:
                log_fn(f"    [WARN] Fetch task error: {e}")

    log_fn(f"\n[TARGETED SEARCH] Collating {len(discovered_raw)} raw results...")

    # ── Deduplication ─────────────────────────────────────────────────────────
    seen_urls: set = set()
    target_locs = [l.strip().lower() for l in re.split(r"[,/]", location) if l.strip()]
    unique_jobs = []
    for job in discovered_raw:
        u = (job["url"] or "").split("?")[0].rstrip("/")
        if u in seen_urls or not u:
            continue
        seen_urls.add(u)
        # Location filter — only skip if location specified AND job location doesn't match
        if target_locs and job.get("location"):
            if not _location_matches(job["location"], target_locs) and not any(
                t in ("remote", "anywhere", "pan india") for t in target_locs
            ):
                continue
        unique_jobs.append(job)

    log_fn(f"[TARGETED SEARCH] {len(unique_jobs)} unique jobs after dedup. Scoring...")

    # ── AI Scoring ─────────────────────────────────────────────────────────────
    from filter import _reload_profile
    from tracker import log_application
    _reload_profile()

    batch_results = []
    log_fn(f"[TARGETED SEARCH] Scoring {len(unique_jobs)} jobs using ThreadPoolExecutor (max_workers=6)...")
    
    with ThreadPoolExecutor(max_workers=6) as scoring_pool:
        futures = {scoring_pool.submit(_score_one, job, skills): job for job in unique_jobs}
        for idx, fut in enumerate(as_completed(futures), 1):
            if stop_event.is_set():
                log_fn("[TARGETED SEARCH] Stop signal — halting scoring.")
                break
            try:
                res = fut.result(timeout=15)
                batch_results.append(res)
                log_fn(f"  [{idx}/{len(unique_jobs)}] Scored: {res['title'][:45]} @ {res['company']} ({res['score']}%)")
            except Exception as e:
                log_fn(f"  [WARN] Scoring error: {e}")

    # Log results to CSV
    for r_job in batch_results:
        status = "Review" if r_job["decision"] in ("auto", "review") else "Skipped"
        log_application(
            company=r_job["company"],
            role=r_job["title"],
            portal=r_job["portal"],
            url=r_job["url"],
            status=status,
            score=r_job["score"],
            matched_skills=r_job.get("matched", []),
            skip_reason=r_job.get("reason", "") if status == "Skipped" else "",
            posted_date=r_job.get("posted", ""),
            missing_skills=r_job.get("missing", []),
            decision=r_job.get("decision", ""),
        )

    with _results_lock:
        TARGETED_SEARCH_RESULTS.clear()
        TARGETED_SEARCH_RESULTS.extend(
            sorted(batch_results, key=lambda x: x["score"], reverse=True)
        )

    count = len(TARGETED_SEARCH_RESULTS)
    high  = sum(1 for r in TARGETED_SEARCH_RESULTS if r["score"] >= 70)
    log_fn(f"\n[OK] Targeted Search complete: {count} jobs found, {high} are 70%+ match.")
    log_fn("[OK] See the '📋 Collated Targeted Search Results' panel below!")
