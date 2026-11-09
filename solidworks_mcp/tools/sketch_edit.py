"""Sketch editing operations on existing sketch entities.

Covers trim and extend, sketch fillet and chamfer, offset, mirror, split,
construction geometry, scaling, rotation and the linear and circular sketch
patterns. Every tool reopens the named sketch for edit, applies one
``ISketchManager``/``IModelDoc2`` operation to the selected entities, closes the
sketch again and confirms success by an observed change rather than by the API
return value.
"""

import math

import pythoncom
import win32com.client

from ..comutil import com, set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


SW_DOC_PART = 1

UNIT_SCHEMA = {
    "type": "string",
    "enum": ["mm", "cm", "m", "inch"],
    "default": "mm",
}

# swSketchChamferType_e from swconst.tlb (verified live 2026-09-22):
# distance_equal must be given the same non-zero value in both value slots;
# passing 0.0 for AngleORdist makes SolidWorks throw.
CHAMFER_TYPES = {
    "distance_angle": 0,
    "distance_distance": 1,
    "distance_equal": 2,
}

# ISketchSegment.GetType(): a line is 0, every curved segment is non-zero.
SKETCH_SEGMENT_LINE = 0

# swSketchTrimChoice_e from swconst.tlb (verified 2026-09-21):
#   closest=0, corner=1, twoentities=2, entitypoint=3, entities=4,
#   outside=5, inside=6
#
# swSketchTrimEntities (4) is deliberately NOT exposed. In SolidWorks 2025 it
# returned False and left the sketch unchanged both with and without a pick
# point, so the tool must not advertise a mode that never applies.
# swSketchTrimClosest (0) does trim correctly but returns False on success,
# which is why success is decided by observed geometry change, not by the
# API return value.
TRIM_OPTIONS = {
    "closest": 0,
    "corner": 1,
    "twoentities": 2,
    "entitypoint": 3,
    "outside": 5,
    "inside": 6,
}

# Minimum selected entities each option needs: corner/twoentities trim a corner
# between two entities, inside/outside need two boundaries plus the trimmed
# entity.
MIN_TRIM_ENTITIES = {
    "closest": 1,
    "corner": 2,
    "twoentities": 2,
    "entitypoint": 1,
    "outside": 3,
    "inside": 3,
}


def _find_feature(document, name):
    feature = com(document, "FirstFeature")
    while feature is not None:
        if com(feature, "Name") == name:
            return feature
        feature = com(feature, "GetNextFeature")
    return None


def _is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _convert_length(sw, value, unit, label):
    """Convert one user-unit length to metres; return (metres, error result)."""
    if not _is_number(value):
        return None, _invalid(sw, f"{label} must be a finite number.")
    try:
        return sw._units.to_meters(value, unit), None
    except (KeyError, TypeError, ValueError) as conversion_error:
        return None, _invalid(sw, f"Invalid unit or {label}: {conversion_error}")


def _require_part(sw):
    """Return (document, error); the active document must be a part."""
    document, error = sw.get_active_doc()
    if error:
        return None, error
    if com(document, "GetType") != SW_DOC_PART:
        return None, sw._result(
            False, "Active document is not a part.", SwErrors.swInvalidFileType
        )
    return document, None


def _clean_names(items):
    if not isinstance(items, list) or not items:
        return None
    cleaned = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            return None
        cleaned.append(item.strip())
    if len(cleaned) != len(set(cleaned)):
        return None
    return cleaned


def _resolve_pick(sw, pick, unit):
    """Return the pick point in metres, or None when the caller passed garbage."""
    if pick is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(pick, (list, tuple)) or len(pick) != 3:
        return None
    try:
        values = [float(value) for value in pick]
    except (TypeError, ValueError):
        return None
    return tuple(sw.units.to_meters(value, unit) for value in values)


def _segment_lengths(document, feature):
    """Snapshot sketch segment lengths so a real geometry change can be proven."""
    sketch = com(feature, "GetSpecificFeature2")
    if sketch is None:
        return None
    lengths = []
    for segment in com(sketch, "GetSketchSegments") or []:
        lengths.append(round(float(com(segment, "GetLength")), 9))
    return lengths


def _sketch_transform(document, feature):
    """Snapshot the sketch coordinate system.

    ``SketchModifyRotate`` rotates the sketch frame instead of rewriting the
    segment coordinates, so the change shows up here and *not* in the segment
    lengths.  Verified live: the geometry visibly and durably rotates while
    ``GetSketchSegments`` keeps returning the pre-edit coordinates.
    """
    sketch = com(feature, "GetSpecificFeature2")
    if sketch is None:
        return None
    transform = com(sketch, "ModelToSketchTransform")
    if transform is None:
        return None
    return tuple(round(float(value), 9) for value in com(transform, "ArrayData"))


def _sketch_state(document, feature):
    """Segment lengths plus the sketch frame; a change in either one counts."""
    return (_segment_lengths(document, feature),
            _sketch_transform(document, feature))


def _sketch_segment_construction(document, feature):
    """Snapshot the construction flag of every segment, for change detection."""
    sketch = com(feature, "GetSpecificFeature2")
    if sketch is None:
        return None
    flags = []
    for segment in com(sketch, "GetSketchSegments") or []:
        flags.append(bool(com(segment, "ConstructionGeometry")))
    return flags


def _open_sketch(document, feature):
    """Select a sketch feature and enter sketch edit mode.

    ``IModelDoc2::EditSketch`` is void in this SolidWorks build and returns
    ``None`` on success, so only an explicit ``False`` counts as failure.
    """
    com(document, "ClearSelection2", True)
    if not com(feature, "Select2", False, 0):
        return False
    result = com(document, "EditSketch")
    return result is not False


def _select_segments(document, names, types=("SKETCHSEGMENT",)):
    """Select sketch entities by name; the target sketch must be active.

    ``types`` allows a caller to select a sketch *point* (``SKETCHPOINT``)
    instead of a segment; each name is tried against every type in turn.
    """
    empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    for position, name in enumerate(names):
        for type_name in types:
            selected = com(
                document.Extension, "SelectByID2", name, type_name,
                0.0, 0.0, 0.0, position > 0, 0, empty_callout, 0,
            )
            if selected:
                break
        else:
            return False
    return True


def _invalid(sw, message):
    return sw._result(False, message, SwErrors.swInvalidInput,
                      {"code": "VALIDATION_FAILED"})


