"""Conservative interpretation of the first reference-frame workflow."""

from __future__ import annotations

import re
from typing import Any


def _millimetres(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return float(match.group(1).replace(",", ".")) if match else None


def interpret_frame_request(request: str) -> dict[str, Any]:
    """Interpret only explicit width requests; uncertain language never mutates a model."""
    preserved = _millimetres(r"ohrani\s+zunanjo\s+širino\s+(\d+(?:[,.]\d+)?)\s*mm", request)
    target = _millimetres(r"povečaj\s+na\s+(\d+(?:[,.]\d+)?)\s*mm", request)
    if preserved is not None and target is not None and preserved != target:
        return {"status": "needs_review", "changes": [], "reasons": ["contradiction"]}

    delta = _millimetres(r"razširi\s+(?:okvir\s+)?za\s+(\d+(?:[,.]\d+)?)\s*mm", request)
    if delta is not None:
        return {
            "status": "ready",
            "changes": [{"parameter": "width", "delta_mm": delta}],
            "invariants": ["profile", "material", "height", "body_count", "joints"],
            "reasons": [],
        }
    return {
        "status": "needs_review",
        "changes": [],
        "reasons": ["width_change_requires_an_explicit_absolute_or_delta_dimension"],
    }


def validate_frame_invariants(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Return every required frame property that changed or became unavailable."""
    invariants = ("profile", "material", "height_mm", "body_count", "joints")
    return [name for name in invariants if after.get(name) != before.get(name)]
