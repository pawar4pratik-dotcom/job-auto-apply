"""
Test PwC real site IDs from robots.txt and find India Data Engineer jobs, then apply.
"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
import requests
import time
from browser import create_browser
from careers_bot import apply_workday

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Referer": "https://pwc.wd3.myworkdayjobs.com/",
}

# Real site IDs from robots.txt (captured earlier)
SITE_IDS = [
    "Global_Campus_Careers",
    "Catalyst",
    "Global_Experienced_Careers",
    "Global_Strategyand_Careers",
    "Acquisition",
    "US_Entry_Level_Careers",
    "US_Experienced_Careers",
]

payload = {"appliedFacets": {}, "limit": 10, "offset": 0, "searchText": "Data Engineer"}

print("=" * 65)
print(" PwC WORKDAY — REAL SITE IDs JOB SEARCH")
print("=" * 65)

all_jobs = []

for site in SITE_IDS:
    url = f"https://pwc.wd3.myworkdayjobs.com/wday/cxs/pwc/{site}/jobs"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            jobs = d.get("jobPostings", [])
            print(f"\nSITE: {site} => {len(jobs)} Data Engineer jobs found!")
            for j in jobs:
                title = j.get("title", "")
                path = j.get("externalPath", "")
                locs = j.get("locationsText", "")
                if isinstance(locs, str):
                    loc_str = locs
                elif isinstance(locs, list) and locs:
                    if isinstance(locs[0], dict):
                        loc_str = ", ".join([l.get("descriptor", "") for l in locs])
                    else:
                        loc_str = ", ".join([str(l) for l in locs])
                else:
                    loc_str = str(locs)
                full_url = f"https://pwc.wd3.myworkdayjobs.com/en-US/{site}{path}"
                print(f"  [{loc_str}] {title}")
                print(f"   => {full_url}")
                all_jobs.append({
                    "title": title,
                    "url": full_url,
                    "location": loc_str,
                    "site": site
                })
        else:
            try:
                msg = r.json().get("message", "")[:80]
            except Exception:
                msg = r.text[:60]
            print(f"FAIL [{r.status_code}]: {site} => {msg}")
    except Exception as e:
        print(f"ERROR: {site} => {e}")

print(f"\n\nTotal jobs found: {len(all_jobs)}")

# Find India/Asia jobs
india_jobs = [j for j in all_jobs if any(
    kw in j.get("location", "").lower()
    for kw in ["india", "bangalore", "bengaluru", "mumbai", "pune", "hyderabad", "delhi", "gurugram", "noida", "kolkata"]
)]
print(f"India-specific jobs: {len(india_jobs)}")

# Pick best match
target_job = None
if india_jobs:
    target_job = india_jobs[0]
elif all_jobs:
    target_job = all_jobs[0]

if not target_job:
    print("\nNo jobs found via API. Cannot proceed.")
else:
    print(f"\n TARGET SELECTED:")
    print(f"  Title    : {target_job['title']}")
    print(f"  Location : {target_job['location']}")
    print(f"  URL      : {target_job['url']}")

    print(f"\nOpening browser to apply...")
    driver = create_browser(headless=False, profile_name="pwc_apply")
    try:
        result = apply_workday(driver, target_job["url"], company="PwC", role=target_job["title"])
        print(f"\n[RESULT] Application Result: {result}")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        print("Keeping browser open 30s...")
        time.sleep(30)
        driver.quit()
