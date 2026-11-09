"""
Weldment tools (part C): list library profiles, create structural members.
"""

import logging
import math
import os

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .inspection import part_edges

logger = logging.getLogger("SolidWorksMCP")

SW_FILE_LOCATIONS_WELDMENT_PROFILES = 29


@tool(
    name="list_weldment_profiles",
    description=(
        "List available weldment profile (.sldlfp) files under the "
        "SolidWorks weldment profiles library, grouped by folder. "
        "Use the returned path with create_structural_member. Read-only."
    ),
    schema={
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Case-insensitive substring to filter by filename. Optional."
            }
        },
        "required": []
    },
    operation_class=OperationClass.READ,
)
def list_weldment_profiles(sw, filter: str = "") -> dict:
    """List .sldlfp profile files under the configured weldment profiles library."""
    doc, err = sw.get_active_doc()
    if err:
        return err

    root = com(sw.app, "GetUserPreferenceStringValue",
               SW_FILE_LOCATIONS_WELDMENT_PROFILES)
    if not root or not os.path.isdir(root):
        return sw._result(False, f"Weldment profiles folder not found: {root}",
                          SwErrors.swFileNotFoundError)

    filter_lower = filter.lower()
    profiles = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".sldlfp"):
                continue
            if name.startswith("~$"):
                continue
            if filter_lower and filter_lower not in name.lower():
                continue
            full_path = os.path.join(dirpath, name)
            profiles.append({
                "name": name,
                "folder": os.path.relpath(dirpath, root),
                "path": full_path
            })

    profiles.sort(key=lambda p: (p["folder"], p["name"]))

    return sw._result(
        True,
        f"Found {len(profiles)} weldment profiles under {root}.",
        data={"root": root, "profiles": profiles}
    )


def _find_feature(doc, name: str):
    feat = com(doc, "FirstFeature")
    while feat is not None:
        if com(feat, "Name") == name:
            return feat
        feat = com(feat, "GetNextFeature")
    return None


def _has_weldment_feature(doc) -> bool:
    feat = com(doc, "FirstFeature")
    while feat is not None:
        if com(feat, "GetTypeName2") == "WeldmentFeature":
            return True
        feat = com(feat, "GetNextFeature")
    return False


@tool(
    name="create_structural_member",
    description=(
        "Weldment structural member from a named sketch's segments and a library profile; connected segments share a group (optional miters). Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "sketch_name": {
                "type": "string"
            },
            "profile_path": {
                "type": "string",
                "description": "Path to a .sldlfp, from list_weldment_profiles"
            },
            "connected_segments_option": {
                "type": "integer",
                "description": "0=None, 1=Apply, 2=Apply for all (default 1)",
                "default": 1
            },
            "allow_protrusion": {
                "type": "boolean",
                "default": True
            },
            "separate_groups": {
                "type": "boolean",
                "description": "One group per segment (default false)",
                "default": False
            },
            "group_mode": {
                "type": "string", "enum": ["auto", "all", "per_segment"],
                "description": "auto (default) | all (one group) | per_segment",
                "default": "auto"
            },
            "corner_type": {
                "type": "string", "enum": ["none", "miter"],
                "description": "Corner of connected segments; miter or none (default)",
                "default": "none"
            },
            "segment_indices": {
                "type": "array", "items": {"type": "integer", "minimum": 0},
                "description": "Omit for all segments"
            }
        },
        "required": ["sketch_name", "profile_path"]
    },
    operation_class=OperationClass.MUTATE,
)
def create_structural_member(sw, sketch_name: str, profile_path: str,
                              connected_segments_option: int = 1,
                              allow_protrusion: bool = True,
                              separate_groups: bool = False,
                              corner_type: str = "none",
                              group_mode: str = "auto",
                              segment_indices=None) -> dict:
    """Create a structural member from a sketch and a library profile."""
    if (not isinstance(separate_groups, bool) or corner_type not in ("none", "miter")
            or group_mode not in ("auto", "all", "per_segment")
            or (separate_groups and group_mode == "all")
            or (separate_groups and corner_type != "none")):
        return sw._result(False,
                          "Miter corners require one group; separate_groups "
                          "conflicts with group_mode='all'.",
                          SwErrors.swInvalidInput)
    if segment_indices is not None:
        if (not isinstance(segment_indices, (list, tuple))
                or not segment_indices
                or any(isinstance(index, bool) or not isinstance(index, int)
                       or index < 0 for index in segment_indices)
                or len(set(segment_indices)) != len(segment_indices)):
            return sw._result(False, "segment_indices must be distinct non-negative integers.",
                              SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err

    if not os.path.isfile(profile_path):
        return sw._result(False, f"Profile file not found: {profile_path}",
                          SwErrors.swFileNotFoundError)

    feat = _find_feature(doc, sketch_name)
    if feat is None:
        return sw._result(False, f"Sketch not found: {sketch_name}",
                          SwErrors.swSketchError)
    if com(feat, "GetTypeName2") not in ("ProfileFeature", "3DProfileFeature"):
        return sw._result(False, f"Feature '{sketch_name}' is not a sketch.",
                          SwErrors.swSketchError)

    try:
        sk = com(feat, "GetSpecificFeature2")
        segs = com(sk, "GetSketchSegments")
    except Exception as e:
        logger.error(f"GetSketchSegments failed: {e}")
        return sw._result(False, f"Could not read sketch segments: {e}",
                          SwErrors.swSketchError)

    if not segs:
        return sw._result(False, f"Sketch '{sketch_name}' has no segments.",
                          SwErrors.swSketchError)

    if segment_indices is not None:
        chosen = []
        for index in segment_indices:
            if index >= len(segs):
                return sw._result(
                    False,
                    f"Segment index {index} is out of range for {len(segs)} segments.",
                    SwErrors.swInvalidInput)
            chosen.append(segs[index])
        segs = chosen

    fm = com(doc, "FeatureManager")

    try:
        if not _has_weldment_feature(doc):
            com(fm, "InsertWeldmentFeature")

        if group_mode == "all":
            segment_sets = [list(segs)]
        elif group_mode == "per_segment" or separate_groups:
            segment_sets = [[segment] for segment in segs]
        else:
            segment_sets = [list(segs)]

        groups = []
        for segment_group in segment_sets:
            grp = com(fm, "CreateStructuralMemberGroup")
            grp.Segments = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
                list(segment_group))
            if corner_type == "miter":
                grp.ApplyCornerTreatment = True
                grp.CornerTreatmentType = 1  # swEndConditionMiter
            groups.append(grp)
        groups_var = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, groups)

        new_feat = com(fm, "InsertStructuralWeldment5", profile_path,
                       connected_segments_option, allow_protrusion,
                       groups_var, "")
    except Exception as e:
        logger.error(f"InsertStructuralWeldment5 failed: {e}")
        return sw._result(False, f"Could not create structural member: {e}",
                          SwErrors.swFeatureError)

    if not new_feat:
        return sw._result(False, "InsertStructuralWeldment5 returned no feature.",
                          SwErrors.swFeatureError)

    return sw._result(
        True,
        f"Created structural member from sketch '{sketch_name}'.",
        data={"feature": com(new_feat, "Name")}
    )


