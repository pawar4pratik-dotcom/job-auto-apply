import time
import functools

def with_retry(max_attempts=3, delay=2.0, exceptions=(Exception,)):
    """Generic retry decorator with incremental delay."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_ex = None
            for i in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_ex = e
                    time.sleep(delay * (i + 1))
            raise last_ex
        return wrapper
    return decorator
