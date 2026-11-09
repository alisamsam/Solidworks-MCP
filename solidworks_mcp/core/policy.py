"""Canonical path and operation-class guard for guarded MCP workflows."""

from __future__ import annotations

from enum import Enum
import os
from pathlib import Path
from typing import Iterable

from .contracts import OperationError


class OperationClass(str, Enum):
    READ = "read"
    PROJECT_WRITE = "project_write"
    STATEFUL_READ = "stateful_read"
    MUTATE = "mutate"
    EXPORT = "export"
    RAW_EXECUTION = "raw_execution"
    SESSION = "session"


class WriteDeniedError(PermissionError):
    """A policy denial with a structured error suitable for an MCP response."""

    def __init__(self, message: str, path: Path):
        super().__init__(message)
        self.operation_error = OperationError(
            code="WRITE_DENIED", message=message, retryable=False, details={"path": str(path)}
        )


class PathPolicy:
    """Permit writes only under canonical approved output roots."""

    _WRITE_CLASSES = frozenset({
        OperationClass.STATEFUL_READ,
        OperationClass.MUTATE,
        OperationClass.EXPORT,
    })

    def __init__(self, output_roots: Iterable[Path], protected_roots: Iterable[Path] = ()) -> None:
        self.output_roots = tuple(self._canonical(root) for root in output_roots)
        self.protected_roots = tuple(self._canonical(root) for root in protected_roots)
        if not self.output_roots:
            raise ValueError("At least one approved output root is required.")

    @staticmethod
    def _canonical(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    @staticmethod
    def _is_within(candidate: Path, root: Path) -> bool:
        """Containment for Windows paths; prefix comparisons are intentionally avoided."""

        try:
            common = os.path.commonpath((os.path.normcase(str(candidate)), os.path.normcase(str(root))))
        except ValueError:
            return False
        return os.path.normcase(common) == os.path.normcase(str(root))

    def require_write(self, path: Path, operation_class: OperationClass) -> Path:
        candidate = self._canonical(path)
        if operation_class not in self._WRITE_CLASSES:
            raise WriteDeniedError(
                f"Operation class '{operation_class.value}' cannot write files.", candidate
            )
        if any(self._is_within(candidate, root) for root in self.protected_roots):
            raise WriteDeniedError("Writes to protected reference projects are denied.", candidate)
        if not any(self._is_within(candidate, root) for root in self.output_roots):
            raise WriteDeniedError("Write path is outside approved output roots.", candidate)
        return candidate
