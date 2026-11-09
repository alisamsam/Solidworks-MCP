"""Advertised tool catalog: guarded mode and enabled toolsets applied to all tools.

Ordinary toolsets only shorten what a client loads. Routing additionally requires
explicit permission, enforced by the dispatcher even for direct calls.
"""

import logging
import os
from typing import List, Optional

from mcp.types import Tool

from .config import get_config
from .registry import registered_tools, tool_module_for

logger = logging.getLogger("SolidWorksMCP")

TOOLSETS = {
    "core": ("connection", "documents", "session", "saving", "history", "views",
             "inspection", "measurements", "export"),
    "sketch": ("sketch_basic", "sketch_entities", "sketch_create", "construction_geometry"),
    "sketch_edit": ("sketch_edit",),
    "features": ("features_basic", "patterns", "advanced_features", "body_features",
                 "reference_geometry", "equations", "material", "appearance",
                 "properties", "configurations"),
    "surfaces": ("surface_features",),
    "assembly": ("assembly", "standard_parts", "component_edges", "component_svg", "assembly_exports"),
    "drawing": ("drawings", "drawing_annotations", "documentation_drawing"),
    "sheetmetal": ("sheetmetal", "sheetmetal_hem", "sheetmetal_bodies", "sheetmetal_body_export"),
    "weldments": ("weldments", "cutlist", "cutlist_bodies", "save_bodies", "hole_catalog"),
    "simulation": ("simulation",),
    "project": ("project_copy", "project_lifecycle", "model_edit", "parameter_workspace",
                "parameter_batch", "cad_workflows", "manufacturing_package", "assembly_documentation", "manufacturing_bodies", "imports"),
    "planners": ("engineering_planners",),
    "routing": ("routing", "routing_edit", "routing_create", "routing_components",
                "routing_measure", "routing_articles", "routing_library", "routing_settings", "routing_path", "routing_active_edit"),
}
_MODULE_TOOLSET = {module: name for name, modules in TOOLSETS.items() for module in modules}

def toolset_of(name: str) -> Optional[str]:
    module = tool_module_for(name)
    return _MODULE_TOOLSET.get(module.rsplit(".", 1)[-1]) if module else None


def enabled_toolsets() -> List[str]:
    raw = os.environ.get("SW_MCP_TOOLSETS")
    if raw is not None:
        requested = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        requested = get_config().enabled_toolsets
    if requested is None:
        return sorted(name for name in TOOLSETS if name != "routing")
    unknown = [name for name in requested if name not in TOOLSETS]
    if unknown:
        logger.warning("Unknown toolsets ignored: %s", ", ".join(unknown))
    return sorted({"core"} | {name for name in requested if name in TOOLSETS
                             and (name != "routing" or routing_enabled())})


def routing_enabled() -> bool:
    """Explicit runtime permission; invalid environment values fail closed."""
    raw = os.environ.get("SW_MCP_ROUTING_ENABLED")
    if raw is not None:
        return raw.strip().lower() == "true"
    return get_config().routing_enabled is True


def advertised_tools() -> List[Tool]:
    """Tools a client should see; unmapped tools are never hidden."""
    enabled = set(enabled_toolsets())
    guarded = get_config().guarded_mode
    result = []
    for item in registered_tools():
        if guarded and item.name == "execute_python":
            continue
        toolset = toolset_of(item.name)
        if toolset is None or toolset in enabled:
            result.append(item)
    return result


def advertised_tool_names() -> set[str]:
    return {item.name for item in advertised_tools()}
