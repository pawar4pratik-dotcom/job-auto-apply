"""
app.py — Job Hunt Bot Web Dashboard (v3.0 — Modular Architecture)

Run:   python app.py
Open:  http://localhost:5005

Architecture (Phase 2 modularization):
  core/state.py          — All shared state (queue, locks, cache, bot_log)
  core/apply_engine.py   — Unified browser apply engine
  scrapers/              — targeted_search, recruiter_scraper
  routes/                — bot_routes, data_routes, review_routes,
                           search_routes, profile_routes
  templates/             — dashboard.html (extracted from TEMPLATE string)

Previous monolithic app.py preserved as: app_v2_monolith.py
"""
import os
import sys
import importlib

# Force standard streams to use UTF-8 with replacement fallbacks
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Force working directory to the script's directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

# ── Import shared state (must happen before routes) ──────────────────
import core.state as state
from core.state import bot_log, STOP_EVENT

# ── Import tracker helpers used by multiple routes ────────────────────
from tracker import get_all_rows, get_today_count, TRACKER_FILE

# ── Import QA store helpers ───────────────────────────────────────────
from qa_store import get_all as qa_get_all, save_answer, get_unanswered, save_question_settings, delete_entry

# ── Load initial profile settings ────────────────────────────────────
from config.profile import DAILY_LIMIT, SCHEDULED_RUNS, HEADLESS_DEFAULT

# ── Create Flask app (templates folder used by render_template) ───────
app = Flask(__name__, template_folder="templates")

# ── Register all Blueprints ───────────────────────────────────────────
from routes.bot_routes     import bot_bp
from routes.data_routes    import data_bp
from routes.review_routes  import review_bp
from routes.search_routes  import search_bp
from routes.profile_routes import profile_bp
from routes.resume_routes  import resume_bp
from routes.workday_routes import workday_bp
from routes.outreach_routes import outreach_bp

app.register_blueprint(bot_bp)
app.register_blueprint(data_bp)
app.register_blueprint(review_bp)
app.register_blueprint(search_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(resume_bp)
app.register_blueprint(workday_bp)
app.register_blueprint(outreach_bp)


# ── Scheduler (APScheduler cron for 09:00 / 14:00 / 19:00 runs) ──────
def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()

        def _run_scheduled():
            """Run all bots on schedule (no Flask context needed)."""
            import sys
            import importlib
            import config.profile
            
            def reload_module_recursive(module_name, reloaded=None):
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

            try:
                import config.secrets
                importlib.reload(config.secrets)
                importlib.reload(config.profile)
                reloaded_set = set()
                for m in ['config.secrets', 'config.profile', 'filter', 'careers_bot', 'linkedin_bot', 'naukri_bot', 'indeed_bot', 'scrapers.targeted_search', 'scrapers.recruiter_scraper']:
                    reload_module_recursive(m, reloaded_set)
            except Exception as ex:
                bot_log(f"[WARN] Scheduled reload failed: {ex}")

            from core.notifier import enable_buffering, send_session_report
            enable_buffering()
            try:
                from linkedin_bot import run_linkedin_bot
                from naukri_bot import run_naukri_bot
                STOP_EVENT.clear()
                run_linkedin_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)
                if not STOP_EVENT.is_set():
                    run_naukri_bot(max_applications=15, headless=True, log_fn=bot_log, stop_event=STOP_EVENT)
            finally:
                send_session_report()

        for run_time in SCHEDULED_RUNS:
            h, m = map(int, run_time.split(":"))
            scheduler.add_job(_run_scheduled, "cron", hour=h, minute=m)

        scheduler.start()
        print(f"[SCHEDULER] Runs scheduled at: {', '.join(SCHEDULED_RUNS)}")
    except ImportError:
        print("[WARN] apscheduler not installed — scheduled runs disabled. Run: pip install apscheduler")
    except Exception as e:
        print(f"[WARN] Scheduler failed to start: {e}")


# ── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    # Start email monitor
    try:
        import email_monitor
        email_monitor.start_monitor(interval_minutes=5, log_fn=bot_log)
    except Exception as e:
        print(f"[WARN] Email monitor failed to start: {e}")

    _start_scheduler()
    print("[DASHBOARD] Open http://localhost:5006")
    app.run(host="0.0.0.0", port=5006, debug=False, threaded=True)
