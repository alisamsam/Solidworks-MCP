"""Session-local snapshot cache and opaque paging cursors."""

from __future__ import annotations

import base64
import json

from ..core.contracts import DocumentRef
from ..core.snapshot import ProjectSnapshot, SnapshotCoverage


class SnapshotCursorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, tuple[ProjectSnapshot, DocumentRef]] = {}

    @staticmethod
    def _cursor(snapshot_id: str, offset: int) -> str:
        payload = json.dumps(
            {"snapshot_id": snapshot_id, "offset": offset},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(cursor: str) -> tuple[str, int]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            return str(payload["snapshot_id"]), int(payload["offset"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SnapshotCursorError("VALIDATION_FAILED", "Invalid snapshot cursor.") from error

    @staticmethod
    def _same_target(expected: DocumentRef, actual: DocumentRef) -> bool:
        return (
            expected.document_id == actual.document_id
            and expected.configuration == actual.configuration
            and expected.revision_token == actual.revision_token
        )

    def add(
        self, snapshot: ProjectSnapshot, target: DocumentRef, *, page_size: int
    ) -> ProjectSnapshot:
        self._snapshots[snapshot.snapshot_id] = (snapshot, target)
        return self._page(snapshot, offset=0, page_size=page_size)

    def resume(
        self, cursor: str | None, target: DocumentRef, *, page_size: int
    ) -> ProjectSnapshot:
        if not cursor:
            raise SnapshotCursorError("VALIDATION_FAILED", "A non-empty cursor is required.")
        snapshot_id, offset = self._decode(cursor)
        stored = self._snapshots.get(snapshot_id)
        if stored is None:
            raise SnapshotCursorError("STALE_REFERENCE", "Snapshot cursor is no longer available.")
        snapshot, expected_target = stored
        if not self._same_target(expected_target, target):
            raise SnapshotCursorError(
                "STALE_REFERENCE", "Document, configuration, or revision changed after inspection."
            )
        return self._page(snapshot, offset=offset, page_size=page_size)

    def _page(self, snapshot: ProjectSnapshot, *, offset: int, page_size: int) -> ProjectSnapshot:
        if page_size < 1:
            raise SnapshotCursorError("VALIDATION_FAILED", "page_size must be at least 1.")
        instances = snapshot.instances[offset:offset + page_size]
        next_offset = offset + len(instances)
        has_more = next_offset < len(snapshot.instances)
        coverage = SnapshotCoverage(
            complete=snapshot.coverage.complete,
            visited_count=len(instances),
            unresolved=snapshot.coverage.unresolved,
            truncated=has_more,
            next_cursor=self._cursor(snapshot.snapshot_id, next_offset) if has_more else None,
        )
        return ProjectSnapshot(
            snapshot_id=snapshot.snapshot_id,
            documents=snapshot.documents,
            instances=instances,
            dependency_edges=snapshot.dependency_edges,
            observations=snapshot.observations,
            coverage=coverage,
        )
