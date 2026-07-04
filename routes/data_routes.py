"""
routes/data_routes.py — Read-only data endpoints.

Routes:
  GET  /api/stats               Today's counts
  GET  /api/applications        Full application log
  GET  /api/analytics           Funnel analytics
  GET  /api/kanban              Kanban board data (SQLite-backed)
  POST /api/applications/status Update application status
  GET  /api/qa                  Unanswered QA questions
  GET  /api/qa/all              All QA entries
  POST /api/qa/update           Save question settings
  POST /api/qa/delete           Delete QA entry
  POST /api/qa/answer           Save answer
  GET  /api/export-csv          Download CSV log
"""
import os
import csv
import datetime

from flask import Blueprint, jsonify, request, send_file

from tracker import get_all_rows, get_today_count, TRACKER_FILE, update_status
from qa_store import get_all as qa_get_all, save_answer, get_unanswered, save_question_settings, delete_entry
import core.state as state

data_bp = Blueprint("data", __name__)


@data_bp.route("/api/stats")
def api_stats():
    return jsonify({
        "applied": get_today_count("Applied"),
        "skipped": get_today_count("Skipped"),
        "manual":  get_today_count("Manual Needed"),
        "total":   get_today_count(None),
        "running": bool(state._bot_thread and state._bot_thread.is_alive()),
    })


@data_bp.route("/api/applications")
def api_applications():
    rows = get_all_rows()
    return jsonify(rows)


@data_bp.route("/api/analytics")
def api_analytics():
    rows = get_all_rows()
    by_status = {}
    by_company = {}
    by_date = {}
    scores = []

    for row in rows:
        status = row.get("Status", "Unknown")
        company = row.get("Company", "Unknown")
        date = row.get("Date", "")[:10]
        score_raw = row.get("Match %", "0%")
        try:
            score = float(str(score_raw).replace("%", "").strip())
            scores.append(score)
        except Exception:
            pass

        by_status[status] = by_status.get(status, 0) + 1
        by_company[company] = by_company.get(company, 0) + 1
        by_date[date] = by_date.get(date, 0) + 1

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    top_companies = sorted(by_company.items(), key=lambda x: x[1], reverse=True)[:8]

    # Calculate funnel stages
    scanned = len(rows)
    ai_passed = sum(1 for r in rows if r.get("Status") != "Skipped")
    applied = sum(1 for r in rows if r.get("Status") in ['Applied', 'Viewed', 'Shortlisted', 'Interview', 'Offer', 'Rejected', 'Ghosted'])
    viewed = sum(1 for r in rows if r.get("Status") in ['Viewed', 'Shortlisted', 'Interview', 'Offer'])
    interview = sum(1 for r in rows if r.get("Status") in ['Interview', 'Offer'])
    offer = sum(1 for r in rows if r.get("Status") == 'Offer')

    return jsonify({
        "by_status": by_status,
        "top_companies": [{"company": c, "count": n} for c, n in top_companies],
        "by_date": [{"date": d, "count": n} for d, n in sorted(by_date.items())[-14:]],
        "total": len(rows),
        "avg_score": avg_score,
        "Scanned": scanned,
        "AI_Passed": ai_passed,
        "Applied": applied,
        "Viewed": viewed,
        "Interview": interview,
        "Offer": offer,
    })


@data_bp.route("/api/kanban")
def api_kanban():
    """
    Returns Kanban board data:
    - 'summary': count per FSM state (for column headers)
    - 'cards':   latest 60 applied/interview rows (for card rendering)
    Reads from SQLite first, falls back to CSV tracker.
    """
    # ── Try SQLite ───────────────────────────────────────────────────
    try:
        from core import database as db
        summary = db.get_fsm_summary()
        all_rows = db.get_all_rows()
        # Normalize field names from SQLite (snake_case) to match JS expectations
        cards = []
        for r in all_rows[:60]:
            if r.get("status") in ("Applied", "Viewed", "Shortlisted",
                                   "Interview", "Offer", "Rejected",
                                   "Manual Needed", "Review"):
                cards.append({
                    "Company":  r.get("company", ""),
                    "Role":     r.get("role", ""),
                    "Status":   r.get("status", ""),
                    "Match %":  r.get("match_pct", ""),
                    "URL":      r.get("url", ""),
                    "Date":     r.get("date", ""),
                    "Portal":   r.get("portal", ""),
                })
        return jsonify({"summary": summary, "cards": cards, "source": "sqlite"})
    except Exception:
        pass

    # ── Fallback: CSV ─────────────────────────────────────────────────
    rows = get_all_rows()[:60]
    summary = {}
    for row in rows:
        s = row.get("Status", "Unknown")
        summary[s] = summary.get(s, 0) + 1
    return jsonify({"summary": summary, "cards": rows, "source": "csv"})


@data_bp.route("/api/applications/status", methods=["POST"])
def api_applications_status():
    data = request.get_json() or {}
    url = data.get("url", "")
    new_status = data.get("status", "")
    if not url or not new_status:
        return jsonify({"ok": False, "error": "url and status required"}), 400
    update_status(url, new_status)
    return jsonify({"ok": True})


@data_bp.route("/api/qa")
def api_qa():
    return jsonify(get_unanswered())


@data_bp.route("/api/qa/all")
def api_qa_all():
    return jsonify(qa_get_all())


@data_bp.route("/api/qa/auto_resolve", methods=["POST"])
def api_qa_auto_resolve():
    try:
        from qa_store import get_unanswered, save_answer
        from core.semantic_qa import resolve_semantic_answer
        
        unanswered = get_unanswered()
        resolved_count = 0
        resolved_details = []
        
        for item in unanswered:
            q = item["question"]
            ans = resolve_semantic_answer(q, portal=item.get("portal", ""))
            if ans:
                save_answer(q, ans)
                resolved_count += 1
                resolved_details.append({"question": q, "answer": ans})
                
        return jsonify({"ok": True, "count": resolved_count, "resolved": resolved_details})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@data_bp.route("/api/qa/update", methods=["POST"])
def api_qa_update():
    data = request.get_json() or {}
    save_question_settings(data.get("question"), data.get("type"), data.get("options"))
    return jsonify({"ok": True})


@data_bp.route("/api/qa/delete", methods=["POST"])
def api_qa_delete():
    data = request.get_json() or {}
    delete_entry(data["question"])
    return jsonify({"ok": True})


@data_bp.route("/api/qa/answer", methods=["POST"])
def api_qa_answer():
    data = request.get_json() or {}
    save_answer(data["question"], data["answer"])
    return jsonify({"ok": True})


@data_bp.route("/api/export-csv")
def api_export_csv():
    from tracker import _tracker_path
    path = _tracker_path()
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    return jsonify({"error": "No CSV file found"}), 404


@data_bp.route("/api/recruiters/find")
def api_recruiters_find():
    company = request.args.get("company", "").strip()
    if not company:
        return jsonify([])
    
    from core import database as db
    from core.recruiter_finder import find_recruiters_online

    # Try cache first
    cached = db.get_recruiters_by_company(company)
    if cached:
        return jsonify(cached)
    
    # Scrape fresh
    try:
        found = find_recruiters_online(company)
        if found:
            db.save_recruiters(company, found)
            cached = db.get_recruiters_by_company(company)
            return jsonify(cached)
    except Exception as e:
        print(f"[API][ERROR] find recruiters failed: {e}")
        
    return jsonify([])


@data_bp.route("/api/recruiters/list")
def api_recruiters_list():
    company = request.args.get("company", "").strip()
    if not company:
        return jsonify([])
    from core import database as db
    cached = db.get_recruiters_by_company(company)
    return jsonify(cached)
