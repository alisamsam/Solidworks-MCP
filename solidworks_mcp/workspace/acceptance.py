"""Aggregate explicit acceptance checks without AI-derived promotion."""

from __future__ import annotations

from typing import Any, Iterable


_PRIORITY = {"passed": 0, "not_run": 1, "needs_review": 2, "blocked": 3, "failed": 4}


def aggregate_checks(checks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return the worst required outcome and its blocking check identifiers."""
    required = [check for check in checks if check.get("required", True)]
    if not required:
        return {"status": "needs_review", "blocking_check_ids": []}
    worst = max(required, key=lambda check: _PRIORITY.get(check.get("status"), 3))
    status = worst.get("status", "blocked")
    if status == "passed":
        return {"status": "passed", "blocking_check_ids": []}
    return {
        "status": status,
        "blocking_check_ids": [
            check["check_id"] for check in required if check.get("status") != "passed"
        ],
    }
