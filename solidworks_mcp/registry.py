"""
Tool registry for the SolidWorks MCP server.

Every tool is a decorated function in solidworks_mcp/tools/. execute() applies
the shared document guard and postflight, so the server only records results.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from jsonschema import Draft7Validator
from mcp.types import Tool

from .constants import SwErrors
from .core.policy import OperationClass
from .core.session import TargetMismatchError
from .validation import ArgumentError, validate_arguments

logger = logging.getLogger("SolidWorksMCP")

_TOOLS: Dict[str, Dict] = {}
_loaded = False

_POSTFLIGHTS = {None, "bind", "bound", "save", "none"}
_GUARDED_CLASSES = frozenset({
    OperationClass.STATEFUL_READ,
    OperationClass.MUTATE,
    OperationClass.EXPORT,
})


def tool(
    name: str,
    description: str,
    schema: Dict,
    operation_class: OperationClass,
    postflight: Optional[str] = None,
    com: bool = True,
) -> Callable:
    """
    Register a function as an MCP tool.

    The handler receives the SolidWorksAutomation instance as its first
    argument, followed by the schema arguments as keywords, and returns a
    result dictionary built with sw._result().

    Args:
        name: Tool name, snake_case
        description: One sentence: what it does and what it acts on
        schema: JSON schema for the tool input
        operation_class: Execution semantics; guarded classes bind the document first
        postflight: Target after success: None = mark a mutation, "bind" = bind the
            new active document, "bound" = report the bound document, "save" = rebind
            when Save As changed the identity, "none" = keep the target unchanged
        com: False for tools that never touch COM; the server runs them beside a busy COM thread

    Returns:
        Decorator that registers the function
    """
    if postflight not in _POSTFLIGHTS:
        raise ValueError(f"Unknown postflight for {name}: {postflight}")

    def decorator(fn: Callable) -> Callable:
        if name in _TOOLS:
            raise ValueError(f"Tool already registered: {name}")
        _TOOLS[name] = {
            "tool": Tool(name=name, description=description, inputSchema=schema),
            "handler": fn,
            "operation_class": operation_class,
            "postflight": postflight,
            "com": com,
        }
        return fn
    return decorator


def _load() -> None:
    """Import the tools package once, so the decorators run"""
    global _loaded
    if _loaded:
        return
    try:
        from . import tools  # noqa: F401
    except Exception as e:
        logger.error(f"Failed to import tools package: {e}")
        raise
    _loaded = True


def registered_tools() -> List[Tool]:
    """All registered tool definitions"""
    _load()
    return [entry["tool"] for entry in _TOOLS.values()]


def operation_class_for(name: str) -> OperationClass | None:
    """Return declared execution semantics for a registered tool."""
    _load()
    entry = _TOOLS.get(name)
    return entry["operation_class"] if entry is not None else None


def needs_com_thread(name: str) -> bool:
    """False only for registered tools that declared they never touch COM."""
    _load()
    entry = _TOOLS.get(name)
    return entry is None or entry["com"]


def tool_module_for(name: str) -> str | None:
    """Source domain for generated catalogs, independent of tool counts."""
    _load()
    entry = _TOOLS.get(name)
    return entry["handler"].__module__ if entry is not None else None


@dataclass(frozen=True)
class Execution:
    """A tool result with the document targets before and after it ran."""
    result: Dict
    target_before: Any = None
    target_after: Any = None


def execute(name: str, sw, arguments: Dict) -> Execution:
    """Run a registered tool with its document guard and postflight."""
    _load()
    entry = _TOOLS.get(name)
    if entry is None:
        return Execution(sw._result(False, f"Unknown tool: {name}", SwErrors.swUnknownError))
    # Catalog visibility is not permission. Reject before validation, binding or COM.
    from . import catalog
    if catalog.toolset_of(name) == "routing" and not catalog.routing_enabled():
        return Execution(sw._result(
            False,
            "Routing is disabled. Enable routing_enabled or SW_MCP_ROUTING_ENABLED=true "
            "and restart the MCP server; add routing to the requested toolsets to advertise it.",
            SwErrors.swInvalidInput,
            {"code": "ROUTING_DISABLED"},
        ))
    validator = entry.get("validator")
    if validator is None:
        validator = entry["validator"] = Draft7Validator(entry["tool"].inputSchema)
    try:
        arguments = validate_arguments(entry["tool"].inputSchema, validator, arguments)
    except ArgumentError as error:
        return Execution(sw._result(
            False,
            str(error),
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED", "argument": error.argument},
        ))
    before = None
    if entry["operation_class"] in _GUARDED_CLASSES and hasattr(sw, "bind_active_document"):
        try:
            if hasattr(sw, "has_bound_document") and sw.has_bound_document():
                before = sw.require_bound_active_document()
            else:
                before = sw.bind_active_document()
        except TargetMismatchError as error:
            detail = error.operation_error
            return Execution(sw._result(
                False,
                str(error),
                SwErrors.swInvalidInput,
                {"code": detail.code, "retryable": detail.retryable},
            ))
    managed_token = None
    if (entry['operation_class'] in (OperationClass.MUTATE, OperationClass.STATEFUL_READ)
            and hasattr(sw, '_begin_managed_operation')):
        managed_token = sw._begin_managed_operation()
    try:
        result = entry["handler"](sw, **arguments)
        if result is None:
            raise ValueError(f"Tool returned no result: {name}")
        after = _postflight(entry, sw, before) if result.get("success") else before
        if not result.get('success') and managed_token is not None:
            sw._end_failed_managed_operation(managed_token)
    except Exception as error:
        if managed_token is not None:
            sw._end_failed_managed_operation(managed_token)
        error.target_before = before  # lets the server journal which document the call started on
        raise
    return Execution(result, before, after)


def _postflight(entry: Dict, sw, before):
    mode = entry["postflight"]
    if mode == "bind":
        return sw.bind_active_document()
    if mode == "bound":
        return sw.require_bound_active_document()
    if mode == "save" and before is not None:
        saved, error = sw.capture_active_document_ref()
        if error:
            raise RuntimeError(error["message"])
        if saved.document_id != before.document_id or saved.path != before.path:
            return sw.bind_active_document()
        return sw.mark_active_document_mutated(before)
    if (
        mode is None
        and before is not None
        and entry["operation_class"] is OperationClass.MUTATE
        and hasattr(sw, "mark_active_document_mutated")
    ):
        return sw.mark_active_document_mutated(before)
    return before


def dispatch(name: str, sw, arguments: Dict) -> Optional[Dict]:
    """Run a registered tool; returns its result, or None if the name is unknown."""
    _load()
    if name not in _TOOLS:
        return None
    return execute(name, sw, arguments).result
