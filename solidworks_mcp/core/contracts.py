"""Stable data contracts shared by MCP tools and their evidence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable, Mapping


class OperationStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class QuantityValidationError(ValueError):
    """Raised when a dimensional value is not safe to pass to SolidWorks."""


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str


def validate_quantity(
    value: float,
    unit: str,
    allowed_units: Iterable[str],
    *,
    minimum: float | None = None,
) -> Quantity:
    """Validate a finite quantity against the units supported by one operation."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuantityValidationError("Quantity value must be a finite number.")
    if not math.isfinite(float(value)):
        raise QuantityValidationError("Quantity value must be finite.")
    numeric_value = float(value)
    if minimum is not None and numeric_value < minimum:
        raise QuantityValidationError(f"Quantity value must be at least {minimum}.")
    supported_units = set(allowed_units)
    if unit not in supported_units:
        choices = ", ".join(sorted(supported_units))
        raise QuantityValidationError(f"Unsupported unit '{unit}'. Supported units: {choices}.")
    return Quantity(value=numeric_value, unit=unit)


@dataclass(frozen=True)
class DocumentRef:
    document_id: str
    path: str | None
    document_type: str
    configuration: str | None = None
    revision_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "path": self.path,
            "document_type": self.document_type,
            "configuration": self.configuration,
            "revision_token": self.revision_token,
        }


@dataclass(frozen=True)
class OperationError:
    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    status: OperationStatus
    target_before: DocumentRef | None = None
    target_after: DocumentRef | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[OperationError, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def completed(
        cls,
        operation_id: str,
        target_after: DocumentRef | None,
        data: Mapping[str, Any],
        **kwargs: Any,
    ) -> "OperationResult":
        return cls(
            operation_id=operation_id,
            status=OperationStatus.COMPLETED,
            target_after=target_after,
            data=data,
            **kwargs,
        )

    @classmethod
    def unknown(
        cls, operation_id: str, target_after: DocumentRef | None, message: str
    ) -> "OperationResult":
        return cls(
            operation_id=operation_id,
            status=OperationStatus.UNKNOWN,
            target_after=target_after,
            errors=(OperationError("OPERATION_OUTCOME_UNKNOWN", message, retryable=False),),
        )

    @classmethod
    def failed(
        cls, operation_id: str, target_after: DocumentRef | None, message: str
    ) -> "OperationResult":
        return cls(
            operation_id=operation_id,
            status=OperationStatus.FAILED,
            target_after=target_after,
            errors=(OperationError("COM_ERROR", message, retryable=False),),
        )

    def to_dict(self, legacy: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a schema-v1 envelope while retaining a tool's legacy fields."""

        result = dict(legacy or {})
        result.update(
            {
                "schema_version": 1,
                "operation_id": self.operation_id,
                "status": self.status.value,
                "target_before": self.target_before.to_dict() if self.target_before else None,
                "target_after": self.target_after.to_dict() if self.target_after else None,
                "data": dict(self.data),
                "warnings": list(self.warnings),
                "errors": [error.to_dict() for error in self.errors],
                "evidence": dict(self.evidence),
            }
        )
        return result
