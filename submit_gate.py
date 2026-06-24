"""
submit_gate.py
─────────────────
Aggregates FieldAnswer confidence scores across a single application page and
decides whether the bot is allowed to auto-click "Next"/"Submit", or must pause
and hand control back to the human.
"""

from dataclasses import dataclass, field
from typing import List
from field_resolver import FieldAnswer


REVIEW_THRESHOLD = 0.55          # any single field below this always blocks auto-submit
AUTO_SUBMIT_THRESHOLD = 0.75     # average non-perfect confidence must clear this bar


@dataclass
class PageGateResult:
    can_auto_submit: bool
    low_confidence_fields: List[FieldAnswer] = field(default_factory=list)
    average_confidence: float = 0.0
    reason: str = ""


class SubmitGate:
    def __init__(self):
        self.answers: List[FieldAnswer] = []

    def record(self, answer: FieldAnswer):
        self.answers.append(answer)

    def reset(self):
        self.answers = []

    def evaluate(self) -> PageGateResult:
        if not self.answers:
            return PageGateResult(can_auto_submit=True, reason="No fields were resolved on this page.")

        # Human-filled inputs are fully trusted
        scored = [a for a in self.answers if a.source != "human"]

        low_conf = [a for a in self.answers if a.confidence < REVIEW_THRESHOLD]
        if low_conf:
            field_names = ", ".join(f"'{a.field_label}'" for a in low_conf)
            return PageGateResult(
                can_auto_submit=False,
                low_confidence_fields=low_conf,
                average_confidence=self._avg(scored),
                reason=f"Low-confidence answers need review: {field_names}",
            )

        avg = self._avg(scored)
        if scored and avg < AUTO_SUBMIT_THRESHOLD:
            return PageGateResult(
                can_auto_submit=False,
                low_confidence_fields=[a for a in scored if a.confidence < AUTO_SUBMIT_THRESHOLD],
                average_confidence=avg,
                reason=f"Average confidence {avg:.2f} is below the auto-submit bar ({AUTO_SUBMIT_THRESHOLD}).",
            )

        return PageGateResult(
            can_auto_submit=True,
            average_confidence=avg,
            reason="All fields confidently resolved.",
        )

    @staticmethod
    def _avg(answers: List[FieldAnswer]) -> float:
        if not answers:
            return 1.0
        return sum(a.confidence for a in answers) / len(answers)