@tool(
    name="trim_weldment_members",
    description=(
        "Miter-trim one solid weldment body against another in the active part, "
        "with an explicit zero weld gap. Use body names from list_planar_faces."
    ),
    schema={
        "type": "object",
        "properties": {
            "body_to_trim": {"type": "string", "minLength": 1,
                             "description": "Name of the solid member body to trim"},
            "trimming_body": {"type": "string", "minLength": 1,
                              "description": "Name of the solid body used as boundary"},
        },
        "required": ["body_to_trim", "trimming_body"],
    },
    operation_class=OperationClass.MUTATE,
)
def trim_weldment_members(sw, body_to_trim: str, trimming_body: str) -> dict:
    """Miter a named solid body against another named solid body."""
    if (not isinstance(body_to_trim, str) or not body_to_trim.strip()
            or not isinstance(trimming_body, str) or not trimming_body.strip()
            or body_to_trim == trimming_body):
        return sw._result(False, "Supply two distinct solid-body names.",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    if not _has_weldment_feature(doc):
        return sw._result(False, "Active part has no weldment feature.",
                          SwErrors.swFeatureError)

    try:
        bodies = com(doc, "GetBodies2", 0, False) or []
        by_name = {}
        for body in bodies:
            by_name.setdefault(com(body, "Name"), []).append(body)
    except Exception as exc:
        return sw._result(False, f"Could not read solid bodies: {exc}",
                          SwErrors.swFeatureError)
    if len(by_name.get(body_to_trim, [])) != 1 or len(by_name.get(trimming_body, [])) != 1:
        return sw._result(False, "Solid-body name not found or ambiguous.",
                          SwErrors.swInvalidInput)

    try:
        com(doc, "ClearSelection2", True)
        array_type = pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH
        trimmed = win32com.client.VARIANT(array_type, by_name[body_to_trim])
        boundary = win32com.client.VARIANT(array_type, by_name[trimming_body])
        # SW 2025 help: swEndConditionMiter=1. Option flags 1|2|4|8
        # match the official Insert Weldment Features example. WeldGap=8
        # makes the supplied gap of 0 m explicit, independent of UI defaults.
        feature = com(com(doc, "FeatureManager"),
                      "InsertWeldmentTrimFeature2", 1, 1 | 2 | 4 | 8,
                      0.0, trimmed, boundary)
    except Exception as exc:
        logger.error("InsertWeldmentTrimFeature2 failed: %s", exc)
        return sw._result(False, f"Could not trim weldment body: {exc}",
                          SwErrors.swFeatureError)
    finally:
        try:
            com(doc, "ClearSelection2", True)
        except Exception:
            logger.warning("Could not clear selection after weldment trim")

    if not feature:
        return sw._result(False, "Weldment trim created no feature.",
                          SwErrors.swFeatureError)
    try:
        com(doc, "ForceRebuild3", False)
        created_name = com(feature, "Name")
        found = _find_feature(doc, created_name)
        if found is None or com(found, "GetTypeName2") != "WeldCornerFeat":
            return sw._result(False, "Weldment trim did not persist in the feature tree.",
                              SwErrors.swFeatureError)
    except Exception as exc:
        return sw._result(False, f"Could not verify weldment trim: {exc}",
                          SwErrors.swFeatureError)
    return sw._result(True, "Created weldment miter trim.",
                      data={"feature": created_name,
                            "body_to_trim": body_to_trim,
                            "trimming_body": trimming_body})


#: Feature types SolidWorks has reported for an end cap across releases.
END_CAP_FEATURE_TYPES = ("EndCap", "EndCapFeature", "EndCapFeat")

#: swEndCapThicknessDirection_e, only reachable through
#: InsertEndCapFeature3. The installed VBA end-cap example documents the
#: values: 0 = outward, 1 = inward, 2 = inset (recessed by the inset distance).
END_CAP_DIRECTIONS = {"outward": 0, "inward": 1, "inset": 2}

#: A face counts as normal to an axis when the cosine is at least this close.
_END_FACE_ALIGNMENT = 0.999


def _body_volume_mm3(body) -> float:
    """Solid volume of one body in cubic millimetres."""
    return float(com(body, "GetMassProperties", 0.0)[3]) * 1e9


def _total_volume_mm3(doc) -> float:
    """Solid volume of every body in the document, in cubic millimetres.

    End caps become their own bodies (``End cap1[1]`` ...) and the inward
    direction also shortens the member, so only the document total proves that
    material was added.
    """
    return sum(_body_volume_mm3(body)
               for body in com(doc, "GetBodies2", 0, False) or [])


def _planar_end_faces(body):
    """Planar faces normal to the body's longest bounding-box axis.

    Those are the cut ends of a straight structural member. The list is
    deterministic (minimum extreme first, then maximum extreme) so callers and
    tests always see the same face order.
    """
    box = [float(value) for value in com(body, "GetBodyBox")]
    spans = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
    axis = max(range(3), key=lambda index: spans[index])
    ends = []
    for face in com(body, "GetFaces") or []:
        if not com(com(face, "GetSurface"), "IsPlane"):
            continue
        normal = [float(value) for value in com(face, "Normal")]
        if abs(normal[axis]) < _END_FACE_ALIGNMENT:
            continue
        face_box = [float(value) for value in com(face, "GetBox")]
        ends.append((face_box[axis + 3], face))
    ends.sort(key=lambda item: item[0])
    return [face for _extreme, face in ends]


@tool(
    name="create_weldment_end_cap",
    description=(
        "Cap the cut end of a hollow weldment member (EndCap). Auto-detects ends unless face_indices are given. Reports volume before and after. Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "body_name": {
                "type": "string", "minLength": 1
            },
            "face_indices": {
                "type": "array", "items": {"type": "integer", "minimum": 0},
                "description": "From list_planar_faces; omit to auto-detect"
            },
            "depth_mm": {
                "type": "number", "minimum": 0.001, "default": 5.0
            },
            "direction": {
                "type": "string", "enum": ["inward", "outward", "inset"],
                "default": "inward",
                "description": "inward (flush, default), outward (protruding) or inset"
            },
            "inset_mm": {
                "type": "number", "minimum": 0.0, "default": 2.0
            },
            "chamfer": {
                "type": "boolean", "default": False
            },
            "chamfer_mm": {
                "type": "number", "minimum": 0.0, "default": 0.0
            },
            "corner_treatment": {
                "type": "boolean", "default": False
            },
            "reverse": {
                "type": "boolean", "default": False
            },
            "given_offset": {
                "type": "boolean", "default": False,
                "description": "true: offset_value_mm; false: wall_thickness_ratio"
            },
            "offset_value_mm": {
                "type": "number", "minimum": 0.0, "default": 0.0
            },
            "wall_thickness_ratio": {
                "type": "number", "minimum": 0.01, "default": 0.6
            }
        },
        "required": ["body_name"]
    },
    operation_class=OperationClass.MUTATE,
)
def create_weldment_end_cap(sw, body_name, face_indices=None, depth_mm=5.0,
                            direction="inward", inset_mm=2.0, chamfer=False,
                            chamfer_mm=0.0, corner_treatment=False,
                            reverse=False, given_offset=False,
                            offset_value_mm=0.0, wall_thickness_ratio=0.6):
    """Cap the cut ends of one named solid weldment body."""
    if not isinstance(body_name, str) or not body_name.strip():
        return sw._result(False, "body_name must be a non-empty string.",
                          SwErrors.swInvalidInput)
    if direction not in END_CAP_DIRECTIONS:
        return sw._result(False, "direction must be inward, outward or inset.",
                          SwErrors.swInvalidInput)
    for label, value in (("chamfer", chamfer), ("corner_treatment", corner_treatment),
                         ("reverse", reverse), ("given_offset", given_offset)):
        if not isinstance(value, bool):
            return sw._result(False, f"{label} must be a boolean.",
                              SwErrors.swInvalidInput)
    numbers = {"depth_mm": depth_mm, "inset_mm": inset_mm,
               "chamfer_mm": chamfer_mm, "offset_value_mm": offset_value_mm,
               "wall_thickness_ratio": wall_thickness_ratio}
    for label, value in numbers.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return sw._result(False, f"{label} must be a number.",
                              SwErrors.swInvalidInput)
    if depth_mm <= 0 or inset_mm < 0 or chamfer_mm < 0 or offset_value_mm < 0:
        return sw._result(False, "depth_mm must be positive; offsets non-negative.",
                          SwErrors.swInvalidInput)
    if face_indices is not None:
        if (not isinstance(face_indices, (list, tuple)) or not face_indices
                or any(isinstance(index, bool) or not isinstance(index, int)
                       or index < 0 for index in face_indices)
                or len(set(face_indices)) != len(face_indices)):
            return sw._result(False, "face_indices must be distinct non-negative integers.",
                              SwErrors.swInvalidInput)

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    if not _has_weldment_feature(doc):
        return sw._result(False, "Active part has no weldment feature.",
                          SwErrors.swFeatureError)

    lookup = _body_lookup(doc)
    if len(lookup.get(body_name, [])) != 1:
        return sw._result(False, "Solid-body name not found or ambiguous.",
                          SwErrors.swInvalidInput)
    body = lookup[body_name][0]

    try:
        if face_indices is None:
            faces = _planar_end_faces(body)
            auto_detected = True
        else:
            faces = []
            auto_detected = False
            for index in face_indices:
                face, error = _planar_face_of_body(doc, body_name, index)
                if error:
                    return sw._result(False, error, SwErrors.swInvalidInput)
                faces.append(face)
    except Exception as exc:
        return sw._result(False, f"Could not resolve end faces: {exc}",
                          SwErrors.swFeatureError)
    if not faces:
        return sw._result(
            False,
            "No planar end face found; pass face_indices from list_planar_faces.",
            SwErrors.swInvalidInput)

    try:
        before_names = set(lookup)
        before = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not read document volume: {exc}",
                          SwErrors.swFeatureError)

    feature = None
    try:
        com(doc, "ClearSelection2", True)
        selection_manager = com(doc, "SelectionManager")
        for position, face in enumerate(faces):
            select_data = com(selection_manager, "CreateSelectData")
            select_data.Mark = 1
            if not com(face, "Select4", position > 0, select_data):
                return sw._result(False, f"Could not select end face {position}.",
                                  SwErrors.swSelectionError)
        # InsertEndCapFeature3 takes the faces from the current selection and is
        # the only variant that exposes the thickness direction; the 2 variant
        # always caps outward.
        feature = com(com(doc, "FeatureManager"), "InsertEndCapFeature3",
                      depth_mm / 1000.0, given_offset, chamfer,
                      offset_value_mm / 1000.0, wall_thickness_ratio,
                      chamfer_mm / 1000.0, corner_treatment, inset_mm / 1000.0,
                      reverse, END_CAP_DIRECTIONS[direction])
    except Exception as exc:
        logger.error("InsertEndCapFeature3 failed: %s", exc)
        return sw._result(False, f"Could not create end cap: {exc}",
                          SwErrors.swFeatureError)
    finally:
        try:
            com(doc, "ClearSelection2", True)
        except Exception:
            logger.warning("Could not clear selection after end cap")

    if not feature:
        return sw._result(False, "End cap created no feature.",
                          SwErrors.swFeatureError)

    try:
        name = str(com(feature, "Name"))
        feature_type = str(com(feature, "GetTypeName2"))
        com(doc, "ForceRebuild3", False)
        found = _find_feature(doc, name)
        if found is None:
            return sw._result(False, "End cap did not persist in the feature tree.",
                              SwErrors.swFeatureError)
        # The pre-feature body proxies are invalidated by the rebuild, so the
        # volumes have to be read from freshly resolved bodies.
        after_names = set(_body_lookup(doc))
        after = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not verify end cap: {exc}",
                          SwErrors.swFeatureError)

    return sw._result(
        True,
        f"Created end cap '{name}' on {len(faces)} face(s) of {body_name}.",
        data={"feature": name, "feature_type": feature_type,
              "body_name": body_name, "face_count": len(faces),
              "auto_detected_faces": auto_detected, "direction": direction,
              "direction_value": END_CAP_DIRECTIONS[direction],
              "cap_bodies": sorted(after_names - before_names),
              "volume_before_mm3": round(before, 4),
              "volume_after_mm3": round(after, 4),
              "added_mm3": round(after - before, 4)})


