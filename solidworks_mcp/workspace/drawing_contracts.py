"""Pure preflight checks for configuration-bound drawing views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class DrawingLayoutError(ValueError):
    """A drawing view would be invalid before any SolidWorks drawing mutation."""


@dataclass(frozen=True)
class DrawingViewRef:
    view_id: str
    document_id: str
    revision: str
    configuration: str | None
    orientation: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    height_mm: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.center_x_mm - self.width_mm / 2,
            self.center_y_mm - self.height_mm / 2,
            self.center_x_mm + self.width_mm / 2,
            self.center_y_mm + self.height_mm / 2,
        )


def _overlaps(first: DrawingViewRef, second: DrawingViewRef) -> bool:
    left_a, top_a, right_a, bottom_a = first.bounds
    left_b, top_b, right_b, bottom_b = second.bounds
    return left_a < right_b and right_a > left_b and top_a < bottom_b and bottom_a > top_b


def validate_drawing_layout(
    views: Iterable[DrawingViewRef], *, sheet_width_mm: float, sheet_height_mm: float,
) -> list[DrawingViewRef]:
    """Validate all views atomically, retaining their source configuration and revision."""
    planned = list(views)
    ids: set[str] = set()
    for view in planned:
        if not view.document_id or not view.revision or not view.configuration:
            raise DrawingLayoutError(f"View {view.view_id!r} requires document, revision, and configuration.")
        if view.view_id in ids:
            raise DrawingLayoutError(f"Duplicate drawing view id: {view.view_id}")
        ids.add(view.view_id)
        left, top, right, bottom = view.bounds
        if view.width_mm <= 0 or view.height_mm <= 0 or left < 0 or top < 0 or right > sheet_width_mm or bottom > sheet_height_mm:
            raise DrawingLayoutError(f"View {view.view_id!r} is outside the sheet bounds.")
    for index, view in enumerate(planned):
        for other in planned[index + 1:]:
            if _overlaps(view, other):
                raise DrawingLayoutError(f"Views {view.view_id!r} and {other.view_id!r} overlap.")
    return planned
