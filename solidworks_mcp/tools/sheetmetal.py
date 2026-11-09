"""
Sheet metal tools (part D): read parameters, export flat pattern.
"""

import logging
import math
import os

import pythoncom
import win32com.client

from ..comutil import com, set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .export import _get_planar_face_by_index
from .guard import require_output_write, require_stateful_document_access
from .inspection import part_edges

logger = logging.getLogger("SolidWorksMCP")


def _find_sheet_metal_feature(doc):
    feat = com(doc, "FirstFeature")
    while feat is not None:
        if com(feat, "GetTypeName2") == "SheetMetal":
            return feat
        feat = com(feat, "GetNextFeature")
    return None


def _find_flat_pattern_feature(doc):
    feat = com(doc, "FirstFeature")
    while feat is not None:
        if com(feat, "GetTypeName2") == "FlatPattern":
            return feat
        feat = com(feat, "GetNextFeature")
    return None


@tool(
    name="get_sheet_metal_info",
    description=(
        "Read the first Sheet-Metal definition: thickness, K-factor, radius and relief. "
        "Use list_sheet_metal_bodies for per-body parameters. Read-only."
    ),
    schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    operation_class=OperationClass.READ,
)
def get_sheet_metal_info(sw) -> dict:
    """Read sheet metal parameters from the active part."""
    doc, err = sw.get_active_doc()
    if err:
        return err

    feat = _find_sheet_metal_feature(doc)
    if feat is None:
        return sw._result(False, "Part has no sheet metal feature.",
                          SwErrors.swFeatureError)

    smdata = com(feat, "GetDefinition")

    return sw._result(
        True,
        "Read sheet metal parameters.",
        data={
            "thickness_mm": com(smdata, "Thickness") * 1000,
            "k_factor": com(smdata, "KFactor"),
            "bend_radius_mm": com(smdata, "BendRadius") * 1000,
            "bend_allowance_type": com(smdata, "BendAllowanceType"),
            "bend_allowance": com(smdata, "BendAllowance"),
            "use_auto_relief": com(smdata, "UseAutoRelief"),
            "auto_relief_type": com(smdata, "AutoReliefType"),
            "relief_ratio": com(smdata, "ReliefRatio"),
            "use_material_sheet_metal_parameters": com(smdata, "UseMaterialSheetMetalParameters"),
            "bend_table_file": com(smdata, "BendTableFile"),
        }
    )


@tool(
    name="flatten_sheet_metal",
    description=(
        "Suppress or unsuppress the active part's Flat-Pattern feature, "
        "toggling the body between flattened and folded state. Modifies "
        "the active part (not saved)."
    ),
    schema={
        "type": "object",
        "properties": {
            "flatten": {
                "type": "boolean",
                "description": "True to flatten (suppress Flat-Pattern feature state 1), "
                                "false to fold back (state 0)."
            }
        },
        "required": ["flatten"]
    },
    operation_class=OperationClass.MUTATE,
)
def flatten_sheet_metal(sw, flatten: bool) -> dict:
    """Toggle the Flat-Pattern feature between flattened and folded state."""
    doc, err = sw.get_active_doc()
    if err:
        return err
    denied = require_stateful_document_access(sw, doc)
    if denied:
        return denied

    feat = _find_flat_pattern_feature(doc)
    if feat is None:
        return sw._result(False, "Part has no Flat-Pattern feature.",
                          SwErrors.swFeatureError)

    state = 1 if flatten else 0
    try:
        ok = com(feat, "SetSuppression", state)
        com(doc, "EditRebuild3")
    except Exception as e:
        logger.error(f"SetSuppression failed: {e}")
        return sw._result(False, f"Could not set flat pattern state: {e}",
                          SwErrors.swFeatureError)

    if not ok:
        return sw._result(False, "SetSuppression returned false.",
                          SwErrors.swFeatureError)

    return sw._result(
        True,
        f"Flat pattern {'flattened' if flatten else 'folded back'}.",
        data={"flattened": flatten}
    )


@tool(
    name="get_flat_pattern_info",
    description=(
        "Flatten the active sheet metal part, read the flat pattern's "
        "bounding box and body/face counts, then fold it back. Net effect "
        "on the model is none (not saved), but the part is flattened and "
        "refolded during the call."
    ),
    schema={
        "type": "object",
        "properties": {},
        "required": []
    },
    operation_class=OperationClass.STATEFUL_READ,
)
def get_flat_pattern_info(sw) -> dict:
    """Read flat pattern bounding-box dimensions, restoring the folded state after."""
    doc, err = sw.get_active_doc()
    if err:
        return err
    denied = require_stateful_document_access(sw, doc)
    if denied:
        return denied

    feat = _find_flat_pattern_feature(doc)
    if feat is None:
        return sw._result(False, "Part has no Flat-Pattern feature.",
                          SwErrors.swFeatureError)

    # IsSuppressed()==True is the normal/folded state (SetSuppression(0));
    # SetSuppression(1) unsuppresses the feature, which is what flattens the
    # body (live-verified: 42 -> 14 faces on a real part). Counter-intuitive
    # naming, but matches swSuppressFeature=0 / swUnSuppressFeature=1.
    was_folded = com(feat, "IsSuppressed")

    try:
        if was_folded:
            com(feat, "SetSuppression", 1)
            com(doc, "EditRebuild3")

        bodies = com(doc, "GetBodies2", 0, True)
        if not bodies:
            return sw._result(False, "No solid body found after flattening.",
                              SwErrors.swFeatureError)
        body = bodies[0]
        box = com(body, "GetBodyBox")
        faces = com(body, "GetFaceCount")
    finally:
        if was_folded:
            com(feat, "SetSuppression", 0)
            com(doc, "EditRebuild3")

    xmin, ymin, zmin, xmax, ymax, zmax = box
    return sw._result(
        True,
        "Read flat pattern info (model restored to folded state).",
        data={
            "length_mm": (xmax - xmin) * 1000,
            "width_mm": (ymax - ymin) * 1000,
            "height_mm": (zmax - zmin) * 1000,
            "face_count": faces
        }
    )