#: swGussetThicknessType_e
GUSSET_DIRECTIONS = {"inner": 0, "both": 1, "outer": 2}

#: swGussetProfileLocationType_e
GUSSET_LOCATIONS = {"start": 0, "center": 1, "end": 2}

#: Feature types SolidWorks has reported for a weldment gusset.
GUSSET_FEATURE_TYPES = ("Gusset", "GussetFeature", "WeldGusset")


def _planar_face_by_index(doc, face_index):
    """Face at the global index list_planar_faces reports.

    Returns (face, body_name, error_message) and mirrors list_planar_faces:
    the counter runs over every face, planar or not, of the visible solid
    bodies.
    """
    index = 0
    for body in com(doc, "GetBodies2", 0, True) or []:
        for face in com(body, "GetFaces") or []:
            if index == face_index:
                if not com(com(face, "GetSurface"), "IsPlane"):
                    return None, None, "Face index is not a planar face."
                return face, str(com(body, "Name")), None
            index += 1
    return None, None, "Face index is out of range."


@tool(
    name="create_weldment_gusset",
    description=(
        "Gusset plate between two faces (list_planar_faces) of different solid members that meet at a real edge. Reports volume before and after. Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "face_a_index": {
                "type": "integer", "minimum": 0
            },
            "face_b_index": {
                "type": "integer", "minimum": 0
            },
            "depth_mm": {
                "type": "number", "minimum": 0.001, "default": 5.0
            },
            "direction": {
                "type": "string", "enum": ["both", "inner", "outer"],
                "default": "both"
            },
            "location": {
                "type": "string", "enum": ["center", "start", "end"],
                "default": "center"
            },
            "profile": {
                "type": "string", "enum": ["triangle", "polygon"],
                "default": "triangle"
            },
            "leg1_mm": {"type": "number", "minimum": 0.001, "default": 25.0},
            "leg2_mm": {"type": "number", "minimum": 0.001, "default": 25.0},
            "leg3_mm": {"type": "number", "minimum": 0.001, "default": 15.0},
            "leg4_mm": {"type": "number", "minimum": 0.001, "default": 15.0},
            "angle_deg": {
                "type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180,
                "default": 45.0
            },
            "use_length_dim": {
                "type": "boolean", "default": False
            },
            "offset": {
                "type": "boolean", "default": False
            },
            "offset_mm": {"type": "number", "minimum": 0.0, "default": 5.0},
            "reverse_dir": {"type": "boolean", "default": False},
            "reverse_face": {
                "type": "boolean", "default": False
            },
            "crv_index": {
                "type": "integer", "minimum": 0, "default": 0
            },
            "chamfer": {
                "type": "boolean", "default": False
            },
            "chamfer1_mm": {"type": "number", "minimum": 0.0, "default": 12.5},
            "chamfer2_mm": {"type": "number", "minimum": 0.0, "default": 12.5},
            "chamfer_angle_deg": {
                "type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 180,
                "default": 45.0
            },
            "use_length_dim_for_chamfer": {
                "type": "boolean", "default": True
            }
        },
        "required": ["face_a_index", "face_b_index"]
    },
    operation_class=OperationClass.MUTATE,
)
def create_weldment_gusset(sw, face_a_index, face_b_index, depth_mm=5.0,
                           direction="both", location="center",
                           profile="triangle", leg1_mm=25.0, leg2_mm=25.0,
                           angle_deg=45.0, use_length_dim=False, leg3_mm=15.0,
                           leg4_mm=15.0, offset=False, offset_mm=5.0,
                           reverse_dir=False, reverse_face=False, crv_index=0,
                           chamfer=False, chamfer1_mm=12.5,
                           chamfer2_mm=12.5, chamfer_angle_deg=45.0,
                           use_length_dim_for_chamfer=True):
    """Insert a weldment gusset between two supporting faces."""
    for label, index in (("face_a_index", face_a_index),
                         ("face_b_index", face_b_index)):
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            return sw._result(False, f"{label} must be a non-negative integer.",
                              SwErrors.swInvalidInput)
    if face_a_index == face_b_index:
        return sw._result(False, "The two supporting faces must differ.",
                          SwErrors.swInvalidInput)
    if (direction not in GUSSET_DIRECTIONS or location not in GUSSET_LOCATIONS
            or profile not in ("triangle", "polygon")):
        return sw._result(False, "Invalid direction, location or profile.",
                          SwErrors.swInvalidInput)
    for label, value in (("use_length_dim", use_length_dim),
                         ("offset", offset), ("reverse_dir", reverse_dir),
                         ("reverse_face", reverse_face), ("chamfer", chamfer),
                         ("use_length_dim_for_chamfer",
                          use_length_dim_for_chamfer)):
        if not isinstance(value, bool):
            return sw._result(False, f"{label} must be a boolean.",
                              SwErrors.swInvalidInput)
    if isinstance(crv_index, bool) or not isinstance(crv_index, int) or crv_index < 0:
        return sw._result(False, "crv_index must be a non-negative integer.",
                          SwErrors.swInvalidInput)
    numbers = {"depth_mm": depth_mm, "leg1_mm": leg1_mm, "leg2_mm": leg2_mm,
               "leg3_mm": leg3_mm, "leg4_mm": leg4_mm,
               "offset_mm": offset_mm, "chamfer1_mm": chamfer1_mm,
               "chamfer2_mm": chamfer2_mm, "angle_deg": angle_deg,
               "chamfer_angle_deg": chamfer_angle_deg}
    for label, value in numbers.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return sw._result(False, f"{label} must be a number.",
                              SwErrors.swInvalidInput)
    if (depth_mm <= 0 or leg1_mm <= 0 or leg2_mm <= 0 or leg3_mm <= 0
            or leg4_mm <= 0 or offset_mm < 0 or chamfer1_mm < 0
            or chamfer2_mm < 0):
        return sw._result(False, "Thickness and legs must be positive; "
                                 "offsets and chamfers non-negative.",
                          SwErrors.swInvalidInput)
    if not 0 < angle_deg < 180 or not 0 < chamfer_angle_deg < 180:
        return sw._result(False, "Angles must be between 0 and 180 degrees.",
                          SwErrors.swInvalidInput)

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    if not _has_weldment_feature(doc):
        return sw._result(False, "Active part has no weldment feature.",
                          SwErrors.swFeatureError)

    face_a, body_a, error = _planar_face_by_index(doc, face_a_index)
    if error:
        return sw._result(False, error, SwErrors.swInvalidInput)
    face_b, body_b, error = _planar_face_by_index(doc, face_b_index)
    if error:
        return sw._result(False, error, SwErrors.swInvalidInput)
    if body_a == body_b:
        return sw._result(
            False, "The two supporting faces must belong to different bodies.",
            SwErrors.swInvalidInput)
    normal_a = [float(value) for value in com(face_a, "Normal")]
    normal_b = [float(value) for value in com(face_b, "Normal")]
    if abs(sum(x * y for x, y in zip(normal_a, normal_b))) > 0.999:
        return sw._result(
            False, "The supporting faces are parallel; a gusset needs two "
                   "faces that meet at a corner.",
            SwErrors.swInvalidInput)

    try:
        before_names = set(_body_lookup(doc))
        before = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not read document volume: {exc}",
                          SwErrors.swFeatureError)

    feature = None
    try:
        com(doc, "ClearSelection2", True)
        selection_manager = com(doc, "SelectionManager")
        for position, face in enumerate((face_a, face_b)):
            select_data = com(selection_manager, "CreateSelectData")
            select_data.Mark = 1
            if not com(face, "Select4", position > 0, select_data):
                return sw._result(False, "Could not select a supporting face.",
                                  SwErrors.swSelectionError)
        # InsertGussetFeature3 takes the two supporting faces from the current
        # selection (mark 1); the array variant InsertGussetFeature2 created no
        # feature in any probe, so only feature3 is used.
        feature = com(com(doc, "FeatureManager"), "InsertGussetFeature3",
                      depth_mm / 1000.0, GUSSET_DIRECTIONS[direction],
                      GUSSET_LOCATIONS[location], profile == "polygon",
                      leg1_mm / 1000.0, leg2_mm / 1000.0, leg3_mm / 1000.0,
                      math.radians(angle_deg), leg4_mm / 1000.0, offset,
                      offset_mm / 1000.0, crv_index, reverse_dir, reverse_face,
                      use_length_dim, chamfer1_mm / 1000.0,
                      chamfer2_mm / 1000.0, math.radians(chamfer_angle_deg),
                      use_length_dim_for_chamfer, chamfer)
    except Exception as exc:
        logger.error("InsertGussetFeature3 failed: %s", exc)
        return sw._result(False, f"Could not create gusset: {exc}",
                          SwErrors.swFeatureError)
    finally:
        try:
            com(doc, "ClearSelection2", True)
        except Exception:
            logger.warning("Could not clear selection after gusset")

    if not feature:
        return sw._result(False, "Gusset created no feature.",
                          SwErrors.swFeatureError)

    try:
        name = str(com(feature, "Name"))
        feature_type = str(com(feature, "GetTypeName2"))
        com(doc, "ForceRebuild3", False)
        if _find_feature(doc, name) is None:
            return sw._result(False, "Gusset did not persist in the feature tree.",
                              SwErrors.swFeatureError)
        after_names = set(_body_lookup(doc))
        after = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not verify gusset: {exc}",
                          SwErrors.swFeatureError)

    added = after - before
    if added <= 0:
        return sw._result(
            False,
            f"Gusset '{name}' added no material ({before:.2f} -> {after:.2f} mm3).",
            SwErrors.swFeatureError,
            {"feature": name, "feature_type": feature_type,
             "gusset_bodies": sorted(after_names - before_names),
             "volume_before_mm3": round(before, 4),
             "volume_after_mm3": round(after, 4),
             "added_mm3": round(added, 4)})

    return sw._result(
        True,
        f"Created gusset '{name}' between {body_a} and {body_b}.",
        data={"feature": name, "feature_type": feature_type,
              "face_a": {"index": face_a_index, "body": body_a},
              "face_b": {"index": face_b_index, "body": body_b},
              "direction": direction, "location": location,
              "profile": profile,
              "gusset_bodies": sorted(after_names - before_names),
              "volume_before_mm3": round(before, 4),
              "volume_after_mm3": round(after, 4),
              "added_mm3": round(added, 4)})


