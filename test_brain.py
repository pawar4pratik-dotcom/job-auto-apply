"""
test_brain.py — sanity tests for the resolver chain.
Run: python test_brain.py
"""

import os
import json
import sys
from field_resolver import resolve_field_value, QAStore, normalize_label
from submit_gate import SubmitGate

# Ensure standard output uses UTF-8 to prevent Windows terminal encoding crashes
if sys.platform.startswith("win"):
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

os.makedirs("logs", exist_ok=True)
TEST_QA_PATH = "logs/test_qa_store.json"
if os.path.exists(TEST_QA_PATH):
    try:
        os.remove(TEST_QA_PATH)
    except Exception:
        pass


def fake_llm(system, user):
    """Stub LLM: simulates Claude/Gemini reading the resume."""
    if "willing to relocate" in user.lower():
        return "Yes"
    if "expected salary" in user.lower():
        return "UNKNOWN"
    return "UNKNOWN"


def fake_human(label, field_type, options):
    return "₹18,00,000 per annum"


print("=" * 70)
print("TEST 1: normalize_label handles ATS label noise and context prefixing")
print("=" * 70)
cases = [
    ("Phone Number *", "", "phone number"),
    ("  Email Address:  ", "", "email address"),
    ("LinkedIn Profile (optional)", "", "linkedin profile optional"),
    ("Job Title", "Work Experience 1", "work experience 1 | job title"),
    ("From", "Education 2", "education 2 | from"),
]
for raw, prefix, expected in cases:
    got = normalize_label(raw, prefix)
    status = "PASS" if got == expected else "FAIL"
    print(f"  [{status}] '{raw}' (prefix={prefix!r}) -> '{got}'")

print()
print("=" * 70)
print("TEST 2: Stage 1 - qa_store exact match (fast path, conf=1.0)")
print("=" * 70)
qa_store = QAStore(path=TEST_QA_PATH)
qa_store.save_answer("Phone Number", "+91-9876543210")

answer = resolve_field_value("Phone Number *", field_type="text", qa_store=qa_store)
print(f"  value={answer.value!r} confidence={answer.confidence} source={answer.source}")
assert answer.source == "qa_store_exact" and answer.confidence == 1.0
print("  [PASS]")

print()
print("=" * 70)
print("TEST 3: Stage 2 - qa_store fuzzy match (slightly different label wording)")
print("=" * 70)
answer = resolve_field_value("Mobile Phone Num.", field_type="text", qa_store=qa_store)
print(f"  value={answer.value!r} confidence={answer.confidence:.2f} source={answer.source}")
assert answer.source in ("qa_store_fuzzy", "qa_store_exact")
print("  [PASS]")

print()
print("=" * 70)
print("TEST 4: Stage 3 - resume KB lookup (no qa_store entry, but resume has it)")
print("=" * 70)
resume_facts = {
    "linkedin_url": "linkedin.com/in/janedoe",
    "email": "jane@example.com",
    "years_of_experience": "5",
}
answer = resolve_field_value(
    "LinkedIn URL", field_type="text",
    qa_store=QAStore(path=TEST_QA_PATH),
    resume_facts=resume_facts,
)
print(f"  value={answer.value!r} confidence={answer.confidence} source={answer.source}")
assert answer.source == "resume_kb" and answer.value == "linkedin.com/in/janedoe"
print("  [PASS]")

print()
print("=" * 70)
print("TEST 5: Stage 4 - LLM inference (nothing in qa_store or resume KB)")
print("=" * 70)
answer = resolve_field_value(
    "Are you willing to relocate?", field_type="yesno",
    qa_store=QAStore(path=TEST_QA_PATH),
    resume_facts={},
    resume_text="Jane Doe is a software engineer based in Mumbai...",
    call_llm=fake_llm,
)
print(f"  value={answer.value!r} confidence={answer.confidence} source={answer.source}")
assert answer.source == "llm" and answer.value == "Yes"
print("  [PASS]")

print()
print("=" * 70)
print("TEST 6: Stage 5 - human fallback (LLM says UNKNOWN, must escalate)")
print("=" * 70)
fresh_store = QAStore(path=TEST_QA_PATH)
answer = resolve_field_value(
    "Expected salary (INR)", field_type="text",
    qa_store=fresh_store,
    resume_facts={},
    resume_text="...",
    call_llm=fake_llm,
    ask_human=fake_human,
)
print(f"  value={answer.value!r} confidence={answer.confidence} source={answer.source}")
assert answer.source == "human" and answer.confidence == 1.0

# Verify it got learned
answer2 = resolve_field_value("Expected salary (INR)", field_type="text", qa_store=fresh_store)
print(f"  re-query -> source={answer2.source} (should now be qa_store_exact)")
assert answer2.source == "qa_store_exact"
print("  [PASS] Bot learned from human answer")

print()
print("=" * 70)
print("TEST 7: Submit gate - blocks on low confidence, allows on high confidence")
print("=" * 70)
gate = SubmitGate()
gate.record(resolve_field_value("Phone Number", qa_store=qa_store))
result = gate.evaluate()
print(f"  All high-confidence -> can_auto_submit={result.can_auto_submit} ({result.reason})")
assert result.can_auto_submit

gate2 = SubmitGate()
from field_resolver import FieldAnswer
gate2.record(FieldAnswer(value="maybe", confidence=0.45, source="llm", field_label="Visa sponsorship needed?"))
result2 = gate2.evaluate()
print(f"  One low-confidence field -> can_auto_submit={result2.can_auto_submit} ({result2.reason})")
assert not result2.can_auto_submit
print("  [PASS] Gate correctly blocks low confidence")

print()
print("=" * 70)
print("ALL TESTS PASSED SUCCESSFULLY")
print("=" * 70)
