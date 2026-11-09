"""Operations on explicitly selected solid bodies.

SOLIDWORKS 2025 TLB: IBody2.Select2(Append, Data),
IFeatureManager.InsertScale(Type, Uniform, Xscale, YScale, ZScale).
swScaleAboutCentroid=0, swScaleAboutOrigin=1 (swconst.tlb).

IPartDoc.InsertPart3(FileName, Options, Configuration) imports the solids of
another saved part as a new Stock body; swInsertPartOptions_e.
swInsertPartImportSolids=1 (swconst.tlb).
"""

import math
import os

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


@tool(
    name="scale_body",
    description="Uniformly scale one solid body by index about its centroid or the part origin.",
    schema={"type": "object", "properties": {
        "body_index": {"type": "integer", "minimum": 0,
                       "description": "Zero-based index in the visible solid body list."},
        "factor": {"type": "number", "exclusiveMinimum": 0},
        "origin": {"type": "string", "enum": ["centroid", "origin"],
                   "default": "centroid"},
    }, "required": ["body_index", "factor"]},
    operation_class=OperationClass.MUTATE,
)
def scale_body(sw, body_index: int, factor: float, origin: str = "centroid") -> dict:
    if (isinstance(body_index, bool) or not isinstance(body_index, int)
            or body_index < 0 or isinstance(factor, bool)
            or not isinstance(factor, (int, float)) or not math.isfinite(factor)
            or factor <= 0 or origin not in ("centroid", "origin")):
        return sw._result(False, "Invalid body index, scale factor, or origin.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Scaling requires a part.", SwErrors.swInvalidFileType)
    try:
        bodies = com(document, "GetBodies2", 0, True) or []
        if body_index >= len(bodies):
            return sw._result(False, "Solid body index is out of range.",
                              SwErrors.swInvalidInput, {"code": "BODY_NOT_FOUND"})
        com(document, "ClearSelection2", True)
        select_data = com(com(document, "SelectionManager"), "CreateSelectData")
        if not com(bodies[body_index], "Select2", False, select_data):
            return sw._result(False, "Could not select solid body.",
                              SwErrors.swSelectionError)
        feature = com(com(document, "FeatureManager"), "InsertScale",
                      0 if origin == "centroid" else 1, True,
                      float(factor), float(factor), float(factor))
        if feature is None:
            return sw._result(False, "SolidWorks did not create a Scale feature.",
                              SwErrors.swFeatureError)
        return sw._result(True, "Scaled solid body.", data={
            "feature_name": str(com(feature, "Name")), "body_index": body_index,
            "factor": factor, "origin": origin,
        })
    except Exception as exc:
        return sw._result(False, f"Scaling solid body failed: {exc}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="delete_body",
    description="Delete a selected solid body or keep only that body in a multibody part.",
    schema={"type": "object", "properties": {
        "body_index": {"type": "integer", "minimum": 0},
        "keep_only": {"type": "boolean", "default": False},
    }, "required": ["body_index"]},
    operation_class=OperationClass.MUTATE,
)
def delete_body(sw, body_index: int, keep_only: bool = False) -> dict:
    if (isinstance(body_index, bool) or not isinstance(body_index, int)
            or body_index < 0 or not isinstance(keep_only, bool)):
        return sw._result(False, "Invalid body index or keep_only flag.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Delete/Keep Body requires a part.",
                          SwErrors.swInvalidFileType)
    try:
        bodies = com(document, "GetBodies2", 0, True) or []
        if len(bodies) < 2 or body_index >= len(bodies):
            return sw._result(False, "Select a body in a multibody part.",
                              SwErrors.swInvalidInput, {"code": "BODY_NOT_FOUND"})
        before_count = len(bodies)
        before_volume = sum(float(com(body, "GetMassProperties", 0.0)[3]) * 1e9
                            for body in bodies)
        com(document, "ClearSelection2", True)
        selection = com(com(document, "SelectionManager"), "CreateSelectData")
        if not com(bodies[body_index], "Select2", False, selection):
            return sw._result(False, "Could not select solid body.",
                              SwErrors.swSelectionError)
        # SW2025 IFeatureManager.InsertDeleteBody2(KeepBodies)
        feature = com(com(document, "FeatureManager"), "InsertDeleteBody2", keep_only)
        remaining = com(document, "GetBodies2", 0, True) or []
        after_volume = sum(float(com(body, "GetMassProperties", 0.0)[3]) * 1e9
                           for body in remaining)
        expected_count = 1 if keep_only else before_count - 1
        if feature is None or len(remaining) != expected_count or after_volume >= before_volume:
            return sw._result(False, "Delete/Keep Body did not remove expected geometry.",
                              SwErrors.swFeatureError,
                              {"bodies_before": before_count, "bodies_after": len(remaining),
                               "volume_before_mm3": before_volume,
                               "volume_after_mm3": after_volume})
        return sw._result(True, f"Created Delete/Keep Body {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")), "keep_only": keep_only,
            "body_index": body_index, "bodies_before": before_count,
            "bodies_after": len(remaining), "volume_before_mm3": before_volume,
            "volume_after_mm3": after_volume,
        })
    except Exception as exc:
        return sw._result(False, f"Delete/Keep Body failed: {exc}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="move_copy_body",
    description="Translate one solid body by an XYZ vector; optionally retain the original as a copy.",
    schema={"type": "object", "properties": {
        "body_index": {"type": "integer", "minimum": 0},
        "dx": {"type": "number"}, "dy": {"type": "number"},
        "dz": {"type": "number"},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
        "copy": {"type": "boolean", "default": False},
    }, "required": ["body_index", "dx", "dy", "dz"]},
    operation_class=OperationClass.MUTATE,
)
def move_copy_body(sw, body_index: int, dx: float, dy: float, dz: float,
                   unit: str = "mm", copy: bool = False) -> dict:
    coords = (dx, dy, dz)
    if (isinstance(body_index, bool) or not isinstance(body_index, int)
            or body_index < 0 or not isinstance(copy, bool)
            or any(isinstance(n, bool) or not isinstance(n, (int, float))
                   or not math.isfinite(n) for n in coords)
            or not any(coords)):
        return sw._result(False, "Invalid body index or translation vector.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        xyz = [sw._units.to_meters(n, unit) for n in coords]
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid translation unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Move/Copy Body requires a part.", SwErrors.swInvalidFileType)
    try:
        bodies = com(document, "GetBodies2", 0, True) or []
        if body_index >= len(bodies):
            return sw._result(False, "Solid body index out of range.",
                              SwErrors.swInvalidInput)
        original = bodies[body_index]
        before_box = tuple(com(original, "GetBodyBox"))
        selected_volume = com(original, "GetMassProperties", 0.0)[3] * 1e9
        before_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                            for body in bodies)
        com(document, "ClearSelection2", True)
        select_data = com(com(document, "SelectionManager"), "CreateSelectData")
        select_data.Mark = 1
        if not com(original, "Select2", False, select_data):
            return sw._result(False, "Could not select solid body.", SwErrors.swSelectionError)
        # TransX/Y/Z are displacement in meters; TransDist is zero when the
        # displacement components are supplied directly (SW 2025 VBA example).
        args = (*xyz, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, copy, 1)
        feature = com(com(document, "FeatureManager"), "InsertMoveCopyBody2", *args)
        after = com(document, "GetBodies2", 0, True) or []
        after_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                           for body in after)
        count_ok = len(after) == len(bodies) + int(copy)
        expected_volume = before_volume + (selected_volume if copy else 0)
        volume_ok = abs(after_volume - expected_volume) < max(0.5, expected_volume * 1e-4)
        expected_box = tuple(before_box[i] + xyz[i % 3] for i in range(6))
        candidates = [tuple(com(body, "GetBodyBox")) for body in after]
        moved_box = min(candidates, key=lambda box: sum(abs(a - b) for a, b in zip(box, expected_box))) if candidates else ()
        shifted = moved_box and all(abs(a - b) < 1e-4 for a, b in zip(moved_box, expected_box))
        if feature is None or not count_ok or not volume_ok or not shifted:
            return sw._result(False, "Move/Copy Body did not change geometry as expected.",
                              SwErrors.swFeatureError, {"bodies_after": len(after),
                                                       "volume_after_mm3": after_volume,
                                                       "box_before_m": before_box,
                                                       "box_after_m": moved_box,
                                                       "feature_created": feature is not None})
        return sw._result(True, f"Created {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")), "body_index": body_index,
            "copy": copy, "translation_m": xyz, "bodies_before": len(bodies),
            "bodies_after": len(after), "volume_before_mm3": before_volume,
            "volume_after_mm3": after_volume, "box_before_m": before_box,
            "box_after_m": moved_box,
        })
    except Exception as exc:
        return sw._result(False, f"Move/Copy Body failed: {exc}", SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="combine_bodies",
    description="Combine two overlapping solid bodies: add, subtract (target minus tool), or common.",
    schema={"type": "object", "properties": {
        "target_index": {"type": "integer", "minimum": 0},
        "tool_index": {"type": "integer", "minimum": 0},
        "operation": {"type": "string", "enum": ["add", "subtract", "common"]},
    }, "required": ["target_index", "tool_index", "operation"]},
    operation_class=OperationClass.MUTATE,
)
def combine_bodies(sw, target_index: int, tool_index: int, operation: str) -> dict:
    if (any(isinstance(index, bool) or not isinstance(index, int) or index < 0
            for index in (target_index, tool_index)) or target_index == tool_index
            or operation not in ("add", "subtract", "common")):
        return sw._result(False, "Choose two distinct solid bodies and a valid operation.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Combine requires a multibody part.",
                          SwErrors.swInvalidFileType)
    try:
        bodies = com(document, "GetBodies2", 0, True) or []
        if len(bodies) != 2 or max(target_index, tool_index) >= len(bodies):
            return sw._result(False, "Combine requires exactly two solid bodies with valid indices.",
                              SwErrors.swInvalidInput)
        target, tool_body = bodies[target_index], bodies[tool_index]
        target_volume = com(target, "GetMassProperties", 0.0)[3] * 1e9
        tool_volume = com(tool_body, "GetMassProperties", 0.0)[3] * 1e9
        before_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                            for body in bodies)
        # SW2025 swBodyOperationType_e: add=15903, cut=15902, intersect=15901.
        body_array = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
                             [tool_body] if operation == "subtract" else [target, tool_body])
        main = target if operation == "subtract" else VARIANT(pythoncom.VT_DISPATCH, None)
        com(document, "ClearSelection2", True)
        feature = com(com(document, "FeatureManager"), "InsertCombineFeature",
                      {"add": 15903, "subtract": 15902, "common": 15901}[operation],
                      main, body_array)
        after = com(document, "GetBodies2", 0, True) or []
        after_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                           for body in after)
        count_ok = len(after) == len(bodies) - 1
        volume_ok = (0 < after_volume < target_volume - 1e-3
                     if operation == "subtract" else 0 < after_volume < before_volume - 1e-3)
        if feature is None or not count_ok or not volume_ok or com(feature, "GetErrorCode"):
            return sw._result(False, "Combine did not produce the expected solid.",
                              SwErrors.swFeatureError, {"bodies_before": len(bodies),
                                                       "bodies_after": len(after),
                                                       "volume_before_mm3": before_volume,
                                                       "volume_after_mm3": after_volume})
        return sw._result(True, f"Created combine feature {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")), "operation": operation,
            "bodies_before": len(bodies), "bodies_after": len(after),
            "target_volume_mm3": target_volume, "tool_volume_mm3": tool_volume,
            "volume_before_mm3": before_volume, "volume_after_mm3": after_volume,
        })
    except Exception as exc:
        return sw._result(False, f"Combine failed: {exc}", SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="insert_part",
    description=("Insert the solid geometry of another saved part (.SLDPRT) into "
                 "the active part as a new Stock body."),
    schema={"type": "object", "properties": {
        "part_path": {"type": "string", "minLength": 1,
                      "description": "Full path of the source .SLDPRT file."},
    }, "required": ["part_path"]},
    operation_class=OperationClass.MUTATE,
)
def insert_part(sw, part_path: str) -> dict:
    if not isinstance(part_path, str) or not part_path.strip():
        return sw._result(False, "part_path must be a non-empty path.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    path = os.path.abspath(part_path.strip())
    if os.path.splitext(path)[1].casefold() != ".sldprt":
        return sw._result(False, "Insert Part requires a .SLDPRT source file.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not os.path.isfile(path):
        return sw._result(False, f"Source part not found: {path}",
                          SwErrors.swInvalidInput,
                          {"code": "SOURCE_NOT_FOUND", "path": path})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Insert Part requires an active part.",
                          SwErrors.swInvalidFileType)
    try:
        before_bodies = com(document, "GetBodies2", 0, True) or []
        before_count = len(before_bodies)
        before_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                            for body in before_bodies)
        # IPartDoc.InsertPart3(FileName, Options, Configuration);
        # swInsertPartOptions_e.swInsertPartImportSolids = 1 (swconst.tlb).
        feature = com(document, "InsertPart3", path, 1, "")
        after_bodies = com(document, "GetBodies2", 0, True) or []
        after_count = len(after_bodies)
        after_volume = sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                           for body in after_bodies)
        error_code = com(feature, "GetErrorCode") if feature is not None else 1
        if (feature is None or error_code
                or after_volume <= before_volume + 1e-6
                or after_count <= before_count):
            return sw._result(False, "Insert Part did not add the source solid.",
                              SwErrors.swFeatureError, {
                                  "code": "INSERT_PART_FAILED",
                                  "bodies_before": before_count,
                                  "bodies_after": after_count,
                                  "volume_before_mm3": before_volume,
                                  "volume_after_mm3": after_volume,
                                  "feature_error_code": int(error_code)})
        return sw._result(
            True,
            f"Inserted {os.path.splitext(os.path.basename(path))[0]}.",
            data={
                "feature_name": str(com(feature, "Name")),
                "feature_type": str(com(feature, "GetTypeName2")),
                "source_path": path, "bodies_before": before_count,
                "bodies_after": after_count, "volume_before_mm3": before_volume,
                "volume_after_mm3": after_volume,
            })
    except Exception as exc:
        return sw._result(False, f"Insert Part failed: {exc}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)
