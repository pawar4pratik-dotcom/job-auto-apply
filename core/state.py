"""
core/state.py — All shared mutable state for the Job Bot.

This module holds the objects that are imported by both routes and scrapers:
  _log_q                  Queue for SSE log streaming
  STOP_EVENT              threading.Event to signal bot stop
  _bot_thread             Reference to the running bot thread
  TARGETED_SEARCH_RESULTS List of scored jobs from targeted search
  _results_lock           Lock protecting TARGETED_SEARCH_RESULTS
  _MAX_BROWSER_SEM        Semaphore capping concurrent Chrome instances
  _notifications_cache    TTL cache for /api/notifications
  bot_log()               Central logging function
"""
import queue
import threading
import datetime
import json

# ── SSE log queue (5000 msgs, expanded from original 1000) ──────────
_log_q: queue.Queue = queue.Queue(maxsize=5000)

# ── Bot lifecycle ────────────────────────────────────────────────────
_bot_thread: threading.Thread | None = None
STOP_EVENT: threading.Event = threading.Event()

# ── Targeted search results (thread-safe) ───────────────────────────
TARGETED_SEARCH_RESULTS: list = []
_results_lock: threading.Lock = threading.Lock()

# ── Browser concurrency cap (prevents OOM on bulk approve) ──────────
_MAX_BROWSER_SEM: threading.Semaphore = threading.Semaphore(3)

# ── Notifications TTL cache (30s) ────────────────────────────────────
_notifications_cache: dict = {"data": [], "ts": 0}
_NOTIF_CACHE_TTL: int = 30  # seconds


def bot_log(msg: str, channel: str = "bot") -> None:
    """Central log function: prints to console AND pushes to SSE queue."""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass
    try:
        log_type = "info"
        if "[SUCCESS]" in msg or "[OK]" in msg:
            log_type = "success"
        elif "[WARN]" in msg or "[WARNING]" in msg:
            log_type = "warn"
        elif "[ERROR]" in msg or "[FAIL]" in msg or "[STOP]" in msg:
            log_type = "error"

        payload = {
            "type": log_type,
            "message": msg,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "channel": channel,
        }
        try:
            _log_q.put_nowait(f"data: {json.dumps(payload)}\n\n")
        except queue.Full:
            if _log_q.qsize() >= 4900:
                try:
                    _log_q.get_nowait()
                    _log_q.put_nowait(
                        f"data: {json.dumps({'type': 'warn', 'message': '[LOG] Buffer full — oldest log evicted.', 'time': datetime.datetime.now().strftime('%H:%M:%S')})}\n\n"
                    )
                except Exception:
                    pass
    except Exception:
        pass
