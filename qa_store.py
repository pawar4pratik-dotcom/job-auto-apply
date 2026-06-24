"""
qa_store.py — Persistent Q&A store for application form questions.

When the bot encounters a form field it cannot answer automatically,
it records the question here. The candidate answers it once in the
dashboard. All future applications with the same question reuse that answer.

Storage: logs/qa_store.json
Schema:  { "question_key": {"answer": "...", "portal": "LinkedIn", "count": 3} }
"""

import json
import os

_QA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "qa_store.json")


def _load() -> dict:
    """Load the Q&A store from disk. Returns empty dict if file missing."""
    try:
        if os.path.exists(_QA_FILE):
            with open(_QA_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save(store: dict) -> None:
    """Write the Q&A store to disk atomically."""
    try:
        os.makedirs(os.path.dirname(_QA_FILE), exist_ok=True)
        tmp = _QA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _QA_FILE)
    except Exception as e:
        print(f"[QA] Save error: {e}")


def _normalise_key(question: str) -> str:
    """
    Normalise a question string to a stable key.
    Strips punctuation, lowercases, trims whitespace.
    This allows "Years of Python experience?" and "years of python experience"
    to match the same stored answer.
    """
    import re
    q = question.lower().strip()
    q = re.sub(r"[^a-z0-9 ]", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q[:120]   # Cap key length


# ── Public API ────────────────────────────────────────────────────────────────

def record_unanswered(question: str, portal: str = "") -> None:
    """
    Record a question that the bot could not answer automatically.
    If the question is already recorded, increment its encounter count.
    The dashboard shows these to the candidate for manual answering.
    """
    if not question or not question.strip():
        return
    key = _normalise_key(question)
    store = _load()
    if key not in store:
        store[key] = {
            "question": question.strip(),
            "answer":   None,
            "portal":   portal,
            "count":    1,
            "mode":     "auto",
        }
    else:
        store[key]["count"] = store[key].get("count", 1) + 1
        if portal and not store[key].get("portal"):
            store[key]["portal"] = portal
    _save(store)


def save_answer(question: str, answer: str) -> None:
    """
    Save a candidate-provided answer for a previously unanswered question.
    Called by the dashboard when the candidate fills in the answer form.
    """
    if not question:
        return
    key = _normalise_key(question)
    store = _load()
    if key in store:
        store[key]["answer"] = answer.strip()
    else:
        # Direct answer save even if question was never recorded
        store[key] = {
            "question": question.strip(),
            "answer":   answer.strip(),
            "portal":   "",
            "count":    0,
        }
    _save(store)


def get_answer(question: str) -> str:
    """
    Look up a stored answer by question text.
    Returns the answer string, or empty string if not found / not yet answered.
    """
    if not question:
        return ""
    key = _normalise_key(question)
    store = _load()
    entry = store.get(key)
    if entry:
        if entry.get("mode") == "manual":
            return "__MANUAL__"
        if entry.get("answer"):
            return entry["answer"]
            
    # Try semantic matching / profile answering if exact match missing
    try:
        from core.semantic_qa import resolve_semantic_answer
        ans = resolve_semantic_answer(question)
        if ans:
            save_auto_answered(question, ans)
            return ans
    except Exception as e:
        print(f"[QA] Semantic lookup error: {e}")
        
    return ""


def get_unanswered() -> list:
    """
    Return list of questions that have been recorded but not yet answered.
    Sorted by encounter count descending (most-seen questions first).
    Used by the dashboard Q&A tab.
    """
    store = _load()
    unanswered = [
        {
            "key":      k,
            "question": v.get("question", k),
            "portal":   v.get("portal", ""),
            "count":    v.get("count", 1),
        }
        for k, v in store.items()
        if not v.get("answer")
    ]
    unanswered.sort(key=lambda x: x["count"], reverse=True)
    return unanswered


def get_all() -> list:
    """
    Return all Q&A entries (answered and unanswered).
    Used by the dashboard to display the full Q&A library.
    """
    store = _load()
    return [
        {
            "key":      k,
            "question": v.get("question", k),
            "answer":   v.get("answer") or "",
            "portal":   v.get("portal", ""),
            "count":    v.get("count", 1),
            "answered": bool(v.get("answer")),
            "mode":     v.get("mode") or "auto",
        }
        for k, v in store.items()
    ]


def delete_entry(question: str) -> bool:
    """Delete a Q&A entry by question text. Returns True if deleted."""
    key = _normalise_key(question)
    store = _load()
    if key in store:
        del store[key]
        _save(store)
        return True
    return False


def get_stats() -> dict:
    """Return summary stats for the Q&A store."""
    store = _load()
    total     = len(store)
    answered  = sum(1 for v in store.values() if v.get("answer"))
    return {
        "total":      total,
        "answered":   answered,
        "unanswered": total - answered,
    }


def save_question_settings(question: str, answer: str, mode: str) -> None:
    """Save setting options (answer and mode) for a question."""
    if not question:
        return
    key = _normalise_key(question)
    store = _load()
    if key in store:
        store[key]["answer"] = answer.strip() if answer else None
        store[key]["mode"] = mode.strip() if mode else "auto"
    else:
        store[key] = {
            "question": question.strip(),
            "answer":   answer.strip() if answer else None,
            "portal":   "",
            "count":    0,
            "mode":     mode.strip() if mode else "auto"
        }
    _save(store)


def save_auto_answered(question: str, answer: str, portal: str = "") -> None:
    """
    Record an automatically answered question to the Q&A database
    so the user can review and correct it in the Memory Bank.
    """
    if not question or not question.strip():
        return
    key = _normalise_key(question)
    store = _load()
    if key not in store:
        store[key] = {
            "question": question.strip(),
            "answer":   str(answer).strip(),
            "portal":   portal,
            "count":    1,
            "mode":     "auto"
        }
        _save(store)
    else:
        # Increment counter
        store[key]["count"] = store[key].get("count", 1) + 1
        # If it doesn't have a saved answer, update it with this auto answer
        if not store[key].get("answer"):
            store[key]["answer"] = str(answer).strip()
        _save(store)
