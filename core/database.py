"""
core/database.py — SQLite application tracker backend.

Safety design:
  - Uses only Python's built-in `sqlite3` — no extra pip installs required.
  - All writes are wrapped in try/except so failures never crash the bot.
  - On first run, auto-imports ALL historical rows from the existing CSV file.
  - Every write is also mirrored back to CSV by tracker.py (dual-write safety).

Tables:
  applications  — mirrors job_applications.csv columns exactly
  qa_bank       — mirrors qa_store.json entries
"""

import sqlite3
import os
import csv
import threading
import datetime

_DB_LOCK = threading.Lock()

# Resolve DB path relative to the project root (one level up from core/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_ROOT, "logs", "job_applications.db")

_CSV_HEADERS = [
    "Date", "Company", "Role", "Portal", "URL", "Status",
    "Match %", "Matched Skills", "Skip Reason", "Follow Up Date",
    "Posted Date", "Missing Skills", "Decision",
]


def _get_conn():
    """Return a thread-local SQLite connection with WAL mode for concurrency."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # WAL = no read/write locks
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_tables(conn):
    """Create tables if they don't exist yet."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            date          TEXT,
            company       TEXT,
            role          TEXT,
            portal        TEXT,
            url           TEXT,
            status        TEXT,
            match_pct     TEXT,
            matched_skills TEXT,
            skip_reason   TEXT,
            follow_up_date TEXT,
            posted_date   TEXT,
            missing_skills TEXT,
            decision      TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qa_bank (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            answer   TEXT,
            portal   TEXT,
            updated  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recruiters (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            company    TEXT,
            name       TEXT,
            role       TEXT,
            linkedin   TEXT,
            email      TEXT,
            created_at TEXT
        )
    """)
    # Index for fast company/status lookups
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status      ON applications(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company     ON applications(company)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_url         ON applications(url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_company ON recruiters(company)")
    conn.commit()


def _import_csv_if_empty(conn):
    """
    On first launch, seed the SQLite DB from the existing CSV file.
    Only runs when the applications table is empty to avoid duplicates.
    """
    try:
        count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        if count > 0:
            return  # DB already has data — skip import

        # Find active CSV path (mirrors tracker.py profile logic)
        try:
            import config.profile
            import importlib
            importlib.reload(config.profile)
            active_profile = getattr(config.profile, "ACTIVE_PROFILE_NAME", "default")
            if active_profile and active_profile != "default":
                csv_name = f"logs/job_applications_{active_profile}.csv"
            else:
                csv_name = "logs/job_applications.csv"
        except Exception:
            csv_name = "logs/job_applications.csv"

        csv_path = os.path.join(_PROJECT_ROOT, csv_name)
        if not os.path.exists(csv_path):
            return

        imported = 0
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conn.execute("""
                    INSERT INTO applications
                    (date, company, role, portal, url, status, match_pct,
                     matched_skills, skip_reason, follow_up_date, posted_date,
                     missing_skills, decision)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    row.get("Date", ""),
                    row.get("Company", ""),
                    row.get("Role", ""),
                    row.get("Portal", ""),
                    row.get("URL", ""),
                    row.get("Status", ""),
                    row.get("Match %", ""),
                    row.get("Matched Skills", ""),
                    row.get("Skip Reason", ""),
                    row.get("Follow Up Date", ""),
                    row.get("Posted Date", ""),
                    row.get("Missing Skills", ""),
                    row.get("Decision", ""),
                ))
                imported += 1
        conn.commit()
        if imported:
            print(f"[DB] Seeded SQLite from CSV: {imported} historical rows imported.")
    except Exception as e:
        print(f"[DB][WARN] CSV import skipped: {e}")