def _edit_and_verify(sw, document, feature, names, action, call, failure_code,
                     failure_label, require_change=False, prepare=None,
                     observe=None, types=("SKETCHSEGMENT",), unchanged_note=None):
    """Run one sketch-manager edit, then prove it changed the sketch geometry.

    ``prepare`` is called once the entities are selected and may fill a context
    dictionary that ``call`` then reads; returning a result from ``prepare``
    aborts the edit and that result is passed through to the caller.

    ``observe`` takes ``(document, feature)`` and returns the snapshot used to
    prove a change; it defaults to the segment lengths. Edits that alter
    something other than length (construction state, the relation list) pass
    their own observer.

    ``types`` lists the selection types tried for each name, and
    ``unchanged_note`` replaces the trailing explanation when nothing changed.
    """
    snapshot = observe or _segment_lengths
    before = snapshot(document, feature)
    if not _open_sketch(document, feature):
        return sw._result(False, "Could not open sketch for editing.",
                          SwErrors.swSelectionError)

    try:
        if not _select_segments(document, names, types):
            return sw._result(
                False,
                "Could not select all requested sketch entities. Check the "
                "exact segment names inside the active sketch.",
                SwErrors.swSelectionError,
            )
        context = {}
        if prepare is not None:
            prepared = prepare(context)
            if prepared is not None:
                return prepared
        applied = call(context)
    except Exception as edit_error:
        return sw._result(False, f"{failure_label} failed: {edit_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "InsertSketch2", True)
        com(document, "ClearSelection2", True)

    after = snapshot(document, feature)
    changed = before != after
    if not changed and (require_change or not applied):
        return sw._result(
            False,
            f"SolidWorks did not {action} {', '.join(names)}; "
            f"{unchanged_note or 'the sketch geometry is unchanged'}.",
            SwErrors.swFeatureError,
            {"code": failure_code},
        )
    return changed


@tool(
    name="trim_entities",
    description=(
        "Trim or extend existing entities inside one named sketch. Select "
        "entities by their exact sketch segment names (for example Line1, "
        "Line2). The sketch is reopened for edit and closed again. Success is "
        "confirmed by an observed geometry change. Trimming invalidates "
        "previously reported entity references."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "mode": {"type": "string", "default": "corner", "enum": [
            "closest", "corner", "twoentities", "entitypoint",
            "outside", "inside",
        ]},
        "pick": {"type": "array", "items": {"type": "number"},
                 "minItems": 3, "maxItems": 3},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default"},
    }, "required": ["sketch", "entities"]},
    operation_class=OperationClass.MUTATE,
)
def trim_entities(sw, sketch, entities, mode="corner", pick=None, unit=None):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    mode_key = mode.strip().lower() if isinstance(mode, str) else ""
    if mode_key not in TRIM_OPTIONS:
        return _invalid(
            sw,
            "mode must be one of: " + ", ".join(sorted(TRIM_OPTIONS)) + ".",
        )

    names = _clean_names(entities)
    if names is None or len(names) < MIN_TRIM_ENTITIES[mode_key]:
        return _invalid(
            sw,
            f"mode '{mode_key}' needs at least "
            f"{MIN_TRIM_ENTITIES[mode_key]} distinct non-empty entity names.",
        )

    point = _resolve_pick(sw, pick, unit)
    if point is None:
        return _invalid(sw, "pick must be three numbers (x, y, z).")

    document, error = _require_part(sw)
    if error:
        return error

    feature = _find_feature(document, sketch.strip())
    if feature is None:
        return sw._result(False, f"Sketch not found: {sketch}",
                          SwErrors.swSelectionError)

    changed = _edit_and_verify(
        sw, document, feature, names,
        action=f"trim using '{mode_key}'",
        call=lambda _context: com(document.SketchManager, "SketchTrim",
                                  TRIM_OPTIONS[mode_key],
                                  point[0], point[1], point[2]),
        failure_code="TRIM_FAILED",
        failure_label="Trim",
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Trimmed {len(names)} entity(ies) in {sketch} using '{mode_key}'.",
        data={
            "sketch": sketch,
            "mode": mode_key,
            "trim_option": TRIM_OPTIONS[mode_key],
            "entities": names,
            "pick": list(point),
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


@tool(
    name="extend_entities",
    description=(
        "Extend one existing sketch entity to the next entity in its path. "
        "Select the entity by its exact sketch segment name and give a pick "
        "point near the end to extend. The sketch is reopened for edit and "
        "closed again; success is confirmed by an observed geometry change."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1, "maxItems": 1},
        "pick": {"type": "array", "items": {"type": "number"},
                 "minItems": 3, "maxItems": 3},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "description": "Unit; omitted = session default"},
    }, "required": ["sketch", "entities"]},
    operation_class=OperationClass.MUTATE,
)
def extend_entities(sw, sketch, entities, pick=None, unit=None):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None or len(names) != 1:
        return _invalid(sw, "entities must contain exactly one entity name.")

    point = _resolve_pick(sw, pick, unit)
    if point is None:
        return _invalid(sw, "pick must be three numbers (x, y, z).")

    document, error = _require_part(sw)
    if error:
        return error

    feature = _find_feature(document, sketch.strip())
    if feature is None:
        return sw._result(False, f"Sketch not found: {sketch}",
                          SwErrors.swSelectionError)

    changed = _edit_and_verify(
        sw, document, feature, names,
        action=f"extend {names[0]}",
        call=lambda _context: com(document.SketchManager, "SketchExtend",
                                  point[0], point[1], point[2]),
        failure_code="EXTEND_FAILED",
        failure_label="Extend",
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Extended {names[0]} in {sketch}.",
        data={
            "sketch": sketch,
            "entities": names,
            "pick": list(point),
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


def _segment_reference_point(segment):
    """Return the (x, y) reference of one sketch segment.

    Circles and arcs are referenced by their centre, lines by their midpoint;
    anything else falls back to its start point. SolidWorks reports these
    points in the sketch's own 2D coordinate system, so no model-space
    transform is involved (verified live 2026-09-22).
    """
    if com(segment, "GetType") != SKETCH_SEGMENT_LINE:
        try:
            centre = com(segment, "GetCenterPoint")
        except Exception:  # noqa: BLE001 - not every segment exposes a centre
            centre = None
        if centre is not None:
            return (float(centre[0]), float(centre[1]))

    try:
        start = com(segment, "GetStartPoint")
    except Exception:  # noqa: BLE001
        start = None
    try:
        end = com(segment, "GetEndPoint")
    except Exception:  # noqa: BLE001
        end = None
    if start is not None and end is not None:
        return ((float(start[0]) + float(end[0])) / 2.0,
                (float(start[1]) + float(end[1])) / 2.0)
    if start is not None:
        return (float(start[0]), float(start[1]))
    return None


def _selection_reference_point(document):
    """Average reference point of the current selection, in sketch space."""
    manager = com(document, "SelectionManager")
    if manager is None:
        return None
    count = com(manager, "GetSelectedObjectCount2", -1)
    if not count:
        return None
    points = []
    for index in range(1, int(count) + 1):
        segment = com(manager, "GetSelectedObject6", index, -1)
        if segment is None:
            continue
        point = _segment_reference_point(segment)
        if point is not None:
            points.append(point)
    if not points:
        return None
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _sketch_feature(sw, document, sketch):
    """Return (feature, error) for one named sketch feature."""
    feature = _find_feature(document, sketch.strip())
    if feature is None:
        return None, sw._result(
            False, f"Sketch not found: {sketch}", SwErrors.swSelectionError
        )
    return feature, None


@tool(
    name="sketch_fillet",
    description=(
        "Round a sketch corner with a fillet arc. Name the two adjacent "
        "entities that meet at the corner by their exact sketch segment names "
        "(for example Line1 and Line2). The sketch is reopened for edit and "
        "closed again; success is confirmed by an observed geometry change and "
        "earlier entity references may be invalidated."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 2, "maxItems": 2},
        "radius": {"type": "number", "exclusiveMinimum": 0},
        "constrained_corners": {"type": "boolean", "default": True},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "radius"]},
    operation_class=OperationClass.MUTATE,
)
def sketch_fillet(sw, sketch, entities, radius, constrained_corners=True,
                  unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None or len(names) != 2:
        return _invalid(sw, "entities must be exactly two distinct entity names.")

    radius_m, error = _convert_length(sw, radius, unit, "radius")
    if error:
        return error
    if radius_m <= 0:
        return _invalid(sw, "radius must be greater than zero.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="fillet the corner between",
        call=lambda _context: com(document.SketchManager, "CreateFillet",
                                  radius_m, bool(constrained_corners)),
        failure_code="FILLET_FAILED",
        failure_label="Sketch fillet",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Filleted the corner between {names[0]} and {names[1]} in {sketch} "
        f"with radius {radius}{unit}.",
        data={
            "sketch": sketch,
            "entities": names,
            "radius": radius,
            "unit": unit,
            "radius_meters": radius_m,
            "constrained_corners": bool(constrained_corners),
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


@tool(
    name="sketch_chamfer",
    description=(
        "Chamfer a sketch corner. Name the two adjacent entities that meet at "
        "the corner by their exact sketch segment names. mode is "
        "distance_angle (distance plus angle_deg), distance_distance (distance "
        "plus distance2) or distance_equal (equal legs of distance). The "
        "sketch is reopened for edit and closed again; success is confirmed by "
        "an observed geometry change."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 2, "maxItems": 2},
        "distance": {"type": "number", "exclusiveMinimum": 0},
        "mode": {"type": "string", "default": "distance_angle",
                 "enum": ["distance_angle", "distance_distance",
                          "distance_equal"]},
        "angle_deg": {"type": "number", "exclusiveMinimum": 0,
                      "exclusiveMaximum": 90, "default": 45},
        "distance2": {"type": "number", "exclusiveMinimum": 0},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "distance"]},
    operation_class=OperationClass.MUTATE,
)
def sketch_chamfer(sw, sketch, entities, distance, mode="distance_angle",
                   angle_deg=45, distance2=None, unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None or len(names) != 2:
        return _invalid(sw, "entities must be exactly two distinct entity names.")

    mode_key = mode.strip().lower() if isinstance(mode, str) else ""
    if mode_key not in CHAMFER_TYPES:
        return _invalid(
            sw, "mode must be one of: " + ", ".join(sorted(CHAMFER_TYPES)) + "."
        )

    distance_m, error = _convert_length(sw, distance, unit, "distance")
    if error:
        return error
    if distance_m <= 0:
        return _invalid(sw, "distance must be greater than zero.")

    if mode_key == "distance_angle":
        # A 90 degree chamfer angle produced no geometry in SW 2025.
        if not _is_number(angle_deg) or not 0 < angle_deg < 90:
            return _invalid(sw, "angle_deg must be in (0, 90) for "
                                "distance_angle chamfers.")
        second = math.radians(angle_deg)
    elif mode_key == "distance_distance":
        distance2_m, error = _convert_length(sw, distance2, unit, "distance2")
        if error:
            return error
        if distance2_m <= 0:
            return _invalid(sw, "distance2 must be greater than zero for "
                                "distance_distance chamfers.")
        second = distance2_m
    else:
        # distance_equal needs the same non-zero value twice; 0.0 throws.
        second = distance_m

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="chamfer the corner between",
        call=lambda _context: com(document.SketchManager, "CreateChamfer",
                                  CHAMFER_TYPES[mode_key], distance_m, second),
        failure_code="CHAMFER_FAILED",
        failure_label="Sketch chamfer",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    data = {
        "sketch": sketch,
        "entities": names,
        "mode": mode_key,
        "chamfer_type": CHAMFER_TYPES[mode_key],
        "distance": distance,
        "unit": unit,
        "distance_meters": distance_m,
        "second_value": second,
        "geometry_changed": changed,
        "references_invalidated": True,
    }
    if mode_key == "distance_angle":
        data["angle_deg"] = angle_deg
    elif mode_key == "distance_distance":
        data["distance2"] = distance2

    return sw._result(
        True,
        f"Chamfered the corner between {names[0]} and {names[1]} in {sketch} "
        f"using '{mode_key}'.",
        data=data,
    )


@tool(
    name="offset_entities",
    description=(
        "Offset the named sketch entities by a signed distance, creating new "
        "parallel entities. A positive offset offsets outward, a negative one "
        "inward. Select entities by their exact sketch segment names; the "
        "sketch is reopened for edit and closed again."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "offset": {"type": "number"},
        "both_directions": {"type": "boolean", "default": False},
        "chain": {"type": "boolean", "default": True},
        "cap_ends": {"type": "boolean", "default": False},
        "make_construction": {"type": "boolean", "default": False},
        "add_dimensions": {"type": "boolean", "default": False},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "offset"]},
    operation_class=OperationClass.MUTATE,
)
def offset_entities(sw, sketch, entities, offset, both_directions=False,
                    chain=True, cap_ends=False, make_construction=False,
                    add_dimensions=False, unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct "
                            "non-empty entity names.")

    offset_m, error = _convert_length(sw, offset, unit, "offset")
    if error:
        return error
    if offset_m == 0:
        return _invalid(sw, "offset must be a non-zero signed distance.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="offset",
        call=lambda _context: com(
            document.SketchManager, "SketchOffset2",
            offset_m, bool(both_directions), bool(chain),
            1 if cap_ends else 0, bool(make_construction), bool(add_dimensions),
        ),
        failure_code="OFFSET_FAILED",
        failure_label="Offset",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Offset {', '.join(names)} in {sketch} by {offset}{unit}.",
        data={
            "sketch": sketch,
            "entities": names,
            "offset": offset,
            "unit": unit,
            "offset_meters": offset_m,
            "both_directions": bool(both_directions),
            "chain": bool(chain),
            "cap_ends": bool(cap_ends),
            "make_construction": bool(make_construction),
            "add_dimensions": bool(add_dimensions),
            "geometry_changed": changed,
        },
    )


@tool(
    name="sketch_mirror",
    description=(
        "Mirror sketch entities about another entity in the same sketch. Name "
        "the entities to mirror and the mirror entity (normally an independent "
        "centerline) by their exact sketch segment names. The mirror entity is "
        "selected last and must not be connected to the entities being "
        "mirrored, because SolidWorks silently ignores such a mirror. The "
        "sketch is reopened for edit and closed again."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "mirror_entity": {"type": "string"},
    }, "required": ["sketch", "entities", "mirror_entity"]},
    operation_class=OperationClass.MUTATE,
)
def sketch_mirror(sw, sketch, entities, mirror_entity):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct "
                            "non-empty entity names.")
    if not isinstance(mirror_entity, str) or not mirror_entity.strip():
        return _invalid(sw, "mirror_entity must be a non-empty entity name.")
    axis = mirror_entity.strip()
    if axis in names:
        return _invalid(sw, "mirror_entity must differ from the mirrored "
                            "entities.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names + [axis],
        action="mirror",
        call=lambda _context: com(document, "SketchMirror"),
        failure_code="MIRROR_FAILED",
        failure_label="Sketch mirror",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Mirrored {', '.join(names)} about {axis} in {sketch}.",
        data={
            "sketch": sketch,
            "entities": names,
            "mirror_entity": axis,
            "geometry_changed": changed,
        },
    )


