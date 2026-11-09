"""Precondition checks for parameter edits before any COM mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class StaleParameterError(ValueError):
    """The model revision or driving value changed since the request was prepared."""


@dataclass(frozen=True)
class ParameterChange:
    selector: str
    expected_old_value: float
    new_value: float


def validate_parameter_changes(
    changes: list[ParameterChange], *, expected_revision: str, actual_revision: str,
    current_values: Mapping[str, float],
) -> list[ParameterChange]:
    """Validate a batch atomically; callers mutate nothing until it returns."""
    if expected_revision != actual_revision:
        raise StaleParameterError("Document revision changed before parameter edit.")
    for change in changes:
        current = current_values.get(change.selector)
        if current != change.expected_old_value:
            raise StaleParameterError(
                f"Driving value for {change.selector} no longer matches expected value."
            )
    return changes
