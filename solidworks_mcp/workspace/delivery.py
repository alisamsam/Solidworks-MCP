"""Build verifiable delivery manifests from staged export artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable


class ArtifactCollisionError(ValueError):
    """Two staged artifacts would overwrite the same final package entry."""


class InvalidPublishNameError(ValueError):
    """An artifact name is unsafe for a flat delivery package."""


def _validate_publish_name(value: str) -> str:
    name = Path(value)
    if not value or name.name != value or value in {".", ".."}:
        raise InvalidPublishNameError(f"Publish name must be a single file name: {value!r}")
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_delivery_manifest(
    artifacts: Iterable[dict[str, Any]], *, source_revision: str,
    configuration: str | None, check_ids: list[str],
) -> dict[str, Any]:
    """Return a manifest only when every staged artifact is uniquely publishable."""
    artifact_list = list(artifacts)
    if not artifact_list:
        raise ValueError("A delivery package must contain at least one artifact")

    entries = []
    publish_names: set[str] = set()
    for artifact in artifact_list:
        path = Path(artifact["path"])
        publish_name = _validate_publish_name(artifact.get("publish_name", path.name))
        publish_key = publish_name.casefold()
        if publish_key in publish_names:
            raise ArtifactCollisionError(f"Duplicate publish name: {publish_name}")
        if not path.is_file():
            raise FileNotFoundError(f"Staged artifact is missing: {path}")
        publish_names.add(publish_key)
        entries.append({
            "artifact_id": artifact["artifact_id"],
            "path": str(path),
            "publish_name": publish_name,
            "format": artifact["format"],
            "sha256": _file_digest(path),
            "byte_size": path.stat().st_size,
            "source_revision": source_revision,
            "configuration": configuration,
            "check_ids": list(check_ids),
        })
    return {"schema_version": 1, "status": "staged", "artifacts": entries}
