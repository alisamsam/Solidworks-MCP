"""Exact, revision-bound references for model and assembly entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


class AmbiguousEntityError(ValueError):
    """The requested entity is not represented by exactly one live candidate."""


@dataclass(frozen=True)
class EntityRef:
    document_id: str
    revision: str
    configuration: str | None
    entity_kind: str
    instance_path: str | None
    entity_name: str

    def matches(self, candidate: dict[str, Any]) -> bool:
        return all(candidate.get(key) == value for key, value in {
            "document_id": self.document_id,
            "revision": self.revision,
            "configuration": self.configuration,
            "entity_kind": self.entity_kind,
            "instance_path": self.instance_path,
            "entity_name": self.entity_name,
        }.items())


def resolve_entity(reference: EntityRef, candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return the only exact candidate; never fall back to index or suffix matching."""
    matches = [candidate for candidate in candidates if reference.matches(candidate)]
    if len(matches) != 1:
        raise AmbiguousEntityError(
            f"Expected exactly one {reference.entity_kind} for {reference.instance_path!r}; "
            f"found {len(matches)} exact matches."
        )
    return matches[0]
