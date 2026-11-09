"""Read-only geometric and physical measurements."""

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


_LENGTH_FACTORS = {
    "m": 1.0,
    "cm": 100.0,
    "mm": 1000.0,
    "inch": 39.37007874015748,
}


def _get_planar_face_by_index(doc, face_index: int):
    """Resolve the same all-face index exposed by list_planar_faces."""
    if not isinstance(face_index, int) or isinstance(face_index, bool) or face_index < 0:
        return None
    index = 0
    for body in com(doc, "GetBodies2", 0, True) or []:
        for face in com(body, "GetFaces") or []:
            if index == face_index:
                surface = com(face, "GetSurface")
                return face if surface is not None and com(surface, "IsPlane") else None
            index += 1
    return None


@tool(
    name="measure_distance",
    description=(
        "Measure the kernel minimum distance between two planar faces by their "
        "current list_planar_faces indexes. Re-list faces after model changes."
    ),
    schema={"type": "object", "properties": {
        "face_index1": {"type": "integer", "minimum": 0},
        "face_index2": {"type": "integer", "minimum": 0},
        "length_unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"],
                        "default": "mm"},
    }, "required": ["face_index1", "face_index2"]},
    operation_class=OperationClass.READ,
)
def measure_distance(sw, face_index1: int, face_index2: int,
                     length_unit: str = "mm") -> dict:
    """Return minimum face-to-face distance, axis deltas, and relation flags."""
    if length_unit not in _LENGTH_FACTORS:
        return sw._result(False, f"Unsupported length unit: {length_unit}",
                          SwErrors.swInvalidInput)
    if face_index1 == face_index2:
        return sw._result(False, "Two different planar face indexes are required.",
                          SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    first = _get_planar_face_by_index(doc, face_index1)
    second = _get_planar_face_by_index(doc, face_index2)
    if first is None or second is None:
        return sw._result(False,
                          "A face index is missing or no longer refers to a planar face; run list_planar_faces again.",
                          SwErrors.swSelectionError)

    doc.ClearSelection2(True)
    try:
        empty_select_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        if not com(first, "Select4", False, empty_select_data):
            return sw._result(False, f"Could not select planar face {face_index1}.",
                              SwErrors.swSelectionError)
        if not com(second, "Select4", True, empty_select_data):
            return sw._result(False, f"Could not select planar face {face_index2}.",
                              SwErrors.swSelectionError)

        measure = com(com(doc, "Extension"), "CreateMeasure")
        if measure is None:
            return sw._result(False, "SolidWorks could not create the measurement object.",
                              SwErrors.swUnknownError)
        # SW 2025 dynamic dispatch exposes Calculate as a property unless it is
        # explicitly marked as a method. The supported VBA/API path measures the
        # currently selected entities by passing NULL.
        measure._FlagAsMethod("Calculate")
        if not measure.Calculate(None):
            return sw._result(False, "SolidWorks could not calculate the face distance.",
                              SwErrors.swUnknownError)

        factor = _LENGTH_FACTORS[length_unit]
        distance_m = float(com(measure, "Distance"))
        normal_m = float(com(measure, "NormalDistance"))
        delta_m = {
            "x": float(com(measure, "DeltaX")),
            "y": float(com(measure, "DeltaY")),
            "z": float(com(measure, "DeltaZ")),
        }
        data = {
            "distance": distance_m * factor,
            "normal_distance": normal_m * factor,
            "delta": {axis: value * factor for axis, value in delta_m.items()},
            "unit": length_unit,
            "distance_kind": "minimum",
            "accuracy": "kernel",
            "method": "IMeasure.Calculate(selected planar faces)",
            "is_intersecting": bool(com(measure, "IsIntersect")),
            "is_parallel": bool(com(measure, "IsParallel")),
            "face_indexes": [face_index1, face_index2],
        }
        return sw._result(True,
                          f"Minimum distance: {data['distance']:.6f} {length_unit}",
                          data=data)
    finally:
        doc.ClearSelection2(True)


@tool(
    name="get_body_bounding_box",
    description="Read approximate per-body and combined bounding boxes for the active part.",
    schema={"type": "object", "properties": {
        "length_unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
        "visible_only": {"type": "boolean", "default": True},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def get_body_bounding_box(sw, length_unit: str = "mm", visible_only: bool = True) -> dict:
    """Return approximate boxes; callers must not treat them as tolerance measurements."""
    if length_unit not in _LENGTH_FACTORS:
        return sw._result(False, f"Unsupported length unit: {length_unit}", SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    bodies = com(doc, "GetBodies2", 0, visible_only) or []
    if not bodies:
        return sw._result(False, "No solid bodies found.", SwErrors.swUnknownError)

    factor = _LENGTH_FACTORS[length_unit]
    entries = []
    boxes = []
    for index, body in enumerate(bodies):
        box = [float(value) for value in com(body, "GetBodyBox")]
        boxes.append(box)
        try:
            name = com(body, "Name")
        except Exception:
            name = f"Body{index + 1}"
        entries.append({
            "name": name,
            "min": {"x": box[0] * factor, "y": box[1] * factor, "z": box[2] * factor},
            "max": {"x": box[3] * factor, "y": box[4] * factor, "z": box[5] * factor},
            "size": {"x": (box[3] - box[0]) * factor,
                     "y": (box[4] - box[1]) * factor,
                     "z": (box[5] - box[2]) * factor},
        })
    combined = [min(box[i] for box in boxes) for i in range(3)] + [
        max(box[i] for box in boxes) for i in range(3, 6)]
    data = {
        "unit": length_unit,
        "accuracy": "approximate",
        "method": "IBody2.GetBodyBox",
        "visible_only": visible_only,
        "bodies": entries,
        "combined": {
            "min": {"x": combined[0] * factor, "y": combined[1] * factor, "z": combined[2] * factor},
            "max": {"x": combined[3] * factor, "y": combined[4] * factor, "z": combined[5] * factor},
            "size": {"x": (combined[3] - combined[0]) * factor,
                     "y": (combined[4] - combined[1]) * factor,
                     "z": (combined[5] - combined[2]) * factor},
        },
    }
    return sw._result(True, f"Approximate bounding box for {len(entries)} body/bodies.", data=data)


@tool(
    name="get_mass_properties",
    description="Read volume, area, mass, density, and center of mass without modifying the active model.",
    schema={"type": "object", "properties": {
        "length_unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def get_mass_properties(sw, length_unit: str = "mm") -> dict:
    """Return SI source values plus explicit display-unit conversions."""
    if length_unit not in _LENGTH_FACTORS:
        return sw._result(False, f"Unsupported length unit: {length_unit}", SwErrors.swInvalidInput)
    doc, err = sw.get_active_doc()
    if err:
        return err
    mass_property = com(com(doc, "Extension"), "CreateMassProperty")
    if mass_property is None:
        return sw._result(False, "SolidWorks could not calculate mass properties.",
                          SwErrors.swUnknownError)

    volume_m3 = float(com(mass_property, "Volume"))
    area_m2 = float(com(mass_property, "SurfaceArea"))
    mass_kg = float(com(mass_property, "Mass"))
    density_kg_m3 = float(com(mass_property, "Density"))
    center_m = [float(value) for value in com(mass_property, "CenterOfMass")]
    factor = _LENGTH_FACTORS[length_unit]
    data = {
        "si": {
            "volume_m3": volume_m3,
            "surface_area_m2": area_m2,
            "mass_kg": mass_kg,
            "center_of_mass_m": center_m,
        },
        "display": {
            "volume": volume_m3 * factor ** 3,
            "volume_unit": f"{length_unit}^3",
            "surface_area": area_m2 * factor ** 2,
            "surface_area_unit": f"{length_unit}^2",
            "center_of_mass": [value * factor for value in center_m],
            "center_of_mass_unit": length_unit,
        },
        "material_evidence": {
            "density_kg_m3": density_kg_m3,
            "source": "IMassProperty",
            "material_name": None,
            "material_name_status": "not_inspected",
        },
        "method": "SolidWorks IMassProperty",
    }
    return sw._result(True, f"Volume: {data['display']['volume']:.3f} {length_unit}^3",
                      data=data)
