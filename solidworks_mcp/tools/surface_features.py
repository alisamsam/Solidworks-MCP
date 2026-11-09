"""Parametric surface features of the active part."""

import math

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .advanced_features import _feature_signatures, _find_feature, _solid_volume_mm3


@tool(
    name="planar_surface",
    description=("Create a planar surface from every segment of a closed, "
                 "non-construction 2D sketch. Supply its exact feature name."),
    schema={"type": "object", "properties": {
        "sketch_name": {"type": "string", "minLength": 1},
    }, "required": ["sketch_name"]},
    operation_class=OperationClass.MUTATE,
)
def planar_surface(sw, sketch_name: str) -> dict:
    if not isinstance(sketch_name, str) or not sketch_name.strip():
        return sw._result(False, "sketch_name must be a non-empty name.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "A planar surface requires an active part.",
                          SwErrors.swInvalidFileType)
    sketch = _find_feature(document, sketch_name)
    if sketch is None or com(sketch, "GetTypeName2") != "ProfileFeature":
        return sw._result(False, f"2D sketch not found: {sketch_name}",
                          SwErrors.swSelectionError)
    try:
        segments = com(com(sketch, "GetSpecificFeature2"), "GetSketchSegments") or []
        if not segments:
            return sw._result(False, "The selected sketch has no boundary segments.",
                              SwErrors.swInvalidInput)
        before, old_proxies = _feature_signatures(document)
        del old_proxies
        com(document, "ClearSelection2", True)
        selection_manager = com(document, "SelectionManager")
        for index, segment in enumerate(segments):
            select_data = com(selection_manager, "CreateSelectData")
            select_data.Mark = 1
            if not com(segment, "Select4", index > 0, select_data):
                return sw._result(False, "Could not select every boundary segment.",
                                  SwErrors.swSelectionError)
        inserted = com(document, "InsertPlanarRefSurface")
        after, new_proxies = _feature_signatures(document)
        del new_proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "PlanarSurface"]
        if not inserted or not created:
            return sw._result(False, "SolidWorks did not create a planar surface.",
                              SwErrors.swFeatureError, {"code": "FEATURE_CREATE_FAILED"})
        feature = _find_feature(document, created[-1])
        code = com(feature, "GetErrorCode")
        if code:
            return sw._result(False, f"Planar surface rebuild error: {code}.",
                              SwErrors.swFeatureError, {"feature_error_code": int(code)})
        return sw._result(True, f"Created planar surface {created[-1]}.", data={
            "feature_name": created[-1], "sketch_name": sketch_name,
            "boundary_segments": len(segments),
        })
    except Exception as create_error:
        return sw._result(False, f"Planar surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="thicken_surface",
    description=("Make a solid by thickening a planar or extruded surface feature."),
    schema={"type": "object", "properties": {
        "surface_name": {"type": "string", "minLength": 1},
        "thickness": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "default": "mm"},
        "side": {"type": "string", "enum": ["one", "other", "both"],
                 "default": "one"},
    }, "required": ["surface_name", "thickness"]},
    operation_class=OperationClass.MUTATE,
)
def thicken_surface(sw, surface_name: str, thickness: float, unit: str = "mm",
                    side: str = "one") -> dict:
    """IFeatureManager.FeatureBossThicken, verified by resulting solid volume."""
    if (not isinstance(surface_name, str) or not surface_name.strip()
            or not isinstance(thickness, (int, float)) or isinstance(thickness, bool)
            or not math.isfinite(thickness) or thickness <= 0
            or side not in ("one", "other", "both")):
        return sw._result(False, "Invalid surface name, thickness or side.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        thickness_m = sw._units.to_meters(thickness, unit)
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid thickness unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Thicken requires an active part.",
                          SwErrors.swInvalidFileType)
    surface = _find_feature(document, surface_name)
    if surface is None or com(surface, "GetTypeName2") not in ("PlanarSurface", "ExtruRefSurface"):
        return sw._result(False, f"Surface feature not found: {surface_name}",
                          SwErrors.swSelectionError)
    try:
        volume_before = _solid_volume_mm3(document)
        com(document, "ClearSelection2", True)
        if not com(surface, "Select2", False, 1):
            return sw._result(False, "Could not select source surface.",
                              SwErrors.swSelectionError)
        feature = com(com(document, "FeatureManager"), "FeatureBossThicken",
                      thickness_m, {"one": 0, "other": 1, "both": 2}[side],
                      0, False, False, False, True)
        if feature is None:
            return sw._result(False, "SolidWorks did not create a thickened solid.",
                              SwErrors.swFeatureError)
        code = com(feature, "GetErrorCode")
        if code:
            return sw._result(False, f"Thicken rebuild error: {code}.",
                              SwErrors.swFeatureError,
                              {"feature_error_code": int(code)})
        volume_after = _solid_volume_mm3(document)
        if volume_after <= volume_before + 1e-6:
            return sw._result(False, "Thicken did not add solid volume.",
                              SwErrors.swFeatureError, {"code": "NO_ADDED_VOLUME"})
        name = com(feature, "Name")
        return sw._result(True, f"Created thickened solid {name}.", data={
            "feature_name": name, "surface_name": surface_name,
            "thickness": thickness, "unit": unit, "side": side,
            "volume_before_mm3": volume_before,
            "volume_after_mm3": volume_after,
        })
    except Exception as create_error:
        return sw._result(False, f"Thicken failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="extrude_surface",
    description="Extrude a named 2D sketch into a single-ended open surface.",
    schema={"type": "object", "properties": {
        "sketch_name": {"type": "string", "minLength": 1},
        "depth": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "default": "mm"},
        "reverse": {"type": "boolean", "default": False},
    }, "required": ["sketch_name", "depth"]},
    operation_class=OperationClass.MUTATE,
)
def extrude_surface(sw, sketch_name: str, depth: float, unit: str = "mm",
                    reverse: bool = False) -> dict:
    if (not isinstance(sketch_name, str) or not sketch_name.strip()
            or not isinstance(depth, (int, float)) or isinstance(depth, bool)
            or not math.isfinite(depth) or depth <= 0 or not isinstance(reverse, bool)):
        return sw._result(False, "Invalid sketch, depth or direction.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        depth_m = sw._units.to_meters(depth, unit)
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid depth unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "An extruded surface requires a part.",
                          SwErrors.swInvalidFileType)
    sketch = _find_feature(document, sketch_name)
    if sketch is None or com(sketch, "GetTypeName2") != "ProfileFeature":
        return sw._result(False, f"2D sketch not found: {sketch_name}",
                          SwErrors.swSelectionError)
    try:
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        if not com(sketch, "Select2", False, 0):
            return sw._result(False, f"Could not select sketch {sketch_name}.",
                              SwErrors.swSelectionError)
        # SW2025 IFeatureManager.FeatureExtruRefSurface3: start at sketch,
        # blind end, no draft, cap, knitting or deleted source faces.
        com(com(document, "FeatureManager"), "FeatureExtruRefSurface3",
            True, reverse, 0, 0.0, 0, 0, depth_m, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, False, False, False, False)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "ExtruRefSurface"]
        if not created:
            return sw._result(False, "SolidWorks did not create an extruded surface.",
                              SwErrors.swFeatureError)
        feature = _find_feature(document, created[-1])
        if com(feature, "GetErrorCode"):
            return sw._result(False, "Extruded surface failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created extruded surface {created[-1]}.", data={
            "feature_name": created[-1], "sketch_name": sketch_name,
            "depth": depth, "unit": unit, "reverse": reverse,
        })
    except Exception as create_error:
        return sw._result(False, f"Extruded surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="revolve_surface",
    description=("Revolve an open 2D sketch containing exactly one construction "
                 "centerline about that centerline into a sheet surface."),
    schema={"type": "object", "properties": {
        "sketch_name": {"type": "string", "minLength": 1},
        "angle": {"type": "number", "exclusiveMinimum": 0, "maximum": 360,
                  "default": 360},
        "reverse": {"type": "boolean", "default": False},
    }, "required": ["sketch_name"]},
    operation_class=OperationClass.MUTATE,
)
def revolve_surface(sw, sketch_name: str, angle: float = 360,
                    reverse: bool = False) -> dict:
    if (not isinstance(sketch_name, str) or not sketch_name.strip()
            or isinstance(angle, bool) or not isinstance(angle, (int, float))
            or not math.isfinite(angle) or not 0 < angle <= 360
            or not isinstance(reverse, bool)):
        return sw._result(False, "Invalid sketch, angle or direction.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "A revolved surface requires a part.",
                          SwErrors.swInvalidFileType)
    sketch = _find_feature(document, sketch_name)
    if sketch is None or com(sketch, "GetTypeName2") != "ProfileFeature":
        return sw._result(False, f"2D sketch not found: {sketch_name}",
                          SwErrors.swSelectionError)
    try:
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        if not com(sketch, "Select2", False, 0):
            return sw._result(False, f"Could not select sketch {sketch_name}.",
                              SwErrors.swSelectionError)
        # SW2025 IFeatureManager.InsertRevolvedRefSurface(Angle radians,
        # ReverseDir, Angle2 radians, RevType=0 one direction).
        feature = com(com(document, "FeatureManager"), "InsertRevolvedRefSurface",
                      math.radians(angle), reverse, 0.0, 0)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "RevolvRefSurf"]
        if not created:
            return sw._result(False, "SolidWorks did not create a revolved surface.",
                              SwErrors.swFeatureError)
        surface = feature or _find_feature(document, created[-1])
        if com(surface, "GetErrorCode"):
            return sw._result(False, "Revolved surface failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created revolved surface {created[-1]}.", data={
            "feature_name": created[-1], "sketch_name": sketch_name,
            "angle": angle, "reverse": reverse,
        })
    except Exception as create_error:
        return sw._result(False, f"Revolved surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="offset_surface",
    description="Create a parallel sheet from a named planar surface at a given offset.",
    schema={"type": "object", "properties": {
        "surface_name": {"type": "string", "minLength": 1},
        "distance": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "default": "mm"},
        "reverse": {"type": "boolean", "default": False},
    }, "required": ["surface_name", "distance"]},
    operation_class=OperationClass.MUTATE,
)
def offset_surface(sw, surface_name: str, distance: float, unit: str = "mm",
                   reverse: bool = False) -> dict:
    if (not isinstance(surface_name, str) or not surface_name.strip()
            or isinstance(distance, bool) or not isinstance(distance, (int, float))
            or not math.isfinite(distance) or distance <= 0
            or not isinstance(reverse, bool)):
        return sw._result(False, "Invalid source surface, offset or direction.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        distance_m = sw._units.to_meters(distance, unit)
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid offset unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Offset surface requires an active part.",
                          SwErrors.swInvalidFileType)
    source = _find_feature(document, surface_name)
    if source is None or com(source, "GetTypeName2") != "PlanarSurface":
        return sw._result(False, f"Planar surface not found: {surface_name}",
                          SwErrors.swSelectionError)
    try:
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        if not com(source, "Select2", False, 0):
            return sw._result(False, "Could not select source surface.",
                              SwErrors.swSelectionError)
        # SW2025 IModelDoc2.InsertOffsetSurface(Thickness metres, Reverse)
        # returns void: the new feature and its sheet body prove creation.
        com(document, "InsertOffsetSurface", distance_m, reverse)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "OffsetRefSurface"]
        if not created:
            return sw._result(False, "SolidWorks did not create an offset surface.",
                              SwErrors.swFeatureError)
        feature = _find_feature(document, created[-1])
        if com(feature, "GetErrorCode"):
            return sw._result(False, "Offset surface failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created offset surface {created[-1]}.", data={
            "feature_name": created[-1], "source_surface": surface_name,
            "distance": distance, "unit": unit, "reverse": reverse,
        })
    except Exception as create_error:
        return sw._result(False, f"Offset surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="knit_surface",
    description="Knit two or more touching named sheet-surface features into one sheet.",
    schema={"type": "object", "properties": {
        "surface_names": {"type": "array", "items": {"type": "string", "minLength": 1},
                          "minItems": 2, "uniqueItems": True},
        "merge_entities": {"type": "boolean", "default": True},
    }, "required": ["surface_names"]},
    operation_class=OperationClass.MUTATE,
)
def knit_surface(sw, surface_names: list[str], merge_entities: bool = True) -> dict:
    if (not isinstance(surface_names, list) or len(surface_names) < 2
            or any(not isinstance(name, str) or not name.strip() for name in surface_names)
            or len(set(surface_names)) != len(surface_names)
            or not isinstance(merge_entities, bool)):
        return sw._result(False, "Supply at least two distinct surface names.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Knit surface requires a part.",
                          SwErrors.swInvalidFileType)
    surfaces = [_find_feature(document, name) for name in surface_names]
    if any(feature is None or com(feature, "GetTypeName2") not in (
            "PlanarSurface", "OffsetRefSurface", "ExtruRefSurface", "RevolvRefSurf")
           for feature in surfaces):
        return sw._result(False, "One or more named surface features were not found.",
                          SwErrors.swSelectionError)
    try:
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        for index, feature in enumerate(surfaces):
            if not com(feature, "Select2", index > 0, 1):
                return sw._result(False, "Could not select all surfaces.",
                                  SwErrors.swSelectionError)
        # SW2025 IFeatureManager.InsertSewRefSurface, marks=1,
        # knit tolerance 0.01 mm (metres), no gap filters or solid conversion.
        result = com(com(document, "FeatureManager"), "InsertSewRefSurface",
                     False, False, merge_entities, 0.00001, 0.0)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "SewRefSurface"]
        if not created:
            return sw._result(False, "SolidWorks did not create a knit surface.",
                              SwErrors.swFeatureError)
        feature = result or _find_feature(document, created[-1])
        if com(feature, "GetErrorCode"):
            return sw._result(False, "Knit surface failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created knit surface {created[-1]}.", data={
            "feature_name": created[-1], "source_surfaces": surface_names,
            "merge_entities": merge_entities,
        })
    except Exception as create_error:
        return sw._result(False, f"Knit surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="cut_with_surface",
    description="Remove one side of a solid using a named planar sheet surface.",
    schema={"type": "object", "properties": {
        "surface_name": {"type": "string", "minLength": 1},
        "flip": {"type": "boolean", "default": False},
    }, "required": ["surface_name"]},
    operation_class=OperationClass.MUTATE,
)
def cut_with_surface(sw, surface_name: str, flip: bool = False) -> dict:
    if (not isinstance(surface_name, str) or not surface_name.strip()
            or not isinstance(flip, bool)):
        return sw._result(False, "Invalid surface name or direction.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Cut with surface requires a part.",
                          SwErrors.swInvalidFileType)
    surface = _find_feature(document, surface_name)
    if surface is None or com(surface, "GetTypeName2") != "PlanarSurface":
        return sw._result(False, f"Planar surface not found: {surface_name}",
                          SwErrors.swSelectionError)
    try:
        volume_before = _solid_volume_mm3(document)
        if volume_before <= 0:
            return sw._result(False, "No solid body to cut.", SwErrors.swSelectionError)
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        if not com(surface, "Select2", False, 0):
            return sw._result(False, "Could not select cutting surface.",
                              SwErrors.swSelectionError)
        # SW2025 IModelDoc2.InsertCutSurface(Flip, KeepPieceIndex);
        # -1 means no ambiguity about the retained side.
        com(document, "InsertCutSurface", flip, -1)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "SurfCut"]
        volume_after = _solid_volume_mm3(document)
        if not created or not 0 < volume_after < volume_before - 1e-6:
            return sw._result(False, "Surface cut did not remove solid volume.",
                              SwErrors.swFeatureError, {"volume_before_mm3": volume_before,
                                                       "volume_after_mm3": volume_after})
        feature = _find_feature(document, created[-1])
        if com(feature, "GetErrorCode"):
            return sw._result(False, "Surface cut failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created surface cut {created[-1]}.", data={
            "feature_name": created[-1], "surface_name": surface_name,
            "flip": flip, "volume_before_mm3": volume_before,
            "volume_after_mm3": volume_after,
        })
    except Exception as create_error:
        return sw._result(False, f"Surface cut failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="extend_surface",
    description="Linearly extend one edge of a sheet surface by a given distance.",
    schema={"type": "object", "properties": {
        "sheet_index": {"type": "integer", "minimum": 0},
        "edge_index": {"type": "integer", "minimum": 0},
        "distance": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                 "default": "mm"},
    }, "required": ["sheet_index", "edge_index", "distance"]},
    operation_class=OperationClass.MUTATE,
)
def extend_surface(sw, sheet_index: int, edge_index: int, distance: float,
                   unit: str = "mm") -> dict:
    if (isinstance(sheet_index, bool) or not isinstance(sheet_index, int)
            or sheet_index < 0 or isinstance(edge_index, bool)
            or not isinstance(edge_index, int) or edge_index < 0
            or isinstance(distance, bool) or not isinstance(distance, (int, float))
            or not math.isfinite(distance) or distance <= 0):
        return sw._result(False, "Invalid sheet, edge or distance.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        distance_m = sw._units.to_meters(distance, unit)
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid extension unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Extend surface requires a part.",
                          SwErrors.swInvalidFileType)
    try:
        sheets = com(document, "GetBodies2", 1, True) or []
        if sheet_index >= len(sheets):
            return sw._result(False, "Sheet body index out of range.",
                              SwErrors.swInvalidInput)
        edges = com(sheets[sheet_index], "GetEdges") or []
        if edge_index >= len(edges):
            return sw._result(False, "Sheet edge index out of range.",
                              SwErrors.swInvalidInput)
        before, proxies = _feature_signatures(document)
        del proxies
        com(document, "ClearSelection2", True)
        selection = com(com(document, "SelectionManager"), "CreateSelectData")
        selection.Mark = 0
        if not com(edges[edge_index], "Select4", False, selection):
            return sw._result(False, "Could not select sheet edge.",
                              SwErrors.swSelectionError)
        # SW2025 IModelDoc2.InsertExtendSurface(ExtendLinear,EndCondition,Distance)
        com(document, "InsertExtendSurface", True, 0, distance_m)
        after, proxies = _feature_signatures(document)
        del proxies
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "ExtendRefSurface"]
        if not created:
            return sw._result(False, "SolidWorks did not extend the surface.",
                              SwErrors.swFeatureError)
        feature = _find_feature(document, created[-1])
        if com(feature, "GetErrorCode"):
            return sw._result(False, "Extended surface failed to rebuild.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Extended surface {created[-1]}.", data={
            "feature_name": created[-1], "sheet_index": sheet_index,
            "edge_index": edge_index, "distance": distance, "unit": unit,
        })
    except Exception as create_error:
        return sw._result(False, f"Extend surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="ruled_surface",
    description="Create a tangent ruled sheet from one selected sheet-body edge.",
    schema={"type": "object", "properties": {
        "sheet_index": {"type": "integer", "minimum": 0},
        "edge_index": {"type": "integer", "minimum": 0},
        "length": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
    }, "required": ["sheet_index", "edge_index", "length"]},
    operation_class=OperationClass.MUTATE,
)
def ruled_surface(sw, sheet_index: int, edge_index: int, length: float,
                  unit: str = "mm") -> dict:
    if (isinstance(sheet_index, bool) or not isinstance(sheet_index, int)
            or sheet_index < 0 or isinstance(edge_index, bool)
            or not isinstance(edge_index, int) or edge_index < 0
            or isinstance(length, bool) or not isinstance(length, (int, float))
            or not math.isfinite(length) or length <= 0):
        return sw._result(False, "Invalid sheet, edge or ruled length.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        length_m = sw._units.to_meters(length, unit)
    except (KeyError, ValueError, TypeError) as conversion_error:
        return sw._result(False, f"Invalid ruled-surface unit: {conversion_error}",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Ruled surface requires a part.",
                          SwErrors.swInvalidFileType)
    try:
        sheets = com(document, "GetBodies2", 1, True) or []
        if sheet_index >= len(sheets):
            return sw._result(False, "Sheet body index out of range.", SwErrors.swInvalidInput)
        edges = com(sheets[sheet_index], "GetEdges") or []
        if edge_index >= len(edges):
            return sw._result(False, "Sheet edge index out of range.", SwErrors.swInvalidInput)
        area_before = sum(com(face, "GetArea") * 1e6 for body in sheets
                          for face in (com(body, "GetFaces") or []))
        com(document, "ClearSelection2", True)
        select_data = com(com(document, "SelectionManager"), "CreateSelectData")
        select_data.Mark = 4  # Default adjacent face (SW2025 API Help).
        if not com(edges[edge_index], "Select4", False, select_data):
            return sw._result(False, "Could not select ruled edge.", SwErrors.swSelectionError)
        feature = com(com(document, "FeatureManager"), "InsertRuledSurfaceFromEdge2",
                      0, length_m, False, False, False, 0.0, False,
                      0.0, 0.0, 0.0, False)
        after = com(document, "GetBodies2", 1, True) or []
        area_after = sum(com(face, "GetArea") * 1e6 for body in after
                         for face in (com(body, "GetFaces") or []))
        if feature is None or area_after <= area_before + 1e-3:
            return sw._result(False, "Ruled surface did not add sheet area.",
                              SwErrors.swFeatureError, {"area_before_mm2": area_before,
                                                       "area_after_mm2": area_after})
        return sw._result(True, f"Created ruled surface {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")), "sheet_index": sheet_index,
            "edge_index": edge_index, "area_before_mm2": area_before,
            "area_after_mm2": area_after,
        })
    except Exception as create_error:
        return sw._result(False, f"Ruled surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="loft_surface",
    description="Create an open lofted sheet through two ordered 2D profile sketches.",
    schema={"type": "object", "properties": {
        "profile_sketches": {"type": "array", "items": {"type": "string", "minLength": 1},
                             "minItems": 2, "maxItems": 2},
    }, "required": ["profile_sketches"]},
    operation_class=OperationClass.MUTATE,
)
def loft_surface(sw, profile_sketches: list[str]) -> dict:
    if (not isinstance(profile_sketches, list) or len(profile_sketches) != 2
            or any(not isinstance(name, str) or not name.strip()
                   for name in profile_sketches)
            or profile_sketches[0] == profile_sketches[1]):
        return sw._result(False, "Supply two distinct sketch names.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Surface loft requires a part.", SwErrors.swInvalidFileType)
    profiles = [_find_feature(document, name) for name in profile_sketches]
    if any(feature is None or com(feature, "GetTypeName2") != "ProfileFeature"
           for feature in profiles):
        return sw._result(False, "At least one 2D profile sketch was not found.",
                          SwErrors.swSelectionError)
    try:
        before = com(document, "GetBodies2", 1, True) or []
        signatures_before, retained = _feature_signatures(document)
        del retained
        com(document, "ClearSelection2", True)
        for index, profile in enumerate(profiles):
            if not com(profile, "Select2", index > 0, 1):
                return sw._result(False, "Could not select loft profile.",
                                  SwErrors.swSelectionError)
        # SW2025 IModelDoc2.InsertLoftRefSurface(Closed,KeepTangency,ForceNonRational)
        com(document, "InsertLoftRefSurface", False, False, False)
        signatures_after, retained = _feature_signatures(document)
        del retained
        created = [name for name, kind in signatures_after
                   if (name, kind) not in signatures_before and kind == "BlendRefSurface"]
        feature = _find_feature(document, created[-1]) if created else None
        after = com(document, "GetBodies2", 1, True) or []
        area_after = sum(com(face, "GetArea") * 1e6 for body in after
                         for face in (com(body, "GetFaces") or []))
        if (feature is None or len(after) <= len(before) or area_after <= 0
                or com(feature, "GetErrorCode")):
            return sw._result(False, "Surface loft did not create a valid sheet.",
                              SwErrors.swFeatureError, {"sheets_before": len(before),
                                                       "sheets_after": len(after),
                                                       "area_after_mm2": area_after})
        return sw._result(True, f"Created surface loft {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")),
            "profile_sketches": profile_sketches, "sheets_before": len(before),
            "sheets_after": len(after), "area_after_mm2": area_after,
        })
    except Exception as create_error:
        return sw._result(False, f"Surface loft failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="sweep_surface",
    description="Sweep a 2D profile along a separate path sketch into an open sheet.",
    schema={"type": "object", "properties": {
        "profile_sketch": {"type": "string", "minLength": 1},
        "path_sketch": {"type": "string", "minLength": 1},
    }, "required": ["profile_sketch", "path_sketch"]},
    operation_class=OperationClass.MUTATE,
)
def sweep_surface(sw, profile_sketch: str, path_sketch: str) -> dict:
    if (not isinstance(profile_sketch, str) or not profile_sketch.strip()
            or not isinstance(path_sketch, str) or not path_sketch.strip()
            or profile_sketch == path_sketch):
        return sw._result(False, "Supply distinct profile and path sketches.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Surface sweep requires a part.", SwErrors.swInvalidFileType)
    profile = _find_feature(document, profile_sketch)
    path = _find_feature(document, path_sketch)
    if any(feature is None or com(feature, "GetTypeName2") != "ProfileFeature"
           for feature in (profile, path)):
        return sw._result(False, "Profile or path sketch not found.",
                          SwErrors.swSelectionError)
    try:
        sheets_before = com(document, "GetBodies2", 1, True) or []
        before, retained = _feature_signatures(document)
        del retained
        com(document, "ClearSelection2", True)
        if not com(profile, "Select2", False, 1) or not com(path, "Select2", True, 4):
            return sw._result(False, "Could not select sweep profile or path.",
                              SwErrors.swSelectionError)
        # SW2025 IModelDoc2.InsertSweepRefSurface(Propagate,TwistCtrlOption,
        # KeepTangency,ForceNonRational) returns void.
        com(document, "InsertSweepRefSurface", False, 0, False, False)
        after, retained = _feature_signatures(document)
        del retained
        created = [name for name, kind in after if (name, kind) not in before
                   and kind == "SweepRefSurface"]
        feature = _find_feature(document, created[-1]) if created else None
        sheets_after = com(document, "GetBodies2", 1, True) or []
        area = sum(com(face, "GetArea") * 1e6 for body in sheets_after
                   for face in (com(body, "GetFaces") or []))
        if (feature is None or len(sheets_after) <= len(sheets_before) or area <= 0
                or com(feature, "GetErrorCode")):
            return sw._result(False, "Surface sweep did not create a valid sheet.",
                              SwErrors.swFeatureError, {"sheets_before": len(sheets_before),
                                                       "sheets_after": len(sheets_after),
                                                       "area_after_mm2": area})
        return sw._result(True, f"Created surface sweep {created[-1]}.", data={
            "feature_name": created[-1], "profile_sketch": profile_sketch,
            "path_sketch": path_sketch, "sheets_after": len(sheets_after),
            "area_after_mm2": area,
        })
    except Exception as create_error:
        return sw._result(False, f"Surface sweep failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="filled_surface",
    description=("Fill a closed 2D sketch boundary with a filled surface patch. "
                 "Supply its exact feature name."),
    schema={"type": "object", "properties": {
        "sketch_name": {"type": "string", "minLength": 1},
    }, "required": ["sketch_name"]},
    operation_class=OperationClass.MUTATE,
)
def filled_surface(sw, sketch_name: str) -> dict:
    if not isinstance(sketch_name, str) or not sketch_name.strip():
        return sw._result(False, "sketch_name must be a non-empty name.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "A filled surface requires an active part.",
                          SwErrors.swInvalidFileType)
    sketch = _find_feature(document, sketch_name)
    if sketch is None or com(sketch, "GetTypeName2") != "ProfileFeature":
        return sw._result(False, f"2D sketch not found: {sketch_name}",
                          SwErrors.swSelectionError)
    try:
        segments = com(com(sketch, "GetSpecificFeature2"), "GetSketchSegments") or []
        if not segments:
            return sw._result(False, "The selected sketch has no boundary segments.",
                              SwErrors.swInvalidInput)
        sheets_before = com(document, "GetBodies2", 1, True) or []
        com(document, "ClearSelection2", True)
        # InsertFillSurface only recognizes a boundary picked through
        # SelectByID2("...", "SKETCH", ..., Mark=1) -- selecting the sketch
        # feature object directly (Select2) or its segments (Select4) is
        # silently ignored and the call returns Nothing (live-verified).
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        if not com(document.Extension, "SelectByID2", sketch_name, "SKETCH",
                   0.0, 0.0, 0.0, False, 1, callout, 0):
            return sw._result(False, "Could not select the sketch boundary.",
                              SwErrors.swSelectionError)
        # SW2025 IFeatureManager.InsertFillSurface(Options) -> IFeature;
        # Options=0 leaves every swFeatureFillSurfaceOptions_e flag off.
        feature = com(com(document, "FeatureManager"), "InsertFillSurface", 0)
        sheets_after = com(document, "GetBodies2", 1, True) or []
        area_after = sum(com(face, "GetArea") * 1e6 for body in sheets_after
                         for face in (com(body, "GetFaces") or []))
        if (feature is None or len(sheets_after) <= len(sheets_before)
                or area_after <= 0 or com(feature, "GetErrorCode")):
            return sw._result(False, "Filled surface did not create a valid patch.",
                              SwErrors.swFeatureError, {"sheets_before": len(sheets_before),
                                                       "sheets_after": len(sheets_after),
                                                       "area_after_mm2": area_after})
        return sw._result(True, f"Created filled surface {com(feature, 'Name')}.", data={
            "feature_name": str(com(feature, "Name")), "sketch_name": sketch_name,
            "boundary_segments": len(segments), "sheets_after": len(sheets_after),
            "area_after_mm2": area_after,
        })
    except Exception as create_error:
        return sw._result(False, f"Filled surface failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)
