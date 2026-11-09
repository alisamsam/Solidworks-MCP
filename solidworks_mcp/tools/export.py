"""
Export tools (part G): planar face and flat pattern export to DXF.
"""

import logging
import hashlib
import math
import os
from pathlib import Path

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .guard import require_output_write

logger = logging.getLogger("SolidWorksMCP")

SW_DOC_PART = 1
SW_SOLID_BODY = 0
SW_EXPORT_SELECTED_FACES_OR_LOOPS = 2
MAX_LOOP_ITER = 500
SW_SAVE_AS_SILENT = 1


def _export_native_model(sw, output_path: str, allowed_extensions: set[str], format_name: str):
    path = Path(output_path).expanduser().resolve()
    if path.suffix.casefold() not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        return sw._result(
            False, f"{format_name} output must use one of: {allowed}.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
        )
    if path.exists():
        return sw._result(
            False, f"Export path already exists: {path}", SwErrors.swFileSaveError,
            {"code": "OUTPUT_EXISTS"},
        )
    denied = require_output_write(sw, str(path))
    if denied:
        return denied
    document, error = sw.get_active_doc()
    if error:
        return error

    path.parent.mkdir(parents=True, exist_ok=True)
    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    empty_export = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    try:
        extension = com(document, "Extension")
        succeeded = com(
            extension, "SaveAs", str(path), 0, SW_SAVE_AS_SILENT,
            empty_export, errors, warnings
        )
    except Exception as export_error:
        path.unlink(missing_ok=True)
        return sw._result(
            False, f"{format_name} export failed: {export_error}", SwErrors.swExportError
        )
    if not succeeded or errors.value or not path.is_file():
        path.unlink(missing_ok=True)
        return sw._result(
            False, f"{format_name} export failed (code {errors.value}).",
            SwErrors.swExportError,
            {"save_error_code": int(errors.value), "save_warning_code": int(warnings.value)},
        )

    payload = path.read_bytes()
    return sw._result(True, f"Exported {format_name} to {path}.", data={
        "path": str(path),
        "format": format_name,
        "save_warning_code": int(warnings.value),
        "verification": {
            "method": "sha256",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        },
    })


@tool(
    name="export_step",
    description="Export the active model to a new STEP/STP file without saving the native document.",
    schema={"type": "object", "properties": {
        "output_path": {"type": "string", "description": "New .step or .stp path."},
    }, "required": ["output_path"]},
    operation_class=OperationClass.EXPORT,
)
def export_step(sw, output_path: str) -> dict:
    return _export_native_model(sw, output_path, {".step", ".stp"}, "STEP")


@tool(
    name="export_stl",
    description=(
        "Export the active model to a new STL file using the current SolidWorks "
        "tessellation and binary/ASCII preferences."
    ),
    schema={"type": "object", "properties": {
        "output_path": {"type": "string", "description": "New .stl path."},
    }, "required": ["output_path"]},
    operation_class=OperationClass.EXPORT,
)
def export_stl(sw, output_path: str) -> dict:
    result = _export_native_model(sw, output_path, {".stl"}, "STL")
    if result.get("success"):
        result["data"]["settings_source"] = "SolidWorks user preferences"
    return result


@tool(
    name="list_planar_faces",
    description=(
        "List the planar faces of the open part, with index, area and normal. "
        "Use the index to pick a face for DXF export. Read-only."
    ),
    schema={
        "type": "object",
        "properties": {
            "min_area_mm2": {
                "type": "number",
                "description": "Skip faces smaller than this. Default 0."
            }
        },
        "required": []
    },
    operation_class=OperationClass.READ,
)
def list_planar_faces(sw, min_area_mm2: float = 0.0) -> dict:
    """List planar faces of the active part"""
    doc, err = sw.get_active_doc()
    if err:
        return err

    if com(doc, "GetType") != SW_DOC_PART:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)

    try:
        bodies = com(doc, "GetBodies2", SW_SOLID_BODY, True)
    except Exception as e:
        logger.error(f"GetBodies2 failed: {e}")
        return sw._result(False, f"Could not read bodies: {e}",
                          SwErrors.swUnknownError)

    if not bodies:
        return sw._result(False, "Part has no solid bodies.",
                          SwErrors.swExportError)

    faces = []
    index = 0
    for body_index, body in enumerate(bodies):
        body_name = com(body, "Name")
        for face in com(body, "GetFaces") or []:
            surface = com(face, "GetSurface")
            if com(surface, "IsPlane"):
                area_mm2 = com(face, "GetArea") * 1_000_000
                if area_mm2 >= min_area_mm2:
                    px, py, pz = com(surface, "PlaneParams")[3:6]
                    # The surface normal can point into the body (B25).
                    nx, ny, nz = com(face, "Normal")[:3]
                    faces.append({
                        "index": index,
                        "body": body_name,
                        "body_index": body_index,
                        "area_mm2": round(area_mm2, 2),
                        "normal": [round(nx, 6), round(ny, 6), round(nz, 6)],
                        "point_mm": [round(px * 1000, 3), round(py * 1000, 3),
                                     round(pz * 1000, 3)]
                    })
            index += 1

    faces.sort(key=lambda f: f["area_mm2"], reverse=True)

    return sw._result(
        True,
        f"Found {len(faces)} planar faces in {len(bodies)} bodies.",
        data={"bodies": len(bodies), "faces": faces}
    )


