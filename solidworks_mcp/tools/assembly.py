"""
Assembly tools (part E): insert components, mate them, and pack and go.
"""

import logging
import math
import os

import pythoncom
import win32com.client

from ..comutil import com, set_com
from ..constants import SwDocumentTypes, SwErrors, SwMateTypes
from ..core.policy import OperationClass
from ..core.progress import report_progress
from ..registry import tool
from .guard import require_output_write

logger = logging.getLogger("SolidWorksMCP")

SW_ADD_COMPONENT_DEFAULT_CONFIG = 0


def _require_assembly(sw):
    """Returns (doc, error_dict). error_dict is None if doc is an open assembly."""
    doc, err = sw.get_active_doc()
    if err:
        return None, err
    if com(doc, "GetType") != SwDocumentTypes.swDocASSEMBLY:
        return None, sw._result(False, "Active document is not an assembly.",
                                SwErrors.swInvalidFileType)
    return doc, None


def _find_component(asm, name):
    """
    Finds a component by Name2 (e.g. "Block1-1") or by its full recursive
    path (e.g. "Sub-1/Part-2"), searched over ALL components, not just
    top-level (api-findings.md §6.2 -- recursive names are "/"-separated
    paths).
    """
    comps = [(comp, com(comp, "Name2")) for comp in com(asm, "GetComponents", False) or []]
    for comp, comp_name in comps:
        if comp_name == name:
            return comp
    for comp, comp_name in comps:
        if comp_name.endswith("/" + name):
            return comp
    return None


def _local_to_global(local_pt, tfdata):
    """
    Component-local point -> assembly-global point, via the component's
    Transform.ArrayData (16 floats: R00..R22, Tx,Ty,Tz, scale, 0,0,0).

    api-findings.md §6.5: IMathUtility.CreatePoint + MultiplyTransform is
    BROKEN (always returns the translation alone, ignores the input
    point) -- do not use it. This manual matrix multiply is the verified
    replacement.
    """
    lx, ly, lz = local_pt
    r = tfdata
    scale = r[12]
    gx = (lx * r[0] + ly * r[3] + lz * r[6]) * scale + r[9]
    gy = (lx * r[1] + ly * r[4] + lz * r[7]) * scale + r[10]
    gz = (lx * r[2] + ly * r[5] + lz * r[8]) * scale + r[11]
    return gx, gy, gz


def _component_bodies(component):
    """
    All solid bodies of a component, in a stable order.

    api-findings.md 21.5: IComponent2.GetBody returns only the FIRST body, so
    a multi-body part (e.g. a bearing modelled as two separate rings) exposed
    none of the faces on its other bodies and every mate against it failed.
    GetBodies2 is preferred, with GetBody as a fallback for mocks/older builds.
    """
    try:
        bodies = com(component, "GetBodies2", 0, True) or []
    except Exception:
        bodies = []
    if not bodies:
        body = com(component, "GetBody")
        bodies = [body] if body is not None else []
    return bodies


def _component_faces(component):
    """
    Enumerates a component's faces in a stable order (planar and
    cylindrical only -- the two types mate_* tools support). Returns a
    list of (face, kind) where kind is "planar" or "cylindrical". Index
    into this list is the face_index used by list_component_faces and
    the mate_* tools.
    """
    result = []
    for body in _component_bodies(component):
        for face in com(body, "GetFaces") or []:
            surface = com(face, "GetSurface")
            if com(surface, "IsPlane"):
                result.append((face, "planar"))
            elif com(surface, "IsCylinder"):
                result.append((face, "cylindrical"))
    return result


def _face_local_point(face, kind):
    """
    A point on the face, in the component's local part-space, chosen to
    lie safely in the face's interior -- not on an edge/corner/boundary.

    api-findings.md §6.5: PlaneParams' and CylinderParams' own point can
    land exactly on a face boundary (a rectangular face's corner, or a
    cylinder's axis endpoint at the end-cap), causing SelectByID2 to fail
    or pick the wrong adjacent face.

    - planar: centroid of the face's own local bounding box.
    - cylindrical: the axis is advanced to the axial middle of the face's
      own bounding box (not a fixed 5 mm from the axis origin, which can
      fall past the end cap and off the face), then stepped out radially,
      so it sits mid-height on the cylindrical wall.
    """
    surface = com(face, "GetSurface")
    if kind == "planar":
        fbox = list(com(face, "GetBox", True))
        return [(fbox[0] + fbox[3]) / 2, (fbox[1] + fbox[4]) / 2,
                (fbox[2] + fbox[5]) / 2]
    else:
        ax, ay, az, dx, dy, dz, radius = com(surface, "CylinderParams")[:7]
        fbox = list(com(face, "GetBox", True))
        cx = (fbox[0] + fbox[3]) / 2
        cy = (fbox[1] + fbox[4]) / 2
        cz = (fbox[2] + fbox[5]) / 2
        # axial coordinate of the face's own box centre, applied to the axis
        t = (cx - ax) * dx + (cy - ay) * dy + (cz - az) * dz
        bx, by, bz = ax + dx * t, ay + dy * t, az + dz * t
        # perpendicular-to-axis direction for the radial offset
        px, py, pz = (1.0, 0.0, 0.0) if abs(dx) < 0.9 else (0.0, 1.0, 0.0)
        # project out the axis component, normalize
        dot = px * dx + py * dy + pz * dz
        px, py, pz = px - dot * dx, py - dot * dy, pz - dot * dz
        n = (px ** 2 + py ** 2 + pz ** 2) ** 0.5
        px, py, pz = px / n, py / n, pz / n
        return [bx + radius * px, by + radius * py, bz + radius * pz]


def _select_component_face(asm, component, face_index, append, mark):
    """Selects a component's face by index (see _component_faces) for a
    mate. Returns True/False from SelectByID2.

    api-findings.md 21.3: a retry loop with nudged points was tried and made
    things worse -- a nudge can land on a neighbouring face, SelectByID2
    returns True for the wrong entity, and AddMate5 then fails. Do not add
    one; keep the single, geometrically-derived point.
    """
    faces = _component_faces(component)
    if face_index < 0 or face_index >= len(faces):
        return False
    face, kind = faces[face_index]
    local_pt = _face_local_point(face, kind)
    tfdata = list(com(com(component, "Transform"), "ArrayData"))
    gx, gy, gz = _local_to_global(local_pt, tfdata)
    ext = com(asm, "Extension")
    return com(ext, "SelectByID2", "", "FACE", gx, gy, gz, append, mark,
               win32com.client.VARIANT(pythoncom.VT_DISPATCH, None), 0)


def _open_part_box(sw, filepath):
    """
    Union bounding box (metres) of an already-open part document, or None.

    api-findings.md 21.2: AddComponent5 places the component's BOUNDING-BOX
    CENTRE at the given point, so placing by the part's own origin needs the
    box centre subtracted first.
    """
    app = getattr(sw, "app", None)
    if app is None:
        return None
    try:
        doc = com(app, "GetOpenDocumentByName", filepath)
    except Exception:
        return None
    if doc is None:
        return None
    boxes = []
    try:
        for body in com(doc, "GetBodies2", 0, True) or []:
            box = com(body, "GetBodyBox")
            if box:
                boxes.append(list(box))
    except Exception:
        return None
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            min(b[2] for b in boxes), max(b[3] for b in boxes),
            max(b[4] for b in boxes), max(b[5] for b in boxes))


def _open_part_for_insert(sw, filepath):
    """Preload a native part or assembly, silent and read-only, for insertion."""
    document_type = {".sldprt": SwDocumentTypes.swDocPART,
                     ".sldasm": SwDocumentTypes.swDocASSEMBLY}.get(
                         os.path.splitext(filepath)[1].lower())
    if document_type is None:
        return None
    app = getattr(sw, "app", None)
    if app is None:
        return None
    if hasattr(app, "_oleobj_"):  # typed wrapper rejects VARIANT byref
        import win32com.client
        app = win32com.client.dynamic.Dispatch(app)
    import pythoncom
    import win32com.client as wc
    errors = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = wc.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        # swOpenDocOptions_Silent | swOpenDocOptions_ReadOnly
        return com(app, "OpenDoc6", filepath, int(document_type), 1 | 2, "", errors, warnings)
    except Exception as e:
        logger.warning("could not open %s for insert: %s", filepath, e)
        return None