@tool(
    name="export_flat_pattern",
    description=(
        "Direct DXF/DWG flat-pattern export of the active saved sheet-metal part. "
        "For one body of a multibody part with source-state isolation, use export_sheet_metal_body_dxf. "
        "Native exports can refresh model state; no source-isolation guarantee on this legacy path."
    ),
    schema={
        "type": "object",
        "properties": {
            "output_path": {
                "type": "string",
                "description": "Full destination path, extension .dxf or .dwg"
            }
        },
        "required": ["output_path"]
    },
    operation_class=OperationClass.EXPORT,
)
def export_flat_pattern(sw, output_path: str) -> dict:
    """Export the flat pattern of the active sheet metal part."""
    denied = require_output_write(sw, output_path)
    if denied:
        return denied
    doc, err = sw.get_active_doc()
    if err:
        return err

    if _find_sheet_metal_feature(doc) is None:
        return sw._result(False, "Part has no sheet metal feature.",
                          SwErrors.swFeatureError)

    ext = os.path.splitext(output_path)[1].lower()
    if ext not in (".dxf", ".dwg"):
        return sw._result(False, f"Unsupported output extension: {ext}",
                          SwErrors.swInvalidInput)

    # ExportToDWG2 needs the model path as its base-name argument. An unsaved
    # scratch part has an empty path, which makes the export fail with no
    # explanation (live-verified: it succeeds as soon as the part is saved).
    model_path = com(doc, "GetPathName")
    if not model_path:
        return sw._result(
            False,
            "SolidWorks needs a saved model path to export a flat pattern. "
            "Save the part first (save_document) and retry.",
            SwErrors.swFileSaveError,
            {"code": "UNSAVED_DOCUMENT"},
        )

    alignment = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, [0.0] * 12)
    views = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

    try:
        ok = com(doc, "ExportToDWG2", output_path, model_path,
                 1, True, alignment, False, False, 0, views)
    except Exception as e:
        logger.error(f"ExportToDWG2 failed: {e}")
        return sw._result(False, f"Export failed: {e}", SwErrors.swExportError)

    if not ok:
        return sw._result(False, "Export failed.", SwErrors.swExportError)

    return sw._result(
        True,
        f"Exported flat pattern to {output_path}.",
        data={"path": output_path}
    )


def _positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


