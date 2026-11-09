"""Shared, COM-independent contracts for SolidWorks MCP operations."""

from .contracts import DocumentRef, OperationError, OperationResult, OperationStatus
from .evidence import OperationJournal
from .snapshot import InstanceRef, ProjectSnapshot, SnapshotCoverage

__all__ = [
    "DocumentRef",
    "OperationError",
    "OperationJournal",
    "OperationResult",
    "OperationStatus",
    "InstanceRef",
    "ProjectSnapshot",
    "SnapshotCoverage",
]
