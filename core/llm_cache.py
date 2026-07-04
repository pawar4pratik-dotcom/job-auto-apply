import sqlite3
import os
import hashlib
import time
from typing import Optional, Callable
import functools

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "llm_cache.db")

def init_db():
    """Ensure logs directory exists and database table is initialized."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache_entries (
                key TEXT PRIMARY KEY,
                prompt TEXT,
                model TEXT,
                response TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def _make_key(prompt: str, model: str) -> str:
    """Create a deterministic SHA-256 cache key from the prompt and model name."""
    content = f"{model}:{prompt}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def get_cached_response(prompt: str, model: str) -> Optional[str]:
    """Retrieve cached response if it exists, otherwise return None."""
    init_db()
    key = _make_key(prompt, model)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT response FROM cache_entries WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row[0]
    except Exception as e:
        print(f"[LLM CACHE][WARN] Failed to read from cache: {e}")
    finally:
        conn.close()
    return None

def set_cached_response(prompt: str, response: str, model: str):
    """Cache a response in the database."""
    init_db()
    key = _make_key(prompt, model)
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO cache_entries (key, prompt, model, response, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (key, prompt, model, response, time.time()))
        conn.commit()
    except Exception as e:
        print(f"[LLM CACHE][WARN] Failed to write to cache: {e}")
    finally:
        conn.close()

def cached_llm(model_name: str):
    """Decorator to automatically cache calls to LLM functions."""
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # The prompt is typically the first argument or keyword argument
            # Let's extract the prompt string dynamically
            prompt = ""
            if args:
                prompt = args[0]
            elif "prompt" in kwargs:
                prompt = kwargs["prompt"]
            elif len(args) > 1: # if we have system_prompt, user_prompt
                prompt = f"{args[0]}\n\n{args[1]}"
            
            if not isinstance(prompt, str) or not prompt.strip():
                return func(*args, **kwargs)
                
            cached = get_cached_response(prompt, model_name)
            if cached is not None:
                print(f"[LLM CACHE] Hit for model {model_name}!")
                return cached
                
            # Execute actual function call
            result = func(*args, **kwargs)
            
            # Store in cache if successful
            if result:
                set_cached_response(prompt, result, model_name)
            return result
        return wrapper
    return decorator
