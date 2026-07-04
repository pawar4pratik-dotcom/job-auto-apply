"""
tracker.py — Job application tracker.

Saves every application event to logs/job_applications.csv.
Also dual-writes to SQLite via core/database.py (additive, non-breaking).
Supports full FSM state: Applied → Viewed → Shortlisted → Interview → Offer / Rejected / Ghosted.
Provides read helpers for the dashboard API.

CSV columns (10):
  Date | Company | Role | Portal | URL | Status | Match % | Matched Skills | Skip Reason | Follow Up Date
"""

import csv
import os
import datetime
import threading

_csv_write_lock = threading.Lock()

# ── SQLite dual-write (safe import — never crashes if DB module is missing) ────
try:
    from core import database as _db
except Exception:
    _db = None

TRACKER_FILE = "logs/job_applications.csv"

HEADERS = [
    "Date",
    "Company",
    "Role",
    "Portal",
    "URL",
    "Status",
    "Match %",
    "Matched Skills",
    "Skip Reason",
    "Follow Up Date",
    "Posted Date",
    "Missing Skills",
    "Decision",
]

# Valid FSM states — used for status validation
VALID_STATUSES = [
    "Applied",
    "Viewed",
    "Shortlisted",
    "Interview",
    "Offer",
    "Rejected",
    "Ghosted",
    "Skipped",
    "Manual Needed",
    "Review",
    "Pending Apply",
]


def _tracker_path() -> str:
    """Always resolve path relative to this file's directory, regardless of cwd."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        import config.profile
        import importlib
        importlib.reload(config.profile)
        active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
        if active_profile and active_profile != "default":
            filename = f"logs/job_applications_{active_profile}.csv"
        else:
            filename = TRACKER_FILE
    except Exception:
        filename = TRACKER_FILE
        
    return os.path.join(script_dir, filename)


def _ensure_file(path: str) -> None:
    """Create the CSV file with headers if it does not exist."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADERS)


# ── Write ─────────────────────────────────────────────────────────────────────

def log_application(
    company: str,
    role: str,
    portal: str,
    url: str,
    status: str,
    score,
    matched_skills: list,
    skip_reason: str = "",
    posted_date: str = "",
    missing_skills: list = None,
    decision: str = ""
) -> None:
    """
    Append one application row to the CSV tracker.
    """
    path = _tracker_path()
    try:
        _ensure_file(path)
        follow_up = (datetime.datetime.now() + datetime.timedelta(days=5)).strftime("%Y-%m-%d")

        score_str = f"{score}%" if not str(score).endswith("%") else str(score)

        with _csv_write_lock:
            with open(path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    company or "Unknown",
                    role or "Unknown",
                    portal or "",
                    url or "",
                    status,
                    score_str,
                    ", ".join(matched_skills) if matched_skills else "",
                    skip_reason,
                    follow_up,
                    posted_date or "",
                    ", ".join(missing_skills) if missing_skills else "",
                    decision or ""
                ])

        # Console confirmation
        _print_logged(status, company, role, score, skip_reason)

        # ── SQLite dual-write (additive — never blocks the CSV path) ──────────
        try:
            if _db:
                _db.insert_application(
                    company=company or "Unknown",
                    role=role or "Unknown",
                    portal=portal or "",
                    url=url or "",
                    status=status,
                    match_pct=score_str,
                    matched_skills=", ".join(matched_skills) if matched_skills else "",
                    skip_reason=skip_reason,
                    posted_date=posted_date or "",
                    missing_skills=", ".join(missing_skills) if missing_skills else "",
                    decision=decision or "",
                )
        except Exception:
            pass  # DB failure never impacts CSV write

        # Trigger notifications for important states
        if status in ["Applied", "Manual Needed", "Review"]:
            subject = f"Job Bot: {status} - {role} at {company}"
            msg_body = (
                f"Job Hunt Bot Alert:\n"
                f"Status: {status}\n"
                f"Role: {role}\n"
                f"Company: {company}\n"
                f"Portal: {portal}\n"
                f"Match Score: {score_str}\n"
                f"URL: {url}\n"
            )
            if skip_reason:
                msg_body += f"Info: {skip_reason}\n"
            try:
                from core.notifier import send_alert
                send_alert(subject, msg_body)
            except Exception as ne:
                print(f"  [WARN] Failed to trigger notifier: {ne}")

    except Exception as e:
        print(f"  [ERROR] Failed to log application: {e}")


