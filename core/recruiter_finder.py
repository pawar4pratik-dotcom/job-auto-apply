"""
core/recruiter_finder.py — Sourcing recruiter LinkedIn profiles and calculating business emails.
"""

import os
import re
import time
import urllib.request
import urllib.parse
import datetime

# Predefined company domains
_COMPANY_DOMAINS = {
    "barclays": "barclays.com",
    "pwc": "pwc.com",
    "pricewaterhousecoopers": "pwc.com",
    "bny mellon": "bnymellon.com",
    "bny": "bnymellon.com",
    "deutsche bank": "db.com",
    "mastercard": "mastercard.com",
    "jpmorgan": "jpmorgan.com",
    "jpmorgan chase": "jpmorgan.com",
    "jp morgan": "jpmorgan.com",
    "ubs": "ubs.com",
    "atlassian": "atlassian.com",
    "salesforce": "salesforce.com",
    "red hat": "redhat.com",
    "capgemini": "capgemini.com",
    "accenture": "accenture.com",
    "deloitte": "deloitte.com",
    "kpmg": "kpmg.com",
    "ey": "ey.com",
    "ernst & young": "ey.com",
    "cognizant": "cognizant.com",
    "tcs": "tcs.com",
    "tata consultancy services": "tcs.com",
    "infosys": "infosys.com",
    "wipro": "wipro.com",
}


def calculate_corporate_email(name: str, company: str) -> str:
    """
    Calculate a recruiter's business email based on their name and company.
    Defaults to first.last@companydomain.com.
    """
    if not name:
        return ""
    
    # 1. Resolve company domain
    comp_clean = re.sub(r"[^\w\s]", "", company.lower()).strip()
    domain = _COMPANY_DOMAINS.get(comp_clean)
    if not domain:
        # Check sub-strings
        for k, v in _COMPANY_DOMAINS.items():
            if k in comp_clean or comp_clean in k:
                domain = v
                break
    if not domain:
        # Default fallback
        domain_part = comp_clean.replace(" ", "")
        domain = f"{domain_part}.com"

    # 2. Clean name
    # Remove titles like Dr., AVP, VP, Senior, 2nd, etc.
    name_clean = name.replace("2nd", "").replace("1st", "").replace("3rd", "")
    name_clean = re.sub(r"\b(avp|vp|hr|talent|acquisition|lead|manager|head|recruiter|specialist)\b", "", name_clean, flags=re.IGNORECASE)
    name_clean = re.sub(r"[^\w\s\.-]", "", name_clean)
    parts = [p.strip().lower() for p in name_clean.split() if p.strip()]
    
    if not parts:
        return f"recruitment@{domain}"
    
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""
    
    if last:
        return f"{first}.{last}@{domain}"
    return f"{first}@{domain}"


def find_recruiters_online(company: str) -> list:
    """
    Scrape Google for LinkedIn recruiter profiles matching the company.
    Uses direct requests first, falling back to Selenium headless browser.
    """
    if not company:
        return []

    # Clean company name for the search query
    company_query = re.sub(r"[^\w\s]", "", company).strip()
    
    # Search query specifically targeting LinkedIn recruiter profiles in Pune / Mumbai / India
    query = f'site:linkedin.com/in/ "{company_query}" ("Talent Acquisition" OR "HR Recruiter" OR "Recruitment Specialist") ("Pune" OR "Mumbai" OR "India")'
    encoded = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={encoded}&num=15&hl=en"

    html = ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # 1. Try Direct HTTP Request
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[RECRUITER][WARN] Direct request failed: {e}. Trying Selenium fallback...")

    # 2. Fall back to Selenium if direct was blocked
    is_blocked = not html or "enablejs" in html or len(html) < 4000 or "unusual traffic" in html.lower()
    if is_blocked:
        try:
            from browser import create_browser
            print("[RECRUITER] Spawning headless browser for Google Search bypass...")
            driver = create_browser(headless=True, profile_name="default")
            try:
                driver.get(url)
                time.sleep(3.5)
                html = driver.page_source
            finally:
                driver.quit()
        except Exception as sel_err:
            print(f"[RECRUITER][ERROR] Headless browser lookup failed: {sel_err}")

    if not html:
        return []

    # 3. Parse LinkedIn URLs and Titles
    # Look for href="/url?q=https://www.linkedin.com/in/... or direct https://www.linkedin.com/in/...
    results = []
    seen_urls = set()

    # Google search result blocks are typically within structured anchor tags
    # Let's find h3 tags and parent anchors
    # A robust regex to find the blocks:
    # Match links containing linkedin.com/in/ and capture URL + text
    matches = re.findall(r'<a href="([^"]*?linkedin\.com/in/[^"]*?)".*?>(.*?)</a>', html, re.DOTALL)
    
    # Fallback to search results in mobile/simple layout
    if not matches:
        matches = re.findall(r'<a href="([^"]*?linkedin\.com/in/[^"]*?)">.*?<h3.*?>(.*?)</h3>', html, re.DOTALL)

    for href, raw_title in matches:
        # Clean URL
        url_clean = href.replace("&amp;", "&")
        if "/url?" in url_clean or "google.com/url?" in url_clean:
            parsed_query = urllib.parse.parse_qs(urllib.parse.urlparse(url_clean).query)
            if "q" in parsed_query:
                url_clean = parsed_query["q"][0]
        
        # Strip trailing markers
        url_clean = url_clean.split("#")[0].split("?")[0].rstrip("&.,;)")
        
        if not url_clean.startswith("https://www.linkedin.com/in/") or url_clean in seen_urls:
            continue

        # Clean title text
        title = re.sub(r"<[^>]*?>", "", raw_title).strip()
        title = title.replace(" - LinkedIn", "").replace(" | LinkedIn", "")
        
        if not title:
            continue

        seen_urls.add(url_clean)

        # Parse Name & Role from title
        # E.g., "Sowjanya Kondapalli - Talent Acquisition Specialist - Barclays"
        # Split by - or |
        parts = re.split(r"\s+[\-\|•]\s+", title)
        name = parts[0].strip() if parts else "Recruiter"
        role = parts[1].strip() if len(parts) > 1 else "Talent Acquisition / HR"
        
        # Clean up name if it has unwanted prefix/suffix
        name = re.sub(r"\s+\(.*\)", "", name) # remove bracketed details
        
        # Calculate email
        email = calculate_corporate_email(name, company)

        results.append({
            "name": name,
            "role": role,
            "linkedin": url_clean,
            "email": email
        })

    # If regex failed to align titles, let's harvest direct links and make a basic list
    if not results:
        direct_links = re.findall(r'https://www\.linkedin\.com/in/[a-zA-Z0-9\-_%]+', html)
        for dlink in direct_links:
            clean_d = dlink.split("?")[0].rstrip("&.,;)")
            if clean_d not in seen_urls:
                seen_urls.add(clean_d)
                # Parse name from profile URL slug
                slug = clean_d.split("/in/")[-1].replace("-", " ").title()
                name = re.sub(r'\d+', '', slug).strip() # strip digits
                email = calculate_corporate_email(name, company)
                results.append({
                    "name": name,
                    "role": "Talent Acquisition / HR Specialist",
                    "linkedin": clean_d,
                    "email": email
                })

    return results[:8]  # return top 8 matches
