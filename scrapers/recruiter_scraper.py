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


def _google_search_recruiter_forms(skills_list: list, company: str, loc_list: list, log_fn) -> list:
    """Search Google for HR recruiter form links using direct HTTPS query with Selenium headless fallback."""
    leads = []
    import urllib.request, urllib.parse, re
    
    skills_part = " OR ".join(skills_list)
    if len(skills_list) > 1:
        skills_part = f"({skills_part})"

    loc_part = " OR ".join(loc_list)
    if len(loc_list) > 1:
        loc_part = f"({loc_part})"

    company_part = f'"{company}" ' if company else ""
    form_sites = "site:docs.google.com/forms OR site:forms.gle OR site:forms.office.com OR site:typeform.com OR site:jotform.com OR site:airtable.com"
    
    if company:
        query = f'{company_part}{skills_part} {loc_part} "apply" ({form_sites})'
    else:
        query = f'{skills_part} {loc_part} "hiring" "apply" ({form_sites})'
        
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
                    "snippet": f"Found via Google Search: {', '.join(skills_list)} {', '.join(loc_list)}",
                    "link": clean_url,
                    "type": form_type,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                
    log_fn(f"    Google Search: {len(leads)} form links found")

    # Fallback: DuckDuckGo HTML search (doesn't block bots)
    if not leads:
        try:
            ddg_query = f"{company_part}{skills_part} {loc_part} hiring apply (site:docs.google.com/forms OR site:forms.gle OR site:forms.office.com)"
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
                        "snippet": f"Found via DuckDuckGo: {', '.join(skills_list)} {', '.join(loc_list)}",
                        "link": clean_url,
                        "type": "Google Form" if "google" in clean_url or "forms.gle" in clean_url else "MS Form",
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
            log_fn(f"    DuckDuckGo fallback: {len(leads)} form links found")
        except Exception as ddg_err:
            log_fn(f"    [WARN] DuckDuckGo fallback: {ddg_err}")

    return leads