def _print_logged(status, company, role, score, skip_reason):
    icons = {"Applied": "✅", "Skipped": "⏭️", "Manual Needed": "⚠️", "Review": "⏳",
             "Interview": "🎯", "Offer": "🎉", "Rejected": "❌", "Ghosted": "👻", "Pending Apply": "🚀"}
    icon = icons.get(status, "📋")
    try:
        line = (f"  [LOGGED] {icon} {company} | {role} | {status} | Match: {score}%"
                + (f" | {skip_reason}" if skip_reason else ""))
        print(line)
    except UnicodeEncodeError:
        print(f"  [LOGGED] {status} | Match: {score}%")


def get_review_queue() -> list:
    """
    Return all jobs with Status == "Review", newest first.
    Includes list-expansion for matched/missing skills.
    """
    rows = get_all_rows()
    for r in rows:
        missing_str = r.get("Missing Skills", "")
        r["Missing"] = [s.strip() for s in missing_str.split(",") if s.strip()] if missing_str else []
        matched_str = r.get("Matched Skills", "")
        r["Matched"] = [s.strip() for s in matched_str.split(",") if s.strip()] if matched_str else []
        try:
            r["Score"] = float(r.get("Match %", "0").replace("%", "").strip())
        except ValueError:
            r["Score"] = 0.0
    return [r for r in rows if r.get("Status") == "Review"]


def approve_review_job(url: str) -> bool:
    """Advance a Review job to Pending Apply status."""
    return update_status(url, "Pending Apply")


def reject_review_job(url: str) -> bool:
    """Move a Review job to Skipped (human rejected)."""
    return update_status(url, "Skipped")



def update_status(url: str, new_status: str) -> bool:
    """
    Update the status of an existing application row (matched by URL).
    Used by email monitor to advance FSM state automatically.
    Returns True if a row was updated.
    """
    path = _tracker_path()
    if not os.path.exists(path):
        return False
    try:
        rows = []
        updated = False
        notif_data = None
        with _csv_write_lock:
            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("URL", "").strip() == url.strip():
                        row["Status"] = new_status
                        updated = True
                        notif_data = {
                            "company": row.get("Company", "Unknown"),
                            "role": row.get("Role", "Unknown"),
                            "portal": row.get("Portal", ""),
                            "score": row.get("Match %", "0%"),
                        }
                    rows.append(row)

            if updated:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=HEADERS)
                    writer.writeheader()
                    writer.writerows(rows)
                
            # Trigger notifications for status transitions
            if notif_data and new_status in ["Applied", "Manual Needed", "Review"]:
                try:
                    subject = f"Job Bot Status Update: {new_status} - {notif_data['role']} at {notif_data['company']}"
                    msg_body = (
                        f"Job Hunt Bot Alert:\n"
                        f"New Status: {new_status}\n"
                        f"Role: {notif_data['role']}\n"
                        f"Company: {notif_data['company']}\n"
                        f"Portal: {notif_data['portal']}\n"
                        f"Match Score: {notif_data['score']}\n"
                        f"URL: {url}\n"
                    )
                    from core.notifier import send_alert
                    send_alert(subject, msg_body)
                except Exception as ne:
                    print(f"  [WARN] Failed to trigger status transition notifier: {ne}")
                    
        # ── SQLite dual-write for status updates ─────────────────────────────
        if updated:
            try:
                if _db:
                    _db.update_status_by_url(url, new_status)
            except Exception:
                pass  # DB failure never impacts CSV write

        return updated
    except Exception as e:
        print(f"  [ERROR] update_status failed: {e}")
        return False