@tool(
    name="insert_component",
    description=(
        "Insert a Part or sub-assembly into the active assembly at x,y,z (meters, assembly space)."
    ),
    schema={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "Full path to the .SLDPRT/.SLDASM"},
            "x": {"type": "number", "description": "Meters, default 0"},
            "y": {"type": "number", "description": "Meters, default 0"},
            "z": {"type": "number", "description": "Meters, default 0"},
            "place": {
                "type": "string",
                "enum": ["center", "origin"],
                "description": (
                    "'center' (default): bounding-box centre at x,y,z; 'origin': part origin (part must be open)"
                ),
            },
            "configuration": {
                "type": "string",
                "description": (
                    "Configuration to insert, e.g. 'ISO 4762 M10 x 16 - 16N'; default the part's default"
                ),
            },
        },
        "required": ["filepath"]
    },
    operation_class=OperationClass.MUTATE,
)
def insert_component(sw, filepath: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
                     place: str = "center", configuration: str = "") -> dict:
    """Insert a component into the active assembly"""
    asm, err = _require_assembly(sw)
    if err:
        return err

    if not os.path.exists(filepath):
        return sw._result(False, f"File not found: {filepath}",
                          SwErrors.swFileNotFoundError)

    place = (place or "center").lower()
    if place not in ("center", "origin"):
        return sw._result(False, "place must be 'center' or 'origin'.",
                          SwErrors.swInvalidInput)

    if place == "origin":
        box = _open_part_box(sw, filepath)
        if box is None:
            return sw._result(
                False,
                f"place='origin' needs the part already open and non-empty: {filepath}",
                SwErrors.swInvalidInput)
        x -= (box[0] + box[3]) / 2.0
        y -= (box[1] + box[4]) / 2.0
        z -= (box[2] + box[5]) / 2.0

    try:
        comp = com(asm, "AddComponent5", filepath, SW_ADD_COMPONENT_DEFAULT_CONFIG,
                   configuration, bool(configuration), "", x, y, z)
    except Exception as e:
        logger.error(f"AddComponent5 failed: {e}")
        return sw._result(False, f"Could not insert component: {e}",
                          SwErrors.swUnknownError)

    if comp is None:
        # Toolbox browser parts (and some library parts) are rejected by a
        # closed-document AddComponent5 -- it returns None with no error.
        # Opening the part first makes the insert work (verified live).
        opened = _open_part_for_insert(sw, filepath)
        if opened is None:
            detail = f" (configuration '{configuration}')" if configuration else ""
            return sw._result(False, f"Could not insert {filepath}{detail}.",
                              SwErrors.swFeatureError)
        try:
            try:
                comp = com(asm, "AddComponent5", filepath,
                           SW_ADD_COMPONENT_DEFAULT_CONFIG,
                           configuration, bool(configuration), "", x, y, z)
            except Exception as e:
                logger.error(f"AddComponent5 (retry, part open) failed: {e}")
                return sw._result(False, f"Could not insert component: {e}",
                                  SwErrors.swUnknownError)
            if comp is None:
                detail = f" (configuration '{configuration}')" if configuration else ""
                return sw._result(False, f"Could not insert {filepath}{detail}.",
                                  SwErrors.swFeatureError)
        finally:
            sw_app = getattr(sw, "app", None)
            if sw_app is not None:
                try:
                    com(sw_app, "CloseDoc", com(opened, "GetTitle"))
                except Exception:
                    pass

    return sw._result(
        True,
        f"Inserted {com(comp, 'Name2')}.",
        data={"name": com(comp, "Name2"), "path": filepath,
              "configuration": configuration or None}
    )


@tool(name="set_component_translation", description=(
    "Set one floating top-level component's absolute translation in millimetres, "
    "preserving rotation and scale. Requires expected current translation; reads "
    "native transform back. Does not save or repair mates."),
    schema={"type": "object", "properties": {
        "component_name": {"type": "string"},
        "translation_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "expected_translation_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}},
        "required": ["component_name", "translation_mm", "expected_translation_mm"]},
    operation_class=OperationClass.MUTATE)