def _get_planar_face_by_index(doc, face_index):
    """
    Looks up a face by the same `index` list_planar_faces reports: a
    counter over ALL faces (planar and not) of all bodies, not reset per
    body. Returns None if face_index is out of range or not planar.
    """
    bodies = com(doc, "GetBodies2", SW_SOLID_BODY, True) or []
    index = 0
    for body in bodies:
        for face in com(body, "GetFaces") or []:
            if index == face_index:
                surface = com(face, "GetSurface")
                return face if com(surface, "IsPlane") else None
            index += 1
    return None


def _longest_edge_direction(face):
    """
    Unit direction of the longest straight edge of a planar face's outer
    loop, projected into the face plane. Used to derive in-plane X/Y axes
    from geometry instead of a blindly assumed global (1,0,0)/(0,1,0)
    (O11 — see api-findings.md §3.4, previous export came out rotated).

    GetFirstLoop/GetFirstCoEdge/GetNext are COM properties in SW2025, not
    methods: a bare `.GetNext` access (no com() wrapper) returns a bound
    method object, which is always truthy, never None -- iterating on that
    hangs forever. Always go through com(), and still cap iterations as a
    second line of defense against a malformed loop.
    """
    # GetFirstLoop may be an inner circular hole, as on the actual stair
    # side plate. Native traversal order does not identify the outer contour.
    outer = [loop for loop in com(face, "GetLoops") or [] if com(loop, "IsOuter")]
    if len(outer) != 1:
        return None
    loop = outer[0]

    first_coedge = com(loop, "GetFirstCoEdge")
    coedge = first_coedge
    best_length = 0.0
    best_dir = None
    i = 0
    while coedge is not None and i < MAX_LOOP_ITER:
        edge = com(coedge, "GetEdge")
        curve = com(edge, "GetCurve")
        if com(curve, "IsLine"):
            sv = com(edge, "GetStartVertex")
            ev = com(edge, "GetEndVertex")
            if sv is not None and ev is not None:
                p1 = com(sv, "GetPoint")
                p2 = com(ev, "GetPoint")
                dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
                length = math.sqrt(dx * dx + dy * dy + dz * dz)
                if length > best_length:
                    best_length = length
                    best_dir = (dx / length, dy / length, dz / length)
        nxt = com(coedge, "GetNext")
        same_first = nxt is first_coedge
        if nxt is not None and hasattr(nxt,'_oleobj_') and hasattr(first_coedge,'_oleobj_'):
            same_first = nxt._oleobj_ == first_coedge._oleobj_
        coedge = None if (nxt is None or same_first) else nxt
        i += 1

    return best_dir


