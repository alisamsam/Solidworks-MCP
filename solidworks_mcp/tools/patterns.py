"""Feature-level linear and circular pattern tools."""

import math

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


SW_DOC_PART = 1


def _find_feature(doc, name):
    feature = com(doc, "FirstFeature")
    while feature is not None:
        if com(feature, "Name") == name:
            return feature
        feature = com(feature, "GetNextFeature")
    return None


def _select_pattern_inputs(sw, doc, seed_name, direction_name):
    seed = _find_feature(doc, seed_name)
    direction = _find_feature(doc, direction_name)
    if seed is None or direction is None:
        missing = seed_name if seed is None else direction_name
        return sw._result(False, f"Feature not found: {missing}", SwErrors.swSelectionError)

    com(doc, "ClearSelection2", True)
    selection_manager = com(doc, "SelectionManager")
    seed_data = com(selection_manager, "CreateSelectData")
    seed_data.Mark = 4
    direction_data = com(selection_manager, "CreateSelectData")
    direction_data.Mark = 1
    if not com(seed, "Select4", True, seed_data):
        return sw._result(False, f"Could not select seed feature: {seed_name}", SwErrors.swSelectionError)
    if not com(direction, "Select4", True, direction_data):
        return sw._result(False, f"Could not select pattern direction: {direction_name}", SwErrors.swSelectionError)
    return None