def set_component_translation(sw, component_name, translation_mm, expected_translation_mm):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        for values in (translation_mm, expected_translation_mm):
            if (not isinstance(values, (list, tuple)) or len(values) != 3 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)):
                raise ValueError("Translations must contain three finite numeric millimetre values.")
        if not isinstance(component_name, str) or not component_name or '/' in component_name:
            raise ValueError("Exact top-level component Name2 required.")
        component = _find_component(asm, component_name)
        if component is None:
            raise ValueError("Component not found.")
        if com(component, "Name2") != component_name:
            raise ValueError("Exact top-level component required; nested suffix matching is not allowed.")
        if com(component, "IsFixed"):
            raise ValueError("Fixed component must not be moved by this tool.")
        before = list(com(com(component, "Transform2"), "ArrayData"))
        if len(before) != 16 or not all(math.isfinite(v) for v in before) or before[12] <= 0:
            raise ValueError("Invalid native component transform.")
        if any(abs(before[9+i] * 1000 - expected_translation_mm[i]) > .001 for i in range(3)):
            raise ValueError("Component translation changed; refresh expected position.")
        desired = list(before)
        desired[9:12] = [v / 1000 for v in translation_mm]
        variant = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, desired)
        transform = com(com(sw.app, "GetMathUtility"), "CreateTransform", variant)
        set_com(transform, "ArrayData", variant)
        prepared = list(com(transform, "ArrayData"))
        if len(prepared) != 16 or any(abs(a-b) > 1e-10 for a,b in zip(prepared, desired)):
            raise ValueError("Math transform did not retain requested placement.")
        changed = True
        set_com(component, "Transform2", transform)
        actual = list(com(com(component, "Transform2"), "ArrayData"))
        if len(actual) != 16 or any(abs(a-b) > 1e-8 for a,b in zip(actual, desired)):
            raise ValueError("Native component placement readback differs; inspect constraints.")
        return sw._result(True, "Component translation verified; no save performed.", data={
            "component_name": component_name, "before_transform": before, "transform": actual,
            "translation_mm": [v * 1000 for v in actual[9:12]], "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})


def _euler_to_matrix(rotation_deg):
    """ArrayData rotation (row-vector convention, as in _local_to_global) of Rz*Ry*Rx.

    X is applied first; positive angles are right-handed. Rows 0-2 / 3-5 / 6-8 are
    the images of the local X / Y / Z axes.
    """
    rx, ry, rz = (math.radians(v) for v in rotation_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [cz * cy, sz * cy, -sy,
            cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx,
            cz * sy * cx + sz * sx, sz * sy * cx - cz * sx, cy * cx]


def _matrix_to_euler(m):
    """Inverse of _euler_to_matrix: [rx, ry, rz] in degrees (ry within -90..90)."""
    sy = max(-1.0, min(1.0, -m[2]))
    ry = math.asin(sy)
    if abs(sy) < 1 - 1e-9:
        rx, rz = math.atan2(m[5], m[8]), math.atan2(m[1], m[0])
    else:  # gimbal lock: only rx - rz (or rx + rz) is defined; put it all in rx
        rx, rz = math.atan2(-m[7], m[4]), 0.0
    return [math.degrees(rx), math.degrees(ry), math.degrees(rz)]


def _check_angles(values, label):
    if (not isinstance(values, (list, tuple)) or len(values) != 3 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)):
        raise ValueError(f"{label} must contain three finite degree values.")


@tool(name="set_component_rotation", description=(
    "Set one floating top-level component's absolute rotation as [rx, ry, rz] degrees (Rz*Ry*Rx, "
    "right-handed, about the component origin), keeping translation and scale. Requires the "
    "expected current rotation (rotation_deg from get_component); reads native transform back. "
    "Does not save or repair mates."),
    schema={"type": "object", "properties": {
        "component_name": {"type": "string"},
        "rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "expected_rotation_deg": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}},
        "required": ["component_name", "rotation_deg", "expected_rotation_deg"]},
    operation_class=OperationClass.MUTATE)
def set_component_rotation(sw, component_name, rotation_deg, expected_rotation_deg):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        _check_angles(rotation_deg, "rotation_deg")
        _check_angles(expected_rotation_deg, "expected_rotation_deg")
        component = _exact_top_level(asm, component_name)
        if com(component, "IsFixed"):
            raise ValueError("Fixed component must not be moved by this tool.")
        before = list(com(com(component, "Transform2"), "ArrayData"))
        if len(before) != 16 or not all(math.isfinite(v) for v in before) or before[12] <= 0:
            raise ValueError("Invalid native component transform.")
        if any(abs(a - b) > 1e-4 for a, b in zip(before[:9], _euler_to_matrix(expected_rotation_deg))):
            raise ValueError("Component rotation changed; refresh expected rotation.")
        desired = _euler_to_matrix(rotation_deg) + before[9:]
        variant = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, desired)
        transform = com(com(sw.app, "GetMathUtility"), "CreateTransform", variant)
        set_com(transform, "ArrayData", variant)
        prepared = list(com(transform, "ArrayData"))
        if len(prepared) != 16 or any(abs(a - b) > 1e-10 for a, b in zip(prepared, desired)):
            raise ValueError("Math transform did not retain requested placement.")
        changed = True
        set_com(component, "Transform2", transform)
        actual = list(com(com(component, "Transform2"), "ArrayData"))
        if len(actual) != 16 or any(abs(a - b) > 1e-8 for a, b in zip(actual, desired)):
            raise ValueError("Native component placement readback differs; inspect constraints.")
        return sw._result(True, "Component rotation verified; no save performed.", data={
            "component_name": component_name, "before_transform": before, "transform": actual,
            "rotation_deg": list(rotation_deg), "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})


@tool(name="set_component_fixed", description="Fix or float an exact top-level component and verify native state. No save performed.",
      schema={"type":"object","properties":{"component_name":{"type":"string","minLength":1},"fixed":{"type":"boolean"}},
              "required":["component_name","fixed"]}, operation_class=OperationClass.MUTATE)
def set_component_fixed(sw, component_name, fixed):
    asm,error=_require_assembly(sw)
    if error:return error
    changed=False
    try:
        if type(fixed) is not bool or not isinstance(component_name,str) or not component_name or '/' in component_name:
            raise ValueError("Exact top-level component Name2 and boolean fixed state required.")
        component=_find_component(asm,component_name)
        if component is None or com(component,"Name2")!=component_name:
            raise ValueError("Exact top-level component not found.")
        before=bool(com(component,"IsFixed"))
        if before!=fixed:
            com(asm,"ClearSelection2",True)
            data=com(com(asm,"SelectionManager"),"CreateSelectData")
            if not com(component,"Select4",False,data,False):raise ValueError("Component selection failed.")
            changed=True
            com(asm,"FixComponent" if fixed else "UnfixComponent")
        actual=bool(com(component,"IsFixed"))
        if actual!=fixed:raise ValueError("Native fixed state did not change; inspect constraints.")
        return sw._result(True,"Component fixed state verified; no save performed.",data={
            "component_name":component_name,"before_fixed":before,"fixed":actual,"saved":False})
    except Exception as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput,data={"document_may_be_modified":changed,"saved":False})
    finally:
        com(asm,"ClearSelection2",True)


SW_DELETE_ABSORBED = 2  # swDelete_Absorbed: also delete features absorbed by the deleted object
SW_COMPONENT_SUPPRESSED = 0
SW_COMPONENT_FULLY_RESOLVED = 2
SW_COMPONENT_RESOLVED = 3


def _exact_top_level(asm, component_name):
    if not isinstance(component_name, str) or not component_name or '/' in component_name:
        raise ValueError("Exact top-level component Name2 required.")
    component = _find_component(asm, component_name)
    if component is None or com(component, "Name2") != component_name:
        raise ValueError("Exact top-level component not found.")
    return component


@tool(name="remove_component", description=(
    "Delete one exact top-level component from the active assembly together with its mates. "
    "Requires its current file path to guard against stale names. Verifies the component is "
    "gone and the others remain. Does not save."),
    schema={"type": "object", "properties": {
        "component_name": {"type": "string", "minLength": 1},
        "expected_path": {"type": "string", "minLength": 1}},
        "required": ["component_name", "expected_path"]},
    operation_class=OperationClass.MUTATE)
def remove_component(sw, component_name, expected_path):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        component = _exact_top_level(asm, component_name)
        actual = str(com(component, "GetPathName") or "")
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(expected_path)):
            raise ValueError("Component reference changed; refresh before removal.")
        before = sorted(com(c, "Name2") for c in com(asm, "GetComponents", True) or [])
        com(asm, "ClearSelection2", True)
        data = com(com(asm, "SelectionManager"), "CreateSelectData")
        if not com(component, "Select4", False, data, False):
            raise ValueError("Component selection failed.")
        changed = True
        com(com(asm, "Extension"), "DeleteSelection2", SW_DELETE_ABSORBED)
        after = sorted(com(c, "Name2") for c in com(asm, "GetComponents", True) or [])
        if component_name in after or after != [n for n in before if n != component_name]:
            raise ValueError("Native delete did not remove exactly the requested component; inspect the assembly.")
        return sw._result(True, "Component removed and verified; no save performed.", data={
            "component_name": component_name, "path": actual,
            "remaining_components": len(after), "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})
    finally:
        try:
            com(asm, "ClearSelection2", True)
        except Exception:
            pass


SW_EXT_REF_UPDATE_COMP_NAMES = 18  # swUserPreferenceToggle_e.swExtRefUpdateCompNames


@tool(name="rename_component", description=(
    "Rename one exact top-level component instance (new_name is the full instance name, e.g. "
    "'stopnica-3'). Requires its current file path. Mates are kept. Verifies the new name. "
    "Does not save."),
    schema={"type": "object", "properties": {
        "component_name": {"type": "string", "minLength": 1},
        "new_name": {"type": "string", "minLength": 1},
        "expected_path": {"type": "string", "minLength": 1}},
        "required": ["component_name", "new_name", "expected_path"]},
    operation_class=OperationClass.MUTATE)
def rename_component(sw, component_name, new_name, expected_path):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        if not isinstance(new_name, str) or not new_name.strip() or any(c in new_name for c in '/@<>'):
            raise ValueError("new_name must be a non-empty instance name without '/', '@', '<' or '>'.")
        component = _exact_top_level(asm, component_name)
        actual = str(com(component, "GetPathName") or "")
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(expected_path)):
            raise ValueError("Component reference changed; refresh before renaming.")
        if new_name == component_name:
            raise ValueError("new_name equals the current name.")
        if any(com(c, "Name2") == new_name for c in com(asm, "GetComponents", True) or []):
            raise ValueError(f"A component named {new_name} already exists.")
        # Name2 cannot be set while this preference is on; it is the user's setting, so only report it.
        if com(sw.app, "GetUserPreferenceToggle", SW_EXT_REF_UPDATE_COMP_NAMES):
            raise ValueError("Renaming is blocked by a SolidWorks option. Switch off System Options > "
                             "External References > 'Update component names when documents are replaced', "
                             "then retry.")
        com(asm, "ClearSelection2", True)
        data = com(com(asm, "SelectionManager"), "CreateSelectData")
        if not com(component, "Select4", False, data, False):
            raise ValueError("Component selection failed.")
        changed = True
        set_com(component, "Name2", new_name)
        now = com(component, "Name2")
        if now != new_name:
            raise ValueError(f"Native rename did not apply (name is {now}); inspect the assembly.")
        return sw._result(True, "Component renamed and verified; no save performed.", data={
            "before": component_name, "after": now, "path": actual, "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})
    finally:
        try:
            com(asm, "ClearSelection2", True)
        except Exception:
            pass


@tool(name="delete_mate", description=(
    "Delete one mate of the active assembly by exact feature name. Requires its current type "
    "(from list_mates) to guard against stale names. Verifies the mate is gone. Does not save."),
    schema={"type": "object", "properties": {
        "mate_name": {"type": "string", "minLength": 1},
        "expected_type": {"type": "string", "minLength": 1}},
        "required": ["mate_name", "expected_type"]},
    operation_class=OperationClass.MUTATE)
def delete_mate(sw, mate_name, expected_type):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        # Mates are features: select by name with type "MATE", then DeleteSelection2(0).
        feature = com(asm, "FeatureByName", mate_name)
        if feature is None:
            raise ValueError(f"Mate not found: {mate_name}")
        kind = str(com(feature, "GetTypeName2"))
        if kind != expected_type or not kind.startswith("Mate") or kind in ("MateGroup",)                 or kind.startswith("MateReference"):
            raise ValueError(f"Feature {mate_name} is {kind}, not the expected mate type; refresh with list_mates.")
        com(asm, "ClearSelection2", True)
        ext = com(asm, "Extension")
        if not com(ext, "SelectByID2", mate_name, "MATE", 0.0, 0.0, 0.0, False, 0,
                   win32com.client.VARIANT(pythoncom.VT_DISPATCH, None), 0):
            raise ValueError("Mate selection failed.")
        changed = True
        com(ext, "DeleteSelection2", 0)
        if com(asm, "FeatureByName", mate_name) is not None:
            raise ValueError("Native delete did not remove the mate; inspect the assembly.")
        return sw._result(True, "Mate deleted and verified; no save performed.", data={
            "mate_name": mate_name, "type": kind, "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})
    finally:
        try:
            com(asm, "ClearSelection2", True)
        except Exception:
            pass


@tool(name="suppress_component", description=(
    "Suppress or unsuppress (fully resolve) one exact top-level component and verify the native "
    "state. Suppressing keeps the component in the tree so it can be restored. Does not save."),
    schema={"type": "object", "properties": {
        "component_name": {"type": "string", "minLength": 1},
        "suppressed": {"type": "boolean"}},
        "required": ["component_name", "suppressed"]},
    operation_class=OperationClass.MUTATE)
def suppress_component(sw, component_name, suppressed):
    asm, error = _require_assembly(sw)
    if error:
        return error
    changed = False
    try:
        if type(suppressed) is not bool:
            raise ValueError("Boolean suppressed required.")
        component = _exact_top_level(asm, component_name)
        before = com(component, "GetSuppression2")
        wanted = SW_COMPONENT_SUPPRESSED if suppressed else SW_COMPONENT_FULLY_RESOLVED
        changed = True
        com(component, "SetSuppression2", wanted)
        actual = com(component, "GetSuppression2")
        ok = actual == 0 if suppressed else actual in (SW_COMPONENT_FULLY_RESOLVED, SW_COMPONENT_RESOLVED)
        if not ok:
            raise ValueError(f"Native suppression state is {actual}; inspect constraints.")
        return sw._result(True, "Component suppression verified; no save performed.", data={
            "component_name": component_name, "before_state": before, "state": actual,
            "suppressed": suppressed, "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})


def _norm_path(path):
    return os.path.normcase(os.path.abspath(path)) if path else None


def _check_expected(expected, tolerance_mm):
    if isinstance(tolerance_mm, bool) or not isinstance(tolerance_mm, (int, float)) \
            or not math.isfinite(tolerance_mm) or tolerance_mm < 0:
        raise ValueError("tolerance_mm must be a finite number >= 0.")
    if not isinstance(expected, (list, tuple)):
        raise ValueError("expected must be a list of component descriptions.")
    seen = set()
    for item in expected:
        unknown = set(item) - {"name", "path", "translation_mm", "suppressed", "fixed"} if isinstance(item, dict) else ()
        if unknown:
            raise ValueError(f"Unknown expected keys: {sorted(unknown)}.")
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or "/" in name:
            raise ValueError("Each expected item needs a top-level component name without '/'.")
        if name in seen:
            raise ValueError(f"Duplicate expected component name: {name}.")
        seen.add(name)
        if item.get("path") is not None and not isinstance(item["path"], str):
            raise ValueError(f"{name}: path must be a string.")
        t = item.get("translation_mm")
        if t is not None and (not isinstance(t, (list, tuple)) or len(t) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in t)):
            raise ValueError(f"{name}: translation_mm must be three finite numbers.")
        for key in ("suppressed", "fixed"):
            if item.get(key) is not None and type(item[key]) is not bool:
                raise ValueError(f"{name}: {key} must be a boolean.")


def _diff(actual, expected, tolerance_mm, ignore_extra):
    """Pure comparison of listed top-level components with an expected list."""
    _check_expected(expected, tolerance_mm)
    by_name = {c["name"]: c for c in actual}
    missing, moved, changed, matching = [], [], [], []
    for item in expected:
        name = item["name"]
        c = by_name.get(name)
        if c is None:
            missing.append(name)
            continue
        problems = []
        if item.get("path") is not None and _norm_path(item["path"]) != _norm_path(c.get("path")):
            problems.append({"name": name, "field": "path", "expected": item["path"], "actual": c.get("path")})
        for key, actual_key in (("suppressed", "suppressed"), ("fixed", "is_fixed")):
            if item.get(key) is not None and c.get(actual_key) is not item[key]:
                problems.append({"name": name, "field": key, "expected": item[key], "actual": c.get(actual_key)})
        move = None
        if item.get("translation_mm") is not None:
            tr = c.get("transform")
            if not tr or len(tr) < 12:
                problems.append({"name": name, "field": "translation", "expected": item["translation_mm"],
                                 "actual": None})
            else:
                actual_mm = [v * 1000 for v in tr[9:12]]
                delta = math.dist(actual_mm, item["translation_mm"])
                if delta > tolerance_mm:
                    move = {"name": name, "expected_mm": list(item["translation_mm"]),
                            "actual_mm": actual_mm, "delta_mm": delta}
        changed.extend(problems)
        if move:
            moved.append(move)
        if not problems and not move:
            matching.append(name)
    wanted = {item["name"] for item in expected}
    extra = [] if ignore_extra else [{"name": c["name"], "path": c.get("path")}
                                     for c in actual if c["name"] not in wanted]
    return {"missing": missing, "extra": extra, "moved": moved, "state_changed": changed,
            "matching": matching, "complete": not (missing or extra or moved or changed)}


@tool(name="assembly_diff", description=(
    "Compare the active assembly's top-level components with an expected list and report "
    "missing, extra, moved and state-changed ones. Read-only; use it to find the minimal edit."),
    schema={"type": "object", "properties": {
        "expected": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "path": {"type": "string"},
            "translation_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
            "suppressed": {"type": "boolean"}, "fixed": {"type": "boolean"}}, "required": ["name"]}},
        "tolerance_mm": {"type": "number", "minimum": 0, "default": 0.1},
        "ignore_extra": {"type": "boolean", "default": False}}, "required": ["expected"]},
    operation_class=OperationClass.READ)
def assembly_diff(sw, expected, tolerance_mm=0.1, ignore_extra=False):
    try:
        _check_expected(expected, tolerance_mm)
        if type(ignore_extra) is not bool:
            raise ValueError("ignore_extra must be a boolean.")
    except ValueError as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    listing = list_components(sw, depth=1, mode="detailed")
    if not listing.get("success"):
        return listing
    data = listing["data"]
    result = _diff(data["components"], expected, tolerance_mm, ignore_extra)
    coverage = data.get("coverage") or {}
    if not coverage.get("complete", True):
        result["complete"] = False
        result["unresolved"] = coverage.get("unresolved", [])
    return sw._result(True, "Assembly is as expected." if result["complete"]
                      else "Assembly differs from expected (or could not be read completely).", data=result)


@tool(
    name="list_components",
    description=(
        "List the components of the active assembly. mode 'fast' reads only "
        "name and path and never queries leaf parts, which keeps large "
        "assemblies quick; mode 'detailed' also reads transforms, suppression "
        "state, configuration and fixed/virtual flags."
    ),
    schema={"type": "object", "properties": {
        "depth": {"type": "integer", "minimum": 1, "maximum": 32, "default": 32},
        "mode": {
            "type": "string", "enum": ["fast", "detailed"], "default": "detailed",
            "description": ("fast: name + path only, leaves are not queried. "
                            "detailed: every member, needed for transforms, "
                            "suppression, configurations.")},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def list_components(sw, depth: int = 32, mode: str = "detailed") -> dict:
    """
    List all component instances of the active assembly recursively.

    ``fast`` mode exists because every COM member access on an instance inside
    a sub-assembly costs about 0.08 s in SolidWorks (a transform ~0.35 s), so
    the cost is the number of calls, not the data. A part instance is a leaf:
    fast mode recognises it by the ``.SLDPRT`` suffix of its referenced
    document and performs no further calls on it at all.
    """
    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 32:
        return sw._result(False, "depth must be an integer from 1 to 32.", SwErrors.swInvalidInput)
    if mode not in ("fast", "detailed"):
        return sw._result(False, "mode must be 'fast' or 'detailed'.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    asm, err = _require_assembly(sw)
    if err:
        return err

    comps = []
    unresolved = []
    truncated = False
    fast = mode == "fast"

    def optional_component_value(comp, member, instance_path):
        try:
            return com(comp, member)
        except Exception as error:
            unresolved.append(f"{instance_path}: {member} unavailable ({error})")
            return None

    def transform_data(comp, instance_path):
        transform = optional_component_value(comp, "Transform2", instance_path)
        if transform is None:
            return None
        try:
            values = com(transform, "ArrayData")
            return list(values) if values is not None else None
        except Exception as error:
            unresolved.append(f"{instance_path}: Transform2.ArrayData unavailable ({error})")
            return None

    suppression_names = {
        0: "suppressed",
        1: "lightweight",
        2: "resolved",
        3: "fully_lightweight",
        4: "internal_id_mismatch",
    }

    def children_of(comp, instance_path):
        try:
            return com(comp, "GetChildren") or []
        except Exception as error:
            unresolved.append(f"{instance_path}: children unavailable ({error})")
            return None

    def visit(comp, parent_path=None, level=1):
        nonlocal truncated
        name = com(comp, "Name2")
        instance_path = f"{parent_path}/{name}" if parent_path else name
        path = optional_component_value(comp, "GetPathName", instance_path)
        # An unresolved path may hide a sub-assembly, so only a path that names
        # a part is a leaf; unknown paths are still descended into.
        if not path:
            is_subassembly = None
        else:
            is_subassembly = str(path).casefold().endswith(".sldasm")

        if fast:
            comps.append({
                "name": name,
                "instance_path": instance_path,
                "parent_path": parent_path,
                "path": path or None,
                "is_subassembly": is_subassembly,
            })
        else:
            suppression = optional_component_value(comp, "GetSuppression", instance_path)
            virtual = optional_component_value(comp, "IsVirtual", instance_path)
            comps.append({
                "name": name,
                "instance_path": instance_path,
                "parent_path": parent_path,
                "path": path or None,
                "is_subassembly": is_subassembly,
                "configuration": optional_component_value(
                    comp, "ReferencedConfiguration", instance_path),
                "transform": transform_data(comp, instance_path),
                "is_fixed": bool(optional_component_value(comp, "IsFixed", instance_path)),
                "suppressed": suppression == 0 if suppression is not None else None,
                "suppression_state": suppression_names.get(suppression, "unknown"),
                "lightweight": suppression in {1, 3} if suppression is not None else None,
                "virtual": bool(virtual) if virtual is not None else None,
            })

        report_progress(len(comps), None, instance_path)

        if fast and is_subassembly is False:
            return
        if level >= depth:
            children = children_of(comp, instance_path)
            if children:
                truncated = True
            return
        for child in children_of(comp, instance_path) or []:
            visit(child, instance_path, level + 1)

    for component in com(asm, "GetComponents", True) or []:
        visit(component)

    return sw._result(
        True, f"Found {len(comps)} component instances ({mode}).",
        data={
            "mode": mode,
            "components": comps,
            "coverage": {
                "complete": not unresolved and not truncated,
                "visited_count": len(comps),
                "unresolved": unresolved,
                "truncated": truncated,
                "next_cursor": None,
            },
        })


@tool(
    name="list_component_faces",
    description=(
        "List the planar and cylindrical faces of one component in the "
        "active assembly, with index, type and size. Use the index with "
        "mate_coincident/mate_concentric/mate_distance's face_index1/"
        "face_index2. Indexes are only valid for the current model state "
        "-- re-run after any mate is added, since components move."
    ),
    schema={
        "type": "object",
        "properties": {
            "component_name": {"type": "string", "description": "Name2 of the component, e.g. \"Block1-1\""},
        },
        "required": ["component_name"]
    },
    operation_class=OperationClass.READ,
)
def list_component_faces(sw, component_name: str) -> dict:
    """List planar/cylindrical faces of one assembly component"""
    asm, err = _require_assembly(sw)
    if err:
        return err

    comp = _find_component(asm, component_name)
    if comp is None:
        return sw._result(False, f"Component not found: {component_name}",
                          SwErrors.swInvalidInput)

    faces = []
    unresolved = []
    for index, (face, kind) in enumerate(_component_faces(comp)):
        surface = com(face, "GetSurface")
        entry = {"index": index, "kind": kind}
        if kind == "planar":
            entry["area_mm2"] = round(com(face, "GetArea") * 1_000_000, 2)
            try:
                tf = list(com(com(comp, "Transform2"), "ArrayData"))
                plane = list(com(surface, "PlaneParams"))
                normal = list(com(face, "Normal"))
                if len(tf) != 16 or len(plane) != 6 or len(normal) != 3:
                    raise ValueError("Unexpected planar face or transform array length.")
                if not all(math.isfinite(v) for v in tf + plane + normal) or tf[12] <= 0:
                    raise ValueError("Non-finite geometry or unsupported component scale.")
                point = _local_to_global(plane[3:6], tf)
                center = _local_to_global(_face_local_point(face, kind), tf)
                rotation = list(tf)
                rotation[9:13] = [0, 0, 0, 1]
                direction = _local_to_global(normal, rotation)
                length = math.sqrt(sum(v*v for v in direction))
                if length <= 1e-12:
                    raise ValueError("Planar face has no usable oriented normal.")
                entry.update(
                    plane_point_assembly_mm=[v*1000 for v in point],
                    box_center_assembly_mm=[v*1000 for v in center],
                    normal_assembly=[v/length for v in direction],
                    geometry_note="Oriented face normal; box centre is not an area centroid or guaranteed interior point.",
                )
            except Exception as exc:
                unresolved.append(f"face[{index}]: assembly geometry unavailable: {exc}")
        else:
            radius = com(surface, "CylinderParams")[6]
            entry["radius_mm"] = round(radius * 1000, 3)
        faces.append(entry)

    return sw._result(True, f"Found {len(faces)} faces on {component_name}.",
                      data={"faces": faces, "complete": not unresolved,
                            "unresolved": unresolved, "coordinate_frame": "active assembly"})


def _add_mate(sw, asm, component1, face_index1, component2, face_index2,
              mate_type, distance_m=0.0, flip=False):
    comp1 = _find_component(asm, component1)
    if comp1 is None:
        return sw._result(False, f"Component not found: {component1}",
                          SwErrors.swInvalidInput)
    comp2 = _find_component(asm, component2)
    if comp2 is None:
        return sw._result(False, f"Component not found: {component2}",
                          SwErrors.swInvalidInput)

    com(asm, "ClearSelection2", True)
    ok1 = _select_component_face(asm, comp1, face_index1, False, 1)
    if not ok1:
        return sw._result(
            False, f"Could not select face {face_index1} on {component1}.",
            SwErrors.swSelectionError)
    ok2 = _select_component_face(asm, comp2, face_index2, True, 1)
    if not ok2:
        return sw._result(
            False, f"Could not select face {face_index2} on {component2}.",
            SwErrors.swSelectionError)

    err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        mate = com(asm, "AddMate5", int(mate_type), 0, flip, distance_m, distance_m,
                   distance_m, 0.0, 0.0, 0.0, 0.0, 0.0, False, False, 0, err)
    except Exception as e:
        logger.error(f"AddMate5 failed: {e}")
        return sw._result(False, f"Could not create mate: {e}",
                          SwErrors.swUnknownError)
    finally:
        com(asm, "ClearSelection2", True)

    if mate is None:
        return sw._result(
            False,
            "Mate could not be created (selection may not be valid for "
            "this mate type). If the two faces are exactly coincident (same "
            "radius or same plane on two components), SelectByID2 cannot "
            "resolve the probe point; pick a different face of the pair, "
            "e.g. a free bore instead of the seat it duplicates "
            "(api-findings.md 21.3).",
            SwErrors.swFeatureError)

    return sw._result(True, f"Mate created between {component1} and {component2}.",
                      data={"mate_type": com(mate, "GetTypeName2")})


@tool(
    name="mate_coincident",
    description=(
        "Add a Coincident mate between a face of two components in the "
        "active assembly, selected by list_component_faces indexes."
    ),
    schema={
        "type": "object",
        "properties": {
            "component1": {"type": "string", "description": "Name2 of the first component"},
            "face_index1": {"type": "integer", "description": "Face index from list_component_faces(component1)"},
            "component2": {"type": "string", "description": "Name2 of the second component"},
            "face_index2": {"type": "integer", "description": "Face index from list_component_faces(component2)"},
            "flip": {"type": "boolean", "description": "Flip mate alignment. Default false."},
        },
        "required": ["component1", "face_index1", "component2", "face_index2"]
    },
    operation_class=OperationClass.MUTATE,
)
def mate_coincident(sw, component1: str, face_index1: int, component2: str,
                     face_index2: int, flip: bool = False) -> dict:
    """Add a Coincident mate between two component faces"""
    asm, err = _require_assembly(sw)
    if err:
        return err
    return _add_mate(sw, asm, component1, face_index1, component2, face_index2,
                     SwMateTypes.swMateCOINCIDENT, flip=flip)


@tool(
    name="mate_concentric",
    description=(
        "Add a Concentric mate between a cylindrical face of two "
        "components in the active assembly, selected by "
        "list_component_faces indexes."
    ),
    schema={
        "type": "object",
        "properties": {
            "component1": {"type": "string", "description": "Name2 of the first component"},
            "face_index1": {"type": "integer", "description": "Cylindrical face index from list_component_faces(component1)"},
            "component2": {"type": "string", "description": "Name2 of the second component"},
            "face_index2": {"type": "integer", "description": "Cylindrical face index from list_component_faces(component2)"},
            "flip": {"type": "boolean", "description": "Flip mate alignment. Default false."},
        },
        "required": ["component1", "face_index1", "component2", "face_index2"]
    },
    operation_class=OperationClass.MUTATE,
)
def mate_concentric(sw, component1: str, face_index1: int, component2: str,
                     face_index2: int, flip: bool = False) -> dict:
    """Add a Concentric mate between two component cylindrical faces"""
    asm, err = _require_assembly(sw)
    if err:
        return err
    return _add_mate(sw, asm, component1, face_index1, component2, face_index2,
                     SwMateTypes.swMateCONCENTRIC, flip=flip)


@tool(
    name="mate_distance",
    description=(
        "Add a Distance mate between a face of two components in the "
        "active assembly, selected by list_component_faces indexes."
    ),
    schema={
        "type": "object",
        "properties": {
            "component1": {"type": "string", "description": "Name2 of the first component"},
            "face_index1": {"type": "integer", "description": "Face index from list_component_faces(component1)"},
            "component2": {"type": "string", "description": "Name2 of the second component"},
            "face_index2": {"type": "integer", "description": "Face index from list_component_faces(component2)"},
            "distance_mm": {"type": "number", "description": "Distance in mm"},
            "flip": {"type": "boolean", "description": "Flip mate direction. Default false."},
        },
        "required": ["component1", "face_index1", "component2", "face_index2", "distance_mm"]
    },
    operation_class=OperationClass.MUTATE,
)
def mate_distance(sw, component1: str, face_index1: int, component2: str,
                   face_index2: int, distance_mm: float, flip: bool = False) -> dict:
    """Add a Distance mate between two component faces"""
    asm, err = _require_assembly(sw)
    if err:
        return err
    return _add_mate(sw, asm, component1, face_index1, component2, face_index2,
                     SwMateTypes.swMateDISTANCE, distance_m=distance_mm / 1000.0,
                     flip=flip)


_MATE_KINDS = {
    "coincident": SwMateTypes.swMateCOINCIDENT, "concentric": SwMateTypes.swMateCONCENTRIC,
    "parallel": SwMateTypes.swMatePARALLEL, "perpendicular": SwMateTypes.swMatePERPENDICULAR,
    "tangent": SwMateTypes.swMateTANGENT, "distance": SwMateTypes.swMateDISTANCE,
    "angle": SwMateTypes.swMateANGLE, "lock": SwMateTypes.swMateLOCK,
}
_REF_SELECTORS = {"plane": "PLANE", "axis": "AXIS"}


def _check_mate_args(mate_type, ref1, ref2, distance_mm, angle_deg):
    """Validates add_mate arguments; returns (SwMateTypes, distance_m, angle_rad)."""
    if mate_type not in _MATE_KINDS:
        raise ValueError(f"mate_type must be one of {sorted(_MATE_KINDS)}.")
    for ref in (ref1, ref2):
        if not isinstance(ref, dict) or not isinstance(ref.get("component"), str) or not ref["component"]:
            raise ValueError("Each reference needs a component name.")
        chosen = [k for k in ("face_index", "plane", "axis") if ref.get(k) is not None]
        if len(chosen) != 1:
            raise ValueError("Each reference needs exactly one of face_index, plane, axis.")
        if chosen[0] == "face_index":
            index = ref["face_index"]
            if type(index) is not int or index < 0:
                raise ValueError("face_index must be a non-negative integer.")
        elif not isinstance(ref[chosen[0]], str) or not ref[chosen[0]].strip():
            raise ValueError(f"{chosen[0]} must be a non-empty name.")
    for given, wanted, label in ((distance_mm, mate_type == "distance", "distance_mm"),
                                 (angle_deg, mate_type == "angle", "angle_deg")):
        if wanted != (given is not None):
            raise ValueError(f"{label} is required for, and only valid with, "
                             f"mate_type '{'distance' if label == 'distance_mm' else 'angle'}'.")
        if given is not None and (isinstance(given, bool) or not isinstance(given, (int, float))
                                  or not math.isfinite(given)):
            raise ValueError(f"{label} must be a finite number.")
    return (_MATE_KINDS[mate_type],
            distance_mm / 1000.0 if distance_mm is not None else 0.0,
            math.radians(angle_deg) if angle_deg is not None else 0.0)


def _assembly_context_name(asm):
    """Assembly name as used in SelectByID2 paths ("Plane@component@assembly")."""
    title = str(com(asm, "GetTitle") or "")
    return title[:-7] if title.lower().endswith(".sldasm") else title


def _select_mate_ref(asm, component, ref, append, mark=1):
    if ref.get("face_index") is not None:
        return _select_component_face(asm, component, ref["face_index"], append, mark)
    key = "plane" if ref.get("plane") is not None else "axis"
    name = f"{ref[key]}@{com(component, 'Name2')}@{_assembly_context_name(asm)}"
    return com(com(asm, "Extension"), "SelectByID2", name, _REF_SELECTORS[key], 0.0, 0.0, 0.0,
               append, mark, win32com.client.VARIANT(pythoncom.VT_DISPATCH, None), 0)


@tool(
    name="add_mate",
    description=(
        "Add a mate of any common type (coincident, concentric, parallel, perpendicular, tangent, "
        "distance, angle, lock) between two components. Each reference is a face_index from "
        "list_component_faces, or the component's own plane/axis by name (stable, e.g. "
        "'Front Plane', 'Axis1'). Verifies the created mate. Does not save."),
    schema={"type": "object", "properties": {
        "mate_type": {"type": "string", "enum": sorted(_MATE_KINDS)},
        "ref1": {"type": "object", "properties": {
            "component": {"type": "string"}, "face_index": {"type": "integer", "minimum": 0},
            "plane": {"type": "string"}, "axis": {"type": "string"}}, "required": ["component"]},
        "ref2": {"type": "object", "properties": {
            "component": {"type": "string"}, "face_index": {"type": "integer", "minimum": 0},
            "plane": {"type": "string"}, "axis": {"type": "string"}}, "required": ["component"]},
        "distance_mm": {"type": "number"}, "angle_deg": {"type": "number"},
        "flip": {"type": "boolean"}},
        "required": ["mate_type", "ref1", "ref2"]},
    operation_class=OperationClass.MUTATE,
)
def add_mate(sw, mate_type, ref1, ref2, distance_mm=None, angle_deg=None, flip=False):
    asm, err = _require_assembly(sw)
    if err:
        return err
    changed = False
    try:
        kind, distance_m, angle_rad = _check_mate_args(mate_type, ref1, ref2, distance_mm, angle_deg)
        if type(flip) is not bool:
            raise ValueError("flip must be a boolean.")
        components = []
        for ref in (ref1, ref2):
            components.append(_exact_top_level(asm, ref["component"]))
        com(asm, "ClearSelection2", True)
        for index, (component, ref) in enumerate(zip(components, (ref1, ref2))):
            if not _select_mate_ref(asm, component, ref, index == 1):
                raise ValueError(f"Could not select the reference on {ref['component']} "
                                 f"({[k for k in ('face_index', 'plane', 'axis') if ref.get(k) is not None][0]}).")
        status = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        changed = True
        mate = com(asm, "AddMate5", int(kind), 0, flip, distance_m, distance_m, distance_m,
                   0.0, 0.0, angle_rad, angle_rad, angle_rad, False, False, 0, status)
        if mate is None:
            raise ValueError("Mate could not be created (the selection may not suit this mate type). "
                             "If two faces are exactly coincident SelectByID2 cannot resolve the probe "
                             "point; use a plane/axis reference or a different face (api-findings 21.3).")
        name = com(mate, "Name")
        if com(asm, "FeatureByName", name) is None:
            raise ValueError("Mate was reported created but cannot be found by name; inspect the assembly.")
        code = getattr(status, "value", status)
        data = {"mate_name": name, "mate_feature_type": com(mate, "GetTypeName2"),
                "mate_type": mate_type, "add_mate_status": code, "saved": False}
        if code not in (0, 1):  # 1 = swAddMateError_NoError; the mate exists, so report instead of failing
            data["warning"] = f"AddMate5 reported status {code}; check list_mates solver_status."
        return sw._result(True, f"Mate {name} created; no save performed.", data=data)
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})
    finally:
        try:
            com(asm, "ClearSelection2", True)
        except Exception:
            pass


_PATTERN_KINDS = {"linear": 108, "circular": 109}  # swFmLocalLPattern, swFmLocalCirPattern
_MAX_PATTERN_COUNT = 1000
_SW_TYPELIB_GUID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"


def _typed(obj, interface):
    """
    Early-bound wrapper for a feature-data object.

    CreateDefinition/GetDefinition return an IDispatch without type info: method
    calls fail and property writes are silently ignored until the object is cast
    to its interface from the generated SolidWorks type library. Objects without
    an _oleobj_ (test fakes) are returned unchanged.
    """
    oleobj = getattr(obj, "_oleobj_", None)
    if oleobj is None and obj is not None:
        return obj
    if obj is None:
        raise ValueError(f"SolidWorks returned no {interface} object.")
    from win32com.client import gencache, selecttlb
    libs = [t for t in selecttlb.EnumTlbs() if t.clsid.upper() == _SW_TYPELIB_GUID]
    if not libs:
        raise RuntimeError("SolidWorks type library is not registered.")
    lib = max(libs, key=lambda t: (int(t.major, 16), int(t.minor, 16)))  # newest installed SolidWorks
    module = gencache.EnsureModule(lib.clsid, int(lib.lcid), int(lib.major, 16), int(lib.minor, 16))
    return getattr(module, interface)(oleobj)


def _check_pattern_args(pattern_type, seed_component, reference, count, spacing_mm, angle_deg,
                        equal_spacing, reverse):
    """Validates create_component_pattern arguments; returns (definition id, count, spacing in m or rad)."""
    if pattern_type not in _PATTERN_KINDS:
        raise ValueError(f"pattern_type must be one of {sorted(_PATTERN_KINDS)}.")
    if not isinstance(seed_component, str) or not seed_component:
        raise ValueError("seed_component must be a component name.")
    chosen = [k for k in ("face_index", "plane", "axis")
              if isinstance(reference, dict) and reference.get(k) is not None]
    if (not isinstance(reference, dict) or not isinstance(reference.get("component"), str)
            or not reference["component"] or len(chosen) != 1):
        raise ValueError("reference needs a component and exactly one of face_index, plane, axis.")
    if chosen[0] == "face_index":
        if type(reference["face_index"]) is not int or reference["face_index"] < 0:
            raise ValueError("face_index must be a non-negative integer.")
    elif not isinstance(reference[chosen[0]], str) or not reference[chosen[0]].strip():
        raise ValueError(f"{chosen[0]} must be a non-empty name.")
    if type(count) is not int or not 2 <= count <= _MAX_PATTERN_COUNT:
        raise ValueError(f"count must be an integer from 2 to {_MAX_PATTERN_COUNT}.")
    if type(reverse) is not bool or type(equal_spacing) is not bool:
        raise ValueError("reverse and equal_spacing must be booleans.")
    if pattern_type == "linear":
        if angle_deg is not None:
            raise ValueError("angle_deg is only valid for circular patterns.")
        value, limit, label = spacing_mm, None, "spacing_mm"
    else:
        if spacing_mm is not None:
            raise ValueError("spacing_mm is only valid for linear patterns.")
        value, limit, label = angle_deg, 360.0, "angle_deg"
    if (value is None or isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0 or (limit is not None and value > limit)):
        raise ValueError(f"{label} must be a finite number greater than 0"
                         + (f" and at most {limit:g}." if limit else "."))
    return (_PATTERN_KINDS[pattern_type], count,
            value / 1000.0 if pattern_type == "linear" else math.radians(value))


@tool(
    name="create_component_pattern",
    description=(
        "Create a linear or circular component pattern of one top-level seed component. "
        "reference is the direction (linear) or axis (circular): a component's face_index from "
        "list_component_faces (planar face / cylindrical face), or its plane/axis by name. "
        "linear: spacing_mm. circular: angle_deg (total angle when equal_spacing, else the step). "
        "Verifies feature, count and new components. Does not save."),
    schema={"type": "object", "properties": {
        "pattern_type": {"type": "string", "enum": sorted(_PATTERN_KINDS)},
        "seed_component": {"type": "string"},
        "reference": {"type": "object", "properties": {
            "component": {"type": "string"}, "face_index": {"type": "integer", "minimum": 0},
            "plane": {"type": "string"}, "axis": {"type": "string"}}, "required": ["component"]},
        "count": {"type": "integer", "minimum": 2, "maximum": _MAX_PATTERN_COUNT},
        "spacing_mm": {"type": "number"}, "angle_deg": {"type": "number"},
        "equal_spacing": {"type": "boolean"}, "reverse": {"type": "boolean"}},
        "required": ["pattern_type", "seed_component", "reference", "count"]},
    operation_class=OperationClass.MUTATE,
)
def create_component_pattern(sw, pattern_type, seed_component, reference, count, spacing_mm=None,
                             angle_deg=None, equal_spacing=True, reverse=False):
    asm, err = _require_assembly(sw)
    if err:
        return err
    changed = False
    try:
        kind, count, value = _check_pattern_args(pattern_type, seed_component, reference, count,
                                                 spacing_mm, angle_deg, equal_spacing, reverse)
        seed = _exact_top_level(asm, seed_component)
        ref_component = _exact_top_level(asm, reference["component"])
        before = [com(c, "Name2") for c in com(asm, "GetComponents", True) or []]
        com(asm, "ClearSelection2", True)
        # Verified live (SolidWorks 2025): direction/axis is selection mark 2, seed mark 1.
        if not _select_mate_ref(asm, ref_component, reference, False, 2):
            raise ValueError("Could not select the direction/axis reference.")
        selected = com(com(asm, "Extension"), "SelectByID2",
                       f"{seed_component}@{_assembly_context_name(asm)}", "COMPONENT", 0.0, 0.0, 0.0,
                       True, 1, win32com.client.VARIANT(pythoncom.VT_DISPATCH, None), 0)
        if not selected:
            raise ValueError("Could not select the seed component.")
        manager = com(asm, "FeatureManager")
        linear = pattern_type == "linear"
        data = _typed(com(manager, "CreateDefinition", kind),
                      "ILocalLinearPatternFeatureData" if linear else "ILocalCircularPatternFeatureData")
        if linear:
            data.D1TotalInstances, data.D1Spacing, data.D1ReverseDirection = count, value, reverse
        else:
            data.TotalInstances, data.Spacing = count, value
            data.EqualSpacing, data.ReverseDirection = equal_spacing, reverse
        changed = True
        feature = com(manager, "CreateFeature", data)
        if feature is None:
            raise ValueError("Pattern was not created (the reference may not suit this pattern type).")
        definition = _typed(com(feature, "GetDefinition"),
                            "ILocalLinearPatternFeatureData" if linear else "ILocalCircularPatternFeatureData")
        made = definition.D1TotalInstances if linear else definition.TotalInstances
        if made != count or definition.GetSeedComponentCount() != 1:
            raise ValueError(f"Pattern readback mismatch: {made} instances, "
                             f"{definition.GetSeedComponentCount()} seeds; inspect the assembly.")
        new = [n for n in (com(c, "Name2") for c in com(asm, "GetComponents", True) or []) if n not in before]
        if len(new) != count - 1:
            raise ValueError(f"Expected {count - 1} new components, found {len(new)}: {new}.")
        return sw._result(True, f"{com(feature, 'Name')} created with {count} instances; no save performed.",
                          data={"feature_name": com(feature, "Name"), "pattern_type": pattern_type,
                                "instances": made, "new_components": new, "saved": False})
    except Exception as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput,
                          data={"document_may_be_modified": changed, "saved": False})
    finally:
        try:
            com(asm, "ClearSelection2", True)
        except Exception:
            pass


def _mates_touching(mates, component_name):
    """Mates with an entity on the component (or inside it, if it is a sub-assembly)."""
    result = []
    for m in mates:
        names = [e.get("component") for e in m.get("entities") or [] if isinstance(e, dict)]
        names = [n for n in names if n]
        inside = [n for n in names if n == component_name or n.startswith(component_name + "/")]
        if inside:
            result.append({"name": m.get("name"), "mate_type_name": m.get("mate_type_name"),
                           "suppressed": m.get("suppressed"),
                           "solver_state": (m.get("solver_status") or {}).get("state"),
                           "other_components": sorted({n for n in names if n not in inside})})
    return result


@tool(name="get_component", description=(
    "Read one exact top-level component: path, configuration, translation (mm), rotation_deg, "
    "suppressed, fixed, and the mates touching it. Read-only."),
    schema={"type": "object", "properties": {"component_name": {"type": "string", "minLength": 1}},
            "required": ["component_name"]},
    operation_class=OperationClass.READ)
def get_component(sw, component_name):
    asm, error = _require_assembly(sw)
    if error:
        return error
    try:
        component = _exact_top_level(asm, component_name)
    except ValueError as exc:
        return sw._result(False, str(exc), SwErrors.swInvalidInput)
    try:
        transform = list(com(com(component, "Transform2"), "ArrayData") or [])
    except Exception:
        transform = []
    suppression = com(component, "GetSuppression")
    valid = len(transform) >= 12
    data = {
        "component_name": component_name,
        "path": com(component, "GetPathName") or None,
        "configuration": com(component, "ReferencedConfiguration"),
        "translation_mm": [v * 1000 for v in transform[9:12]] if valid else None,
        "rotation_deg": _matrix_to_euler(transform[:9]) if valid else None,
        "fixed": bool(com(component, "IsFixed")),
        "suppressed": suppression == 0,
    }
    listing = list_mates(sw)
    if listing.get("success"):
        data["mates"] = _mates_touching(listing["data"]["mates"], component_name)
        data["mates_complete"] = bool((listing["data"].get("coverage") or {}).get("complete", True))
    else:
        data["mates"] = None
        data["mates_error"] = listing.get("msg")
    return sw._result(True, f"Component {component_name} read.", data=data)


@tool(
    name="list_mates",
    description="List the mates already present in the active assembly's Mates feature group.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def list_mates(sw) -> dict:
    """List mate definitions, entities, values, and rebuild status."""
    asm, err = _require_assembly(sw)
    if err:
        return err

    unresolved = []

    def optional(obj, member, context, *args):
        try:
            return com(obj, member, *args)
        except Exception as error:
            unresolved.append(f"{context}: {member} unavailable ({error})")
            return None

    def mate_type_name(value):
        try:
            return SwMateTypes(value).name.removeprefix("swMate").lower()
        except (ValueError, TypeError):
            return "unknown"

    def solver_status(feature, context, definition_available):
        warning = win32com.client.VARIANT(
            pythoncom.VT_BYREF | pythoncom.VT_BOOL, False
        )
        try:
            error_code = com(feature, "GetErrorCode2", warning)
            is_warning = bool(warning.value) if error_code else False
        except Exception as error:
            unresolved.append(f"{context}: GetErrorCode2 unavailable ({error})")
            error_code = None
            is_warning = None
        if not definition_available:
            state = "unavailable"
        elif error_code is None:
            state = "unknown"
        elif error_code == 0:
            state = "solved"
        elif is_warning:
            state = "warning"
        else:
            state = "error"
        return {"state": state, "error_code": error_code, "is_warning": is_warning}

    def inspect_entity(entity, context):
        component = optional(entity, "ReferenceComponent", context)
        component_name = (
            optional(component, "Name2", context) if component is not None else None
        )
        params = optional(entity, "EntityParams", context)
        values = list(params) if params is not None else []
        if len(values) < 8:
            unresolved.append(
                f"{context}: EntityParams returned {len(values)} of 8 values"
            )
            values.extend([None] * (8 - len(values)))
        return {
            "component": component_name,
            "reference_type": optional(entity, "ReferenceType2", context),
            "point_m": values[0:3],
            "vector": values[3:6],
            "radius_1_m": values[6],
            "radius_2_m": values[7],
        }

    def inspect_mate(feature):
        name = optional(feature, "Name", "mate") or "<unknown>"
        context = f"mate {name}"
        definition = optional(feature, "GetSpecificFeature2", context)
        feature_type = optional(feature, "GetTypeName2", context) or "<unknown>"
        mate_type = optional(definition, "Type", context) if definition is not None else None
        entities = []
        value = None
        if definition is not None:
            count = optional(definition, "GetMateEntityCount", context)
            if isinstance(count, int):
                for index in range(count):
                    entity = optional(definition, "MateEntity", f"{context}/entity[{index}]", index)
                    if entity is not None:
                        entities.append(inspect_entity(entity, f"{context}/entity[{index}]"))
            if mate_type in {
                int(SwMateTypes.swMateDISTANCE), int(SwMateTypes.swMateANGLE)
            }:
                display = optional(definition, "DisplayDimension2", context, 0)
                dimension = (
                    optional(display, "GetDimension2", context, 0)
                    if display is not None else None
                )
                system_value = (
                    optional(dimension, "SystemValue", context)
                    if dimension is not None else None
                )
                value = {
                    "system_value": system_value,
                    "unit": (
                        "m" if mate_type == int(SwMateTypes.swMateDISTANCE) else "rad"
                    ),
                }
        else:
            unresolved.append(f"{context}: mate definition unavailable")

        is_flippable_type = mate_type in {
            int(SwMateTypes.swMateDISTANCE), int(SwMateTypes.swMateANGLE)
        }

        return {
            "name": name,
            "feature_id": optional(feature, "GetID", context),
            "feature_type": feature_type,
            "mate_type": mate_type,
            "mate_type_name": mate_type_name(mate_type),
            "alignment": (
                optional(definition, "Alignment", context)
                if definition is not None else None
            ),
            "can_flip": (
                optional(definition, "CanBeFlipped", context)
                if definition is not None and is_flippable_type else None
            ),
            "flipped": (
                optional(definition, "Flipped", context)
                if definition is not None and is_flippable_type else None
            ),
            "suppressed": optional(feature, "IsSuppressed", context),
            "value": value,
            "entities": entities,
            "solver_status": solver_status(feature, context, definition is not None),
        }

    mate_group = None
    feat = com(asm, "FirstFeature")
    while feat is not None:
        if com(feat, "GetTypeName2") == "MateGroup":
            mate_group = feat
            break
        feat = com(feat, "GetNextFeature")

    mates = []
    if mate_group is not None:
        sub = com(mate_group, "GetFirstSubFeature")
        while sub is not None:
            mates.append(inspect_mate(sub))
            sub = com(sub, "GetNextSubFeature")

    return sw._result(True, f"Found {len(mates)} mates.", data={
        "mates": mates,
        "coverage": {
            "complete": not unresolved,
            "visited_count": len(mates),
            "unresolved": unresolved,
            "truncated": False,
            "next_cursor": None,
        },
    })


@tool(
    name="pack_and_go",
    description=(
        "Save the active assembly and all referenced documents (parts, "
        "sub-assemblies, drawings) into a destination folder, using "
        "SolidWorks Pack and Go. Reports any referenced documents that "
        "live outside the assembly's own project folder, since those "
        "would silently break with a plain folder copy (O15)."
    ),
    schema={
        "type": "object",
        "properties": {
            "destination_folder": {"type": "string", "description": "Folder to save the packed assembly into"},
            "include_drawings": {"type": "boolean", "description": "Include referenced drawings. Default true."},
        },
        "required": ["destination_folder"]
    },
    operation_class=OperationClass.EXPORT,
)
def pack_and_go(sw, destination_folder: str, include_drawings: bool = True) -> dict:
    """Pack and Go the active assembly to a destination folder"""
    denied = require_output_write(sw, destination_folder)
    if denied:
        return denied
    asm, err = _require_assembly(sw)
    if err:
        return err

    project_folder = os.path.dirname(com(asm, "GetPathName") or "")

    try:
        ext = com(asm, "Extension")
        # GetPackAndGo's live signature (SW2025) needs one ByRef IDispatch*
        # out-argument -- calling with 0 args raises "Parameter not
        # optional" (api-findings.md §6.3). pywin32 cannot marshal a
        # BYREF VT_DISPATCH out-param back to Python (known client-side
        # limitation, not an API misuse), so pgo is always None here.
        placeholder = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)
        ext.GetPackAndGo(placeholder)
        pgo = placeholder.value
        if pgo is None:
            return sw._result(
                False,
                "GetPackAndGo could not be retrieved (pywin32 cannot "
                "marshal this COM out-parameter back to Python; see "
                "api-findings.md §6.3). Pack and Go is not usable "
                "from this tool without a different COM binding (e.g. "
                "comtypes).",
                SwErrors.swUnknownError)

        try:
            pgo.IncludeDrawings = include_drawings
        except Exception:
            pass

        names = list(com(pgo, "GetDocumentNames"))
        outside = [n for n in names
                   if os.path.normcase(os.path.dirname(n)) != os.path.normcase(project_folder)]

        os.makedirs(destination_folder, exist_ok=True)
        save_names = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_BSTR,
            [os.path.join(destination_folder, os.path.basename(n)) for n in names])
        com(pgo, "SetDocumentSaveToNames", save_names)
        com(pgo, "SetSaveToName", True, destination_folder)

        ok = com(ext, "SavePackAndGo", pgo)
    except Exception as e:
        logger.error(f"Pack and Go failed: {e}")
        return sw._result(False, f"Pack and Go failed: {e}", SwErrors.swUnknownError)

    if not ok:
        return sw._result(False, "Pack and Go reported failure.", SwErrors.swFileSaveError)

    return sw._result(
        True,
        f"Packed {len(names)} documents to {destination_folder}."
        + (f" {len(outside)} came from outside the project folder."
           if outside else ""),
        data={"documents": list(names), "outside_project_folder": outside}
    )
