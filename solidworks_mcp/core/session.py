"""Pure document-target validation and legacy result adaptation."""

from __future__ import annotations

from dataclasses import dataclass
import ntpath
from typing import Any, Mapping
from collections.abc import Callable
from uuid import uuid4

from .contracts import DocumentRef, OperationError, OperationResult, OperationStatus


class TargetMismatchError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.operation_error = OperationError(code=code, message=message, retryable=False)


@dataclass(frozen=True)
class SessionTarget:
    document_id: str
    canonical_path: str | None
    document_type: str
    configuration: str | None
    revision_token: str | None

    @classmethod
    def from_document(cls, document: DocumentRef) -> "SessionTarget":
        return cls(
            document_id=document.document_id,
            canonical_path=document.path,
            document_type=document.document_type,
            configuration=document.configuration,
            revision_token=document.revision_token,
        )


class SessionState:
    def __init__(self) -> None:
        self.target: SessionTarget | None = None

    def bind(self, document: DocumentRef) -> SessionTarget:
        self.target = SessionTarget.from_document(document)
        return self.target


class DocumentSession:
    """Own serializable document identities and MCP-side revision tokens.

    No COM object is retained here.  The automation adapter takes a fresh
    snapshot on the owning COM thread and passes only strings and integers.
    """

    def __init__(self, id_factory: Callable[[], str] | None = None) -> None:
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._document_ids: dict[tuple[str, ...], str] = {}
        self._revisions: dict[str, int] = {}
        self.state = SessionState()

    @staticmethod
    def _key(*, title: str, path: str | None, document_type: str) -> tuple[str, ...]:
        if path:
            canonical = ntpath.normcase(ntpath.normpath(path))
            return ("path", canonical)
        return ("unsaved", document_type.casefold(), title.casefold())

    def capture(
        self,
        *,
        title: str,
        path: str | None,
        document_type: str,
        configuration: str | None,
    ) -> DocumentRef:
        key = self._key(title=title, path=path, document_type=document_type)
        document_id = self._document_ids.get(key)
        if document_id is None:
            document_id = self._id_factory()
            self._document_ids[key] = document_id
            self._revisions[document_id] = 0
        return DocumentRef(
            document_id=document_id,
            path=ntpath.normpath(path) if path else None,
            document_type=document_type.casefold(),
            configuration=configuration,
            revision_token=f"mcp:{self._revisions[document_id]}",
        )

    def bind(self, **snapshot: Any) -> DocumentRef:
        document = self.capture(**snapshot)
        self.state.bind(document)
        return document

    def require_bound(self, actual: DocumentRef) -> None:
        if self.state.target is None:
            raise TargetMismatchError("WRONG_DOCUMENT", "No document is bound to this session.")
        require_target(self.state.target, actual)

    def mark_mutated(self, before: DocumentRef) -> DocumentRef:
        self.require_bound(before)
        self._revisions[before.document_id] += 1
        after = DocumentRef(
            document_id=before.document_id,
            path=before.path,
            document_type=before.document_type,
            configuration=before.configuration,
            revision_token=f"mcp:{self._revisions[before.document_id]}",
        )
        self.state.bind(after)
        return after


def require_target(target: SessionTarget, actual: DocumentRef) -> None:
    """Reject a focus/configuration/revision change before calling COM."""

    if target.document_id != actual.document_id or target.canonical_path != actual.path:
        raise TargetMismatchError("WRONG_DOCUMENT", "The active document differs from the bound target.")
    if target.configuration != actual.configuration:
        raise TargetMismatchError("WRONG_DOCUMENT", "The active configuration differs from the bound target.")
    if target.revision_token != actual.revision_token:
        raise TargetMismatchError("STALE_REFERENCE", "The document revision differs from the bound target.")


def with_operation_metadata(
    legacy: Mapping[str, Any],
    *,
    operation_id: str,
    target_before: DocumentRef | None,
    target_after: DocumentRef | None,
    status: OperationStatus,
    warnings: tuple[str, ...] = (),
    errors: tuple[OperationError, ...] = (),
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add the v1 envelope to an existing MCP response without removing fields."""

    result = OperationResult(
        operation_id=operation_id,
        status=status,
        target_before=target_before,
        target_after=target_after,
        data=dict(legacy.get("data", {})),
        warnings=warnings,
        errors=errors,
        evidence=dict(evidence or {}),
    )
    return result.to_dict(legacy=legacy)
