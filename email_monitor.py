"""
email_monitor.py — IMAP email watcher that auto-advances the job application FSM.

Polls inbox every 5 minutes, matches email subjects/bodies against applied companies,
and calls tracker.update_status() to advance FSM state automatically.
Also reads company list from SQLite (via core/database.py) when available.

Setup: add IMAP credentials to config/profile.py:
  IMAP_HOST     = "imap.gmail.com"
  IMAP_EMAIL    = "your@gmail.com"
  IMAP_PASSWORD = "your-app-password"   # Use Gmail App Password, not real password
"""

import imaplib
import email
import re
import time
import threading
import datetime
import csv
import os

# ── SQLite dual-read (safe import) ───────────────────────────────────────
try:
    from core import database as _db
except Exception:
    _db = None

_STOP = threading.Event()
_monitor_thread = None

# ── Keyword patterns → FSM state ─────────────────────────────────────────────
EMAIL_PATTERNS = [
    # Interview signals
    (re.compile(r"interview|schedule a call|meet with|hiring manager|talent acquisition|discussion round", re.I), "Interview"),
    # Shortlist signals
    (re.compile(r"shortlist|short.?listed|moved forward|next round|assessment|test link", re.I),           "Shortlisted"),
    # Offer signals
    (re.compile(r"offer letter|job offer|congratulations.*offer|pleased to offer|compensation details", re.I), "Offer"),
    # Rejection signals
    (re.compile(r"not moving forward|unfortunately|regret to inform|not selected|other candidate|other applicants", re.I), "Rejected"),
    # Viewed / acknowledgement signals
    (re.compile(r"application received|thank you for applying|we received your application|acknowledg", re.I), "Viewed"),
]

def _load_applied_companies() -> list:
    """
    Return list of rows currently in 'Applied', 'Viewed', or 'Shortlisted' state.
    Tries SQLite first (faster, lock-free), falls back to CSV read.
    """
    # ── Try SQLite first ───────────────────────────────────────────────
    try:
        if _db:
            rows = _db.get_applied_companies()
            if rows:
                # Normalize keys to match CSV-style dict keys used downstream
                return [{"Company": r["company"], "URL": r["url"],
                         "Status": "Applied"} for r in rows]
    except Exception:
        pass

    # ── Fallback: CSV read ───────────────────────────────────────────────
    tracker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "job_applications.csv")
    if not os.path.exists(tracker_path):
        return []
    rows = []
    try:
        with open(tracker_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Status") in ("Applied", "Viewed", "Shortlisted", "Pending Apply"):
                    rows.append(row)
    except Exception:
        pass
    return rows

def _classify_email(subject: str, body: str) -> str | None:
    """Return FSM status string if email matches a known pattern, else None."""
    text = f"{subject} {body}"
    for pattern, status in EMAIL_PATTERNS:
        if pattern.search(text):
            return status
    return None

def _match_company_in_email(subject: str, body: str, applied_rows: list) -> list:
    """Return list of matching (url, new_status, company) tuples."""
    matches = []
    new_status = _classify_email(subject, body)
    if not new_status:
        return matches
    text_lower = f"{subject} {body}".lower()
    for row in applied_rows:
        company = (row.get("Company") or "").lower().strip()
        if company and len(company) > 2:
            # Enforce word boundaries for company name matching to avoid substrings matches
            # e.g. "amgen" shouldn't match "amgenta", "wipro" shouldn't match "wiproject"
            pattern = r"\b" + re.escape(company) + r"\b"
            if re.search(pattern, text_lower):
                matches.append((row.get("URL", ""), new_status, row.get("Company")))
    return matches

def poll_inbox(log_fn=print) -> int:
    """Connect to IMAP, scan unseen emails, update FSM. Returns count of updates."""
    import importlib
    import config.profile
    importlib.reload(config.profile)

    host     = getattr(config.profile, "IMAP_HOST",     "imap.gmail.com")
    email_   = getattr(config.profile, "IMAP_EMAIL",    "")
    password = getattr(config.profile, "IMAP_PASSWORD", "")

    if not email_ or not password:
        # Silently skip if credentials not filled in
        return 0

    updates = 0
    try:
        mail = imaplib.IMAP4_SSL(host, timeout=15)
        mail.login(email_, password)
        mail.select("INBOX")

        # Search unseen emails from last 30 days
        since_date = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%d-%b-%Y")
        _, msg_ids = mail.search(None, f'(UNSEEN SINCE {since_date})')
        ids = msg_ids[0].split()

        if not ids:
            mail.logout()
            return 0

        applied_rows = _load_applied_companies()
        if not applied_rows:
            mail.logout()
            return 0

        from tracker import update_status

        for msg_id in ids[-50:]:   # Cap at 50 per poll cycle
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                subject = msg.get("Subject", "")
                
                # Fetch clean header text
                from email.header import decode_header
                decoded_subject = ""
                for part, encoding in decode_header(subject):
                    if isinstance(part, bytes):
                        decoded_subject += part.decode(encoding or "utf-8", errors="replace")
                    else:
                        decoded_subject += part
                subject = decoded_subject
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            except Exception:
                                pass
                else:
                    try:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                matches = _match_company_in_email(subject, body, applied_rows)
                for url, new_status, company in matches:
                    if url:
                        updated = update_status(url, new_status)
                        if updated:
                            log_fn(f"  [EMAIL WATCH] Advanced: {company} status updated to {new_status} (Subject: {subject[:50]}...)")
                            updates += 1
            except Exception as e:
                # Log fetch warning
                pass

        mail.logout()
    except Exception as e:
        # Quiet connection errors
        pass

    return updates

def _monitor_loop(interval_minutes: int = 5, log_fn=print):
    log_fn(f"[EMAIL] IMAP email monitor thread active (polling every {interval_minutes}m)...")
    while not _STOP.is_set():
        try:
            poll_inbox(log_fn=log_fn)
        except Exception as e:
            pass
        _STOP.wait(interval_minutes * 60)

def start_monitor(interval_minutes: int = 5, log_fn=print) -> bool:
    global _monitor_thread, _STOP
    if _monitor_thread and _monitor_thread.is_alive():
        return False
    _STOP.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(interval_minutes, log_fn),
        daemon=True,
    )
    _monitor_thread.start()
    return True

def stop_monitor():
    global _STOP
    _STOP.set()
