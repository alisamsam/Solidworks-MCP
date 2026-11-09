"""Bounded repair-attempt bookkeeping for guarded workflows."""

from __future__ import annotations


class RepairBudgetExceeded(RuntimeError):
    """No further repair attempt may run for this job."""


class RepairJournal:
    def __init__(self, max_attempts: int = 2) -> None:
        self.max_attempts = max_attempts
        self._attempts: list[dict[str, object]] = []

    def record_attempt(self, reason: str, checkpoint: str) -> None:
        if len(self._attempts) >= self.max_attempts:
            raise RepairBudgetExceeded("Repair attempt limit reached; return blocked or restore checkpoint.")
        if not reason or not checkpoint:
            raise ValueError("Every repair attempt requires a reason and checkpoint.")
        self._attempts.append({
            "attempt": len(self._attempts) + 1,
            "reason": reason,
            "checkpoint": checkpoint,
        })

    def to_dict(self) -> dict[str, object]:
        return {"max_attempts": self.max_attempts, "attempts": list(self._attempts)}
