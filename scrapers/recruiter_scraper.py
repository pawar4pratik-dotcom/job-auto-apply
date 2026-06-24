"""
scrapers/recruiter_scraper.py — LinkedIn + Google recruiter post scanner (v2).

Improvements:
  - Dual source: LinkedIn Content Search + Google CSE (no browser login needed)
  - Finds Google Forms, MS Forms, Typeform, JotForm, Airtable form links
  - Saves leads to logs/recruiter_leads.json (structured, not just txt)
  - Also saves to logs/recruiter_leads.txt for backward compatibility
  - Returns leads count via log_fn for live UI feedback
"""
import os
import re
import json
import time
import datetime
import urllib.parse


def _google_search_recruiter_forms(skills: str, company: str, location: str, log_fn) -> list:
    """Search Google for HR recruiter form links using direct HTTPS query with Selenium headless fallback."""
    leads = []
    import urllib.request, urllib.parse, re
    
    query = f'{company} {skills} {location} "apply" site:docs.google.com/forms OR site:forms.gle OR site:forms.office.com'
    if not company:
        query = f'{skills} hiring recruiter google form apply {location}'
        
    encoded = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={encoded}&num=20&hl=en"
    
    html = ""
    
    # Try direct HTTP first
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log_fn(f"    [WARN] Direct Google search request failed: {e}. Trying Selenium fallback...")
        
    # If blocked (enablejs check, captcha or too short), use Selenium fallback
    is_blocked = "enablejs" in html or len(html) < 5000 or "unusual traffic" in html.lower()
    if not html or is_blocked:
        try:
            from browser import create_browser
            log_fn("    Launching headless Chrome to bypass Google bot checks...")
            driver = create_browser(headless=True, profile_name="default")
            try:
                driver.get(url)
                time.sleep(3.5)  # Wait for JS to render
                html = driver.page_source
            finally:
                driver.quit()
        except Exception as sel_err:
            log_fn(f"    [WARN] Google Selenium search fallback failed: {sel_err}")

    if not html:
        return []

    # Parse and decode all hrefs and urls from HTML
    raw_links = []
    # 1. Extract href contents
    for m in re.finditer(r'''href=["']([^"']+)["']''', html):
        raw_links.append(m.group(1))
    # 2. Extract text links
    for m in re.finditer(r'(https?://[^\s"\'<>]+)', html):
        raw_links.append(m.group(1))
        
    seen = set()
    form_domains = ["docs.google.com/forms", "forms.gle", "forms.office.com", "typeform.com", "jotform.com", "airtable.com"]
    
    for rl in raw_links:
        # Decode URL-encoded parameters
        decoded = urllib.parse.unquote(rl.replace("&amp;", "&"))
        
        # Extract target from google redirection urls
        if "/url?" in decoded or "google.com/url?" in decoded:
            parsed_query = urllib.parse.parse_qs(urllib.parse.urlparse(decoded).query)
            if "q" in parsed_query:
                decoded = parsed_query["q"][0]
                
        # Clean URL trailing markers
        clean_url = decoded.split("#")[0].split("?")[0].rstrip("&.,;)")
        
        if clean_url in seen:
            continue
            
        # Check target domains and filter out internal Google search paths
        if any(d in clean_url for d in form_domains):
            if not any(g in clean_url for g in ["google.com/search", "google.com/support", "google.com/accounts", "google.com/preferences"]):
                seen.add(clean_url)
                
                # Determine form type
                form_type = (
                    "Google Form" if "docs.google.com" in clean_url or "forms.gle" in clean_url
                    else "MS Form" if "forms.office.com" in clean_url
                    else "Typeform" if "typeform.com" in clean_url
                    else "JotForm" if "jotform.com" in clean_url
                    else "Airtable" if "airtable.com" in clean_url
                    else "Form"
                )
                
                leads.append({
                    "source": "Google Search",
                    "company": company or "Unknown",
                    "snippet": f"Found via Google Search: {skills} {location}",
                    "link": clean_url,
                    "type": form_type,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                
    log_fn(f"    Google Search: {len(leads)} form links found")

    # Fallback: DuckDuckGo HTML search (doesn't block bots)
    if not leads:
        try:
            ddg_query = f"{company} {skills} {location} hiring google form apply"
            ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(ddg_query)}"
            req = urllib.request.Request(ddg_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                ddg_html = resp.read().decode("utf-8", errors="ignore")
            for m in re.finditer(r'(https?://(?:docs\.google\.com/forms|forms\.gle|forms\.office\.com)[^\s"\'<>]+)', ddg_html):
                clean_url = urllib.parse.unquote(m.group(1).split("#")[0].rstrip("&.,;)"))
                if clean_url not in seen:
                    seen.add(clean_url)
                    leads.append({
                        "source": "DuckDuckGo Search",
                        "company": company or "Unknown",
                        "snippet": f"Found via DuckDuckGo: {skills} {location}",
                        "link": clean_url,
                        "type": "Google Form" if "google" in clean_url or "forms.gle" in clean_url else "MS Form",
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
            log_fn(f"    DuckDuckGo fallback: {len(leads)} form links found")
        except Exception as ddg_err:
            log_fn(f"    [WARN] DuckDuckGo fallback: {ddg_err}")

    return leads


def _linkedin_content_search(skills: str, company: str, location: str, log_fn) -> list:
    """Search LinkedIn content for recruiter posts - HTTP first, Selenium fallback."""
    leads = []

    query = f"{company} {skills} hiring google form apply {location}"
    encoded = urllib.parse.quote(query)

    # Try HTTP first (no browser needed)
    try:
        import requests as _req
        url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html",
        }
        r = _req.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            html = r.text
            seen = set()
            raw_links = re.findall(r'(https?://[^\s"\'<>]+)', html)
            for rl in raw_links:
                decoded = urllib.parse.unquote(rl.replace("&amp;", "&"))
                clean_url = decoded.split("#")[0].split("?")[0].rstrip("&.,;)")
                if clean_url in seen:
                    continue
                if any(d in clean_url for d in ["docs.google.com/forms", "forms.gle", "forms.office.com", "typeform.com", "jotform.com", "airtable.com"]):
                    seen.add(clean_url)
                    leads.append({
                        "source": "LinkedIn Post",
                        "company": company or "LinkedIn Recruiter",
                        "snippet": f"Found via LinkedIn Search: {skills}",
                        "link": clean_url,
                        "type": "Google Form" if "google" in clean_url or "forms.gle" in clean_url else "MS Form" if "forms.office" in clean_url else "Form",
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
            if leads:
                log_fn(f"    LinkedIn Content (HTTP): {len(leads)} links found")
                return leads
    except Exception as e:
        log_fn(f"    [WARN] LinkedIn HTTP search: {e}")

    # Selenium fallback (only if HTTP found nothing)
    try:
        from browser import create_browser
        log_fn("    Launching LinkedIn browser session to scan posts...")
        driver = create_browser(headless=True, profile_name="linkedin")
        try:
            url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}&origin=GLOBAL_SEARCH_HEADER"
            driver.get(url)
            time.sleep(5.0)
            html = driver.page_source
            seen = set()
            raw_links = re.findall(r'(https?://[^\s"\'<>]+)', html)
            for rl in raw_links:
                decoded = urllib.parse.unquote(rl.replace("&amp;", "&"))
                clean_url = decoded.split("#")[0].split("?")[0].rstrip("&.,;)")
                if clean_url in seen:
                    continue
                if any(d in clean_url for d in ["docs.google.com/forms", "forms.gle", "forms.office.com", "typeform.com", "jotform.com", "airtable.com"]):
                    seen.add(clean_url)
                    leads.append({
                        "source": "LinkedIn Post",
                        "company": company or "LinkedIn Recruiter",
                        "snippet": f"Found via LinkedIn Post: {skills}",
                        "link": clean_url,
                        "type": "Google Form" if "google" in clean_url or "forms.gle" in clean_url else "MS Form",
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
        finally:
            driver.quit()
    except Exception as e:
        log_fn(f"    [WARN] LinkedIn browser search skipped: {e}")

    log_fn(f"    LinkedIn Content Search: {len(leads)} links found")
    return leads


def _naukri_recruiter_search(skills: str, company: str, location: str, log_fn) -> list:
    """Check Naukri job posts for links to external forms."""
    leads = []
    try:
        import requests as _req
        kw = f"{company} {skills}".strip()
        url = (
            f"https://www.naukri.com/jobapi/v3/search?noOfResults=20&urlType=search_by_keyword"
            f"&searchType=adv&keyword={urllib_quote(kw)}&location={urllib_quote(location)}&pageNo=1&mode=o"
        )
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Appid": "109",
            "Systemid": "Naukri",
        }
        r = _req.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for j in data.get("jobDetails", []):
                desc = j.get("jobDescription", "")
                for pat in [r"https://docs\.google\.com/forms/[^\s\"'<>]+",
                             r"https://forms\.gle/[^\s\"'<>]+"]:
                    for m in re.finditer(pat, desc):
                        leads.append({
                            "source": "Naukri",
                            "company": j.get("companyName", company),
                            "snippet": desc[:100],
                            "link": m.group(0),
                            "type": "Google Form",
                            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        })
    except Exception as e:
        log_fn(f"    [WARN] Naukri recruiter search: {e}")
    log_fn(f"    Naukri recruiter: {len(leads)} form links")
    return leads


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(str(s))


def _save_leads(leads: list, company: str):
    """Save leads to both JSON and TXT for backward compatibility."""
    os.makedirs("logs", exist_ok=True)

    # Save to JSON (structured)
    json_path = "logs/recruiter_leads.json"
    existing = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Deduplicate by link
    existing_links = {e["link"] for e in existing}
    new_leads = [l for l in leads if l["link"] not in existing_links]
    all_leads = new_leads + existing  # newest first
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_leads[:500], f, ensure_ascii=False, indent=2)

    # Also append to TXT for backward compatibility
    txt_path = "logs/recruiter_leads.txt"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(txt_path, "a", encoding="utf-8") as f:
        for lead in new_leads:
            f.write(
                f"Date: {timestamp} | Company: {lead['company']} | "
                f"Post Text Snippet: {lead['snippet'][:100]} | "
                f"Links: ['{lead['link']}']\n"
            )
    return len(new_leads)


def run_recruiter_scraper_flow(company: str, skills: str, location: str, log_fn, stop_event):
    """
    Multi-source recruiter form lead scanner.
    Sources: Google Search + LinkedIn Content + Naukri (no browser login needed).
    """
    log_fn(f"\n[RECRUITER SCANNER] Company: {company or 'Any'} | Skills: {skills} | Location: {location}")
    log_fn("[RECRUITER SCANNER] Searching: Google → LinkedIn → Naukri (no browser needed)...")

    all_leads = []

    # Source 1: Google search (most reliable, no auth)
    if not stop_event.is_set():
        log_fn("  [1/3] Google Search for recruiter forms...")
        leads = _google_search_recruiter_forms(skills, company, location, log_fn)
        all_leads.extend(leads)

    # Source 2: LinkedIn content search
    if not stop_event.is_set():
        log_fn("  [2/3] LinkedIn content search...")
        leads = _linkedin_content_search(skills, company, location, log_fn)
        all_leads.extend(leads)

    # Source 3: Naukri job posts
    if not stop_event.is_set():
        log_fn("  [3/3] Naukri recruiter posts...")
        leads = _naukri_recruiter_search(skills, company, location, log_fn)
        all_leads.extend(leads)

    # Deduplicate
    seen = set()
    unique_leads = []
    for lead in all_leads:
        if lead["link"] not in seen:
            seen.add(lead["link"])
            unique_leads.append(lead)

    new_count = _save_leads(unique_leads, company)

    if unique_leads:
        log_fn(f"\n[OK] Found {len(unique_leads)} recruiter form links ({new_count} new).")
        log_fn("[OK] Check '📬 Recruiter Form Leads' panel — click links to apply directly!")
        for lead in unique_leads[:5]:
            log_fn(f"  🎯 [{lead['type']}] {lead['company']}: {lead['link'][:80]}")
    else:
        log_fn("[RECRUITER SCANNER] No recruiter forms found. Try broader skills or different location.")
        log_fn("  Tip: Try 'Data Engineer' as skills with city like 'Pune' for best results.")
