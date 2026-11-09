"""Read-only structural inspection tools."""

import math
from pathlib import PureWindowsPath
from uuid import uuid4

from ..comutil import com
from ..constants import SwErrors, SwPlanes
from ..core.snapshot import InstanceRef, ProjectSnapshot, SnapshotCoverage
from ..core.policy import OperationClass
from ..inspection.snapshots import SnapshotCursorError, SnapshotStore
from ..inspection.documents import inspect_dependencies, inspect_feature_tree
from ..registry import tool
from .assembly import list_components, list_mates


_INSPECTION_SECTIONS = {
    "summary", "configurations", "features", "parameters", "assembly",
    "mates", "dependencies", "manufacturing",
}


def _component_document_type(path: str | None) -> str:
    suffix = PureWindowsPath(path).suffix.casefold() if path else ""
    return {".sldprt": "part", ".sldasm": "assembly", ".slddrw": "drawing"}.get(
        suffix, "unknown"
    )


@tool(
    name="inspect_document",
    description=(
        "Build a versioned, pageable snapshot of the active document and assembly graph. "
        "Repeated instances and incomplete references are preserved."
    ),
    schema={"type": "object", "properties": {
        "sections": {"type": "array", "items": {"type": "string", "enum": sorted(_INSPECTION_SECTIONS)}},
        "depth": {"type": "integer", "minimum": 1, "maximum": 32, "default": 4},
        "cursor": {"type": "string"},
        "page_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        "component_mode": {
            "type": "string", "enum": ["fast", "detailed"], "default": "detailed",
            "description": ("Traversal mode for the assembly components: 'fast' "
                            "reads only name and path and skips leaf parts "
                            "(much cheaper on large assemblies, but instances "
                            "then carry no transform or suppression state).")},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def inspect_document(
    sw,
    sections: list[str] | None = None,
    depth: int = 4,
    cursor: str | None = None,
    page_size: int = 100,
    component_mode: str = "detailed",
) -> dict:
    """Return a read-only project snapshot or resume a stored snapshot page."""
    requested = tuple(sections or ("summary", "assembly", "dependencies"))
    unknown = sorted(set(requested) - _INSPECTION_SECTIONS)
    if unknown:
        return sw._result(
            False, f"Unknown inspection sections: {', '.join(unknown)}",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
        )
    if component_mode not in ("fast", "detailed"):
        return sw._result(
            False, "component_mode must be 'fast' or 'detailed'.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
        )
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 500:
        return sw._result(False, "page_size must be an integer from 1 to 500.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    target, error = sw.capture_active_document_ref()
    if error:
        return error
    store = getattr(sw, "_snapshot_store", None)
    if store is None:
        store = SnapshotStore()
        sw._snapshot_store = store

    try:
        if cursor:
            page = store.resume(cursor, target, page_size=page_size)
            return sw._result(True, "Inspection snapshot page resumed.", data={
                "snapshot": page.to_dict(), "sections": list(requested),
            })

        documents = {target.document_id: target}
        instances = []
        dependency_edges = []
        unresolved = []
        complete = True
        truncated = False
        observations = []

        if "summary" in requested:
            observations.append({
                "section": "summary",
                "source": "SolidWorks COM",
                "document_id": target.document_id,
                "configuration": target.configuration,
                "revision_token": target.revision_token,
                "state": "known",
            })

        if {"features", "parameters"} & set(requested):
            document, document_error = sw.get_active_doc()
            if document_error:
                return document_error
            feature_report = inspect_feature_tree(document, max_depth=depth)
            if feature_report["unresolved"]:
                complete = False
                unresolved.extend(feature_report["unresolved"])
            common = {
                "source": "SolidWorks COM",
                "document_id": target.document_id,
                "configuration": target.configuration,
                "revision_token": target.revision_token,
                "state": "known" if not feature_report["unresolved"] else "unavailable",
            }
            if "features" in requested:
                observations.append({
                    **common, "section": "features", "value": feature_report["features"],
                })
            if "parameters" in requested:
                observations.append({
                    **common,
                    "section": "parameters",
                    "value": {"equations": feature_report["equations"]},
                })

        if "dependencies" in requested:
            document, document_error = sw.get_active_doc()
            if document_error:
                return document_error
            dependency_report = inspect_dependencies(document)
            complete = complete and dependency_report["complete"]
            unresolved.extend(dependency_report["unresolved"])
            observations.append({
                "section": "dependencies",
                "source": dependency_report["source_method"],
                "document_id": target.document_id,
                "configuration": target.configuration,
                "revision_token": target.revision_token,
                "state": "known" if dependency_report["complete"] else "unavailable",
                "value": {
                    "count": len(dependency_report["dependencies"]),
                    "evidence": dependency_report["evidence"],
                },
            })
            for dependency in dependency_report["dependencies"]:
                dependency_path = dependency["path"]
                dependency_document = None
                if dependency_path:
                    dependency_document = sw._document_session.capture(
                        title=PureWindowsPath(dependency_path).name,
                        path=dependency_path,
                        document_type=_component_document_type(dependency_path),
                        configuration=None,
                    )
                    documents.setdefault(
                        dependency_document.document_id, dependency_document
                    )
                dependency_edges.append({
                    "source": target.document_id,
                    "target": (
                        dependency_document.document_id if dependency_document else None
                    ),
                    "referenced_name": dependency["name"],
                    "kind": "document_reference",
                    "state": dependency["state"],
                    "source_method": dependency["source"],
                })

        if "mates" in requested:
            if target.document_type != "assembly":
                unresolved.append("mates: active document is not an assembly")
                complete = False
                observations.append({
                    "section": "mates",
                    "source": "SolidWorks IMate2",
                    "document_id": target.document_id,
                    "configuration": target.configuration,
                    "revision_token": target.revision_token,
                    "state": "unavailable",
                    "value": [],
                })
            else:
                mate_result = list_mates(sw)
                if not mate_result["success"]:
                    return mate_result
                mate_data = mate_result["data"]
                mate_coverage = mate_data["coverage"]
                complete = complete and bool(mate_coverage["complete"])
                unresolved.extend(mate_coverage["unresolved"])
                observations.append({
                    "section": "mates",
                    "source": "SolidWorks IMate2",
                    "document_id": target.document_id,
                    "configuration": target.configuration,
                    "revision_token": target.revision_token,
                    "state": (
                        "known" if mate_coverage["complete"] else "unavailable"
                    ),
                    "value": mate_data["mates"],
                })

        if target.document_type == "assembly" and ({"assembly", "dependencies"} & set(requested)):
            component_result = list_components(sw, depth=depth, mode=component_mode)
            if not component_result["success"]:
                return component_result
            component_data = component_result["data"]
            coverage = component_data["coverage"]
            unresolved.extend(coverage["unresolved"])
            complete = complete and bool(coverage["complete"])
            truncated = truncated or bool(coverage["truncated"])
            for component in component_data["components"]:
                path = component.get("path")
                component_document = sw._document_session.capture(
                    title=PureWindowsPath(path).name if path else component["name"],
                    path=path,
                    document_type=_component_document_type(path),
                    configuration=component.get("configuration"),
                )
                documents.setdefault(component_document.document_id, component_document)
                instances.append(InstanceRef(
                    instance_path=component["instance_path"],
                    parent_path=component.get("parent_path"),
                    document_id=component_document.document_id,
                    configuration=component.get("configuration"),
                    transform=tuple(component["transform"]) if component.get("transform") else None,
                    suppression_state=component.get("suppression_state"),
                ))
                dependency_edges.append({
                    "source": target.document_id,
                    "target": component_document.document_id,
                    "instance_path": component["instance_path"],
                    "kind": "assembly_component",
                    "state": "known" if path else "unresolved",
                })

        snapshot = ProjectSnapshot(
            snapshot_id=str(uuid4()),
            documents=tuple(documents.values()),
            instances=tuple(instances),
            dependency_edges=tuple(dependency_edges),
            observations=tuple(observations),
            coverage=SnapshotCoverage(
                complete=complete,
                visited_count=len(instances),
                unresolved=tuple(unresolved),
                truncated=truncated,
            ),
        )
        page = store.add(snapshot, target, page_size=page_size)
        return sw._result(True, "Inspection snapshot captured.", data={
            "snapshot": page.to_dict(), "sections": list(requested),
        })
    except SnapshotCursorError as cursor_error:
        return sw._result(False, str(cursor_error), SwErrors.swInvalidInput,
                          {"code": cursor_error.code})


@tool(
    name="list_planes",
    description="List standard and reference planes in the active document without changing selection.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def list_planes(sw) -> dict:
    """Return usable standard plane names and explicit RefPlane features."""
    doc, err = sw.get_active_doc()
    if err:
        return err

    planes = [
        {"name": SwPlanes.FRONT, "kind": "standard"},
        {"name": SwPlanes.TOP, "kind": "standard"},
        {"name": SwPlanes.RIGHT, "kind": "standard"},
    ]
    standard_names = {plane["name"] for plane in planes}
    try:
        feature = com(doc, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "RefPlane":
                name = com(feature, "Name")
                if name not in standard_names:
                    planes.append({"name": name, "kind": "reference"})
            feature = com(feature, "GetNextFeature")
    except Exception as error:
        return sw._result(False, f"Could not inspect reference planes: {error}",
                          SwErrors.swUnknownError)

    return sw._result(True, f"{len(planes)} planes found.", data={"planes": planes})


_PART_EDGE_CACHE = None

def part_edges(document):
    """Unique edges with endpoint parameters, indexed for the current topology.

    The index counts unique edges across all bodies in native body/edge order, so it is
    the same index list_body_edges reports and create_cosmetic_weld_bead
    consumes. Closed loops without distinct endpoints are omitted. Coincident
    edges in different bodies retain separate identities.
    Returns dicts with ``index``, ``body``, ``start_mm``, ``end_mm``,
    ``length_mm`` (straight edges only) and ``is_line``; the raw IEdge is kept
    under ``edge`` for internal callers.
    """
    global _PART_EDGE_CACHE
    bodies = list(com(document, 'GetBodies2', 0, True) or [])
    cache_key = None
    try:
        cache_key = (document._oleobj_, int(com(document,'GetUpdateStamp')),
                     tuple((body._oleobj_,str(com(body,'Name'))) for body in bodies))
    except AttributeError:
        pass
    if cache_key is not None and _PART_EDGE_CACHE is not None and _PART_EDGE_CACHE[0]==cache_key:
        return _PART_EDGE_CACHE[1]
    edges = []
    seen = set()
    for body_index, body in enumerate(bodies):
        body_name = str(com(body, "Name"))
        try:
            native_edges = com(body, "GetEdges") or []
        except AttributeError:
            native_edges = [edge for face in com(body, "GetFaces") or []
                            for edge in com(face, "GetEdges") or []]
        for edge in native_edges:
            curve = com(edge, "GetCurve")
            is_line = bool(com(curve, "IsLine"))
            try:
                # One native parameter array replaces four vertex COM calls.
                # GetCurve must precede GetCurveParams2 (SolidWorks API contract).
                params = com(edge, "GetCurveParams2")
                if params is None or len(params) < 6:
                    raise ValueError("Missing edge endpoint parameters")
                start = [round(float(v)*1000,4) for v in params[:3]]
                end = [round(float(v)*1000,4) for v in params[3:6]]
                if start == end and not is_line:
                    continue
            except (AttributeError, ValueError, TypeError):
                start_vertex = com(edge, "GetStartVertex")
                end_vertex = com(edge, "GetEndVertex")
                if start_vertex is None or end_vertex is None:
                    continue
                start = [round(float(v)*1000,4) for v in com(start_vertex,"GetPoint")]
                end = [round(float(v)*1000,4) for v in com(end_vertex,"GetPoint")]
            key = (body_index, tuple(sorted((tuple(start), tuple(end)))))
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "index": len(edges),
                "body": body_name,
                "body_index": body_index,
                "start_mm": start,
                "end_mm": end,
                "length_mm": (round(math.dist(start, end), 4) if is_line
                              else None),
                "is_line": is_line,
                "edge": edge,
            })
    if cache_key is not None:
        _PART_EDGE_CACHE = (cache_key,edges)
    return edges


@tool(
    name="list_body_edges",
    description=(
        "List the unique edges of every solid body in the active part, with "
        "index, body, endpoints in millimetres, straight-edge length and curve "
        "type. Use the index with create_cosmetic_weld_bead. Read-only."
    ),
    schema={
        "type": "object",
        "properties": {
            "min_length_mm": {
                "type": "number", "minimum": 0.0, "default": 0.0,
                "description": "Only report edges at least this long (straight edges)"
            }
        },
        "required": []
    },
    operation_class=OperationClass.READ,
)
def list_body_edges(sw, min_length_mm: float = 0.0) -> dict:
    """Return the indexed edges of the active part."""
    if (isinstance(min_length_mm, bool)
            or not isinstance(min_length_mm, (int, float)) or min_length_mm < 0):
        return sw._result(False, "min_length_mm must be a non-negative number.",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)

    try:
        edges = part_edges(doc)
    except Exception as exc:
        return sw._result(False, f"Could not read body edges: {exc}",
                          SwErrors.swUnknownError)

    reported = []
    for edge in edges:
        if edge["length_mm"] is None:
            # Curves without a measured length are only listed when no minimum
            # is requested, so a length filter stays meaningful.
            if min_length_mm == 0:
                reported.append({key: value for key, value in edge.items()
                                 if key != "edge"})
        elif edge["length_mm"] >= min_length_mm:
            reported.append({key: value for key, value in edge.items()
                             if key != "edge"})
    return sw._result(
        True,
        f"Found {len(reported)} of {len(edges)} edges.",
        data={"count": len(reported), "total_edges": len(edges),
              "edges": reported})
