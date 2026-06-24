import time

_cache = {}

def get_scored(url: str):
    """Retrieve cached scoring entry if not expired (30 min TTL)."""
    entry = _cache.get(url)
    if entry and time.time() - entry["ts"] < 1800:
        return entry["data"]
    return None

def set_scored(url: str, data: dict):
    """Store scoring result in cache with current timestamp."""
    _cache[url] = {"ts": time.time(), "data": data}