#: Feature types SolidWorks reports for a cosmetic weld bead.
COSMETIC_BEAD_FEATURE_TYPES = ("CosmeticWeldBead",)

#: swCosmeticWeldBeadMode_e: weld along the given edges/sketches.
COSMETIC_BEAD_WELD_PATH = 1


def _find_feature_recursive(document, name):
    """Find a feature by name anywhere in the tree, foldered features included.

    Cosmetic weld beads live under the Weld Folder, so the top-level
    FirstFeature/GetNextFeature chain does not reach them.
    """
    def walk(feature, next_name):
        while feature is not None:
            if str(com(feature, "Name")) == name:
                return feature
            child = com(feature, "GetFirstSubFeature")
            if child is not None:
                found = walk(child, "GetNextSubFeature")
                if found is not None:
                    return found
            feature = com(feature, next_name)
        return None

    return walk(com(document, "FirstFeature"), "GetNextFeature")


@tool(
    name="create_cosmetic_weld_bead",
    description=(
        "Create a cosmetic weld bead along a path of edges in the active part "
        "(InsertCosmeticWeldBead2, weld-path mode). Cosmetic beads are drawing "
        "annotations: they add no solid material, so success is proven by the "
        "persistent CosmeticWeldBead feature and its recorded total weld "
        "length, not by a volume change. Use edge indices from list_body_edges. "
        "Select several edges of one loop to weld all the way around. "
        "Modifies the active part."
    ),
    schema={
        "type": "object",
        "properties": {
            "edge_indices": {
                "type": "array", "items": {"type": "integer", "minimum": 0},
                "minItems": 1,
                "description": "Edge indices from list_body_edges, in path order"
            },
            "size_mm": {
                "type": "number", "minimum": 0.001, "default": 4.0,
                "description": "Weld bead leg size in millimetres"
            }
        },
        "required": ["edge_indices"]
    },
    operation_class=OperationClass.MUTATE,
)
def create_cosmetic_weld_bead(sw, edge_indices, size_mm=4.0):
    """Weld a cosmetic bead along the named edges of the active part."""
    if (not isinstance(edge_indices, (list, tuple)) or not edge_indices
            or any(isinstance(index, bool) or not isinstance(index, int)
                   or index < 0 for index in edge_indices)
            or len(set(edge_indices)) != len(edge_indices)):
        return sw._result(False, "edge_indices must be distinct non-negative integers.",
                          SwErrors.swInvalidInput)
    if (isinstance(size_mm, bool) or not isinstance(size_mm, (int, float))
            or size_mm <= 0):
        return sw._result(False, "size_mm must be a positive number.",
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
                          SwErrors.swFeatureError)
    for index in edge_indices:
        if index >= len(edges):
            return sw._result(
                False,
                f"Edge index {index} is out of range for {len(edges)} edges; "
                "re-run list_body_edges.",
                SwErrors.swInvalidInput)
    chosen = [edges[index] for index in edge_indices]
    try:
        before = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not read document volume: {exc}",
                          SwErrors.swFeatureError)

    returned = None
    try:
        com(doc, "ClearSelection2", True)
        selection_manager = com(doc, "SelectionManager")
        for position, item in enumerate(chosen):
            select_data = com(selection_manager, "CreateSelectData")
            select_data.Mark = 0
            if not com(item["edge"], "Select4", position > 0, select_data):
                return sw._result(False, f"Could not select edge {item['index']}.",
                                  SwErrors.swSelectionError)
        returned = com(com(doc, "FeatureManager"), "InsertCosmeticWeldBead2",
                       COSMETIC_BEAD_WELD_PATH,
                       win32com.client.VARIANT(
                           pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
                           [item["edge"] for item in chosen]),
                       None, size_mm / 1000.0)
    except Exception as exc:
        logger.error("InsertCosmeticWeldBead2 failed: %s", exc)
        return sw._result(False, f"Could not create cosmetic weld bead: {exc}",
                          SwErrors.swFeatureError)
    finally:
        try:
            com(doc, "ClearSelection2", True)
        except Exception:
            logger.warning("Could not clear selection after weld bead")

    features = (list(returned) if isinstance(returned, (list, tuple))
                else [returned] if returned is not None else [])
    features = [feature for feature in features if feature is not None]
    if not features:
        return sw._result(False, "Cosmetic weld bead created no feature.",
                          SwErrors.swFeatureError)

    names = []
    feature_type = None
    bead_size_mm = None
    total_length_mm = None
    try:
        for feature in features:
            names.append(str(com(feature, "Name")))
        com(doc, "ForceRebuild3", False)
        for name, feature in zip(names, features):
            if _find_feature_recursive(doc, name) is None:
                return sw._result(
                    False, f"Weld bead '{name}' did not persist in the feature tree.",
                    SwErrors.swFeatureError)
        feature_type = str(com(features[0], "GetTypeName2"))
        if "bead" not in feature_type.casefold():
            return sw._result(
                False, f"Feature '{names[0]}' is a {feature_type}, not a weld bead.",
                SwErrors.swFeatureError)
        definition = com(features[0], "GetDefinition")
        bead_size_mm = round(float(com(definition, "BeadSize")) * 1000, 4)
        # ICosmeticWeldBeadFolder.TotalLength follows the document units; the
        # project works in millimetre documents, so it is already in mm.
        total_length_mm = round(
            float(com(com(definition, "GetWeldBeadFolder"), "TotalLength")), 4)
        after = _total_volume_mm3(doc)
    except Exception as exc:
        return sw._result(False, f"Could not verify cosmetic weld bead: {exc}",
                          SwErrors.swFeatureError)

    return sw._result(
        True,
        f"Created {len(names)} cosmetic weld bead(s) along {len(chosen)} edge(s).",
        data={"features": names, "feature_type": feature_type,
              "edge_count": len(chosen), "edge_length_mm": round(
                  sum(item["length_mm"] or 0.0 for item in chosen), 4),
              "bead_size_mm": bead_size_mm,
              "total_weld_length_mm": total_length_mm,
              "volume_before_mm3": round(before, 4),
              "volume_after_mm3": round(after, 4),
              "added_mm3": round(after - before, 6)})


