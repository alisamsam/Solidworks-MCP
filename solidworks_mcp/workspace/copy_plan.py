"""Pure planning for an isolated project copy; this module never writes files."""

from __future__ import annotations

from pathlib import PureWindowsPath
from typing import Any

from ..core.snapshot import ProjectSnapshot


class CopyPlanError(ValueError):
    """The requested copy would be unsafe or ambiguous."""


def _normal_path(path: PureWindowsPath) -> str:
    return str(path).replace("\\", "/")


def plan_project_copy(
    snapshot: ProjectSnapshot, output_root: str, library_policy: str
) -> dict[str, Any]:
    """Build a deterministic, write-free manifest for a self-contained project copy."""
    if not snapshot.coverage.complete:
        raise CopyPlanError("Copy planning requires complete source snapshot coverage.")
    unresolved_mutable = [
        edge for edge in snapshot.dependency_edges
        if edge.get("kind") == "mutable" and edge.get("state") == "unresolved"
    ]
    if unresolved_mutable:
        raise CopyPlanError("Copy planning is blocked by unresolved mutable dependencies.")
    if library_policy not in {"copy", "reuse_read_only"}:
        raise CopyPlanError("library_policy must be 'copy' or 'reuse_read_only'.")

    root = PureWindowsPath(output_root)
    documents = []
    for document in sorted(snapshot.documents, key=lambda item: item.document_id):
        source_name = PureWindowsPath(document.path).name
        destination = root / f"{document.document_id}-{source_name}"
        documents.append({
            "document_id": document.document_id,
            "source": document.path,
            "destination": _normal_path(destination),
            "configuration": document.configuration,
            "copy_mode": library_policy,
        })
    return {
        "schema_version": 1,
        "source_snapshot_id": snapshot.snapshot_id,
        "output_root": _normal_path(root),
        "library_policy": library_policy,
        "documents": documents,
        "unresolved_edges": [],
    }
