"""
routes/bot_routes.py — Bot lifecycle endpoints.

Routes:
  GET  /               Dashboard HTML (rendered from templates/dashboard.html)
  GET  /stream         SSE log stream (BUG1-FIX: timeout + keepalive)
  POST /api/run        Start bot (all / linkedin / naukri / targeted / recruiter_posts)
  POST /api/stop       Send stop signal to running bot
"""
import importlib
import queue
import threading

from flask import Blueprint, render_template, jsonify, request, Response, stream_with_context

import config.profile
from core.state import _log_q, STOP_EVENT, bot_log
import core.state as state

bot_bp = Blueprint("bot", __name__)


@bot_bp.route("/")
@bot_bp.route("/react")
def index():
    return render_template("dashboard_react.html")


@bot_bp.route("/legacy")
def legacy_index():
    try:
        importlib.reload(config.profile)
        from config.profile import DAILY_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT
    except Exception:
        from config.profile import DAILY_LIMIT, SCHEDULED_RUNS
        HEADLESS_DEFAULT = True
    return render_template(
        "dashboard.html",
        daily_limit=DAILY_LIMIT,
        sched_runs=SCHEDULED_RUNS,
        headless_default=HEADLESS_DEFAULT,
    )



@bot_bp.route("/stream")
def stream():
    """
    BUG1-FIX: SSE stream with timeout — no zombie threads on tab close.
    Sends keepalive comment every 5s to detect dead connections.
    """
    def generate():
        try:
            while True:
                try:
                    msg = _log_q.get(timeout=5)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def reload_module_recursive(module_name, reloaded=None):
    import sys
    import importlib
    if reloaded is None:
        reloaded = set()
    if module_name in reloaded:
        return
    reloaded.add(module_name)
    if module_name not in sys.modules:
        return
    mod = sys.modules[module_name]
    for attr_name in list(dir(mod)):
        try:
            attr = getattr(mod, attr_name)
            if hasattr(attr, "__name__") and hasattr(attr, "__file__"):
                dep_name = attr.__name__
                if (dep_name.startswith("config") or dep_name.startswith("core") or 
                    dep_name.startswith("scrapers") or dep_name.startswith("routes") or 
                    dep_name in ["filter", "linkedin_bot", "naukri_bot", "indeed_bot", "careers_bot", "tracker", "qa_store", "browser"]):
                    reload_module_recursive(dep_name, reloaded)
        except Exception:
            pass
    try:
        importlib.reload(mod)
    except Exception as ex:
        print(f"[WARN] Failed to reload {module_name}: {ex}")


def reload_all_settings():
    import sys
    import importlib
    import config.secrets
    import config.profile
    try:
        importlib.reload(config.secrets)
        importlib.reload(config.profile)
        reloaded_set = set()
        for m in ['config.secrets', 'config.profile', 'filter', 'careers_bot', 'linkedin_bot', 'naukri_bot', 'indeed_bot', 'scrapers.targeted_search', 'scrapers.recruiter_scraper']:
            reload_module_recursive(m, reloaded_set)
    except Exception as ex:
        print(f"[WARN] Failed reload_all_settings: {ex}")


@bot_bp.route("/api/run", methods=["POST"])
def api_run():
    # Auto-clear dead threads so they don't block new runs
    if state._bot_thread and not state._bot_thread.is_alive():
        state._bot_thread = None

    if state._bot_thread and state._bot_thread.is_alive():
        return jsonify({"error": "Bot already running"}), 409

    # Reload all modules so latest profile/settings take effect
    try:
        reload_all_settings()
    except Exception as e:
        bot_log(f"[WARN] Module reload warning: {e}")

    STOP_EVENT.clear()
    data = request.get_json() or {}
    target   = data.get("target") or data.get("mode") or "all"
    headless = data.get("headless", False)
    max_apps = data.get("max_applications") or data.get("max_apps") or 15
    company  = (data.get("company") or "").strip()
    skills   = (data.get("skills") or "").strip()
    location = (data.get("location") or "").strip()

    # Load defaults from active config.profile if empty
    try:
        import config.profile
        importlib.reload(config.profile)
        if skills.lower() in ("null", "undefined"):
            skills = ""
        if location.lower() in ("null", "undefined"):
            location = ""

        if not skills:
            kws = getattr(config.profile, "SEARCH_KEYWORDS", [])
            if isinstance(kws, list):
                skills = ", ".join([k for k in kws if k])
        if not location:
            locs = getattr(config.profile, "SEARCH_LOCATIONS", [])
            if isinstance(locs, list):
                location = ", ".join([l for l in locs if l])
    except Exception:
        pass

    # Map aliases
    if target in ("targeted", "targeted_search"):
        target = "targeted"
    elif target in ("recruiter_posts", "recruiter_scraper"):
        target = "recruiter_posts"

    def _run():
        from core.notifier import enable_buffering, send_session_report
        enable_buffering()
        try:
            # Reload configuration and modules dynamically to pick up any profile changes
            try:
                reload_all_settings()
            except Exception as ex:
                bot_log(f"[WARN] Failed to reload settings in runner: {ex}")

            if target == "targeted":
                from scrapers.targeted_search import run_targeted_search_flow
                run_targeted_search_flow(company, skills, location, max_apps, headless, lambda m: bot_log(m, channel="search"), STOP_EVENT)
            elif target == "recruiter_posts":
                from scrapers.recruiter_scraper import run_recruiter_scraper_flow
                run_recruiter_scraper_flow(company, skills, location, lambda m: bot_log(m, channel="search"), STOP_EVENT)
            else:
                if target in ("linkedin", "all"):
                    from linkedin_bot import run_linkedin_bot
                    run_linkedin_bot(max_applications=max_apps, headless=headless, log_fn=lambda m: bot_log(m, channel="bot"), stop_event=STOP_EVENT)
                if not STOP_EVENT.is_set() and target in ("naukri", "all"):
                    from naukri_bot import run_naukri_bot
                    run_naukri_bot(max_applications=max_apps, headless=headless, log_fn=lambda m: bot_log(m, channel="bot"), stop_event=STOP_EVENT)
                if not STOP_EVENT.is_set() and target in ("indeed", "all"):
                    from indeed_bot import run_indeed_bot
                    run_indeed_bot(max_applications=max_apps, headless=headless, log_fn=lambda m: bot_log(m, channel="bot"), stop_event=STOP_EVENT)
        except Exception as e:
            import traceback
            bot_log(f"[ERROR] Bot crashed: {e}\n{traceback.format_exc()}")
        finally:
            send_session_report()

    state._bot_thread = threading.Thread(target=_run, daemon=True)
    state._bot_thread.start()
    return jsonify({"ok": True})


@bot_bp.route("/api/stop", methods=["POST"])
def api_stop():
    STOP_EVENT.set()
    bot_log("[STOP] Stop signal sent — bot will halt at next checkpoint.")
    return jsonify({"ok": True, "note": "Stop signal sent."})


@bot_bp.route("/api/force_stop", methods=["POST"])
def api_force_stop():
    STOP_EVENT.set()
    state._bot_thread = None
    bot_log("[STOP] Force stop — thread state cleared.")
    return jsonify({"ok": True, "note": "Force stopped and state cleared."})