# ── Read ──────────────────────────────────────────────────────────────────────

def get_today_count(status_filter: str = None) -> int:
    """
    Return number of applications logged today.
    Pass status_filter="Applied" to count only applied, etc.
    """
    path = _tracker_path()
    if not os.path.exists(path):
        return 0
    today = datetime.date.today().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("Date", "").startswith(today):
                    continue
                if status_filter is None or row.get("Status") == status_filter:
                    count += 1
    except Exception:
        pass
    return count


def get_all_rows() -> list:
    """Return all rows as list-of-dicts, newest first."""
    path = _tracker_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return list(reversed(rows))
    except Exception:
        return []


def get_rows_by_status(status: str) -> list:
    """Return all rows matching a specific status, newest first."""
    return [r for r in get_all_rows() if r.get("Status") == status]


def get_fsm_summary() -> dict:
    """
    Return a count per FSM state — used by dashboard Kanban and analytics.
    Example: {"Applied": 12, "Interview": 3, "Offer": 1, ...}
    """
    summary = {s: 0 for s in VALID_STATUSES}
    for row in get_all_rows():
        s = row.get("Status", "")
        if s in summary:
            summary[s] += 1
    return summary


def get_today_summary() -> dict:
    """Return applied/skipped/manual counts for today only."""
    return {
        "applied":  get_today_count("Applied"),
        "skipped":  get_today_count("Skipped"),
        "manual":   get_today_count("Manual Needed"),
        "total":    get_today_count(),
    }


def print_summary() -> None:
    """Print a formatted table of today's applications to console."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    rows = [r for r in get_all_rows() if r.get("Date", "").startswith(today)]
    print(f"\n{'='*70}")
    print(f"  TODAY'S APPLICATIONS ({today}) — {len(rows)} total")
    print(f"{'='*70}")
    for r in rows:
        reason = f" [{r.get('Skip Reason', '')}]" if r.get("Skip Reason") else ""
        print(f"  {r['Status']:<14} | {r['Company']:<22} | {r['Role']:<30} | {r['Portal']}{reason}")
    print(f"{'='*70}\n")


def ghosted_check(days: int = 21) -> list:
    """
    Return applications that have been in 'Applied' state for more than
    `days` days with no status update — candidates for Ghosted marking.
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    ghosts = []
    for row in get_all_rows():
        if row.get("Status") != "Applied":
            continue
        try:
            applied_date = datetime.datetime.strptime(row["Date"], "%Y-%m-%d %H:%M")
            if applied_date < cutoff:
                ghosts.append(row)
        except Exception:
            pass
    return ghosts


def run_ghosted_check() -> None:
    """Auto-advance stale 'Applied' rows to 'Ghosted' after 21 days."""
    path = _tracker_path()
    if not os.path.exists(path):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=21)
    updated = 0
    try:
        rows = []
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("Status") == "Applied":
                    try:
                        applied_date = datetime.datetime.strptime(row["Date"], "%Y-%m-%d %H:%M")
                        if applied_date < cutoff:
                            row["Status"] = "Ghosted"
                            updated += 1
                    except Exception:
                        pass
                rows.append(row)
        if updated:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            print(f"[GHOSTED] Auto-marked {updated} stale applications as Ghosted.")
    except Exception as e:
        print(f"[ERROR] ghosted_check failed: {e}")


def clear_non_applied_from_csv():
    """
    Remove all 'Skipped', 'Review', and 'Manual Needed' entries from the CSV log 
    for the active profile, keeping only actual 'Applied' entries.
    This ensures that the dashboard stats are reset properly when retrying.
    """
    path = _tracker_path()
    if not os.path.exists(path):
        return
    import csv
    try:
        rows = []
        with _csv_write_lock:
            with open(path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get("Status", "")
                    if status not in ["Skipped", "Review", "Manual Needed"]:
                        rows.append(row)
            
            with open(path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
                writer.writerows(rows)
    except Exception as e:
        print(f"  [ERROR] clear_non_applied_from_csv failed: {e}")
