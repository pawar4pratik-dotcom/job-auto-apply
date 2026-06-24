"""
field_resolver.py
───────────────────
The bot's "brain" and fallback pipeline. It tries sources in order of cost and confidence:
  1. QA Store Exact Match (conf 1.0)
  2. QA Store Fuzzy Match (conf 0.9)
  3. Resume Knowledge Base (conf 0.8)
  4. LLM inference (conf 0.5-0.7)
  5. Human-in-the-loop overlay learning (conf 1.0, blocking fallback)
"""

import json
import os
import re
import difflib
from dataclasses import dataclass
from typing import Optional, Callable, Dict, List

# Local page cache for LLM queries to prevent duplicate calls
_PAGE_LLM_CACHE: Dict[str, str] = {}

def clear_page_llm_cache():
    global _PAGE_LLM_CACHE
    _PAGE_LLM_CACHE.clear()

def populate_page_llm_cache(answers: Dict[str, str]):
    global _PAGE_LLM_CACHE
    for label, val in answers.items():
        _PAGE_LLM_CACHE[normalize_label(label)] = val

@dataclass
class FieldAnswer:
    value: str
    confidence: float          # 0.0 - 1.0
    source: str                 # "qa_store_exact" | "qa_store_fuzzy" | "resume_kb" | "llm" | "human" | "none"
    field_label: str = ""

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.75

    def to_dict(self):
        return {
            "value": self.value, 
            "confidence": self.confidence,
            "source": self.source, 
            "field_label": self.field_label
        }

def normalize_label(label: str, context_prefix: str = "") -> str:
    """Normalizes field labels to standard forms, prefixing context to prevent collisions."""
    label = label.lower().strip()
    label = re.sub(r"[*:]+\s*$", "", label)  # Strip required field markers
    label = re.sub(r"\s+", " ", label)
    label = re.sub(r"[^\w\s|]", "", label)  # Strip punctuation but preserve context separators
    label = label.strip()

    abbreviations = {
        "num": "number", "no": "number", "tel": "phone", "mob": "phone",
        "addr": "address", "dob": "date of birth", "exp": "experience",
        "edu": "education", "curr": "current", "yrs": "years",
    }
    tokens = [abbreviations.get(tok, tok) for tok in label.split()]
    normalized = " ".join(tokens)

    if context_prefix:
        prefix_norm = context_prefix.lower().strip()
        prefix_norm = re.sub(r"[^\w\s]", "", prefix_norm)
        return f"{prefix_norm} | {normalized}"

    return normalized