@tool(
    name="create_sheet_metal_base_flange",
    description=(
        "Create a base flange from the last sketch. new_body=true adds a separate "
        "sheet body to an existing sheet-metal part and verifies existing solids unchanged. "
        "Closed sketch sets outline; width_mm applies to open profiles. Not saved."
    ),
    schema={
        "type": "object",
        "properties": {
            "thickness_mm": {"type": "number",
                             "description": "Sheet thickness in mm."},
            "bend_radius_mm": {"type": "number",
                               "description": "Default bend radius in mm. Defaults to the thickness."},
            "width_mm": {"type": "number", "default": 50.0,
                         "description": "Width for open profiles, split across the sketch plane."},
            "new_body": {"type":"boolean", "default":False,
                         "description":"Explicitly add a body to existing sheet metal; use a fresh separate sketch."}
        },
        "required": ["thickness_mm"]
    },
    operation_class=OperationClass.MUTATE,
)
def create_sheet_metal_base_flange(sw, thickness_mm: float,
                                   bend_radius_mm: float = None,
                                   width_mm: float = 50.0,
                                   new_body: bool = False) -> dict:
    """Create a base flange from the last sketch using InsertSheetMetalBaseFlange."""
    if type(new_body) is not bool:
        return sw._result(False,"new_body must be boolean.",SwErrors.swInvalidInput,{"code":"VALIDATION_FAILED"})
    if not _positive(thickness_mm) or not math.isfinite(thickness_mm):
        return sw._result(False, "thickness_mm must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if bend_radius_mm is not None and (
            not isinstance(bend_radius_mm, (int, float))
            or isinstance(bend_radius_mm, bool) or not math.isfinite(bend_radius_mm) or bend_radius_mm < 0):
        return sw._result(False, "bend_radius_mm must be a non-negative number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not _positive(width_mm) or not math.isfinite(width_mm):
        return sw._result(False, "width_mm must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    doc, err = sw.get_active_doc()
    if err:
        return err
    if new_body:
        from .sheetmetal_multibody import add_sheet_metal_body
        return add_sheet_metal_body(sw,doc,thickness_mm,
                                   thickness_mm if bend_radius_mm is None else bend_radius_mm,width_mm)
    if _find_sheet_metal_feature(doc) is not None:
        return sw._result(
            False, "The active part already has a sheet-metal feature.",
            SwErrors.swFeatureError, {"code": "ALREADY_SHEET_METAL"},
        )

    selected, sketch_name, message = sw._close_and_select_sketch(doc)
    if not selected:
        return sw._result(False, f"Could not select a sketch: {message}",
                          SwErrors.swSketchError)

    radius_mm = thickness_mm if bend_radius_mm is None else bend_radius_mm

    # InsertSheetMetalBaseFlange2 returns None in SW 2025 rev 33.1.1 even when
    # its arguments are the v2 equivalents; the 16-argument
    # InsertSheetMetalBaseFlange creates the Sheet-Metal feature reliably
    # (live-verified).
    try:
        feature = _insert_base_flange(doc,thickness_mm,radius_mm,width_mm)
    except Exception as create_error:
        logger.error(f"InsertSheetMetalBaseFlange failed: {create_error}")
        return sw._result(False, f"Could not create the base flange: {create_error}",
                          SwErrors.swFeatureError)

    sheet_metal = _find_sheet_metal_feature(doc)
    if sheet_metal is None:
        # The API returns a feature even when nothing usable was built, so
        # success is only reported when the Sheet-Metal feature is observed.
        return sw._result(
            False,
            "No sheet-metal feature appeared after the base flange call.",
            SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"},
        )

    return sw._result(
        True,
        f"Created base flange '{com(feature, 'Name')}' from sketch '{sketch_name}'.",
        data={
            "feature": com(feature, "Name") if feature is not None else None,
            "sheet_metal_feature": com(sheet_metal, "Name"),
            "sketch": sketch_name,
            "thickness_mm": thickness_mm,
            "bend_radius_mm": radius_mm,
            "width_mm": width_mm,
        },
    )


def _insert_base_flange(doc,thickness_mm,radius_mm,width_mm):
    """Shared, live-verified 16-argument base-flange call; units are metres."""
    half=width_mm/2000.
    return com(com(doc,'FeatureManager'),'InsertSheetMetalBaseFlange',
               thickness_mm/1000.,False,radius_mm/1000.,half,half,False,0,0,0,
               win32com.client.VARIANT(pythoncom.VT_DISPATCH,None),False,0,0.,0.,0.,False)


#: swFeatureNameID_e value passed to CreateDefinition (read from swconst.tlb).
SW_FM_TAB_AND_SLOT = 88

#: swTabSlotFeatureSpacingType_e: 'single' is equal spacing with one instance.
TAB_SLOT_SPACING = {"single": 0, "equal": 0, "length": 1}

#: swTabSlotFeatureHeightType_e. Only Blind is live-verified; UpToSurface and
#: OffsetFromSurface produced no feature in the probed fixture (see findings).
TAB_SLOT_HEIGHT_BLIND = 0

#: swTabEdgesType_e
TAB_SLOT_EDGE_TREATMENT = {"sharp": 0, "fillet": 1, "chamfer": 2}

#: Feature types SolidWorks has reported for a Tab and Slot feature.
TAB_SLOT_FEATURE_TYPES = ("TabAndSlotFeature",)


def _non_negative(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value >= 0)


def _body_volumes(doc):
    """Per-body volume and face count, in the GetBodies2 order."""
    bodies = []
    for body in com(doc, "GetBodies2", 0, True) or []:
        mass = com(body, "GetMassProperties", 0.0)
        bodies.append({
            "name": str(com(body, "Name")),
            "centroid_m": [float(v) for v in mass[:3]],
            "volume_mm3": float(mass[3]) * 1e9,
            "faces": len(com(body, "GetFaces") or []),
        })
    return bodies


def _match_body(bodies, prefix, reference):
    """Find the body that plays a role after the feature, order-independently.

    Tab and Slot renames the two joined bodies to 'Tab and Slot-Tab<N>' and
    'Tab and Slot-Slot<N>'; that name is the role.  If no body carries the
    prefix (a localised UI), the closest volume to the body's own earlier
    volume is used instead.
    """
    candidates = [item for item in bodies if item['name'].startswith(prefix)]
    if not candidates:
        candidates = [item for item in bodies if item['name']==reference['name']] or bodies
    def score(item):
        distance = math.dist(item.get('centroid_m',[0,0,0]),reference.get('centroid_m',[0,0,0]))
        return distance,abs(item['volume_mm3']-reference['volume_mm3'])
    return min(candidates,key=score)


def _coplanar_tab_face(tab_edge, slot_face):
    """The face sharing the tab edge that is coplanar with the slot face.

    The tab grows perpendicular to its own reference face, so the reference face
    decides whether the tab can reach the other body at all.  The face that lies
    in the slot face's plane is the one that works: on two flat plates it is the
    thin rim face that is coplanar with the target plate, and on tubes it is the
    end face (the annulus at the joint) rather than the tube wall.  Returns None
    when no such face exists, in which case the API default is used.
    """
    try:
        slot_normal = [float(value) for value in com(slot_face, "Normal")[:3]]
        candidates = com(tab_edge, "GetTwoAdjacentFaces2") or []
    except Exception:
        return None
    for face in candidates:
        try:
            if not com(com(face, "GetSurface"), "IsPlane"):
                continue
            normal = [float(value) for value in com(face, "Normal")[:3]]
        except Exception:
            continue
        if abs(sum(normal[axis] * slot_normal[axis] for axis in range(3))) > 0.999:
            return face
    return None


def _find_feature(doc, name):
    feature = com(doc, "FirstFeature")
    while feature is not None:
        if str(com(feature, "Name")) == name:
            return feature
        feature = com(feature, "GetNextFeature")
    return None


@tool(
    name="create_tab_and_slot",
    description=(
        "Tab and Slot joining two bodies: tab grows from one body's edge (list_body_edges), slot is cut in the other body's face (list_planar_faces). Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "tab_edge_index": {
                "type": "integer", "minimum": 0,
            },
            "slot_face_index": {
                "type": "integer", "minimum": 0,
            },
            "tab_face_index": {
                "type":"integer", "minimum":0,
            },
            "tab_length_mm": {
                "type": "number", "exclusiveMinimum": 0, "default": 10.0,
            },
            "tab_height_mm": {
                "type": "number", "exclusiveMinimum": 0, "default": 6.0,
                "description": ("Protrusion; use the wall thickness for tubes"),
            },
            "slot_clearance_mm": {
                "type": "number", "minimum": 0, "default": 0.2,
            },
            "spacing": {
                "type": "string", "enum": ["single", "equal", "length"],
                "default": "single",
            },
            "instances": {
                "type": "integer", "minimum": 1, "default": 1,
                "description": "When spacing is 'equal'",
            },
            "spacing_mm": {
                "type": "number", "exclusiveMinimum": 0,
                "description": "When spacing is 'length'",
            },
            "edge_treatment": {
                "type": "string", "enum": ["sharp", "fillet", "chamfer"],
                "default": "sharp",
            },
            "edge_treatment_mm": {
                "type": "number", "exclusiveMinimum": 0, "default": 1.0,
            },
            "tab_thickness_mm": {
                "type": "number", "exclusiveMinimum": 0,
            },
            "offset_from_edges": {
                "type": "boolean", "default": False,
            },
            "start_offset_mm": {
                "type": "number", "minimum": 0, "default": 0.0,
            },
            "end_offset_mm": {
                "type": "number", "minimum": 0, "default": 0.0,
            },
        },
        "required": ["tab_edge_index", "slot_face_index"],
    },
    operation_class=OperationClass.MUTATE,
)
def create_tab_and_slot(sw, tab_edge_index, slot_face_index, tab_length_mm=10.0,
                        tab_height_mm=6.0, slot_clearance_mm=0.2,
                        spacing="single", instances=1, spacing_mm=None,
                        edge_treatment="sharp", edge_treatment_mm=1.0,
                        tab_thickness_mm=None, offset_from_edges=False,
                        start_offset_mm=0.0, end_offset_mm=0.0, tab_face_index=None) -> dict:
    """Grow a tab from one body's edge and cut its slot in another body's face."""
    if (isinstance(tab_edge_index, bool) or not isinstance(tab_edge_index, int)
            or tab_edge_index < 0):
        return sw._result(False, "tab_edge_index must be a non-negative integer.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if (isinstance(slot_face_index, bool) or not isinstance(slot_face_index, int)
            or slot_face_index < 0):
        return sw._result(False, "slot_face_index must be a non-negative integer.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if tab_face_index is not None and (isinstance(tab_face_index,bool) or not isinstance(tab_face_index,int) or tab_face_index<0):
        return sw._result(False,'tab_face_index must be a non-negative integer.',SwErrors.swInvalidInput,{'code':'VALIDATION_FAILED'})
    for name, value in (("tab_length_mm", tab_length_mm),
                        ("tab_height_mm", tab_height_mm),
                        ("edge_treatment_mm", edge_treatment_mm)):
        if not _positive(value):
            return sw._result(False, f"{name} must be a positive number.",
                              SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not _non_negative(slot_clearance_mm):
        return sw._result(False, "slot_clearance_mm must be a non-negative number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if spacing not in TAB_SLOT_SPACING:
        return sw._result(False, f"spacing must be one of {sorted(TAB_SLOT_SPACING)}.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if spacing == "equal" and (isinstance(instances, bool)
                               or not isinstance(instances, int) or instances < 1):
        return sw._result(False, "instances must be a positive integer.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if spacing == "length" and not _positive(spacing_mm):
        return sw._result(
            False, "spacing_mm must be a positive number when spacing is 'length'.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if edge_treatment not in TAB_SLOT_EDGE_TREATMENT:
        return sw._result(
            False, f"edge_treatment must be one of {sorted(TAB_SLOT_EDGE_TREATMENT)}.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if tab_thickness_mm is not None and not _positive(tab_thickness_mm):
        return sw._result(False, "tab_thickness_mm must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(offset_from_edges, bool):
        return sw._result(False, "offset_from_edges must be a boolean.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not _non_negative(start_offset_mm) or not _non_negative(end_offset_mm):
        return sw._result(False, "Offsets must be non-negative numbers.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)

    try:
        bodies = com(doc, "GetBodies2", 0, True) or []
    except Exception as read_error:
        return sw._result(False, f"Could not read bodies: {read_error}",
                          SwErrors.swUnknownError)
    if len(bodies) < 2:
        return sw._result(
            False,
            "Tab and Slot needs at least two solid bodies: the tab comes from "
            "one body's edge and the slot is cut in another body's face.",
            SwErrors.swFeatureError, {"code": "NOT_ENOUGH_BODIES"})

    try:
        edges = part_edges(doc)
    except Exception as read_error:
        return sw._result(False, f"Could not read body edges: {read_error}",
                          SwErrors.swUnknownError)
    if tab_edge_index >= len(edges):
        return sw._result(
            False,
            f"Tab edge index {tab_edge_index} is out of range for {len(edges)} "
            "edges; re-run list_body_edges.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    tab_edge = edges[tab_edge_index]

    slot_face = _get_planar_face_by_index(doc, slot_face_index)
    if slot_face is None:
        return sw._result(
            False,
            f"Slot face index {slot_face_index} is not a planar face of the "
            "active part; re-run list_planar_faces.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    before = _body_volumes(doc)
    tab_candidates = [item for item in before if item["name"] == tab_edge["body"]]
    try:
        if 'body_index' in tab_edge:
            tab_before = before[tab_edge['body_index']]
        else:
            tab_center = list(com(com(tab_edge['edge'], 'GetBody'), 'GetMassProperties', 0.0)[:3])
            tab_before = min(tab_candidates,key=lambda item:math.dist(item['centroid_m'],tab_center))
    except AttributeError:
        tab_before = tab_candidates[0] if tab_candidates else None
    if tab_before is None:
        return sw._result(
            False,
            f"Tab edge body '{tab_edge['body']}' was not found among the solid "
            "bodies.",
            SwErrors.swFeatureError, {"code": "BODY_NOT_FOUND"})
    try:
        slot_body_name = str(com(com(slot_face, "GetBody"), "Name"))
    except Exception as body_error:
        return sw._result(False, f"Could not read the slot face's body: {body_error}",
                          SwErrors.swUnknownError)
    slot_candidates = [item for item in before if item['name']==slot_body_name]
    try:
        slot_center = list(com(com(slot_face,'GetBody'),'GetMassProperties',0.0)[:3])
        slot_before = min(slot_candidates,key=lambda item:math.dist(item['centroid_m'],slot_center))
    except AttributeError:
        slot_before = slot_candidates[0] if slot_candidates else None
    if slot_before is None:
        return sw._result(
            False,
            f"Slot face body '{slot_body_name}' was not found among the solid "
            "bodies.",
            SwErrors.swFeatureError, {"code": "BODY_NOT_FOUND"})
    if slot_body_name == tab_before["name"]:
        return sw._result(
            False,
            "The tab edge and the slot face belong to the same body; the slot "
            "must be cut in another body.",
            SwErrors.swInvalidInput, {"code": "SAME_BODY"})

    values = {
        "SelectionTabEdge": tab_edge["edge"],
        "SelectionSlotFace": slot_face,
        "TabLength": tab_length_mm / 1000.0,
        "SlotClearance": slot_clearance_mm / 1000.0,
        "TabHeightType": TAB_SLOT_HEIGHT_BLIND,
        "TabHeightValue": tab_height_mm / 1000.0,
        "TabEdgesType": TAB_SLOT_EDGE_TREATMENT[edge_treatment] if edge_treatment else 0,
        "SpacingType": TAB_SLOT_SPACING[spacing],
        "SpacingNumberOfInstances": instances if spacing == "equal" else 1,
    }
    if spacing == "length":
        values["Spacing"] = spacing_mm / 1000.0
    if edge_treatment == "fillet":
        values["TabFilletEdgeTreatmentValue"] = edge_treatment_mm / 1000.0
    elif edge_treatment == "chamfer":
        values["TabChamferEdgeTreatmentValue"] = edge_treatment_mm / 1000.0
    if tab_thickness_mm is not None:
        values["TabThickness"] = tab_thickness_mm / 1000.0
    if offset_from_edges:
        values["Offset"] = True
        values["D1OffsetFromStart"] = start_offset_mm / 1000.0
        values["D2OffsetFromEnd"] = end_offset_mm / 1000.0
    # The tab's reference face decides which way the tab can grow. Prefer the
    # face sharing the tab edge that lies in the slot face's plane (verified on
    # plates and on weldment tubes); without a match the API default is used and
    # the request is still attempted.
    tab_face = _coplanar_tab_face(tab_edge["edge"], slot_face)
    if tab_face_index is not None:
        selected_face = _get_planar_face_by_index(doc,tab_face_index)
        adjacent = com(tab_edge['edge'],'GetTwoAdjacentFaces2') or []
        if selected_face is None or not any(selected_face._oleobj_ == face._oleobj_ for face in adjacent):
            return sw._result(False,'tab_face_index must identify a planar face sharing the selected tab edge.',SwErrors.swInvalidInput,{'code':'INVALID_TAB_FACE'})
        tab_face = selected_face
    if tab_face is not None:
        values["TabFace"] = tab_face

    feature_manager = com(doc, "FeatureManager")
    try:
        definition = com(feature_manager, "CreateDefinition", SW_FM_TAB_AND_SLOT)
    except Exception as create_error:
        return sw._result(False, f"Could not create the Tab and Slot definition: "
                                 f"{create_error}", SwErrors.swFeatureError)
    if definition is None:
        return sw._result(False, "SolidWorks returned no Tab and Slot definition.",
                          SwErrors.swFeatureError)
    group = com(definition, "SelectionAddNewGroup")
    if group is None:
        return sw._result(False, "SolidWorks returned no Tab and Slot group.",
                          SwErrors.swFeatureError)
    try:
        for name, value in values.items():
            set_com(group, name, value)
    except Exception as set_error:
        return sw._result(False, f"Could not configure the Tab and Slot group: "
                                 f"{set_error}", SwErrors.swFeatureError)

    try:
        feature = com(feature_manager, "CreateFeature", definition)
    except Exception as create_error:
        logger.error(f"CreateFeature for Tab and Slot failed: {create_error}")
        return sw._result(False, f"Could not create the Tab and Slot feature: "
                                 f"{create_error}", SwErrors.swFeatureError)
    if feature is None:
        return sw._result(
            False,
            "SolidWorks created no Tab and Slot feature. The edge must lie in "
            "the slot face's plane on another body, and the tab must reach that "
            "face; too many equally spaced instances for the edge also fail.",
            SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"})

    name = str(com(feature, "Name"))
    feature_type = str(com(feature, "GetTypeName2"))
    if feature_type not in TAB_SLOT_FEATURE_TYPES:
        return sw._result(
            False, f"Feature '{name}' is a {feature_type}, not a Tab and Slot.",
            SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"})

    com(doc, "ForceRebuild3", False)
    if _find_feature(doc, name) is None:
        return sw._result(False, f"Tab and Slot '{name}' did not persist.",
                          SwErrors.swFeatureError, {"code": "FEATURE_NOT_PERSISTED"})

    after = _body_volumes(doc)
    if len(after) != len(before):
        return sw._result(
            False,
            f"Tab and Slot changed the body count from {len(before)} to "
            f"{len(after)}; it must only modify the two joined bodies.",
            SwErrors.swFeatureError, {"code": "UNEXPECTED_BODY_COUNT"})

    # The feature renames the two joined bodies to 'Tab and Slot-Tab<N>' and
    # 'Tab and Slot-Slot<N>'. Those names are how the two roles are told apart
    # after the body order may have changed; a localised name falls back to
    # matching the closest volume.
    tab_after = _match_body(after, "Tab and Slot-Tab", tab_before)
    slot_after = _match_body([item for item in after if item is not tab_after],
                            "Tab and Slot-Slot", slot_before)
    gained = tab_after["volume_mm3"] - tab_before["volume_mm3"]
    removed = slot_before["volume_mm3"] - slot_after["volume_mm3"]
    if gained <= 1e-6 or removed <= 1e-6:
        return sw._result(
            False,
            "The feature was created but no material was added to one body and "
            "removed from the other, so no tab and slot were formed.",
            SwErrors.swFeatureError, {"code": "NO_GEOMETRY_CHANGE"})

    readback = {}
    try:
        created_definition = com(feature, "GetDefinition")
        com(created_definition, "AccessSelections", doc,
            win32com.client.VARIANT(pythoncom.VT_DISPATCH, None))
        try:
            groups = com(created_definition, "SelectionGetGroups")
            readback["groups"] = len(groups) if groups else 0
            if groups:
                for key in ("TabLength", "TabThickness", "SlotClearance",
                            "TabHeightType", "TabHeightValue", "SpacingType",
                            "SpacingNumberOfInstances", "TabEdgesType"):
                    try:
                        readback[key] = com(groups[0], key)
                    except Exception:
                        readback[key] = None
        finally:
            com(created_definition, "ReleaseSelectionAccess")
    except Exception as read_error:
        logger.warning(f"Tab and Slot readback failed: {read_error}")
        readback = {"error": str(read_error)}

    return sw._result(
        True,
        f"Created '{name}': tab on {tab_before['name']} and slot on "
        f"{slot_before['name']}.",
        data={
            "feature": name,
            "feature_type": feature_type,
            "tab_edge_index": tab_edge_index,
            "tab_edge_body": tab_edge["body"],
            "slot_face_index": slot_face_index,
            "slot_face_body": slot_body_name,
            "bodies_before": [round(item["volume_mm3"], 4) for item in before],
            "bodies_after": [round(item["volume_mm3"], 4) for item in after],
            "body_names_after": [item["name"] for item in after],
            "faces_before": [item["faces"] for item in before],
            "faces_after": [item["faces"] for item in after],
            "gained_mm3": round(gained, 4),
            "removed_mm3": round(removed, 4),
            "tab_body": {"name": tab_before["name"],
                         "before_mm3": round(tab_before["volume_mm3"], 4),
                         "after_mm3": round(tab_after["volume_mm3"], 4),
                         "faces_before": tab_before["faces"],
                         "faces_after": tab_after["faces"]},
            "slot_body": {"name": slot_before["name"],
                          "before_mm3": round(slot_before["volume_mm3"], 4),
                          "after_mm3": round(slot_after["volume_mm3"], 4),
                          "faces_before": slot_before["faces"],
                          "faces_after": slot_after["faces"]},
            "tab_length_mm": tab_length_mm,
            "tab_height_mm": tab_height_mm,
            "slot_clearance_mm": slot_clearance_mm,
            "spacing": spacing,
            "instances": instances if spacing == "equal" else 1,
            "edge_treatment": edge_treatment,
            "definition_readback": readback,
        },
    )


#: swInsertEdgeFlangeOptions_e bits used by create_edge_flange.
EDGE_FLANGE_USE_DEFAULT_RADIUS = 1
EDGE_FLANGE_USE_DEFAULT_RELIEF = 128

#: swFlangePositionTypes_e. Only bend-outside builds a flange through the API in
#: this build: material-inside, material-outside, bend-centerline, bend-sharp and
#: bend-tangent were probed on a 100 x 50 x 1 plate and every one returned no
#: feature, while bend-outside added 2135.6 mm3 (see docs/api-findings.md).
EDGE_FLANGE_POSITION_BEND_OUTSIDE = 3

#: swSheetMetalReliefTypes_e. Uses the sheet's own default relief, which is what
#: ProbeView's hand-made flange carries.
EDGE_FLANGE_RELIEF_NONE = 4

#: swFlangeDimTypes_e: measure the flange to the inner virtual sharp.
EDGE_FLANGE_SHARP_INNER = 2

#: Feature types SolidWorks has reported for an edge flange.
EDGE_FLANGE_FEATURE_TYPES = ("EdgeFlange",)


def _dispatch_array(items):
    """A VARIANT array of IDispatch, which is how these calls take selections."""
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(items))


def _top_level_edge(document, edge_index):
    """The IEdge at the given list_body_edges index, plus its body name."""
    edges = part_edges(document)
    if edge_index >= len(edges):
        return None, None, len(edges)
    return edges[edge_index]["edge"], edges[edge_index]["body"], len(edges)


def _select_edge(document, edge):
    """Select one edge on its own, the way the sample does before the sketch."""
    empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    com(document, "ClearSelection2", True)
    return bool(com(edge, "Select4", False, empty))


def _write_flange_profile(document, sketch, edge, length_m):
    """Close the bend line with three lines, giving a rectangular profile.

    SolidWorks stores exactly this shape (a rectangle) in the profile sketch of
    a flange made in the user interface, so the flange grows one length past the
    bend edge.
    """
    com(document, "ClearSelection2", True)
    empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    com(edge, "Select4", False, empty)
    com(com(document, "SketchManager"), "SketchUseEdge", False)
    segments = com(sketch, "GetSketchSegments") or []
    if not segments:
        return False
    line = segments[0]
    start = com(line, "GetStartPoint2")
    end = com(line, "GetEndPoint2")
    start_x, start_y = float(com(start, "X")), float(com(start, "Y"))
    end_x, end_y = float(com(end, "X")), float(com(end, "Y"))
    # Add straight to the database: inference would try to merge the new lines
    # into the bend line and change the profile.
    com(document, "SetAddToDB", True)
    com(document, "SetDisplayWhenAdded", False)
    try:
        com(document, "CreateLine2", start_x, start_y, 0.0,
            start_x, start_y + length_m, 0.0)
        com(document, "CreateLine2", start_x, start_y + length_m, 0.0,
            end_x, end_y + length_m, 0.0)
        com(document, "CreateLine2", end_x, end_y + length_m, 0.0,
            end_x, end_y, 0.0)
    finally:
        com(document, "SetDisplayWhenAdded", True)
        com(document, "SetAddToDB", False)
    return True


@tool(
    name="create_edge_flange",
    description=(
        "Add an edge flange to an existing sheet-metal body: the flange grows "
        "from one straight edge of the sheet, over a bend, for the given length "
        "at the given angle. Use the edge index from list_body_edges; the edge "
        "must belong to a sheet-metal body, because the flange bends the sheet "
        "rather than adding a separate solid. Success is only reported when the "
        "sheet gains the flange's material and the face count grows. Modifies "
        "the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "edge_index": {
                "type": "integer", "minimum": 0,
                "description": "Bend-line edge index from list_body_edges",
            },
            "length_mm": {
                "type": "number", "exclusiveMinimum": 0,
                "description": "Flange length past the bend line",
            },
            "angle_deg": {
                "type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180,
                "default": 90.0,
                "description": "Bend angle between the sheet and the flange",
            },
            "bend_radius_mm": {
                "type": "number", "exclusiveMinimum": 0,
                "description": ("Inside bend radius; omit to use the sheet's own "
                                "default radius"),
            },
        },
        "required": ["edge_index", "length_mm"],
    },
    operation_class=OperationClass.MUTATE,
)
def create_edge_flange(sw, edge_index, length_mm, angle_deg=90.0,
                       bend_radius_mm=None) -> dict:
    """Grow an edge flange from one straight edge of a sheet-metal body."""
    if (isinstance(edge_index, bool) or not isinstance(edge_index, int)
            or edge_index < 0):
        return sw._result(False, "edge_index must be a non-negative integer.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not _positive(length_mm):
        return sw._result(False, "length_mm must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not _positive(angle_deg) or angle_deg >= 180:
        return sw._result(False, "angle_deg must be between 0 and 180.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if bend_radius_mm is not None and not _positive(bend_radius_mm):
        return sw._result(False, "bend_radius_mm must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    if _find_sheet_metal_feature(doc) is None:
        return sw._result(
            False,
            "The active part has no sheet-metal feature; create a base flange "
            "first, because an edge flange bends an existing sheet.",
            SwErrors.swFeatureError, {"code": "NO_SHEET_METAL"})

    try:
        edge, body_name, edge_count = _top_level_edge(doc, edge_index)
    except Exception as read_error:
        return sw._result(False, f"Could not read body edges: {read_error}",
                          SwErrors.swUnknownError)
    if edge is None:
        return sw._result(
            False,
            f"Edge index {edge_index} is out of range for {edge_count} edges; "
            "re-run list_body_edges.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    before = _body_volumes(doc)
    angle_rad = math.radians(angle_deg)
    length_m = length_mm / 1000.0

    try:
        if not _select_edge(doc, edge):
            return sw._result(
                False,
                f"Edge {edge_index} could not be selected for the flange.",
                SwErrors.swFeatureError, {"code": "SELECTION_FAILED"})
        sketch_feature = com(doc, "InsertSketchForEdgeFlange", edge, angle_rad,
                             False)
        if sketch_feature is None:
            return sw._result(
                False,
                f"SolidWorks built no flange profile sketch for edge "
                f"{edge_index}; the edge may not be a bendable edge of the "
                "sheet.",
                SwErrors.swFeatureError, {"code": "SKETCH_CREATE_FAILED"})
        com(sketch_feature, "Select2", False, 0)
        com(doc, "EditSketch")
        sketch = com(doc, "GetActiveSketch2")
        if sketch is None:
            return sw._result(False, "The flange profile sketch did not open.",
                              SwErrors.swSketchError)
        if not _write_flange_profile(doc, sketch, edge, length_m):
            com(doc, "InsertSketch2", True)
            return sw._result(
                False,
                "The flange profile sketch has no bend line to build on.",
                SwErrors.swSketchError, {"code": "EMPTY_PROFILE"})
        com(doc, "InsertSketch2", True)
        profile = com(sketch_feature, "GetSpecificFeature2")
    except Exception as profile_error:
        logger.error(f"Edge flange profile failed: {profile_error}")
        return sw._result(
            False, f"Could not build the flange profile: {profile_error}",
            SwErrors.swFeatureError)

    options = EDGE_FLANGE_USE_DEFAULT_RELIEF
    radius_m = 0.0
    if bend_radius_mm is None:
        # swInsertEdgeFlangeUseDefaultRadius makes SolidWorks take the radius
        # from the sheet-metal feature, so the argument is not read.
        options |= EDGE_FLANGE_USE_DEFAULT_RADIUS
    else:
        radius_m = bend_radius_mm / 1000.0

    empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    try:
        feature = com(
            com(doc, "FeatureManager"), "InsertSheetMetalEdgeFlange2",
            _dispatch_array([edge]), _dispatch_array([profile]),
            options,                 # UseDefaultRadius / UseDefaultRelief
            angle_rad,               # BendAngle
            radius_m,                # BendRadius
            EDGE_FLANGE_POSITION_BEND_OUTSIDE,
            length_m,                # FlangeOffsetDist
            EDGE_FLANGE_RELIEF_NONE,
            0.0, 0.0, 0.0,           # relief ratio / width / depth
            EDGE_FLANGE_SHARP_INNER,
            empty_callout,           # parent bend allowance
        )
    except Exception as create_error:
        logger.error(f"InsertSheetMetalEdgeFlange2 failed: {create_error}")
        return sw._result(False, f"Could not create the edge flange: "
                                 f"{create_error}", SwErrors.swFeatureError)

    if feature is None:
        return sw._result(
            False,
            "SolidWorks created no edge flange. The flange grows from one "
            "straight edge of the sheet; a curved edge, an edge already used by "
            "another flange, or several edges at once does not build.",
            SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"})

    name = str(com(feature, "Name"))
    feature_type = str(com(feature, "GetTypeName2"))
    if feature_type not in EDGE_FLANGE_FEATURE_TYPES:
        return sw._result(
            False, f"Feature '{name}' is a {feature_type}, not an edge flange.",
            SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"})

    com(doc, "ForceRebuild3", False)
    if _find_feature(doc, name) is None:
        return sw._result(False, f"Edge flange '{name}' did not persist.",
                          SwErrors.swFeatureError,
                          {"code": "FEATURE_NOT_PERSISTED"})

    after = _body_volumes(doc)
    gained_mm3 = sum(item["volume_mm3"] for item in after) - \
        sum(item["volume_mm3"] for item in before)
    faces_before = sum(item["faces"] for item in before)
    faces_after = sum(item["faces"] for item in after)
    if gained_mm3 <= 1e-6 or faces_after <= faces_before:
        return sw._result(
            False,
            "The feature was created but the sheet did not gain the flange: "
            "neither its volume nor its face count grew.",
            SwErrors.swFeatureError, {"code": "NO_GEOMETRY_CHANGE"})

    return sw._result(
        True,
        f"Created '{name}' on edge {edge_index}, {length_mm} mm long at "
        f"{angle_deg} deg.",
        data={
            "feature": name,
            "feature_type": feature_type,
            "edge_index": edge_index,
            "edge_body": body_name,
            "length_mm": length_mm,
            "angle_deg": angle_deg,
            "bend_radius_mm": (bend_radius_mm if bend_radius_mm is not None
                               else _default_bend_radius_mm(doc)),
            "uses_default_bend_radius": bend_radius_mm is None,
            "options": options,
            "gained_mm3": round(gained_mm3, 4),
            "volume_before_mm3": round(sum(item["volume_mm3"] for item in before), 4),
            "volume_after_mm3": round(sum(item["volume_mm3"] for item in after), 4),
            "faces_before": faces_before,
            "faces_after": faces_after,
            "bodies_before": len(before),
            "bodies_after": len(after),
        },
    )


def _default_bend_radius_mm(doc):
    """The sheet-metal feature's own bend radius, read for the report."""
    try:
        feature = _find_sheet_metal_feature(doc)
        data = com(feature, "GetDefinition")
        return round(float(com(data, "BendRadius")) * 1000.0, 4)
    except Exception:
        return None


@tool(
    name="create_miter_flange",
    description=(
        "Create a miter flange on one straight sheet-metal edge using an "
        "existing, CLOSED, four-segment open profile sketch. Draw the profile "
        "on a plane normal to the edge, starting exactly at the edge, and pass "
        "its feature name together with an edge index from list_body_edges. "
        "The profile controls the bends and lengths; no flange length is "
        "inferred. Only the four-segment profile/default bend settings have "
        "been live-verified. Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "edge_index": {"type": "integer", "minimum": 0,
                           "description": "Edge index from list_body_edges"},
            "sketch_name": {"type": "string", "minLength": 1,
                            "description": "Feature name of the closed profile sketch"},
        },
        "required": ["edge_index", "sketch_name"],
    },
    operation_class=OperationClass.MUTATE,
)
def create_miter_flange(sw, edge_index, sketch_name) -> dict:
    """Select both edge and real profile sketch for InsertSheetMetalMiterFlange.

    A zero-length sketch produced by a failed coordinate transform is silently
    discarded by SolidWorks; checking the stored segments before insertion is
    essential. The older IModelDoc2 variant does not build this fixture.
    """
    if (isinstance(edge_index, bool) or not isinstance(edge_index, int)
            or edge_index < 0 or not isinstance(sketch_name, str)
            or not sketch_name.strip()):
        return sw._result(False, "Provide a non-negative edge_index and a "
                          "non-empty sketch_name.", SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED"})

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    if _find_sheet_metal_feature(doc) is None:
        return sw._result(False, "Part has no sheet-metal feature.",
                          SwErrors.swFeatureError, {"code": "NO_SHEET_METAL"})
    if com(doc, "GetActiveSketch2") is not None:
        return sw._result(False, "Close the profile sketch before inserting "
                          "the miter flange.", SwErrors.swSketchError,
                          {"code": "SKETCH_STILL_OPEN"})

    sketch_feature = _find_feature(doc, sketch_name)
    if (sketch_feature is None
            or str(com(sketch_feature, "GetTypeName2")) != "ProfileFeature"):
        return sw._result(False, f"'{sketch_name}' is not a profile sketch.",
                          SwErrors.swInvalidInput, {"code": "SKETCH_NOT_FOUND"})
    sketch = com(sketch_feature, "GetSpecificFeature2")
    segments = com(sketch, "GetSketchSegments") or []
    # The one verified API workflow is an open profile with four real lines;
    # do not advertise other profiles until each is proven on a live sheet.
    if len(segments) != 4:
        return sw._result(False, "The verified miter profile needs four "
                          "nonzero straight segments.", SwErrors.swSketchError,
                          {"code": "INVALID_PROFILE"})
    try:
        for segment in segments:
            start = com(segment, "GetStartPoint2")
            end = com(segment, "GetEndPoint2")
            if (math.hypot(float(com(start, "X")) - float(com(end, "X")),
                           float(com(start, "Y")) - float(com(end, "Y")))
                    <= 1e-9):
                raise ValueError("zero-length sketch line")
    except (AttributeError, TypeError, ValueError) as profile_error:
        return sw._result(False, f"Invalid miter profile: {profile_error}",
                          SwErrors.swSketchError, {"code": "INVALID_PROFILE"})

    try:
        edge, body_name, edge_count = _top_level_edge(doc, edge_index)
    except Exception as read_error:
        return sw._result(False, f"Could not read body edges: {read_error}",
                          SwErrors.swUnknownError)
    if edge is None:
        return sw._result(False, f"Edge {edge_index} is out of range for "
                          f"{edge_count} edges; re-run list_body_edges.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    before = _body_volumes(doc)
    empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    try:
        com(doc, "ClearSelection2", True)
        if not com(edge, "Select4", False, empty):
            return sw._result(False, "Could not select the edge.",
                              SwErrors.swFeatureError, {"code": "SELECTION_FAILED"})
        if not com(sketch_feature, "Select2", True, 0):
            return sw._result(False, "Could not append the profile sketch "
                              "to the edge selection.", SwErrors.swFeatureError,
                              {"code": "SELECTION_FAILED"})
        # The 14-argument IFeatureManager method needs BOTH selections. The
        # sketch defines the flange shape; the edge defines where it starts.
        feature = com(
            com(doc, "FeatureManager"), "InsertSheetMetalMiterFlange",
            True, 0.001, 0.00025, True, False, 0.05,
            0.0, 0.0, 1, False, 1, 0.0, 0.0, empty,
        )
    except Exception as create_error:
        logger.error(f"InsertSheetMetalMiterFlange failed: {create_error}")
        return sw._result(False, f"Could not create the miter flange: "
                          f"{create_error}", SwErrors.swFeatureError)
    finally:
        com(doc, "ClearSelection2", True)

    if feature is None:
        return sw._result(False, "SolidWorks created no miter flange from "
                          "this sketch and edge.", SwErrors.swFeatureError,
                          {"code": "FEATURE_CREATE_FAILED"})
    name = str(com(feature, "Name"))
    feature_type = str(com(feature, "GetTypeName2"))
    if feature_type != "SMMiteredFlange":
        return sw._result(False, f"'{name}' is not a miter flange.",
                          SwErrors.swFeatureError,
                          {"code": "FEATURE_CREATE_FAILED"})
    com(doc, "ForceRebuild3", False)
    if _find_feature(doc, name) is None:
        return sw._result(False, f"Miter flange '{name}' did not persist.",
                          SwErrors.swFeatureError,
                          {"code": "FEATURE_NOT_PERSISTED"})
    after = _body_volumes(doc)
    volume_before = sum(item["volume_mm3"] for item in before)
    volume_after = sum(item["volume_mm3"] for item in after)
    faces_before = sum(item["faces"] for item in before)
    faces_after = sum(item["faces"] for item in after)
    if volume_after - volume_before <= 1e-6 or faces_after <= faces_before:
        return sw._result(False, "Miter flange did not add sheet material "
                          "and faces.", SwErrors.swFeatureError,
                          {"code": "NO_GEOMETRY_CHANGE"})
    return sw._result(
        True, f"Created '{name}' using {sketch_name} and edge {edge_index}.",
        data={
            "feature": name, "feature_type": feature_type,
            "sketch": sketch_name, "edge_index": edge_index,
            "edge_body": body_name, "profile_segments": len(segments),
            "gained_mm3": round(volume_after - volume_before, 4),
            "volume_before_mm3": round(volume_before, 4),
            "volume_after_mm3": round(volume_after, 4),
            "faces_before": faces_before, "faces_after": faces_after,
            "bodies_before": len(before), "bodies_after": len(after),
        },
    )
