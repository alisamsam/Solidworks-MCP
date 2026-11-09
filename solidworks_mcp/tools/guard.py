"""Shared guarded-mode adapters for MCP tool handlers."""

from pathlib import Path

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass, WriteDeniedError


def require_output_write(sw, output_path: str):
    """Return a legacy denial result before a tool touches COM, if guarded."""
    policy = getattr(sw, "_path_policy", None)
    if policy is None:
        return None
    try:
        policy.require_write(Path(output_path), OperationClass.EXPORT)
    except WriteDeniedError as error:
        return sw._result(False, f"Write denied: {error}", SwErrors.swExportError)
    return None


def require_stateful_document_access(sw, document):
    """Deny temporary document mutations outside trusted output roots."""
    policy = getattr(sw, "_path_policy", None)
    if policy is None:
        return None
    try:
        path = com(document, "GetPathName")
        policy.require_write(Path(path), OperationClass.STATEFUL_READ)
    except (WriteDeniedError, TypeError, ValueError) as error:
        return sw._result(False, f"Write denied: {error}", SwErrors.swFeatureError)
    return None
