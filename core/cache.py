import time

_cache = {}

def get_scored(url: str):
    """Retrieve cached scoring entry if not expired (30 min TTL)."""
    entry = _cache.get(url)
    if entry and time.time() - entry["ts"] < 1800:
        return entry["data"]
    return None

def set_scored(url: str, data: dict):
    """Store scoring result in cache with current timestamp."""
    _cache[url] = {"ts": time.time(), "data": data}

def clear_cache():
    """Clear all cached scoring decisions and keep only actual Applied status in history."""
    _cache.clear()
    try:
        restore_applied_only()
    except Exception:
        pass
    try:
        from tracker import clear_non_applied_from_csv
        clear_non_applied_from_csv()
    except Exception:
        pass

def restore_applied_only():
    """
    Overwrites applied_linkedin and applied_naukri text files to contain ONLY 
    job IDs that were successfully applied (Status == 'Applied') in the CSV log.
    """
    import csv
    import os
    import re
    import config.profile
    
    script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    profile_name = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
    
    csv_filename = f"logs/job_applications_{profile_name}.csv" if profile_name != "default" else "logs/job_applications.csv"
    csv_path = os.path.join(script_dir, csv_filename)
        
    if not os.path.exists(csv_path):
        return
        
    applied_ids = set()
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for r in reader:
                if len(r) >= 6:
                    status = r[5]
                    url = r[4]
                    if status.lower() == "applied" and url:
                        m = re.search(r'(\d{9,12})', url)
                        if m:
                            applied_ids.add(m.group(1))
    except Exception:
        return

    for portal in ["linkedin", "naukri"]:
        applied_filename = f"logs/applied_{portal}_{profile_name}.txt" if profile_name != "default" else f"logs/applied_{portal}.txt"
        path = os.path.join(script_dir, applied_filename)
            
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current_ids = set(line.strip() for line in f if line.strip())
                new_ids = current_ids.intersection(applied_ids)
                with open(path, "w", encoding="utf-8") as f:
                    for jid in new_ids:
                        f.write(f"{jid}\n")
            except Exception:
                pass

        # Clean skipped cache files on retry
        skip_filename = f"logs/skipped_{portal}_{profile_name}.txt" if profile_name != "default" else f"logs/skipped_{portal}.txt"
        skip_path = os.path.join(script_dir, skip_filename)
        if os.path.exists(skip_path):
            try:
                os.remove(skip_path)
            except Exception:
                pass
