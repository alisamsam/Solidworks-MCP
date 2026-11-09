"""
Sketch creation tools (M1.4).

A sketch on a named plane (standard or reference) and a 3D sketch.  The
distinction is read back from SolidWorks rather than assumed: a 2D sketch is a
``ProfileFeature`` and a 3D sketch is a ``3DProfileFeature``, and
``ISketch.Is3D`` confirms what is active.  See docs/api-findings.md section 29.
"""

import pythoncom
import win32com.client

from ..comutil import com, set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

# Convenience spellings for the standard planes.
PLANE_SHORTHAND = {
    "front": "Front Plane",
    "top": "Top Plane",
    "right": "Right Plane",
}

# swFeatureNameID type names as SolidWorks reports them.
SKETCH_TYPE_2D = "ProfileFeature"
SKETCH_TYPE_3D = "3DProfileFeature"

SW_DOC_PART = 1


def _invalid(sw, message, code="VALIDATION_FAILED"):
    return sw._result(False, message, SwErrors.swInvalidInput, {"code": code})


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


def _newest_sketch(document, type_name):
    """Name of the newest sketch feature of one type, or None."""
    name = None
    cursor = com(document, "FirstFeature")
    while cursor is not None:
        if com(cursor, "GetTypeName2") == type_name:
            name = com(cursor, "Name")
        cursor = com(cursor, "GetNextFeature")
    return name


def _active_sketch_is_3d(document):
    """True/False for the active sketch, or None when no sketch is open."""
    sketch = com(document, "GetActiveSketch2")
    if sketch is None:
        return None
    return bool(com(sketch, "Is3D"))


def _already_open(sw):
    return _invalid(
        sw,
        "A sketch is already open. Close it before starting another one.",
        "SKETCH_ALREADY_OPEN",
    )


@tool(
    name="create_sketch_on_plane",
    description=(
        "Start a new 2D sketch on any named plane that exists in the part: a "
        "standard plane (Front Plane, Top Plane, Right Plane, or the shorthands "
        "Front/Top/Right) or a reference plane such as Plane1. The sketch is "
        "created and left open for editing, and its feature name is returned."
    ),
    schema={"type": "object", "properties": {
        "plane": {"type": "string"},
        "exact_geometry": {"type": "boolean", "default": False},
    }, "required": ["plane"]},
    operation_class=OperationClass.MUTATE,
)
def create_sketch_on_plane(sw, plane, exact_geometry=False):
    if not isinstance(plane, str) or not plane.strip():
        return _invalid(sw, "plane must be a non-empty plane name.")

    if not isinstance(exact_geometry, bool):
        return _invalid(sw, "exact_geometry must be true or false.")

    name = plane.strip()
    name = PLANE_SHORTHAND.get(name.casefold(), name)

    document, error = _require_part(sw)
    if error:
        return error
    if _active_sketch_is_3d(document) is not None:
        return _already_open(sw)

    com(document, "ClearSelection2", True)
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    if not com(document.Extension, "SelectByID2", name, "PLANE", 0.0, 0.0, 0.0,
               False, 0, callout, 0):
        return sw._result(
            False,
            f"Plane not found: {name}. Use the exact plane feature name.",
            SwErrors.swSelectionError,
            {"code": "PLANE_NOT_FOUND"},
        )

    com(document, "InsertSketch2", True)
    active = _active_sketch_is_3d(document)
    if active is None:
        return sw._result(
            False,
            f"SolidWorks did not start a sketch on {name}.",
            SwErrors.swSketchError,
            {"code": "SKETCH_NOT_CREATED"},
        )
    if active:
        return sw._result(
            False,
            f"SolidWorks started a 3D sketch on {name} instead of a 2D sketch.",
            SwErrors.swSketchError,
            {"code": "UNEXPECTED_3D_SKETCH"},
        )

    set_com(com(document, "SketchManager"), "AddToDB", exact_geometry)
    sketch_name = _newest_sketch(document, SKETCH_TYPE_2D)
    return sw._result(
        True,
        f"Started a sketch on {name}.",
        SwErrors.swSuccess,
        {
            "plane": name,
            "sketch": sketch_name,
            "is_3d": False,
            "exact_geometry": exact_geometry,
        },
    )


@tool(
    name="create_3d_sketch",
    description=(
        "Start a new 3D sketch. Nothing has to be selected; the sketch is "
        "created and left open for editing. In a 3D sketch the points passed to "
        "the drawing tools are world coordinates (x, y, z) instead of "
        "coordinates in a sketch plane."
    ),
    schema={"type": "object", "properties": {
        "exact_geometry": {"type": "boolean", "default": False},
    }, "required": []},
    operation_class=OperationClass.MUTATE,
)
def create_3d_sketch(sw, exact_geometry=False):
    if not isinstance(exact_geometry, bool):
        return _invalid(sw, "exact_geometry must be true or false.")

    document, error = _require_part(sw)
    if error:
        return error
    if _active_sketch_is_3d(document) is not None:
        return _already_open(sw)

    com(document, "ClearSelection2", True)
    com(document, "Insert3DSketch2", True)

    active = _active_sketch_is_3d(document)
    if active is None:
        return sw._result(
            False,
            "SolidWorks did not start a 3D sketch.",
            SwErrors.swSketchError,
            {"code": "SKETCH_NOT_CREATED"},
        )
    if not active:
        return sw._result(
            False,
            "SolidWorks started a 2D sketch instead of a 3D sketch.",
            SwErrors.swSketchError,
            {"code": "NOT_A_3D_SKETCH"},
        )

    set_com(com(document, "SketchManager"), "AddToDB", exact_geometry)
    sketch_name = _newest_sketch(document, SKETCH_TYPE_3D)
    return sw._result(
        True,
        "Started a 3D sketch.",
        SwErrors.swSuccess,
        {
            "sketch": sketch_name,
            "is_3d": True,
            "exact_geometry": exact_geometry,
        },
    )