def _resolve_shortener(url: str) -> str:
    """Resolve shortened URLs (like lnkd.in, bit.ly, t.co, tinyurl.com) to find original forms."""
    shorteners = ["lnkd.in", "bit.ly", "t.co", "tinyurl.com", "shorturl.at"]
    if not any(s in url for s in shorteners):
        return url
    try:
        import requests as _req
        from bs4 import BeautifulSoup
        
        r = _req.get(url, allow_redirects=True, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        # If we got redirected directly
        if "lnkd.in" not in r.url:
            return r.url
            
        # Parse the interstitial page
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if href and "linkedin.com/help" not in href and "linkedin.com/legal" not in href:
                return href
        return r.url
    except Exception:
        return url


def _is_valid_external_job_link(url: str) -> bool:
    """Check if the resolved link is a valid external job application or form link."""
    if not url:
        return False
    # Must be an absolute URL starting with http/https
    if not url.startswith(("http://", "https://")):
        return False
    url_lower = url.lower()
    
    # Exclude internal LinkedIn URLs and non-application targets
    exclusions = [
        "linkedin.com/in/",           # Profile links
        "linkedin.com/safety/go",     # Warning interstitial
        "linkedin.com/help",          # Help center
        "linkedin.com/legal",         # Legal terms
        "linkedin.com/search/results",# Search lists
        "linkedin.com/feed",          # Feed items
        "mailto:",                    # Emails are parsed separately
        "javascript:",                # Script anchors
        "tel:",                       # Phone numbers
    ]
    if any(e in url_lower for e in exclusions):
        return False
        
    return True


def _extract_leads_from_html(html: str, company: str, seen: set, loc_list: list = None) -> list:
    """Helper to extract recruiter form leads from LinkedIn content HTML with recruiter headline and remote-tolerant location filtering."""
    from bs4 import BeautifulSoup
    import re
    import urllib.parse
    import datetime
    
    # Parse target companies list
    company_list = [c.strip() for c in company.split(",") if c.strip()]
    if any(c.lower() in ("any", "all", "none", "null", "undefined", "") for c in company_list):
        company_list = []
        
    soup = BeautifulSoup(html, "html.parser")
    leads = []
    
    # Find all profile links on the page
    profile_links = []
    seen_hrefs = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href")
        if "/in/" in href and href not in seen_hrefs:
            profile_links.append(a_tag)
            seen_hrefs.add(href)
            
    processed_cards = set()
    recruiter_keywords = [
        "talent acquisition", "recruiter", "human capital", 
        "talent acquisition specialist", "hr manager", "hr executive", 
        "senior executive- talent acquisition", "human resources", 
        "talent partner", "headhunter", "head of hr", "hr generalist"
    ]
    
    for a_tag in profile_links:
        # Trace up to find card container (class-agnostic DOM traversal)
        card = None
        current = a_tag
        prev_text = " ".join(current.get_text().split())
        prev_len = len(prev_text)
        
        for depth in range(8):
            parent = current.parent
            if not parent:
                break
            parent_text = " ".join(parent.get_text().split())
            parent_len = len(parent_text)
            if parent.name == "div" and parent_len > prev_len + 150:
                card = parent
                break
            current = parent
            prev_len = parent_len
            
        if not card:
            continue
            
        card_text = " ".join(card.get_text().split())
        if card_text in processed_cards:
            continue
        processed_cards.add(card_text)
        
        # Filter 1: Check if poster headline contains recruiter keywords
        headline_area = card_text[:300].lower()
        is_recruiter = any(kw in headline_area for kw in recruiter_keywords)
        if not is_recruiter:
            continue
            
        # Filter 2: If company list is specified, check if poster headline contains target companies or their aliases
        if company_list:
            has_company = False
            for comp in company_list:
                comp_lower = comp.lower()
                aliases = [comp_lower]
                if comp_lower == "ey":
                    aliases.extend(["ernst & young", "ernst and young"])
                elif comp_lower == "pwc":
                    aliases.append("pricewaterhousecoopers")
                elif comp_lower == "deloitte":
                    aliases.append("deilite")
                elif comp_lower == "deilite":
                    aliases.extend(["deloitte", "deilite"])
                    
                if any(alias in headline_area for alias in aliases):
                    has_company = True
                    break
            if not has_company:
                continue
                
        # Filter 3: Check if post text contains any of the user's locations or remote keywords
        if loc_list:
            locs_clean = [l.lower() for l in loc_list if l.lower() not in ("any", "all", "none", "")]
            if locs_clean:
                has_location = False
                target_keywords = locs_clean + ["remote", "wfh", "work from home", "pan india"]
                for kw in target_keywords:
                    aliases = [kw]
                    if kw == "bengaluru":
                        aliases.append("bangalore")
                    elif kw == "bangalore":
                        aliases.append("bengaluru")
                    if any(alias in card_text.lower() for alias in aliases):
                        has_location = True
                        break
                if not has_location:
                    continue
            
        # Extract and resolve links from this card container
        card_links = [lk.get('href') for lk in card.find_all('a', href=True)]
        card_text_links = re.findall(r'(https?://[^\s"\'<>]+)', card_text)
        card_shortener_links = re.findall(r'https?://lnkd\.in/[a-zA-Z0-9_-]+', card_text)
        
        all_card_links = set(card_links + card_text_links + card_shortener_links)
        for rl in all_card_links:
            decoded = urllib.parse.unquote(rl.replace("&amp;", "&"))
            clean_url = decoded.split("#")[0].split("?")[0].rstrip("&.,;)")
            
            clean_url = _resolve_shortener(clean_url)
            if clean_url in seen:
                continue
                
            if _is_valid_external_job_link(clean_url):
                seen.add(clean_url)
                
                # Classify lead type
                lead_type = "Job Link"
                if any(d in clean_url.lower() for d in ["docs.google.com/forms", "forms.gle"]):
                    lead_type = "Google Form"
                elif "forms.office.com" in clean_url.lower():
                    lead_type = "MS Form"
                elif any(d in clean_url.lower() for d in ["workday", "greenhouse.io", "lever.co", "taleo", "icims"]):
                    lead_type = "ATS Portal"
                elif any(d in clean_url.lower() for d in ["typeform.com", "jotform.com", "airtable.com"]):
                    lead_type = "Form Link"
                elif "linkedin.com/jobs/view" in clean_url.lower():
                    lead_type = "LinkedIn Job"
                    
                leads.append({
                    "source": "LinkedIn Post",
                    "company": company or "LinkedIn Recruiter",
                    "snippet": card_text[:200],
                    "link": clean_url,
                    "type": lead_type,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                
        # Extract recruiter email addresses from this card
        card_emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', card_text)
        for email in card_emails:
            # Skip generic platform/system emails
            if any(generic in email.lower() for generic in ["support@", "noreply@", "no-reply@", "jobs-listings@", "help@", "privacy@"]):
                continue
            mailto_link = f"mailto:{email}"
            if mailto_link in seen:
                continue
            seen.add(mailto_link)
            leads.append({
                "source": "LinkedIn Post",
                "company": company or "LinkedIn Recruiter",
                "snippet": card_text[:200],
                "link": mailto_link,
                "type": "Email Lead",
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
    return leads


def _linkedin_content_search(skills_list: list, company: str, loc_list: list, log_fn) -> list:
    """Search LinkedIn content for recruiter posts - HTTP first, Selenium fallback."""
    leads = []
    seen = set()
    
    # 1. Parse target companies list
    company_list = [c.strip() for c in company.split(",") if c.strip()]
    if any(c.lower() in ("any", "all", "none", "null", "undefined", "") for c in company_list) or not company_list:
        company_list = [""]
        
    # 2. Generate location-agnostic company * skill combinations to maximize matching volume
    combos = []
    for comp in company_list[:3]: # Limit to top 3 companies
        for skill in skills_list[:2]: # Limit to top 2 skills
            combos.append((comp, skill))
            
    # Try HTTP first (no browser needed)
    for comp, skill in combos:
        # Search query format: "PwC "Data Engineer" hiring" (covers all locations in one page)
        query = f"{comp + ' ' if comp else ''}\"{skill}\" hiring"
        encoded = urllib.parse.quote(query)
        try:
            import requests as _req
            url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            }
            r = _req.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                http_leads = _extract_leads_from_html(r.text, company, seen, loc_list)
                leads.extend(http_leads)
        except Exception:
            pass

    # Selenium fallback (always run if HTTP found nothing or to expand results)
    try:
        from browser import create_browser
        from linkedin_bot import login, is_logged_in
        log_fn("    Launching LinkedIn browser session to scan posts...")
        driver = create_browser(headless=True, profile_name="linkedin")
        try:
            if not is_logged_in(driver):
                log_fn("    [INFO] Not logged in to LinkedIn. Running login flow...")
                login(driver, log_fn=log_fn)
                
            for comp, skill in combos[:6]: # Scan top 6 combos in browser
                query = f"{comp + ' ' if comp else ''}\"{skill}\" hiring"
                encoded = urllib.parse.quote(query)
                url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}&origin=GLOBAL_SEARCH_HEADER"
                driver.get(url)
                time.sleep(4.0)
                
                # Scroll down 4 times to load a large batch of dynamic posts
                for scroll in range(4):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2.0)
                    
                html = driver.page_source
                sel_leads = _extract_leads_from_html(html, company, seen, loc_list)
                leads.extend(sel_leads)
        finally:
            driver.quit()
    except Exception as e:
        log_fn(f"    [WARN] LinkedIn browser search skipped: {e}")

    log_fn(f"    LinkedIn Content Search: {len(leads)} links found")
    return leads


def _naukri_recruiter_search(skills_list: list, company: str, loc_list: list, log_fn) -> list:
    """Check Naukri job posts for links to external forms."""
    leads = []
    try:
        import requests as _req
        kw = f"{company + ' ' if company else ''}{' '.join(skills_list[:2])}".strip()
        loc = loc_list[0] if loc_list else ""
        url = (
            f"https://www.naukri.com/jobapi/v3/search?noOfResults=20&urlType=search_by_keyword"
            f"&searchType=adv&keyword={urllib_quote(kw)}&location={urllib_quote(loc)}&pageNo=1&mode=o"
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
    # 1. Normalize company wildcard
    norm_company = company.strip()
    if norm_company.lower() in ("any", "all", "none", "null", "undefined", ""):
        norm_company = ""

    # 2. Parse comma-separated skills
    skills_list = [s.strip() for s in skills.split(",") if s.strip()]
    if not skills_list:
        skills_list = ["Data Engineer"]

    # 3. Parse comma-separated locations
    loc_list = [l.strip() for l in location.split(",") if l.strip()]
    if not loc_list:
        loc_list = ["Remote"]

    log_fn(f"\n[RECRUITER SCANNER] Company: {company or 'Any'} | Skills: {', '.join(skills_list)} | Location: {', '.join(loc_list)}")
    log_fn("[RECRUITER SCANNER] Searching: Google → LinkedIn → Naukri (no browser needed)...")

    all_leads = []

    # Source 1: Google search (most reliable, no auth)
    if not stop_event.is_set():
        log_fn("  [1/3] Google Search for recruiter forms...")
        leads = _google_search_recruiter_forms(skills_list, norm_company, loc_list, log_fn)
        all_leads.extend(leads)

    # Source 2: LinkedIn content search
    if not stop_event.is_set():
        log_fn("  [2/3] LinkedIn content search...")
        leads = _linkedin_content_search(skills_list, norm_company, loc_list, log_fn)
        all_leads.extend(leads)

    # Source 3: Naukri job posts
    if not stop_event.is_set():
        log_fn("  [3/3] Naukri recruiter posts...")
        leads = _naukri_recruiter_search(skills_list, norm_company, loc_list, log_fn)
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