#: swEndConditionTrim: trim or extend a body to a boundary.
SW_END_CONDITION_TRIM = 4

#: Bit flags of swWeldmentTrimExtendOptionType_e, summed as in the installed
#: official "Insert Weldment Features" example.
TRIM_EXTEND_OPTIONS = 1 | 2 | 4 | 8


def _body_lookup(doc):
    lookup = {}
    for body in com(doc, "GetBodies2", 0, False) or []:
        lookup.setdefault(str(com(body, "Name")), []).append(body)
    return lookup


def _planar_face_of_body(doc, body_name, face_index):
    """Face at the global index list_planar_faces reports, if it is planar
    and belongs to the named body. Returns (face, error_message)."""
    index = 0
    for body in com(doc, "GetBodies2", 0, False) or []:
        for face in com(body, "GetFaces") or []:
            if index == face_index:
                if str(com(body, "Name")) != body_name:
                    return None, "Boundary face does not belong to the named body."
                if not com(com(face, "GetSurface"), "IsPlane"):
                    return None, "Boundary face is not planar."
                return face, None
            index += 1
    return None, "Boundary face index is out of range."


#: Selection marks the installed help documents for InsertWeldmentTrimFeature2.
MARK_BODY_TO_TRIM = 1
MARK_TRIMMING_BOUNDARY = 2