@tool(
    name="split_entities",
    description=(
        "Split one sketch entity in two at points on it. Name the entity by its "
        "exact sketch segment name. An open entity takes one split point (x, y); "
        "a closed entity such as a circle takes two (x, y and x2, y2). The "
        "sketch is reopened for edit and closed again."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1, "maxItems": 1},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "x2": {"type": "number"},
        "y2": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "x", "y"]},
    operation_class=OperationClass.MUTATE,
)
def split_entities(sw, sketch, entities, x, y, unit="mm", x2=None, y2=None):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None or len(names) != 1:
        return _invalid(sw, "entities must contain exactly one entity name.")

    if (x2 is None) != (y2 is None):
        return _invalid(sw, "x2 and y2 must be given together to split a closed "
                            "entity.")

    x_m, error = _convert_length(sw, x, unit, "x")
    if error:
        return error
    y_m, error = _convert_length(sw, y, unit, "y")
    if error:
        return error

    closed = x2 is not None
    if closed:
        x2_m, error = _convert_length(sw, x2, unit, "x2")
        if error:
            return error
        y2_m, error = _convert_length(sw, y2, unit, "y2")
        if error:
            return error
    else:
        x2_m = y2_m = None

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    if closed:
        def call(_context):
            return com(document.SketchManager, "SplitClosedSegment",
                       x_m, y_m, 0.0, x2_m, y2_m, 0.0)
    else:
        def call(_context):
            return com(document.SketchManager, "SplitOpenSegment", x_m, y_m, 0.0)

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="split",
        call=call,
        failure_code="SPLIT_FAILED",
        failure_label="Split",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    pick = [x, y] if not closed else [x, y, x2, y2]
    return sw._result(
        True,
        f"Split {names[0]} in {sketch} at {pick} "
        f"({'closed' if closed else 'open'} entity).",
        data={
            "sketch": sketch,
            "entities": names,
            "pick": pick,
            "closed": closed,
            "unit": unit,
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


@tool(
    name="rotate_entities",
    description=(
        "Rotate the named sketch entities about a point in the sketch plane. "
        "SolidWorks applies this to the sketch frame, so the sketch coordinate "
        "system rotates with the geometry. Positive angles turn "
        "counter-clockwise; the centre is given in sketch coordinates."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "angle_deg": {"type": "number"},
        "center_x": {"type": "number", "default": 0},
        "center_y": {"type": "number", "default": 0},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "angle_deg"]},
    operation_class=OperationClass.MUTATE,
)
def rotate_entities(sw, sketch, entities, angle_deg, center_x=0, center_y=0,
                    unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct non-empty "
                            "entity names.")

    if not _is_number(angle_deg):
        return _invalid(sw, "angle_deg must be a finite number.")
    if angle_deg % 360 == 0:
        return _invalid(sw, "angle_deg must not be a full turn; that changes "
                            "nothing.")

    center_x_m, error = _convert_length(sw, center_x, unit, "center_x")
    if error:
        return error
    center_y_m, error = _convert_length(sw, center_y, unit, "center_y")
    if error:
        return error

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="rotate",
        call=lambda _context: com(document, "SketchModifyRotate",
                                  center_x_m, center_y_m,
                                  math.radians(angle_deg)),
        failure_code="ROTATE_FAILED",
        failure_label="Sketch rotate",
        require_change=True,
        observe=_sketch_state,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Rotated {', '.join(names)} in {sketch} by {angle_deg} degrees about "
        f"({center_x}, {center_y}){unit}.",
        data={
            "sketch": sketch,
            "entities": names,
            "angle_deg": angle_deg,
            "center": [center_x, center_y],
            "unit": unit,
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


@tool(
    name="scale_entities",
    description=(
        "Scale the named sketch entities by a factor. SolidWorks scales about "
        "the sketch origin and has no scale centre argument, so the entities "
        "also move unless they are centred on the origin."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "factor": {"type": "number", "exclusiveMinimum": 0},
    }, "required": ["sketch", "entities", "factor"]},
    operation_class=OperationClass.MUTATE,
)
def scale_entities(sw, sketch, entities, factor):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct non-empty "
                            "entity names.")

    if not _is_number(factor) or factor <= 0:
        return _invalid(sw, "factor must be a positive finite number.")
    if factor == 1:
        return _invalid(sw, "factor must differ from 1; a factor of 1 changes "
                            "nothing.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="scale",
        call=lambda _context: com(document, "SketchModifyScale", float(factor)),
        failure_code="SCALE_FAILED",
        failure_label="Sketch scale",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Scaled {', '.join(names)} in {sketch} by {factor}.",
        data={
            "sketch": sketch,
            "entities": names,
            "factor": factor,
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


@tool(
    name="toggle_construction",
    description=(
        "Switch the named sketch entities between normal and construction "
        "geometry. Pass construction true or false to force one state, or leave "
        "it out to flip every named entity."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "construction": {"type": "boolean"},
    }, "required": ["sketch", "entities"]},
    operation_class=OperationClass.MUTATE,
)
def toggle_construction(sw, sketch, entities, construction=None):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct non-empty "
                            "entity names.")

    if construction is not None and not isinstance(construction, bool):
        return _invalid(sw, "construction must be true, false or omitted.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    def apply(_context):
        # The property setter is the only path that also turns construction
        # geometry back off; ISketchManager.CreateConstructionGeometry only
        # turns it on.
        manager = com(document, "SelectionManager")
        for index in range(1, len(names) + 1):
            segment = com(manager, "GetSelectedObject6", index, -1)
            if segment is None:
                raise RuntimeError("a selected sketch entity disappeared")
            target = construction
            if target is None:
                target = not bool(com(segment, "ConstructionGeometry"))
            set_com(segment, "ConstructionGeometry", bool(target))
        return True

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="toggle the construction state of",
        call=apply,
        failure_code="CONSTRUCTION_FAILED",
        failure_label="Construction toggle",
        require_change=True,
        observe=_sketch_segment_construction,
    )
    if isinstance(changed, dict):
        return changed

    if construction is None:
        message = (f"Flipped the construction state of {', '.join(names)} "
                   f"in {sketch}.")
    elif construction:
        message = f"Marked {', '.join(names)} in {sketch} as construction geometry."
    else:
        message = (f"Returned {', '.join(names)} in {sketch} to normal "
                   "geometry.")
    return sw._result(
        True,
        message,
        data={
            "sketch": sketch,
            "entities": names,
            "construction": construction,
            "geometry_changed": changed,
            "references_invalidated": True,
        },
    )