class QAStore:
    def __init__(self, path: str = "logs/qa_store.json"):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_answer(self, label: str, value: str, context_prefix: str = ""):
        key = normalize_label(label, context_prefix)
        # Store metadata structure compatible with dashboard qa_store schema
        self._data[key] = {
            "question": label.strip(),
            "answer": value.strip(),
            "portal": "Workday",
            "count": self._data.get(key, {}).get("count", 1),
            "mode": "auto"
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def exact_match(self, label: str, context_prefix: str = "") -> Optional[str]:
        entry = self._data.get(normalize_label(label, context_prefix))
        if entry:
            if isinstance(entry, dict):
                return entry.get("answer")
            return str(entry)
        return None

    def fuzzy_match(self, label: str, context_prefix: str = "", threshold: float = 0.6) -> Optional[tuple]:
        target = normalize_label(label, context_prefix)
        target_tokens = set(target.split())
        best_key, best_score = None, 0.0

        for stored_key in self._data:
            char_sim = difflib.SequenceMatcher(None, target, stored_key).ratio()

            stored_tokens = set(stored_key.split())
            if target_tokens and stored_tokens:
                overlap = len(target_tokens & stored_tokens)
                token_sim = overlap / max(len(target_tokens), len(stored_tokens))
            else:
                token_sim = 0.0

            score = (0.6 * token_sim) + (0.4 * char_sim)

            if score > best_score:
                best_key, best_score = stored_key, score

        if best_key and best_score >= threshold:
            val_entry = self._data[best_key]
            val = val_entry.get("answer") if isinstance(val_entry, dict) else str(val_entry)
            return val, min(0.95, best_score)
        return None

RESUME_FIELD_MAP = {
    "linkedin": "linkedin_url",
    "github": "github_url",
    "portfolio": "github_url",
    "years of experience": "years_of_experience",
    "phone": "phone",
    "mobile": "phone",
    "email": "email",
    "summary": "summary_text",
    "about you": "summary_text",
    "professional summary": "summary_text",
}

def resume_kb_lookup(label: str, resume_facts: dict, context_prefix: str = "") -> Optional[str]:
    norm = normalize_label(label, context_prefix)
    for keyword, fact_key in RESUME_FIELD_MAP.items():
        if keyword in norm:
            value = resume_facts.get(fact_key)
            if value:
                return value
    return None

LLM_SYSTEM_PROMPT = """You are filling out a job application form on behalf of a candidate.
You will be given the candidate's resume text and a single form field's label (and options,
if it's a dropdown/radio/checkbox). Answer ONLY with the value to put in the field — no
explanation, no extra text. If the field is a yes/no question, answer exactly "Yes" or "No".
If the field is a dropdown, answer with EXACTLY one of the provided options, verbatim.
If you cannot confidently answer from the resume, respond with exactly: UNKNOWN
"""

def llm_infer_answer(
    label: str,
    field_type: str,
    options: Optional[list],
    resume_text: str,
    call_llm: Callable[[str, str], str],
    context_prefix: str = ""
) -> Optional[tuple]:
    """Resolves field via LLM inference, checking option compatibility for select boxes."""
    # First check page-level batch cache
    norm_key = normalize_label(label, context_prefix)
    if norm_key in _PAGE_LLM_CACHE:
        val = _PAGE_LLM_CACHE[norm_key]
        if val:
            return val, 0.75

    options_block = f"\nOptions: {options}" if options else ""
    user_prompt = f"""Field label: "{label}"
Context Prefix: "{context_prefix}"
Field type: {field_type}{options_block}

Candidate resume:
---
{resume_text[:6000]}
---

Answer:"""

    raw_answer = call_llm(LLM_SYSTEM_PROMPT, user_prompt).strip()

    if raw_answer.upper() == "UNKNOWN" or not raw_answer:
        return None

    if options:
        matched = next((opt for opt in options if opt.strip().lower() == raw_answer.lower()), None)
        if not matched:
            matched = next((opt for opt in options if raw_answer.lower() in opt.lower()), None)
            if matched:
                return matched, 0.55
            return None
        return matched, 0.70

    if raw_answer.lower() in ("yes", "no"):
        return raw_answer, 0.65
    return raw_answer, 0.60

def build_human_prompt(label: str, field_type: str, options: Optional[list]) -> str:
    if options:
        return f"I couldn't confidently answer '{label}'. Choose one: {', '.join(options)}"
    return f"I couldn't confidently answer '{label}'. What should I fill in?"

def resolve_field_value(
    label: str,
    field_type: str = "text",
    options: Optional[list] = None,
    qa_store: Optional[QAStore] = None,
    resume_facts: Optional[dict] = None,
    resume_text: Optional[str] = None,
    call_llm: Optional[Callable[[str, str], str]] = None,
    ask_human: Optional[Callable[[str, str, Optional[list]], str]] = None,
    context_prefix: str = ""
) -> FieldAnswer:
    """Executes the fallback chain to resolve a field value."""
    qa_store = qa_store or QAStore()

    # Stage 1: Exact stored Q&A match
    exact = qa_store.exact_match(label, context_prefix)
    if exact:
        return FieldAnswer(value=exact, confidence=1.0, source="qa_store_exact", field_label=label)

    # Stage 2: Fuzzy stored Q&A match
    fuzzy = qa_store.fuzzy_match(label, context_prefix)
    if fuzzy:
        value, score = fuzzy
        return FieldAnswer(value=value, confidence=min(0.9, score), source="qa_store_fuzzy", field_label=label)

    # Stage 3: Resume parsed facts KB
    if resume_facts:
        kb_value = resume_kb_lookup(label, resume_facts, context_prefix)
        if kb_value:
            return FieldAnswer(value=kb_value, confidence=0.8, source="resume_kb", field_label=label)

    # Stage 4: LLM inference (Claude/Gemini)
    if call_llm and resume_text:
        try:
            inferred = llm_infer_answer(label, field_type, options, resume_text, call_llm, context_prefix)
            if inferred:
                value, conf = inferred
                return FieldAnswer(value=value, confidence=conf, source="llm", field_label=label)
        except Exception as e:
            print(f"  [RESOLVER] LLM inference failed for '{label}': {e}")

    # Stage 5: Human override fallback
    if ask_human:
        human_value = ask_human(label, field_type, options)
        if human_value:
            qa_store.save_answer(label, human_value, context_prefix)
            return FieldAnswer(value=human_value, confidence=1.0, source="human", field_label=label)

    return FieldAnswer(value="", confidence=0.0, source="none", field_label=label)
