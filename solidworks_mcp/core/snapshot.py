"""Serializable project-structure facts for reference-model inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import DocumentRef


@dataclass(frozen=True)
class SnapshotCoverage:
    complete: bool
    visited_count: int
    unresolved: tuple[str, ...] = ()
    truncated: bool = False
    next_cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "visited_count": self.visited_count,
            "unresolved": list(self.unresolved),
            "truncated": self.truncated,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class InstanceRef:
    instance_path: str
    parent_path: str | None
    document_id: str
    configuration: str | None
    transform: tuple[float, ...] | None = None
    suppression_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_path": self.instance_path,
            "parent_path": self.parent_path,
            "document_id": self.document_id,
            "configuration": self.configuration,
            "transform": list(self.transform) if self.transform else None,
            "suppression_state": self.suppression_state,
        }


@dataclass(frozen=True)
class ProjectSnapshot:
    snapshot_id: str
    documents: tuple[DocumentRef, ...]
    instances: tuple[InstanceRef, ...]
    coverage: SnapshotCoverage
    dependency_edges: tuple[dict[str, Any], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "documents": [document.to_dict() for document in self.documents],
            "instances": [instance.to_dict() for instance in self.instances],
            "dependency_edges": [dict(edge) for edge in self.dependency_edges],
            "observations": [dict(observation) for observation in self.observations],
            "coverage": self.coverage.to_dict(),
        }