def _pattern_count(value, label):
    """Validate one sketch pattern instance count."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None, f"{label} must be a positive integer."
    return value, None


@tool(
    name="sketch_pattern_linear",
    description=(
        "Create a linear sketch pattern of the selected entities. count_x and "
        "count_y are the total instance counts including the seed, so a 2 by 3 "
        "pattern creates six instances. spacing_x and spacing_y are the "
        "distances between instances; angle_y_deg defaults to 90 so the second "
        "direction is perpendicular to the first."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "spacing_x": {"type": "number", "exclusiveMinimum": 0},
        "spacing_y": {"type": "number", "minimum": 0, "default": 0},
        "count_x": {"type": "integer", "minimum": 1, "default": 2},
        "count_y": {"type": "integer", "minimum": 1, "default": 1},
        "angle_x_deg": {"type": "number", "default": 0},
        "angle_y_deg": {"type": "number", "default": 90},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "spacing_x"]},
    operation_class=OperationClass.MUTATE,
)
def sketch_pattern_linear(sw, sketch, entities, spacing_x, spacing_y=0,
                          count_x=2, count_y=1, angle_x_deg=0,
                          angle_y_deg=90, unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct "
                            "non-empty entity names.")

    count_x, error = _pattern_count(count_x, "count_x")
    if error:
        return _invalid(sw, error)
    count_y, error = _pattern_count(count_y, "count_y")
    if error:
        return _invalid(sw, error)
    if count_x * count_y < 2:
        return _invalid(sw, "count_x times count_y must be at least 2.")

    spacing_x_m, error = _convert_length(sw, spacing_x, unit, "spacing_x")
    if error:
        return error
    if spacing_x_m <= 0:
        return _invalid(sw, "spacing_x must be greater than zero.")
    spacing_y_m, error = _convert_length(sw, spacing_y, unit, "spacing_y")
    if error:
        return error
    if count_y > 1 and spacing_y_m <= 0:
        return _invalid(sw, "spacing_y must be greater than zero when "
                            "count_y is greater than one.")

    if not _is_number(angle_x_deg) or not _is_number(angle_y_deg):
        return _invalid(sw, "angle_x_deg and angle_y_deg must be finite "
                            "numbers.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="pattern",
        call=lambda _context: com(
            document.SketchManager, "CreateLinearSketchStepAndRepeat",
            count_x, count_y, spacing_x_m, spacing_y_m,
            math.radians(angle_x_deg), math.radians(angle_y_deg), "",
            False, False, False, False, False,
        ),
        failure_code="PATTERN_FAILED",
        failure_label="Linear sketch pattern",
        require_change=True,
    )
    if isinstance(changed, dict):
        return changed

    return sw._result(
        True,
        f"Created a {count_x} by {count_y} linear pattern of "
        f"{', '.join(names)} in {sketch}.",
        data={
            "sketch": sketch,
            "entities": names,
            "count_x": count_x,
            "count_y": count_y,
            "instances": count_x * count_y,
            "spacing_x": spacing_x,
            "spacing_y": spacing_y,
            "unit": unit,
            "spacing_x_meters": spacing_x_m,
            "spacing_y_meters": spacing_y_m,
            "angle_x_deg": angle_x_deg,
            "angle_y_deg": angle_y_deg,
            "geometry_changed": changed,
        },
    )


@tool(
    name="sketch_pattern_circular",
    description=(
        "Create an equal-spacing circular sketch pattern of the selected "
        "entities about centre_x/centre_y, both in the sketch's own 2D "
        "coordinate system. The seed is one of the count instances, so the "
        "angular step is total_angle_deg/count; use 360 for a full circle. "
        "SolidWorks derives its own pattern centre from the seed geometry, so "
        "the tool computes and reports the arc radius and angle it passes on."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "count": {"type": "integer", "minimum": 2},
        "center_x": {"type": "number", "default": 0},
        "center_y": {"type": "number", "default": 0},
        "total_angle_deg": {"type": "number", "exclusiveMinimum": 0,
                            "maximum": 360, "default": 360},
        "rotate_instances": {"type": "boolean", "default": False},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "count"]},
    operation_class=OperationClass.MUTATE,
)
def sketch_pattern_circular(sw, sketch, entities, count, center_x=0, center_y=0,
                            total_angle_deg=360, rotate_instances=False,
                            unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct "
                            "non-empty entity names.")

    count, error = _pattern_count(count, "count")
    if error:
        return _invalid(sw, error)
    if count < 2:
        return _invalid(sw, "count must be at least 2.")

    if not _is_number(total_angle_deg) or not 0 < total_angle_deg <= 360:
        return _invalid(sw, "total_angle_deg must be in (0, 360].")

    center_x_m, error = _convert_length(sw, center_x, unit, "center_x")
    if error:
        return error
    center_y_m, error = _convert_length(sw, center_y, unit, "center_y")
    if error:
        return error

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    computed = {}

    def prepare(_context):
        reference = _selection_reference_point(document)
        if reference is None:
            return _invalid(
                sw,
                "Could not read the selected seed geometry; the circular "
                "pattern needs selectable sketch entities.",
            )
        seed = reference
        radius = math.hypot(seed[0] - center_x_m, seed[1] - center_y_m)
        if radius <= 1e-9:
            return _invalid(
                sw,
                "The seed geometry sits on the pattern centre; choose a "
                "centre away from the seed.",
            )
        computed["seed"] = seed
        computed["radius"] = radius
        # SolidWorks puts the pattern centre at
        # seed + radius * (cos(ArcAngle), sin(ArcAngle)), so the angle that
        # makes the seed a vertex about the requested centre is its bearing
        # from the centre turned through 180 degrees.
        computed["arc_angle"] = math.atan2(
            seed[1] - center_y_m, seed[0] - center_x_m
        ) + math.pi
        # A negative spacing steps counter-clockwise in SW 2025.
        computed["spacing"] = (
            0.0 if total_angle_deg >= 360.0
            else -math.radians(total_angle_deg) / count
        )
        return None

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="pattern",
        call=lambda _context: com(
            document.SketchManager, "CreateCircularSketchStepAndRepeat",
            computed["radius"], computed["arc_angle"], count,
            computed["spacing"], bool(rotate_instances), "",
            False, False, False,
        ),
        failure_code="PATTERN_FAILED",
        failure_label="Circular sketch pattern",
        require_change=True,
        prepare=prepare,
    )
    if isinstance(changed, dict):
        return changed

    try:
        radius_display = sw._units.from_meters(computed["radius"], unit)
        seed_display = [
            sw._units.from_meters(value, unit) for value in computed["seed"]
        ]
    except (KeyError, TypeError, ValueError):  # pragma: no cover - defensive
        radius_display = computed["radius"]
        seed_display = list(computed["seed"])

    return sw._result(
        True,
        f"Created a {count}-instance circular pattern of "
        f"{', '.join(names)} in {sketch} about ({center_x}, {center_y}){unit}.",
        data={
            "sketch": sketch,
            "entities": names,
            "count": count,
            "center": [center_x, center_y],
            "total_angle_deg": total_angle_deg,
            "rotate_instances": bool(rotate_instances),
            "unit": unit,
            "seed_center": seed_display,
            "arc_radius": radius_display,
            "arc_radius_meters": computed["radius"],
            "arc_angle_deg": math.degrees(computed["arc_angle"]),
            "spacing_radians": computed["spacing"],
            "geometry_changed": changed,
        },
    )


# SketchAddConstraints takes these legacy strings; verified live one by one in
# SW 2025 SP1.1 (docs/api-findings.md section 27). Note the one-L "sgCOLINEAR"
# and that "sgEQUAL" does not exist in this build - equal length and equal
# radius are both "sgSAMELENGTH".
SKETCH_RELATION_STRINGS = {
    "horizontal": "sgHORIZONTAL",
    "vertical": "sgVERTICAL",
    "tangent": "sgTANGENT",
    "parallel": "sgPARALLEL",
    "perpendicular": "sgPERPENDICULAR",
    "coincident": "sgCOINCIDENT",
    "concentric": "sgCONCENTRIC",
    "symmetric": "sgSYMMETRIC",
    "same_length": "sgSAMELENGTH",
    "fixed": "sgFIXED",
    "colinear": "sgCOLINEAR",
}

# swConstraintType_e -> relation name, for reporting.
SKETCH_RELATION_LABELS = {
    4: "horizontal",
    5: "vertical",
    6: "tangent",
    7: "parallel",
    8: "perpendicular",
    9: "coincident",
    10: "concentric",
    11: "symmetric",
    14: "same_length",
    17: "fixed",
    27: "colinear",
}

# swConstrainedStatus_e.
SKETCH_CONSTRAINED_STATUS = {
    1: "unknown",
    2: "under_constrained",
    3: "fully_constrained",
    4: "over_constrained",
    5: "no_solution",
    6: "invalid_solution",
    7: "autosolve_off",
}


def _relation_reader(feature):
    """An ISketchRelationManager for a sketch feature, open or closed."""
    sketch = com(feature, "GetSpecificFeature2")
    if sketch is None:
        return None, None
    manager = com(sketch, "RelationManager")
    return sketch, manager


def _sketch_relations(document, feature):
    """(constrained status id, sorted relation type ids) of a sketch."""
    sketch, manager = _relation_reader(feature)
    if manager is None:
        return None
    types = []
    for relation in list(com(manager, "GetRelations", 0) or []):
        try:
            types.append(int(com(relation, "GetRelationType")))
        except Exception:  # noqa: BLE001
            continue
    return (int(com(sketch, "GetConstrainedStatus")), tuple(sorted(types)))


def _delete_relations(document, relation_key):
    """Delete every relation, or only those of one type, in the active sketch."""
    manager = com(com(document, "GetActiveSketch2"), "RelationManager")
    if manager is None:
        return False
    if relation_key is None:
        return bool(com(manager, "DeleteAllRelations"))
    wanted = SKETCH_RELATION_LABELS.items()
    wanted_id = next(identifier for identifier, label in wanted
                     if label == relation_key)
    removed = False
    for relation in list(com(manager, "GetRelations", 0) or []):
        if int(com(relation, "GetRelationType")) == wanted_id:
            if com(manager, "DeleteRelation", relation):
                removed = True
    return removed


@tool(
    name="add_sketch_relation",
    description=(
        "Add one geometric relation (constraint) to entities inside a named "
        "sketch. Entities are given by their exact sketch names (Line1, Arc1, "
        "Point1) and are selected as segments or sketch points automatically. "
        "SolidWorks silently ignores a relation the geometry already "
        "satisfies, and that is reported as a failure. Relations: "
        "horizontal, vertical, tangent, parallel, perpendicular, coincident, "
        "concentric, symmetric, same_length, fixed, colinear."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1},
        "relation": {"type": "string", "enum": sorted(SKETCH_RELATION_STRINGS)},
    }, "required": ["sketch", "entities", "relation"]},
    operation_class=OperationClass.MUTATE,
)
def add_sketch_relation(sw, sketch, entities, relation):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None:
        return _invalid(sw, "entities must be one or more distinct non-empty "
                            "entity names.")

    key = relation.strip().casefold() if isinstance(relation, str) else None
    if key not in SKETCH_RELATION_STRINGS:
        return _invalid(sw, f"relation must be one of: "
                            f"{', '.join(sorted(SKETCH_RELATION_STRINGS))}.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    changed = _edit_and_verify(
        sw, document, feature, names,
        action=f"add the {key} relation to",
        call=lambda _context: com(document, "SketchAddConstraints",
                                  SKETCH_RELATION_STRINGS[key]),
        failure_code="RELATION_NOT_ADDED",
        failure_label=f"{key} relation",
        require_change=True,
        observe=_sketch_relations,
        types=("SKETCHSEGMENT", "SKETCHPOINT"),
        unchanged_note=("the relation list did not change, which is how "
                        "SolidWorks ignores a relation the geometry already "
                        "satisfies"),
    )
    if isinstance(changed, dict):
        return changed

    status = _sketch_relations(document, feature)
    new_relations = []
    if status is not None:
        new_relations = [SKETCH_RELATION_LABELS.get(identifier, str(identifier))
                         for identifier in status[1]]
    return sw._result(
        True,
        f"Added the {key} relation to {', '.join(names)} in {sketch}.",
        SwErrors.swSuccess,
        {
            "sketch": sketch,
            "entities": names,
            "relation": key,
            "relation_string": SKETCH_RELATION_STRINGS[key],
            "relations": new_relations,
            "relation_count": len(new_relations),
            "geometry_changed": changed,
        },
    )


@tool(
    name="get_sketch_relations",
    description=(
        "List the relations of a named sketch and report whether it is fully "
        "defined. Runs on a closed sketch and changes nothing."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
    }, "required": ["sketch"]},
    operation_class=OperationClass.READ,
)
def get_sketch_relations(sw, sketch):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    state = _sketch_relations(document, feature)
    if state is None:
        return sw._result(False, f"Could not read the relations of {sketch}.",
                          SwErrors.swSketchError)
    status, types = state
    relations = [{"type_id": identifier,
                  "relation": SKETCH_RELATION_LABELS.get(identifier,
                                                         str(identifier))}
                 for identifier in types]
    counts = {}
    for identifier in types:
        label = SKETCH_RELATION_LABELS.get(identifier, str(identifier))
        counts[label] = counts.get(label, 0) + 1
    return sw._result(
        True,
        f"{sketch} has {len(relations)} relation(s) and is "
        f"{SKETCH_CONSTRAINED_STATUS.get(status, 'unknown').replace('_', ' ')}.",
        SwErrors.swSuccess,
        {
            "sketch": sketch,
            "relation_count": len(relations),
            "relations": relations,
            "relation_counts": counts,
            "constrained_status_id": status,
            "constrained_status": SKETCH_CONSTRAINED_STATUS.get(status, "unknown"),
            "fully_defined": status == 3,
        },
    )


@tool(
    name="delete_sketch_relations",
    description=(
        "Delete relations from a named sketch: all of them, or every relation "
        "of one type. Success is confirmed by the relation list changing."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "relation": {"type": "string",
                     "enum": sorted(SKETCH_RELATION_STRINGS)},
        "all": {"type": "boolean", "default": False},
    }, "required": ["sketch"]},
    operation_class=OperationClass.MUTATE,
)
def delete_sketch_relations(sw, sketch, relation=None, all=False):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    if relation is None and not all:
        return _invalid(sw, "Give a relation to delete, or set all true to "
                            "delete every relation.")
    if relation is not None and all:
        return _invalid(sw, "Give either a relation or all true, not both.")

    key = relation.strip().casefold() if isinstance(relation, str) else None
    if relation is not None and key not in SKETCH_RELATION_STRINGS:
        return _invalid(sw, f"relation must be one of: "
                            f"{', '.join(sorted(SKETCH_RELATION_STRINGS))}.")

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    target = "all relations" if key is None else f"every {key} relation"
    changed = _edit_and_verify(
        sw, document, feature, [],
        action=f"delete {target} from",
        call=lambda _context: _delete_relations(document, key),
        failure_code="RELATION_NOT_DELETED",
        failure_label=f"delete {target}",
        require_change=True,
        observe=_sketch_relations,
        unchanged_note="the relation list did not change; no such relation "
                       "was present",
    )
    if isinstance(changed, dict):
        return changed

    state = _sketch_relations(document, feature)
    remaining = 0 if state is None else len(state[1])
    return sw._result(
        True,
        f"Deleted {target} in {sketch}; {remaining} relation(s) remain.",
        SwErrors.swSuccess,
        {
            "sketch": sketch,
            "deleted": target,
            "relation_count": remaining,
            "geometry_changed": changed,
        },
    )


# swSetValueReturnStatus_e.
SET_VALUE_STATUS = {
    0: "success",
    1: "failure",
    2: "invalid_value",
    3: "driven_dimension",
    4: "model_not_loaded",
    5: "frozen_feature_owner",
}

# swUserPreferenceToggle_e.swInputDimValOnCreate.  SOLIDWORKS API Help for
# IModelDoc2.AddDimension2 explicitly recommends disabling this preference to
# suppress the dialog that asks the user to enter the new dimension value.
SW_INPUT_DIM_VALUE_ON_CREATE = 10


# SolidWorks keeps reporting the just-finished sketch as the running
# "Edit Sketch" command after InsertSketch2, so that name means nothing.
# Measured in SW 2025 SP1.1: idle is (-3, '', False), a committed dimension is
# (-3, '', False), an uncommitted one is (17, 'Dimension', True) and the stale
# sketch report is (17, 'Edit Sketch', True).  The command id is 17 in both
# running cases, so the name is what distinguishes them.
IGNORED_RUNNING_COMMANDS = frozenset({"Edit Sketch"})


def _running_command(sw):
    """The SolidWorks command that is still waiting for the user, if any.

    ``AddDimension2`` leaves the Dimension command running until the user
    confirms; an immediate ``EditRebuild3`` commits it and clears this.
    """
    try:
        info = com(sw.app, "GetRunningCommandInfo")
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    values = list(info) + [None, None, None]
    command_id, command_name = values[0], values[1]
    name = str(command_name).strip() if command_name else ""
    if not name or name in IGNORED_RUNNING_COMMANDS:
        return None
    return (command_id, name)


@tool(
    name="add_sketch_dimension",
    description=(
        "Add a driving dimension to one or two entities of a named sketch, at "
        "the given label position, and optionally set its value. The dimension "
        "is committed with an immediate rebuild, so SolidWorks is never left "
        "waiting for a manual confirmation. Setting a value resizes the "
        "geometry; a dimension SolidWorks makes reference-only is reported as "
        "DRIVEN_DIMENSION."
    ),
    schema={"type": "object", "properties": {
        "sketch": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"},
                     "minItems": 1, "maxItems": 2},
        "x": {"type": "number"},
        "y": {"type": "number"},
        "value": {"type": "number"},
        "unit": UNIT_SCHEMA,
    }, "required": ["sketch", "entities", "x", "y"]},
    operation_class=OperationClass.MUTATE,
)
def add_sketch_dimension(sw, sketch, entities, x, y, value=None, unit="mm"):
    if not isinstance(sketch, str) or not sketch.strip():
        return _invalid(sw, "sketch must be a non-empty sketch name.")

    names = _clean_names(entities)
    if names is None or len(names) > 2:
        return _invalid(sw, "entities must be one or two distinct non-empty "
                            "entity names.")

    if not _is_number(x) or not _is_number(y):
        return _invalid(sw, "The label position must be two finite numbers.")

    value_meters = None
    if value is not None:
        value_meters, error = _convert_length(sw, value, unit, "value")
        if error:
            return error
        if value_meters <= 0:
            return _invalid(sw, "value must be greater than zero.")

    x_meters, error = _convert_length(sw, x, unit, "x")
    if error:
        return error
    y_meters, error = _convert_length(sw, y, unit, "y")
    if error:
        return error

    document, error = _require_part(sw)
    if error:
        return error
    feature, error = _sketch_feature(sw, document, sketch)
    if error:
        return error

    captured = {}

    def apply(_context):
        old_input_prompt = bool(com(
            sw.app, "GetUserPreferenceToggle", SW_INPUT_DIM_VALUE_ON_CREATE))
        try:
            com(sw.app, "SetUserPreferenceToggle",
                SW_INPUT_DIM_VALUE_ON_CREATE, False)
            display = com(document, "AddDimension2", x_meters, y_meters, 0.0)
        finally:
            # This is a global SOLIDWORKS user preference, not a document
            # setting.  Always restore it, including when AddDimension2 fails.
            com(sw.app, "SetUserPreferenceToggle",
                SW_INPUT_DIM_VALUE_ON_CREATE, old_input_prompt)
        if display is None:
            return None
        captured["display"] = display
        # Rebuild after creation and again after assigning the driving value.
        # The preference above, not this rebuild, suppresses the input dialog.
        com(document, "EditRebuild3")
        if value_meters is None:
            return display
        dimension = com(display, "GetDimension")
        if dimension is None:
            return None
        captured["dimension"] = dimension
        captured["set_status"] = int(
            com(dimension, "SetSystemValue2", value_meters, 0))
        com(document, "EditRebuild3")
        return dimension

    changed = _edit_and_verify(
        sw, document, feature, names,
        action="dimension",
        call=apply,
        failure_code="DIMENSION_FAILED",
        failure_label="Sketch dimension",
    )
    if isinstance(changed, dict):
        return changed

    # A command that is still running means SolidWorks is waiting for the user
    # to confirm; that must never be reported as success.
    pending = _running_command(sw)
    if pending is not None:
        return sw._result(
            False,
            f"SolidWorks is still running the {pending[1]} command; the "
            "dimension was not committed.",
            SwErrors.swFeatureError,
            {"code": "DIMENSION_NOT_COMMITTED", "running_command": pending[1]},
        )

    status = captured.get("set_status")
    if value_meters is not None and status != 0:
        return sw._result(
            False,
            f"SolidWorks refused the value: "
            f"{SET_VALUE_STATUS.get(status, status)}.",
            SwErrors.swFeatureError,
            {"code": "DIMENSION_VALUE_REJECTED",
             "set_value_status": SET_VALUE_STATUS.get(status, status)},
        )

    if value_meters is not None and not changed and len(names) == 1:
        return sw._result(
            False,
            f"The {names[0]} dimension was accepted but the geometry did not "
            "change, so it is not driving the sketch.",
            SwErrors.swFeatureError,
            {"code": "DIMENSION_DID_NOT_DRIVE"},
        )

    dimension = captured.get("dimension")
    display = captured.get("display")
    reported = {}
    for label, source in (("value", dimension), ("display", display)):
        if source is None:
            continue
        try:
            if label == "value":
                reported["dimension_value"] = round(
                    float(com(source, "SystemValue")) / sw._units.to_meters(
                        1.0, unit), 6)
                reported["dimension_name"] = com(source, "FullName")
                reported["read_only"] = bool(com(source, "ReadOnly"))
            else:
                reported["display_dimension"] = True
        except Exception:  # noqa: BLE001
            continue

    return sw._result(
        True,
        f"Dimension added to {', '.join(names)} in {sketch}"
        + (f" and set to {value}{unit}." if value_meters is not None
           else " without changing its value."),
        SwErrors.swSuccess,
        {
            "sketch": sketch,
            "entities": names,
            "label_position": [x, y],
            "unit": unit,
            "value": value,
            "geometry_changed": changed,
            **reported,
        },
    )
