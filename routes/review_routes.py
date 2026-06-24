"""
routes/review_routes.py — Human-in-the-loop review queue management.

Routes:
  GET  /api/review_queue         All jobs awaiting human review
  POST /api/approve              Approve + trigger auto-apply (BUG8-FIX: uses unified engine)
  POST /api/reject               Reject a job
  POST /api/review/bulk_approve  Approve multiple jobs (BUG2-FIX: time imported at top)
  POST /api/review/bulk_reject   Reject all queued jobs
"""
import time
import threading

from flask import Blueprint, jsonify, request

from tracker import get_review_queue, approve_review_job, reject_review_job, get_all_rows
from core.apply_engine import run_apply_for_url
from core.state import bot_log

review_bp = Blueprint("review", __name__)


@review_bp.route("/api/review_queue")
def api_review_queue():
    return jsonify(get_review_queue())


@review_bp.route("/api/approve", methods=["POST"])
def api_approve():
    """
    BUG8-FIX: Uses unified run_apply_for_url() — no duplicated code.
    Accepts company/role in body (from targeted results) OR looks up from tracker.
    """
    data    = request.get_json() or {}
    url     = data.get("url", "")
    company = data.get("company", "").strip()
    role    = data.get("role", "").strip()

    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400

    if not company or not role:
        for row in get_all_rows():
            if row.get("URL") == url:
                company = company or row.get("Company", "Company")
                role    = role or row.get("Role", "Role")
                break

    approve_review_job(url)  # No-op if not in queue (targeted results direct apply)
    threading.Thread(
        target=run_apply_for_url, args=(url, company or "Company", role or "Role"), daemon=True
    ).start()
    return jsonify({"ok": True, "message": "Auto-application started in background."})


@review_bp.route("/api/reject", methods=["POST"])
def api_reject():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"ok": False, "error": "No URL provided"}), 400
    ok = reject_review_job(url)
    return jsonify({"ok": ok})


@review_bp.route("/api/review/bulk_approve", methods=["POST"])
def api_review_bulk_approve():
    """
    BUG2-FIX: time imported at module level — no NameError.
    BUG8-FIX: Uses run_apply_for_url() — no duplicated apply logic.
    PERF: Staggered 2s launches + Semaphore(3) cap on concurrent Chrome.
    """
    data = request.get_json() or {}
    min_score = data.get("min_score")
    if min_score is not None:
        try:
            min_score = float(min_score)
        except ValueError:
            min_score = None

    review_jobs = get_review_queue()
    approved_count = 0

    for job in review_jobs:
        score   = job.get("Score", 0)
        url     = job.get("URL", "")
        company = job.get("Company", "Company")
        role    = job.get("Role", "Role")

        if min_score is not None and score < min_score:
            continue

        if approve_review_job(url):
            approved_count += 1
            time.sleep(2)  # Stagger launches to avoid Chrome OOM
            threading.Thread(
                target=run_apply_for_url, args=(url, company, role), daemon=True
            ).start()

    return jsonify({"ok": True, "count": approved_count})


@review_bp.route("/api/review/bulk_reject", methods=["POST"])
def api_review_bulk_reject():
    review_jobs = get_review_queue()
    rejected_count = sum(1 for job in review_jobs if reject_review_job(job.get("URL", "")))
    return jsonify({"ok": True, "count": rejected_count})
