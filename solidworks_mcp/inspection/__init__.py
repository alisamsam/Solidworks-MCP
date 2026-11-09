"""Structured read-only inspection of SolidWorks projects."""

from .snapshots import SnapshotCursorError, SnapshotStore
from .documents import inspect_feature_tree

__all__ = ["SnapshotCursorError", "SnapshotStore", "inspect_feature_tree"]
