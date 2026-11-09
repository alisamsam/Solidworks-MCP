"""Reference geometry creation tools."""

import math

import pythoncom
import win32com.client

from ..comutil import com, set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


SW_REF_PLANE_DISTANCE = 8
SW_REF_PLANE_DISTANCE_REVERSED = 264

@tool(name='create_sketch_on_planar_face',
      description='Create a sketch on the exact native planar face index from list_planar_faces. Avoids ambiguous coordinate selection.',
      schema={'type':'object','properties':{'face_index':{'type':'integer','minimum':0},'exact_geometry':{'type':'boolean','default':False}},'required':['face_index']},
      operation_class=OperationClass.MUTATE)
def create_sketch_on_planar_face(sw,face_index,exact_geometry=False):
    if isinstance(face_index,bool) or not isinstance(face_index,int) or face_index<0 or not isinstance(exact_geometry,bool):
        return sw._result(False,'Invalid face index or exact_geometry flag.',SwErrors.swInvalidInput)
    doc,error=sw.get_active_doc()
    if error:return error
    from .export import _get_planar_face_by_index
    try:
        if int(com(doc,'GetType'))!=1 or com(doc,'GetActiveSketch2') is not None:
            return sw._result(False,'Requires a part with no active sketch.',SwErrors.swInvalidInput)
        face=_get_planar_face_by_index(doc,face_index)
        if face is None:return sw._result(False,'Face index is missing or non-planar.',SwErrors.swInvalidInput)
        com(doc,'ClearSelection2',True)
        if not com(face,'Select4',False,win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)):
            return sw._result(False,'Native face selection failed.',SwErrors.swSelectionError)
        com(doc,'InsertSketch2',True)
        sketch=com(doc,'GetActiveSketch2')
        if sketch is None:return sw._result(False,'No sketch was created.',SwErrors.swSketchError)
        tf=list(com(com(sketch,'ModelToSketchTransform'),'ArrayData'))
        point=list(com(com(face,'GetSurface'),'PlaneParams')[3:6])
        residual=sum(point[j]*tf[j*3+2] for j in range(3))+tf[11]
        if abs(residual)>1e-7:
            return sw._result(False,'Sketch does not lie on the selected face plane.',SwErrors.swSketchError)
        set_com(com(doc,'SketchManager'),'AddToDB',exact_geometry)
        return sw._result(True,'Sketch created on the exact native planar face.',data={'face_index':face_index,'model_to_sketch_transform':tf,'plane_residual_m':residual,'exact_geometry':exact_geometry})
    except Exception as exc:
        return sw._result(False,f'Indexed face sketch failed: {exc}',SwErrors.swSketchError)

#: Degrees -> radians, for the coordinate-system rotation parameters.
_DEGREES_TO_RADIANS = math.pi / 180.0


def _rotation_matrix(x: float, y: float, z: float):
    """Return Rx(x) @ Ry(y) @ Rz(z), the rotation SW applies to a numeric CS."""
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    return (
        (cy * cz, -cy * sz, sy),
        (sx * sy * cz + cx * sz, -sx * sy * sz + cx * cz, -sx * cy),
        (-cx * sy * cz + sx * sz, cx * sy * sz + sx * cz, cx * cy),
    )


def _matmul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def _matvec(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def _transpose(a):
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))


