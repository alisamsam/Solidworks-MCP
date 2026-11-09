"""Read-only feature, parameter, and equation inspection."""

from __future__ import annotations

from typing import Any

from ..comutil import com


def inspect_dependencies(document) -> dict[str, Any]:
    """Return document dependency pairs without hiding broken references.

    The current extension API is preferred.  The obsolete document API is a
    compatibility fallback for older SolidWorks releases or unusual COM
    dispatch wrappers.
    """
    evidence: list[str] = []
    unresolved: list[str] = []
    source_method = "IModelDocExtension.GetDependencies"

    try:
        extension = com(document, "Extension")
        payload = com(extension, "GetDependencies", True, False, False, True, True)
    except Exception as extension_error:
        source_method = "IModelDoc2.GetDependencies2"
        evidence.append(
            f"Compatibility fallback used after extension API failure: {extension_error}"
        )
        try:
            payload = com(document, "GetDependencies2", True, False, False)
        except Exception as fallback_error:
            unresolved.append(
                "Dependency inspection unavailable: "
                f"extension={extension_error}; fallback={fallback_error}"
            )
            return {
                "dependencies": [],
                "unresolved": unresolved,
                "complete": False,
                "source_method": source_method,
                "evidence": evidence,
            }

    if payload is None:
        values: list[Any] = []
    elif isinstance(payload, (list, tuple)):
        values = list(payload)
    else:
        values = [payload]

    dependencies = []
    for index in range(0, len(values), 2):
        raw_name = values[index]
        raw_path = values[index + 1] if index + 1 < len(values) else None
        name = str(raw_name) if raw_name not in (None, "") else "<unknown>"
        path = str(raw_path).strip() if raw_path not in (None, "") else None
        state = "known" if path else "unresolved"
        dependencies.append({
            "name": name,
            "path": path,
            "state": state,
            "source": source_method,
        })
        if not path:
            unresolved.append(f"Dependency {name}: referenced path is unavailable")

    return {
        "dependencies": dependencies,
        "unresolved": unresolved,
        "complete": not unresolved,
        "source_method": source_method,
        "evidence": evidence,
    }


def inspect_feature_tree(document, *, max_depth: int = 8) -> dict[str, Any]:
    """Read a feature tree without dropping unknown nodes or unavailable values."""
    unresolved: list[str] = []
    visited: set[int] = set()
    retained_com_wrappers: list[Any] = []

    def optional(obj, member, context, *args):
        try:
            return com(obj, member, *args)
        except Exception as error:
            unresolved.append(f"{context}: {member} unavailable ({error})")
            return None

    def parameters(feature, path):
        values = []
        display = optional(feature, "GetFirstDisplayDimension", path)
        seen = set()
        while display is not None and id(display) not in seen:
            # Keep each COM proxy alive while walking the linked dimension
            # list. Otherwise Python can reuse its id for a later proxy and
            # falsely report a cycle after only a few dimensions.
            retained_com_wrappers.append(display)
            seen.add(id(display))
            dimension = optional(display, "GetDimension2", path, 0)
            if dimension is not None:
                name = optional(dimension, "FullName", path) or "<unknown>"
                resolved = optional(dimension, "SystemValue", f"{path}/{name}")
                values.append({
                    "name": name,
                    "raw_value": None,
                    "resolved_value_m": resolved,
                    "state": "known" if resolved is not None else "unavailable",
                    "source": "SolidWorks dimension",
                })
            display = optional(feature, "GetNextDisplayDimension", path, display)
        return values

    def node(feature, path, depth):
        # Keep pywin32 wrappers alive: otherwise Python may reuse id() for a
        # later COM proxy and create a false cycle in long feature chains.
        retained_com_wrappers.append(feature)
        identity = id(feature)
        if identity in visited:
            unresolved.append(f"{path}: feature cycle detected")
            return None
        visited.add(identity)
        name = optional(feature, "Name", path) or "<unknown>"
        feature_path = f"{path}/{name}" if path else name
        feature_type = optional(feature, "GetTypeName2", feature_path) or "<unknown>"
        suppressed = optional(feature, "IsSuppressed", feature_path)
        children = []
        if depth < max_depth:
            child = optional(feature, "GetFirstSubFeature", feature_path)
            child_seen = set()
            while child is not None and id(child) not in child_seen:
                child_seen.add(id(child))
                child_node = node(child, feature_path, depth + 1)
                if child_node is not None:
                    children.append(child_node)
                child = optional(child, "GetNextSubFeature", feature_path)
        else:
            possible_child = optional(feature, "GetFirstSubFeature", feature_path)
            if possible_child is not None:
                unresolved.append(f"{feature_path}: feature depth limit reached")
        return {
            "name": name,
            "type": feature_type,
            "suppressed": bool(suppressed) if suppressed is not None else None,
            "parameters": parameters(feature, feature_path),
            "children": children,
        }

    features = []
    feature = optional(document, "FirstFeature", "document")
    top_seen = set()
    while feature is not None and id(feature) not in top_seen:
        retained_com_wrappers.append(feature)
        top_seen.add(id(feature))
        feature_node = node(feature, "", 1)
        if feature_node is not None:
            features.append(feature_node)
        feature = optional(feature, "GetNextFeature", "document")

    equations = []
    manager = optional(document, "GetEquationMgr", "document")
    if manager is not None:
        try:
            count = com(manager, "GetCount")
        except Exception:
            count = optional(manager, "Count", "equations")
        if isinstance(count, int):
            for index in range(count):
                raw = optional(manager, "Equation", f"equation[{index}]", index)
                resolved = optional(manager, "Value", f"equation[{index}]", index)
                global_variable = optional(manager, "GlobalVariable", f"equation[{index}]", index)
                equations.append({
                    "index": index,
                    "raw_expression": raw,
                    "resolved_value": resolved,
                    "global_variable": bool(global_variable) if global_variable is not None else None,
                    "state": "known" if raw is not None else "unavailable",
                    "source": "SolidWorks equation manager",
                })

    return {"features": features, "equations": equations, "unresolved": unresolved}