@tool(
    name="circular_pattern",
    description="Pattern one named feature around one named reference axis using exact feature names.",
    schema={"type": "object", "properties": {
        "seed_feature": {"type": "string"},
        "axis_feature": {"type": "string"},
        "instances": {"type": "integer", "minimum": 2},
        "total_angle_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 360, "default": 360},
        "flip_direction": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": True},
    }, "required": ["seed_feature", "axis_feature", "instances"]},
    operation_class=OperationClass.MUTATE,
)
def circular_pattern(sw, seed_feature: str, axis_feature: str, instances: int,
                     total_angle_deg: float = 360, flip_direction: bool = False,
                     geometry_pattern: bool = True) -> dict:
    if instances < 2 or not 0 < total_angle_deg <= 360:
        return sw._result(False, "Circular pattern requires at least 2 instances and an angle in (0, 360].",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    selection_error = _select_pattern_inputs(sw, doc, seed_feature, axis_feature)
    if selection_error:
        return selection_error
    feature = com(doc.FeatureManager, "FeatureCircularPattern4", instances,
                  math.radians(total_angle_deg), flip_direction, "NULL",
                  geometry_pattern, True, False)
    if feature is None:
        return sw._result(False, "SolidWorks did not create the circular pattern.", SwErrors.swFeatureError)
    return sw._result(True, f"Circular pattern created with {instances} instances.", data={
        "seed_feature": seed_feature, "axis_feature": axis_feature,
        "instances": instances, "total_angle_deg": total_angle_deg,
    })


@tool(
    name="linear_pattern",
    description="Pattern one named feature along one named direction feature using exact feature names.",
    schema={"type": "object", "properties": {
        "seed_feature": {"type": "string"},
        "direction_feature": {"type": "string"},
        "instances": {"type": "integer", "minimum": 2},
        "spacing": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
        "flip_direction": {"type": "boolean", "default": False},
        "geometry_pattern": {"type": "boolean", "default": True},
    }, "required": ["seed_feature", "direction_feature", "instances", "spacing"]},
    operation_class=OperationClass.MUTATE,
)
def linear_pattern(sw, seed_feature: str, direction_feature: str, instances: int,
                   spacing: float, unit: str = "mm", flip_direction: bool = False,
                   geometry_pattern: bool = True) -> dict:
    if instances < 2 or spacing <= 0:
        return sw._result(False, "Linear pattern requires at least 2 instances and positive spacing.",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    selection_error = _select_pattern_inputs(sw, doc, seed_feature, direction_feature)
    if selection_error:
        return selection_error
    spacing_m = sw._units.to_meters(spacing, unit)
    feature = com(doc.FeatureManager, "FeatureLinearPattern4",
                  instances, spacing_m, 1, 0.0, flip_direction, False,
                  "NULL", "NULL", geometry_pattern, False,
                  False, False, False, False, False, False,
                  False, False, 0.0, 0.0)
    if feature is None:
        return sw._result(False, "SolidWorks did not create the linear pattern.", SwErrors.swFeatureError)
    return sw._result(True, f"Linear pattern created with {instances} instances.", data={
        "seed_feature": seed_feature, "direction_feature": direction_feature,
        "instances": instances, "spacing": spacing, "unit": unit,
    })


def _select_mirror_inputs(sw, doc, seed_name, plane_name):
    seed = _find_feature(doc, seed_name)
    plane = _find_feature(doc, plane_name)
    if seed is None or plane is None:
        missing = seed_name if seed is None else plane_name
        return sw._result(False, f"Feature or plane not found: {missing}",
                          SwErrors.swSelectionError)

    com(doc, "ClearSelection2", True)
    selection_manager = com(doc, "SelectionManager")
    seed_data = com(selection_manager, "CreateSelectData")
    seed_data.Mark = 1
    plane_data = com(selection_manager, "CreateSelectData")
    plane_data.Mark = 2
    if not com(seed, "Select4", False, seed_data):
        return sw._result(False, f"Could not select seed feature: {seed_name}",
                          SwErrors.swSelectionError)
    if not com(plane, "Select4", True, plane_data):
        return sw._result(False, f"Could not select mirror plane: {plane_name}",
                          SwErrors.swSelectionError)
    return None


@tool(
    name="mirror_feature",
    description=(
        "Mirror one named feature about one exactly named plane on the active "
        "part. Use exact feature and plane names from list_planes."
    ),
    schema={"type": "object", "properties": {
        "seed_feature": {"type": "string"},
        "mirror_plane": {"type": "string"},
        "geometry_pattern": {"type": "boolean", "default": True},
        "merge": {"type": "boolean", "default": True},
    }, "required": ["seed_feature", "mirror_plane"]},
    operation_class=OperationClass.MUTATE,
)
def mirror_feature(sw, seed_feature: str, mirror_plane: str,
                   geometry_pattern: bool = True, merge: bool = True) -> dict:
    if (
        not isinstance(seed_feature, str)
        or not seed_feature.strip()
        or not isinstance(mirror_plane, str)
        or not mirror_plane.strip()
        or not isinstance(geometry_pattern, bool)
        or not isinstance(merge, bool)
    ):
        return sw._result(
            False,
            "seed_feature and mirror_plane must be non-empty strings; "
            "geometry_pattern and merge must be boolean.",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != SW_DOC_PART:
        return sw._result(False, "Active document is not a part.",
                          SwErrors.swInvalidFileType)

    try:
        selection_error = _select_mirror_inputs(sw, doc, seed_feature, mirror_plane)
        if selection_error:
            return selection_error
        feature = com(doc.FeatureManager, "InsertMirrorFeature2",
                      False, geometry_pattern, merge, False, 0)
        error_code = com(feature, "GetErrorCode") if feature is not None else None
    except Exception as create_error:
        return sw._result(False, f"Mirror creation failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(doc, "ClearSelection2", True)

    if feature is None:
        return sw._result(False, "SolidWorks did not create the mirror feature.",
                          SwErrors.swFeatureError)

    feature_name = com(feature, "Name")
    if error_code:
        cleanup_error = None
        try:
            com(doc, "ClearSelection2", True)
            com(feature, "Select2", False, 0)
            com(doc, "EditDelete")
        except Exception as remove_error:
            cleanup_error = str(remove_error)
        finally:
            com(doc, "ClearSelection2", True)
        return sw._result(
            False,
            f"SolidWorks created {feature_name} but the mirror has error code "
            f"{error_code}; the broken feature was removed. Check that the seed "
            "feature and the mirror plane produce valid, non-coincident geometry.",
            SwErrors.swFeatureError,
            {
                "code": "MIRROR_REBUILD_FAILED",
                "feature_name": feature_name,
                "feature_error_code": int(error_code),
                "removed": cleanup_error is None,
                "cleanup_error": cleanup_error,
            },
        )

    return sw._result(
        True,
        f"Mirror feature {feature_name} created from {seed_feature} "
        f"about {mirror_plane}.",
        data={
            "feature_name": feature_name,
            "seed_feature": seed_feature,
            "mirror_plane": mirror_plane,
            "geometry_pattern": geometry_pattern,
            "merge": merge,
        },
    )