def trim_weldment_member_to_face(sw, body_to_trim, trimming_body,
                                 boundary_face_index=None,
                                 allow_extension=False,
                                 end_condition=SW_END_CONDITION_TRIM,
                                 options=TRIM_EXTEND_OPTIONS,
                                 boundary_kind="face",
                                 mark_selection=False,
                                 use_v1=False):
    """Research entry point: trim or extend one weldment body to a frame face.

    Not registered as an MCP tool while the live test is still failing; see
    ``W2.face`` in the capability register. Returns a diagnostics dictionary
    so a probe can see exactly what SolidWorks did.
    """
    if (not isinstance(body_to_trim, str) or not body_to_trim.strip()
            or not isinstance(trimming_body, str) or not trimming_body.strip()
            or body_to_trim == trimming_body):
        return sw._result(False, "Supply two distinct solid-body names.",
                          SwErrors.swInvalidInput)
    if boundary_kind not in ("face", "body"):
        return sw._result(False, "boundary_kind must be 'face' or 'body'.",
                          SwErrors.swInvalidInput)
    if boundary_kind == "face" and (isinstance(boundary_face_index, bool)
                                    or not isinstance(boundary_face_index, int)
                                    or boundary_face_index < 0):
        return sw._result(False, "boundary_face_index must be a non-negative integer.",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 1:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)
    lookup = _body_lookup(doc)
    if len(lookup.get(body_to_trim, [])) != 1 or len(lookup.get(trimming_body, [])) != 1:
        return sw._result(False, "Solid-body name not found or ambiguous.",
                          SwErrors.swInvalidInput)
    if boundary_kind == "face":
        boundary_entity, error = _planar_face_of_body(
            doc, trimming_body, boundary_face_index)
        if error:
            return sw._result(False, error, SwErrors.swInvalidInput)
    else:
        boundary_entity = lookup[trimming_body][0]

    array_type = pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH
    proxy_name = None
    proxy_type = None
    readback_corner = None
    proxy_error = None
    feature_manager = com(doc, "FeatureManager")
    try:
        com(doc, "ClearSelection2", True)
        if use_v1:
            extension = com(doc, "Extension")
            null_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            selected = com(extension, "SelectByID2", body_to_trim, "SOLIDBODY",
                           0, 0, 0, False, MARK_BODY_TO_TRIM, null_callout, 0)
            if not selected:
                return sw._result(False, "Could not select the body to trim.",
                                  SwErrors.swInvalidInput)
            if boundary_kind == "face":
                box = com(boundary_entity, "GetBox")
                point = [(box[index] + box[index + 3]) / 2 for index in range(3)]
                selected = com(extension, "SelectByID2", "", "FACE",
                               point[0], point[1], point[2], True,
                               MARK_TRIMMING_BOUNDARY, null_callout, 0)
            else:
                selected = com(extension, "SelectByID2", trimming_body,
                               "SOLIDBODY", 0, 0, 0, True,
                               MARK_TRIMMING_BOUNDARY, null_callout, 0)
            if not selected:
                return sw._result(False, "Could not select the trimming boundary.",
                                  SwErrors.swInvalidInput)
            feature = com(feature_manager, "InsertWeldmentTrimFeature",
                          end_condition)
        else:
            if mark_selection:
                com(lookup[body_to_trim][0], "Select", False)
                com(boundary_entity, "Select4", True, MARK_TRIMMING_BOUNDARY)
            trimmed = win32com.client.VARIANT(array_type, lookup[body_to_trim])
            boundary = win32com.client.VARIANT(array_type, [boundary_entity])
            feature = com(feature_manager,
                          "InsertWeldmentTrimFeature2", end_condition,
                          options, 0.0, trimmed, boundary)
        if feature:
            proxy_name = str(com(feature, "Name"))
            try:
                proxy_type = str(com(feature, "GetTypeName2"))
            except Exception:
                proxy_type = "unavailable"
            try:
                definition = com(feature, "GetDefinition")
                readback_corner = int(com(definition, "CornerType"))
                com(definition, "ReleaseSelectionAccess")
            except Exception:
                readback_corner = None
            try:
                proxy_error = int(com(feature, "GetErrorCode"))
            except Exception:
                proxy_error = None
    except Exception as exc:
        logger.error("InsertWeldmentTrimFeature2 (face) failed: %s", exc)
        return sw._result(False, f"Could not trim to face: {exc}",
                          SwErrors.swFeatureError)
    finally:
        try:
            com(doc, "ClearSelection2", True)
        except Exception:
            logger.warning("Could not clear selection after weldment face trim")

    com(doc, "ForceRebuild3", False)
    corners = [com(item, "Name") for item in _iter_features(doc)
               if com(item, "GetTypeName2") == "WeldCornerFeat"]
    persisted = proxy_name is not None and proxy_name in corners
    return sw._result(
        persisted,
        f"Face trim proxy {proxy_name!r}; WeldCornerFeat in tree: {corners}.",
        SwErrors.swSuccess if persisted else SwErrors.swFeatureError,
        {"proxy": proxy_name,
         "proxy_type": proxy_type,
         "readback_corner_type": readback_corner,
         "proxy_error": proxy_error,
         "weld_corner_features": corners,
         "end_condition": end_condition,
         "options": options,
         "boundary_kind": boundary_kind,
         "allow_extension": allow_extension,
         "mark_selection": mark_selection,
         "use_v1": use_v1})


def _iter_features(doc):
    feature = com(doc, "FirstFeature")
    while feature is not None:
        yield feature
        feature = com(feature, "GetNextFeature")