def _face_plane_axes(face):
    """
    Returns (normal, point, xdir, ydir) for a planar face: the outward
    normal from IFace2.Normal (PlaneParams' normal can point into the body,
    which mirrored the DXF -- B25), point from PlaneParams, xdir from the longest straight edge (projected into
    the plane), ydir = normal x xdir. All unit vectors, meters.
    """
    surface = com(face, "GetSurface")
    px, py, pz = com(surface, "PlaneParams")[3:6]
    nx, ny, nz = com(face, "Normal")[:3]
    normal = (nx, ny, nz)
    point = (px, py, pz)

    edge_dir = _longest_edge_direction(face)
    if edge_dir is None:
        return normal, point, None, None

    dot = edge_dir[0] * nx + edge_dir[1] * ny + edge_dir[2] * nz
    xpx = edge_dir[0] - dot * nx
    xpy = edge_dir[1] - dot * ny
    xpz = edge_dir[2] - dot * nz
    xn = math.sqrt(xpx * xpx + xpy * xpy + xpz * xpz)
    if xn < 1e-9:
        return normal, point, None, None
    xdir = (xpx / xn, xpy / xn, xpz / xn)
    ydir = (
        ny * xdir[2] - nz * xdir[1],
        nz * xdir[0] - nx * xdir[2],
        nx * xdir[1] - ny * xdir[0],
    )
    return normal, point, xdir, ydir


@tool(
    name="export_face_to_dxf",
    description=(
        "Export a single planar face of the active part to a DXF or DWG "
        "file, for laser/plasma cutting. face_index refers to the index "
        "from list_planar_faces on the current model state -- re-run "
        "list_planar_faces if the model changed since. In-plane axes are "
        "derived from the face's longest straight edge, so the output is "
        "not rotated. Does not modify the model."
    ),
    schema={
        "type": "object",
        "properties": {
            "face_index": {
                "type": "integer",
                "description": "Index from list_planar_faces"
            },
            "output_path": {
                "type": "string",
                "description": "Full destination path, extension .dxf or .dwg"
            }
        },
        "required": ["face_index", "output_path"]
    },
    operation_class=OperationClass.EXPORT,
)
def export_face_to_dxf(sw, face_index: int, output_path: str) -> dict:
    """Export a single planar face of the active part to DXF/DWG."""
    denied = require_output_write(sw, output_path)
    if denied:
        return denied
    doc, err = sw.get_active_doc()
    if err:
        return err

    if com(doc, "GetType") != SW_DOC_PART:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)

    ext = os.path.splitext(output_path)[1].lower()
    if ext not in (".dxf", ".dwg"):
        return sw._result(False, f"Unsupported output extension: {ext}",
                          SwErrors.swInvalidInput)

    # ExportToDWG2 needs the model path as its base-name argument; with an
    # unsaved part it fails with no explanation (same as flat patterns).
    if not com(doc, "GetPathName"):
        return sw._result(
            False,
            "SolidWorks needs a saved model path to export a face. "
            "Save the part first (save_document) and retry.",
            SwErrors.swFileSaveError,
            {"code": "UNSAVED_DOCUMENT"},
        )

    face = _get_planar_face_by_index(doc, face_index)
    if face is None:
        return sw._result(
            False,
            f"face_index {face_index} does not refer to a planar face on "
            "the current model. Re-run list_planar_faces.",
            SwErrors.swInvalidInput
        )

    normal, point, xdir, ydir = _face_plane_axes(face)
    if xdir is None:
        return sw._result(
            False,
            "Could not derive in-plane axes from face geometry "
            "(no straight edge found on outer loop).",
            SwErrors.swExportError
        )

    try:
        com(doc, "ClearSelection2", True)
        com(face, "Select4", False,
            win32com.client.VARIANT(pythoncom.VT_DISPATCH, None))

        alignment = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [point[0], point[1], point[2],
             xdir[0], xdir[1], xdir[2],
             ydir[0], ydir[1], ydir[2],
             normal[0], normal[1], normal[2]])
        views = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

        ok = com(doc, "ExportToDWG2", output_path, com(doc, "GetPathName"),
                 SW_EXPORT_SELECTED_FACES_OR_LOOPS, True, alignment,
                 False, False, 0, views)
    except Exception as e:
        logger.error(f"ExportToDWG2 (face) failed: {e}")
        return sw._result(False, f"Export failed: {e}", SwErrors.swExportError)
    finally:
        com(doc, "ClearSelection2", True)

    if not ok:
        return sw._result(False, "Export failed.", SwErrors.swExportError)

    exported = Path(output_path)
    if not exported.is_file() or exported.stat().st_size==0:
        return sw._result(False,'Export returned success without a non-empty output file.',SwErrors.swExportError)

    return sw._result(
        True,
        f"Exported face {face_index} to {output_path}.",
        data={"path": output_path,'size_bytes':exported.stat().st_size,
              'sha256':hashlib.sha256(exported.read_bytes()).hexdigest()}
    )