def _seed_recruiters_if_empty(conn):
    """Seed the recruiters table with pre-compiled recruiter records if empty."""
    try:
        count = conn.execute("SELECT COUNT(*) FROM recruiters").fetchone()[0]
        if count > 0:
            return
        
        pre_seeded = [
            # Barclays
            ("Barclays", "Sowjanya Kondapalli", "Talent Acquisition", "https://www.linkedin.com/in/sowjanya-kondapalli-45a68084/", "sowjanya.kondapalli@barclays.com"),
            ("Barclays", "Anu Shree", "Assistant Manager Tech Hiring", "https://www.linkedin.com/in/anu-shree/", "anu.shree@barclays.com"),
            ("Barclays", "Pallavi Vasava", "Talent Acquisition", "https://www.linkedin.com/in/pallavi-vasava-2b379ab/", "pallavi.vasava@barclays.com"),
            # BNY Mellon
            ("BNY Mellon", "Sumet Yeotekar", "Talent Acquisition", "https://www.linkedin.com/in/sumetyeotekar1995/", "sumet.yeotekar@bnymellon.com"),
            ("BNY Mellon", "Shahista Shaikh", "Talent Acquisition Consultant", "https://www.linkedin.com/in/shahista-shaikh-45192a13/", "shahista.shaikh@bnymellon.com"),
            # Deutsche Bank
            ("Deutsche Bank", "Advait Syamsunder", "Sr Talent Acquisition Analyst", "https://www.linkedin.com/in/advait-syamsunder/", "advait.syamsunder@db.com"),
            ("Deutsche Bank", "Shilpa Roy", "Talent Acquisition Specialist", "https://www.linkedin.com/in/shilpa-roy-b8212b110/", "shilpa.roy@db.com"),
            ("Deutsche Bank", "Priyanshi Malviya", "Assistant Manager Talent Acquisition", "https://www.linkedin.com/in/priyanshi-malviya-004531168/", "priyanshi.malviya@db.com"),
            # Mastercard
            ("Mastercard", "Vidhi Sarvaiya", "Tech & Cloud Talent Partner", "https://www.linkedin.com/in/vidhisarvaiya/", "vidhi.sarvaiya@mastercard.com"),
            ("Mastercard", "Stephen Pagi", "HR Specialist", "https://www.linkedin.com/in/stephen-pagi-b4b38586/", "stephen.pagi@mastercard.com"),
            # JPMorgan Chase
            ("JPMorgan Chase", "Nisha Hebbar", "AVP Tech Recruitment", "https://www.linkedin.com/in/nisha-hebbar-2418537b/", "nisha.hebbar@jpmorgan.com"),
            ("JPMorgan Chase", "Anuja Ghosalkar", "Vice President Recruiting", "https://www.linkedin.com/in/anuja-ghosalkar-016ba972/", "anuja.ghosalkar@jpmorgan.com"),
            # Others
            ("UBS", "Amrita Mishra", "Recruitment Specialist", "https://www.linkedin.com/in/amrita-mishra-a123/", "amrita.mishra@ubs.com"),
            ("Atlassian", "Jeevan B", "Senior Talent Acquisition", "https://www.linkedin.com/in/jeevan-b-a123/", "jeevan.b@atlassian.com"),
            ("Salesforce", "Priya Shejul", "Talent Acquisition Lead", "https://www.linkedin.com/in/priya-shejul-a123/", "priya.shejul@salesforce.com"),
            ("Red Hat", "Nidhi Nitin Damle", "Talent Acquisition Partner", "https://www.linkedin.com/in/nidhi-damle-a123/", "nidhi.damle@redhat.com"),
            # PwC
            ("PwC", "Seema Kumari", "Talent Acquisition Specialist", "https://www.linkedin.com/in/seema-kumari-98b2a2150/", "seema.kumari@pwc.com"),
            ("PwC", "Madhuri Thakur", "Senior Manager Talent Acquisition", "https://www.linkedin.com/in/madhurithakur/", "madhuri.thakur@pwc.com"),
            ("PwC", "Richa Singh", "Talent Acquisition Lead", "https://www.linkedin.com/in/richa-singh-58959723/", "richa.singh@pwc.com"),
            ("PwC", "Komal Pawar", "Talent Acquisition Specialist", "https://www.linkedin.com/in/komal-pawar-82b60917b/", "komal.pawar@pwc.com"),
            ("PwC", "Nikita Goel", "Associate Director - Talent Acquisition", "https://www.linkedin.com/in/nikita-goel-22270318/", "nikita.goel@pwc.com"),
            ("PwC", "Archana Shirodkar", "Talent Acquisition - Technology", "https://www.linkedin.com/in/archana-shirodkar-19a01a1b/", "archana.shirodkar@pwc.com"),
            ("PwC", "Nisha Mewada", "Talent Acquisition", "https://www.linkedin.com/in/nisha-mewada-52118620/", "nisha.mewada@pwc.com"),
            ("PwC", "Shefali Kale", "Talent Acquisition Specialist", "https://www.linkedin.com/in/shefali-kale-50129a116/", "shefali.kale@pwc.com"),
            ("PwC", "Jenis Fernandes", "Talent Acquisition Senior Associate", "https://www.linkedin.com/in/jenis-fernandes/", "jenis.fernandes@pwc.com"),
        ]
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for company, name, role, linkedin, email in pre_seeded:
            conn.execute("""
                INSERT INTO recruiters (company, name, role, linkedin, email, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (company, name, role, linkedin, email, now))
        conn.commit()
        print(f"[DB] Seeded {len(pre_seeded)} verified recruiter contacts.")
    except Exception as e:
        print(f"[DB][WARN] Recruiter seeding failed: {e}")


# ── Public API ─────────────────────────────────────────────────────────────────

def init():
    """
    Initialize the database. Called once at startup.
    Safe to call multiple times — idempotent.
    """
    try:
        with _DB_LOCK:
            conn = _get_conn()
            _ensure_tables(conn)
            _import_csv_if_empty(conn)
            _seed_recruiters_if_empty(conn)
            conn.close()
    except Exception as e:
        print(f"[DB][WARN] Init failed (CSV fallback still active): {e}")


def insert_application(
    company, role, portal, url, status, match_pct,
    matched_skills="", skip_reason="", posted_date="",
    missing_skills="", decision=""
):
    """
    Insert one application row into SQLite.
    Returns True on success, False on failure (so CSV fallback triggers).
    """
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        follow_up = (datetime.datetime.now() + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        with _DB_LOCK:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO applications
                (date, company, role, portal, url, status, match_pct,
                 matched_skills, skip_reason, follow_up_date, posted_date,
                 missing_skills, decision)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                now, company or "Unknown", role or "Unknown",
                portal or "", url or "", status,
                str(match_pct), matched_skills, skip_reason,
                follow_up, posted_date, missing_skills, decision
            ))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB][WARN] insert_application failed: {e}")
        return False


def update_status_by_url(url: str, new_status: str) -> bool:
    """
    Update an application's status by matching URL.
    Returns True if any row was updated.
    """
    try:
        with _DB_LOCK:
            conn = _get_conn()
            cur = conn.execute(
                "UPDATE applications SET status=? WHERE url=?",
                (new_status, url)
            )
            changed = cur.rowcount > 0
            conn.commit()
            conn.close()
        return changed
    except Exception as e:
        print(f"[DB][WARN] update_status_by_url failed: {e}")
        return False


def get_today_count(status_filter: str = None) -> int:
    """Count applications logged today, optionally filtered by status."""
    try:
        today = datetime.date.today().strftime("%Y-%m-%d")
        with _DB_LOCK:
            conn = _get_conn()
            if status_filter:
                row = conn.execute(
                    "SELECT COUNT(*) FROM applications WHERE date LIKE ? AND status=?",
                    (f"{today}%", status_filter)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM applications WHERE date LIKE ?",
                    (f"{today}%",)
                ).fetchone()
            conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def get_all_rows() -> list:
    """Return all rows as list-of-dicts, newest first."""
    try:
        with _DB_LOCK:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM applications ORDER BY id DESC"
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_fsm_summary() -> dict:
    """Return count-per-status dict for Kanban board."""
    statuses = [
        "Applied", "Viewed", "Shortlisted", "Interview",
        "Offer", "Rejected", "Ghosted", "Skipped",
        "Manual Needed", "Review", "Pending Apply",
    ]
    summary = {s: 0 for s in statuses}
    try:
        with _DB_LOCK:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
            ).fetchall()
            conn.close()
        for row in rows:
            if row["status"] in summary:
                summary[row["status"]] = row["cnt"]
    except Exception:
        pass
    return summary


def get_applied_companies() -> list:
    """Return rows in trackable FSM states for email monitor matching."""
    try:
        with _DB_LOCK:
            conn = _get_conn()
            rows = conn.execute(
                """SELECT company, url FROM applications
                   WHERE status IN ('Applied','Viewed','Shortlisted','Pending Apply')"""
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def upsert_qa(question: str, answer: str, portal: str = ""):
    """Insert or update a Q&A entry in the qa_bank table."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with _DB_LOCK:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO qa_bank (question, answer, portal, updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(question) DO UPDATE SET
                    answer=excluded.answer,
                    portal=excluded.portal,
                    updated=excluded.updated
            """, (question, answer, portal, now))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[DB][WARN] upsert_qa failed: {e}")


def save_recruiters(company: str, recruiters_list: list) -> bool:
    """Save a list of recruiters for a company, replacing duplicates."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        with _DB_LOCK:
            conn = _get_conn()
            conn.execute("DELETE FROM recruiters WHERE LOWER(company)=?", (company.lower(),))
            for rec in recruiters_list:
                conn.execute("""
                    INSERT INTO recruiters (company, name, role, linkedin, email, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    company,
                    rec.get("name", ""),
                    rec.get("role", ""),
                    rec.get("linkedin", ""),
                    rec.get("email", ""),
                    now
                ))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"[DB][WARN] save_recruiters failed: {e}")
        return False


def get_recruiters_by_company(company: str) -> list:
    """Get all cached recruiters for a given company."""
    try:
        with _DB_LOCK:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT * FROM recruiters WHERE LOWER(company)=? ORDER BY id ASC",
                (company.lower(),)
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB][WARN] get_recruiters_by_company failed: {e}")
        return []


# Auto-initialize when this module is first imported
try:
    init()
except Exception:
    pass