@tool(
    name="create_reference_axis",
    description="Create an axis along the intersection of two distinct, exactly named planes.",
    schema={"type": "object", "properties": {
        "first_plane": {"type": "string", "minLength": 1},
        "second_plane": {"type": "string", "minLength": 1},
    }, "required": ["first_plane", "second_plane"]},
    operation_class=OperationClass.MUTATE,
)
def create_reference_axis(sw, first_plane: str, second_plane: str) -> dict:
    if (not isinstance(first_plane, str) or not first_plane.strip()
            or not isinstance(second_plane, str) or not second_plane.strip()
            or first_plane.strip() == second_plane.strip()):
        return sw._result(False, "Select two distinct named planes.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "An axis requires a part.", SwErrors.swInvalidFileType)
    def axes():
        found = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "RefAxis":
                found.append(str(com(feature, "Name")))
            feature = com(feature, "GetNextFeature")
        return found
    try:
        before = axes()
        com(document, "ClearSelection2", True)
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        extension = com(document, "Extension")
        for index, name in enumerate((first_plane, second_plane)):
            if not com(extension, "SelectByID2", name, "PLANE", 0.0, 0.0, 0.0,
                       index > 0, 0, empty, 0):
                return sw._result(False, f"Plane not found: {name}",
                                  SwErrors.swSelectionError)
        inserted = com(document, "InsertAxis2", True)
        created = [name for name in axes() if name not in before]
        if not inserted or not created:
            return sw._result(False, "SolidWorks did not create a reference axis.",
                              SwErrors.swFeatureError)
        return sw._result(True, f"Created reference axis {created[-1]}.", data={
            "feature_name": created[-1], "first_plane": first_plane,
            "second_plane": second_plane,
        })
    except Exception as create_error:
        return sw._result(False, f"Reference axis failed: {create_error}",
                          SwErrors.swFeatureError)
    finally:
        com(document, "ClearSelection2", True)


@tool(
    name="create_reference_plane",
    description="Create an offset reference plane from one exactly named existing plane.",
    schema={"type": "object", "properties": {
        "base_plane": {"type": "string", "description": "Exact plane name from list_planes."},
        "offset": {"type": "number", "exclusiveMinimum": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
        "reverse_direction": {"type": "boolean", "default": False},
    }, "required": ["base_plane", "offset"]},
    operation_class=OperationClass.MUTATE,
)
def create_reference_plane(sw, base_plane: str, offset: float, unit: str = "mm",
                           reverse_direction: bool = False) -> dict:
    if (
        not isinstance(base_plane, str)
        or not base_plane.strip()
        or isinstance(offset, bool)
        or not isinstance(offset, (int, float))
        or not math.isfinite(offset)
        or offset <= 0
    ):
        return sw._result(
            False,
            "base_plane must be non-empty and offset must be a finite positive number.",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    try:
        offset_m = sw._units.to_meters(offset, unit)
    except (KeyError, TypeError, ValueError) as conversion_error:
        return sw._result(
            False,
            f"Invalid reference-plane offset: {conversion_error}",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    document, error = sw.get_active_doc()
    if error:
        return error

    try:
        com(document, "ClearSelection2", True)
        extension = com(document, "Extension")
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        selected = com(
            extension,
            "SelectByID2",
            base_plane,
            "PLANE",
            0.0,
            0.0,
            0.0,
            False,
            0,
            empty,
            0,
        )
        if not selected:
            return sw._result(
                False,
                f"Reference plane not found by exact name: {base_plane}",
                SwErrors.swSelectionError,
            )

        constraint = (
            SW_REF_PLANE_DISTANCE_REVERSED
            if reverse_direction
            else SW_REF_PLANE_DISTANCE
        )
        feature_manager = com(document, "FeatureManager")
        reference_plane = com(
            feature_manager, "InsertRefPlane", constraint, offset_m, 0, 0, 0, 0
        )
        if reference_plane is None:
            return sw._result(
                False,
                "SolidWorks did not create the reference plane.",
                SwErrors.swFeatureError,
            )
    except Exception as create_error:
        return sw._result(
            False,
            f"Reference plane creation failed: {create_error}",
            SwErrors.swFeatureError,
        )
    finally:
        com(document, "ClearSelection2", True)

    return sw._result(
        True,
        f"Created an offset reference plane from {base_plane}.",
        data={
            "base_plane": base_plane,
            "offset": offset,
            "unit": unit,
            "offset_m": offset_m,
            "reverse_direction": reverse_direction,
            "constraint": constraint,
            "next_step": "Call list_planes to read the generated plane name.",
        },
    )


@tool(
    name="create_coordinate_system",
    description=(
        "Create a named coordinate system at a numeric origin offset with an "
        "optional XYZ rotation of the part axes."
    ),
    schema={"type": "object", "properties": {
        "x_offset": {"type": "number", "default": 0},
        "y_offset": {"type": "number", "default": 0},
        "z_offset": {"type": "number", "default": 0},
        "unit": {"type": "string", "enum": ["mm", "cm", "m", "inch"], "default": "mm"},
        "rotate_x": {"type": "number", "default": 0},
        "rotate_y": {"type": "number", "default": 0},
        "rotate_z": {"type": "number", "default": 0},
        "angle_unit": {"type": "string", "enum": ["deg", "rad"], "default": "deg"},
        "name": {"type": "string", "minLength": 1,
                 "description": "Optional feature name; defaults to SolidWorks' own name."},
    }},
    operation_class=OperationClass.MUTATE,
)
def create_coordinate_system(sw, x_offset: float = 0.0, y_offset: float = 0.0,
                             z_offset: float = 0.0, unit: str = "mm",
                             rotate_x: float = 0.0, rotate_y: float = 0.0,
                             rotate_z: float = 0.0, angle_unit: str = "deg",
                             name: str | None = None) -> dict:
    offsets = (x_offset, y_offset, z_offset)
    angles = (rotate_x, rotate_y, rotate_z)
    if (
        any(isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in offsets + angles)
        or angle_unit not in ("deg", "rad")
        or (name is not None and (not isinstance(name, str) or not name.strip()))
    ):
        return sw._result(
            False,
            "Offsets and rotations must be finite numbers, angle_unit must be "
            "deg or rad, and name must be a non-empty string.",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    try:
        offsets_m = tuple(sw._units.to_meters(float(value), unit) for value in offsets)
    except (KeyError, TypeError, ValueError) as conversion_error:
        return sw._result(
            False,
            f"Invalid coordinate-system unit or offset: {conversion_error}",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    angle_factor = _DEGREES_TO_RADIANS if angle_unit == "deg" else 1.0
    angles_rad = tuple(float(value) * angle_factor for value in angles)

    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "A coordinate system requires a part.",
                          SwErrors.swInvalidFileType)

    def existing_coordinate_systems():
        found = []
        feature = com(document, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "CoordSys":
                found.append(str(com(feature, "Name")))
            feature = com(feature, "GetNextFeature")
        return found

    try:
        before = existing_coordinate_systems()
        if name is not None and name.strip() in before:
            return sw._result(
                False, f"A coordinate system named {name.strip()} already exists.",
                SwErrors.swInvalidInput, {"code": "NAME_IN_USE"},
            )

        # SolidWorks interprets DeltaX/Y/Z in the rotated frame, so pre-rotate
        # the requested model-space origin by M^2 to land the origin exactly
        # where the caller asked (verified live; see docs/api-findings.md).
        rotation = _rotation_matrix(*angles_rad)
        delta = _matvec(_matmul(rotation, rotation), offsets_m)

        feature = com(
            com(document, "FeatureManager"),
            "CreateCoordinateSystemUsingNumericalValues",
            True, delta[0], delta[1], delta[2],
            any(angles_rad), angles_rad[0], angles_rad[1], angles_rad[2],
        )
        created = [item for item in existing_coordinate_systems() if item not in before]
        if feature is None or not created:
            return sw._result(False, "SolidWorks did not create a coordinate system.",
                              SwErrors.swFeatureError)

        feature_name = created[-1]
        if name is not None and name.strip() != feature_name:
            set_com(feature, "Name", name.strip())
            renamed = str(com(feature, "Name"))
            if renamed != name.strip():
                return sw._result(
                    False, "SolidWorks did not accept the requested name.",
                    SwErrors.swFeatureError)
            feature_name = renamed

        transform = com(document, "GetCoordinateSystemXformByName", feature_name)
        if transform is None or len(transform) < 12:
            return sw._result(
                False, "Could not read back the coordinate-system transform.",
                SwErrors.swFeatureError)
        values = [float(value) for value in transform]
        rotation_read = (tuple(values[0:3]), tuple(values[3:6]), tuple(values[6:9]))
        translation = tuple(values[9:12])
        origin_m = tuple(-value for value in _matvec(_transpose(rotation_read), translation))
        axes = rotation_read  # rows are the coordinate-system axes in model space
        factor = sw._units.to_meters(1.0, unit)
        origin = tuple(value / factor for value in origin_m)

        return sw._result(
            True,
            f"Created coordinate system {feature_name}.",
            data={
                "feature_name": feature_name,
                "origin": [round(value, 9) for value in origin],
                "origin_m": [round(value, 9) for value in origin_m],
                "unit": unit,
                "axes": [[round(value, 9) for value in axis] for axis in axes],
                "transform": [round(value, 12) for value in values],
                "requested_offsets": list(offsets),
                "requested_angles_rad": list(angles_rad),
                "angle_unit": angle_unit,
                "next_step": "Use the returned axes/origin as a reference frame.",
            },
        )
    except Exception as create_error:
        return sw._result(False, f"Coordinate system creation failed: {create_error}",
                          SwErrors.swFeatureError)
