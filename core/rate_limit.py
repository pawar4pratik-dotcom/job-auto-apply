import time
import threading

class RateLimiter:
    """Thread-safe rate limiter checking minimal elapsed intervals between actions."""
    def __init__(self, min_interval_sec: float):
        self.min_interval = min_interval_sec
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.time()

LINKEDIN_LIMITER = RateLimiter(3.0)   # 3s between LinkedIn requests
NAUKRI_LIMITER   = RateLimiter(1.5)
GOOGLE_LIMITER   = RateLimiter(5.0)
