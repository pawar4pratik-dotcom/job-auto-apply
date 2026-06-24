import os
import threading
import queue
import datetime
from flask import Flask, render_template_string, jsonify, request, Response, stream_with_context

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from tracker import get_all_rows, get_today_count
from qa_store import get_all as qa_get_all, save_answer, get_unanswered
from config.profile import DAILY_LIMIT, SCHEDULED_RUNS

app = Flask(__name__)
_log_q = queue.Queue(maxsize=500)
_bot_thread = None
STOP_EVENT = threading.Event()  # <-- ADDED FOR GRACEFUL SHUTDOWN

def bot_log(msg: str):
    print(msg)
    try:
        _log_q.put_nowait(f"data: {msg}\n")
    except queue.Full:
        pass

# ... [Keep the exact same TEMPLATE HTML string from your original app.py here] ...
# (Omitted for brevity, paste your original TEMPLATE variable here)

@app.route("/")
def index():
    return render_template_string(TEMPLATE, daily_limit=DAILY_LIMIT, sched_runs=SCHEDULED_RUNS)

@app.route("/stream")
def stream():
    def generate():
        while True:
            try:
                msg = _log_q.get(timeout=1)
                yield msg
            except queue.Empty:
                yield "data: \n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/stats")
def api_stats():
    return jsonify({
        "applied": get_today_count("Applied"),
        "skipped": get_today_count("Skipped"),
        "manual": get_today_count("Manual Needed"),
        "total": get_today_count(),
        "running": _bot_thread is not None and _bot_thread.is_alive(),
    })

@app.route("/api/applications")
def api_applications():
    return jsonify(get_all_rows())

@app.route("/api/qa")
def api_qa():
    return jsonify(get_unanswered())

@app.route("/api/qa/answer", methods=["POST"])
def api_qa_answer():
    data = request.get_json()
    save_answer(data["question"], data["answer"])
    return jsonify({"ok": True})

@app.route("/api/run", methods=["POST"])
def api_run():
    global _bot_thread
    if _bot_thread and _bot_thread.is_alive():
        return jsonify({"error": "Bot already running"}), 409
    
    STOP_EVENT.clear()  # <-- RESET STOP FLAG
    target = request.get_json().get("target", "all")
    headless = False
    
    def _run():
        if target in ("linkedin", "all"):
            from linkedin_bot import run_linkedin_bot
            run_linkedin_bot(max_applications=15, headless=headless, log_fn=bot_log, stop_event=STOP_EVENT)
        if not STOP_EVENT.is_set() and target in ("naukri", "all"):
            from naukri_bot import run_naukri_bot
            run_naukri_bot(max_applications=15, headless=headless, log_fn=bot_log, stop_event=STOP_EVENT)

    _bot_thread = threading.Thread(target=_run, daemon=True)
    _bot_thread.start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    STOP_EVENT.set()  # <-- TRIGGER STOP FLAG
    bot_log("[INFO] Stop requested. Bot will finish current action and halt.")
    return jsonify({"ok": True, "note": "Stop signal sent."})

def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        for run_time in SCHEDULED_RUNS:
            h, m = map(int, run_time.split(":"))
            scheduler.add_job(lambda: api_run_internal("all"), "cron", hour=h, minute=m)
        scheduler.start()
        print(f"[SCHEDULER] Scheduled runs at: {', '.join(SCHEDULED_RUNS)}")
    except ImportError:
        print("[WARN] apscheduler not installed — scheduled runs disabled. Run: pip install apscheduler")

def api_run_internal(target):
    from linkedin_bot import run_linkedin_bot
    from naukri_bot import run_naukri_bot
    STOP_EVENT.clear()
    if target in ("linkedin", "all"):
        run_linkedin_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)
    if not STOP_EVENT.is_set() and target in ("naukri", "all"):
        run_naukri_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)

if __name__ == "__main__":
    _start_scheduler()
    print("[DASHBOARD] Open http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)