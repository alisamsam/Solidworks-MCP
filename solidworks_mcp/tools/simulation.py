"""
SOLIDWORKS Simulation static-study workflow.

The Simulation API lives in the ``SldWorks.Simulation`` add-in, which must be
loaded by the user (Tools > Add-ins). Every entry point therefore resolves the
add-in first and returns a clear ``SIMULATION_UNAVAILABLE`` failure instead of
raising when it is missing.

COM signatures, enum values and the official "Analyze Part" recipe were taken
from the installed ``cosworks.tlb`` type library and ``cworksapi.chm``; see
docs/upgrade/research-simulation-api.md.  Every output parameter of the add-in
is a ``ByRef`` variant in pywin32 terms, so it must be passed as
``VARIANT(VT_BYREF | VT_I4/VT_R8, ...)`` or the call fails with "Type
mismatch".
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pythoncom
from win32com.client import VARIANT

from ..comutil import com, set_com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .export import _get_planar_face_by_index

SIMULATION_ADDIN_PROGID = "SldWorks.Simulation"

# swsAnalysisStudyType_e / swsMeshType_e
SW_SIM_STUDY_STATIC = 0
SW_SIM_MESH_SOLID = 0
SW_SIM_MESH_BEAM = 4

# swsRestraintType_e
SW_SIM_RESTRAINT_FIXED = 0

#: Standard gravity in m/s^2, used to turn a mass load into a force.
SW_SIM_GRAVITY = 9.80665

# swsForceType_e / swsSelectionType_e
SW_SIM_FORCE_NORMAL = 1
SW_SIM_FORCE_TORQUE = 2
SW_SIM_SELECTION_FACE_EDGE_VERTEX_POINT = 0

#: Newtons per unit accepted by ``apply_force_load``. kN and kgf are forces;
#: kg and t are masses whose weight (m * g) is applied.
SW_SIM_FORCE_UNITS = {
    "n": 1.0,
    "kn": 1000.0,
    "kgf": SW_SIM_GRAVITY,
    "kg": SW_SIM_GRAVITY,
    "t": 1000.0 * SW_SIM_GRAVITY,
}

# swsPressureType_e
SW_SIM_PRESSURE_NORMAL = 0

#: Pascal per unit accepted by ``apply_pressure_load``.
SW_SIM_PRESSURE_UNITS = {
    "pa": 1.0,
    "kpa": 1e3,
    "mpa": 1e6,
    "n/mm2": 1e6,
    "n/mm²": 1e6,
    "bar": 1e5,
    "kgf/cm2": 98066.5,
    "psi": 6894.757293168361,
    "ksi": 6894757.293168361,
}

#: The add-in ignores writes to ``ICWPressure.Unit`` inside the edit block
#: (verified live: the unit stays Pascal), so the value is converted into the
#: unit the load reports instead. Maps ``swsStrengthUnit_e`` to pascal.
SW_SIM_PRESSURE_ADDIN_UNITS = {
    0: 1.0,                # swsStrengthUnitPascal
    1: 6894.757293168361,  # swsStrengthUnitPSI
    2: 98066.5,            # swsStrengthUnitKilogramsPerSquareCentimeter
    3: 1e6,                # swsStrengthUnitNewtonPerSquareMillimeter
    4: 6894757.293168361,  # swsStrengthUnitKSI
}

SW_SIM_PRESSURE_UNIT_NAMES = {
    0: "Pa", 1: "psi", 2: "kgf/cm2", 3: "N/mm2", 4: "ksi",
}

#: Spellings offered by the tool schema. The lookup case-folds, so both these
#: and the lower-case table keys are accepted; a caller who writes "MPa" must
#: not be turned away by the schema while the description says MPa.
SW_SIM_PRESSURE_UNIT_SPELLINGS = [
    "Pa", "kPa", "MPa", "N/mm2", "N/mm²", "bar", "kgf/cm2", "psi", "ksi",
]

#: Newton-metres per unit accepted by a torque load. A mass cannot be a torque
#: without a lever arm, so only torque units are listed.
SW_SIM_TORQUE_UNITS = {
    "n*m": 1.0,
    "kn*m": 1000.0,
    "n*mm": 0.001,
    "kgf*m": SW_SIM_GRAVITY,
}

# swsStressComponent_e / swsStrengthUnit_e / swsLinearUnit_e
SW_SIM_STRESS_VON_MISES = 9
SW_SIM_STRESS_UNIT_MPA = 3
SW_SIM_LINEAR_UNIT_MM = 0

#: swsLinearUnit_e index per unit accepted by ``get_displacement_results``.
SW_SIM_LINEAR_UNITS = {"mm": 0, "cm": 1, "m": 2, "inch": 3}

#: swsForceUnit_e index per unit accepted by ``get_reaction_results``.
SW_SIM_REACTION_UNITS = {"N": 0, "lbf": 1, "kgf": 2}

#: The moment half of the force unit pair reported by the reaction API.
SW_SIM_REACTION_MOMENT_UNITS = {0: "N*m", 1: "lbf*in", 2: "kgf*cm"}

#: swsDisplacementComponent_e names, used only to report what was read.
SW_SIM_DISPLACEMENT_COMPONENTS = {
    0: "UX", 1: "UY", 2: "UZ", 3: "URES",
    4: "RFX", 5: "RFY", 6: "RFZ", 7: "RFRES",
    8: "RX", 9: "RY", 10: "RZ", 11: "RMX", 12: "RMY", 13: "RMZ", 14: "RMRES",
}

SW_SIM_STUDY_ERRORS = {
    1: "no solid body to process",
    2: "study name is a duplicate or invalid",
    3: "study type is not defined",
    4: "invalid mesh type",
    5: "invalid study sub-option",
}

SW_SIM_RESTRAINT_ERRORS = {
    1: "select faces, edges, or vertices",
    2: "select a planar face",
    3: "specify a cylindrical face",
    4: "specify a spherical face",
    6: "specify a face, edge, plane, or axis",
    7: "select a face",
    8: "invalid mesh type for this restraint",
    9: "invalid study type for this restraint",
    10: "no entities were passed",
    11: "invalid entity array",
    12: "specify two faces and one axis",
    13: "invalid restraint type",
    14: "cannot apply this restraint to the selection",
    15: "invalid mesh",
}

SW_SIM_FORCE_ERRORS = {
    1: "select faces, edges, or vertices",
    2: "select a valid entity",
    3: "invalid force type",
    4: "invalid selection type",
    6: "specify a valid direction reference",
    10: "no entities were passed",
    11: "invalid entity array",
    14: "cannot apply this force to the selection",
}

#: swsPressureError_e
SW_SIM_PRESSURE_ERRORS = {
    1: "select a face or faces",
    2: "select faces or shell edges",
    3: "select a face, edge, plane, or axis",
    4: "invalid pressure type",
    5: "invalid study type for a pressure load",
    6: "invalid entity array",
    7: "cannot apply pressure to the selection",
}

SW_SIM_MESH_ERRORS = {
    0: "successful",
    1: "no valid shells defined",
    2: "no solid body to process",
    3: "element size is too small",
    4: "element size is too large",
    5: "specify a positive value",
    6: "element size scale factor must be between 0.1 and 10",
    7: "tolerance scale factor must be between 0.01 and 100",
}

SW_SIM_RUN_ERRORS = {
    0: "successful",
    2: "rigid virtual wall contact must be defined for grounded bolts",
    3: "define initial temperatures to run a transient thermal analysis",
    4: "multiple loads on an entity must use the same time curve",
    11: "the mesh is not identical for the static studies in this event",
    12: "no valid shell defined",
    13: "elastic modulus (EX) is not defined",
    14: "elastic modulus (EX) must be greater than 0",
    15: "Poisson's ratio must be less than 0.5",
    18: "material is not defined for one or more shells",
    19: "material is not defined",
    20: "material is not defined for one or more components",
    21: "no solid body to process",
    22: "authorization failed for this analysis type",
    23: "mesh not found; create the mesh first",
    24: "analysis failed",
    25: "study does not exist",
    30: "invalid load boundary conditions",
}


def _int_byref(value: int = 0) -> Any:
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, int(value))


def _float_byref(value: float = 0.0) -> Any:
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_R8, float(value))


def _null_dispatch() -> Any:
    """A by-value null IDispatch, as VBA's ``Nothing`` marshals."""
    return VARIANT(pythoncom.VT_DISPATCH, None)


def _dispatch_array(entities: Sequence[Any]) -> Any:
    """
    A SAFEARRAY of VARIANT, each holding one IDispatch entity.

    This mirrors the VBA ``Array(entity1, entity2)`` the official examples
    pass to ``AddRestraint``/``AddForce3``. A SAFEARRAY of plain IDispatch is
    rejected by the add-in with "the server threw an exception".
    """
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT,
                   [VARIANT(pythoncom.VT_DISPATCH, entity) for entity in entities])


def _simulation_model(sw) -> Tuple[Optional[Any], Optional[Dict]]:
    """Return ``(model, None)`` for the active part, else ``(None, error)``."""
    document, error = sw.get_active_doc()
    if error:
        return None, error
    if com(document, "GetType") != 1:
        return None, sw._result(
            False, "SOLIDWORKS Simulation studies require an active part.",
            SwErrors.swSimulationError,
            {"code": "SIMULATION_REQUIRES_PART"})
    try:
        callback = com(sw.app, "GetAddInObject", SIMULATION_ADDIN_PROGID)
    except Exception as exc:  # pragma: no cover - defensive COM guard
        return None, sw._result(
            False, f"Could not query the Simulation add-in: {exc}",
            SwErrors.swSimulationError, {"code": "SIMULATION_ADDIN_ERROR"})
    if callback is None:
        return None, sw._result(
            False, "SOLIDWORKS Simulation add-in is not loaded; enable it in "
                   "Tools > Add-ins > SOLIDWORKS Simulation.",
            SwErrors.swSimulationError, {"code": "SIMULATION_UNAVAILABLE"})
    cosmos = com(callback, "COSMOSWORKS")
    if cosmos is None:
        return None, sw._result(
            False, "The Simulation add-in returned no COSMOSWORKS object.",
            SwErrors.swSimulationError, {"code": "SIMULATION_UNAVAILABLE"})
    model = com(cosmos, "ActiveDoc")
    if model is None:
        return None, sw._result(
            False, "The Simulation add-in sees no active document.",
            SwErrors.swSimulationError, {"code": "SIMULATION_NO_MODEL"})
    return model, None


def _resolve_study(sw, model, name: Optional[str]):
    """Return ``(study, None)``; without ``name`` the newest study is used."""
    manager = com(model, "StudyManager")
    if manager is None:
        return None, sw._result(
            False, "The document has no Simulation study manager.",
            SwErrors.swSimulationError, {"code": "SIMULATION_NO_STUDY_MANAGER"})
    count = int(com(manager, "StudyCount"))
    if count <= 0:
        return None, sw._result(
            False, "No Simulation study exists; create one first.",
            SwErrors.swSimulationError, {"code": "SIMULATION_NO_STUDY"})
    if not name:
        index = count - 1
        set_com(manager, "ActiveStudy", index)
        return com(manager, "GetStudy", index), None
    for index in range(count):
        study = com(manager, "GetStudy", index)
        if str(com(study, "Name")) == name:
            set_com(manager, "ActiveStudy", index)
            return study, None
    return None, sw._result(
        False, f"Simulation study not found: {name}.",
        SwErrors.swSimulationError,
        {"code": "SIMULATION_STUDY_NOT_FOUND", "study": name})


def _check_indices(sw, face_indices) -> Optional[Dict]:
    """Validate a planar-face index list before any COM call."""
    if (not isinstance(face_indices, (list, tuple)) or not face_indices
            or any(not isinstance(index, int) or isinstance(index, bool)
                   for index in face_indices)):
        return sw._result(
            False, "face_indices must be a non-empty list of planar-face indices.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    return None


def _faces(sw, document, face_indices: Sequence[int]):
    """Resolve planar-face indices to ``IFace2`` objects."""
    faces = []
    for index in face_indices:
        face = _get_planar_face_by_index(document, index)
        if face is None:
            return None, sw._result(
                False, f"Face {index} is not a planar face of the active part.",
                SwErrors.swSelectionError,
                {"code": "SIMULATION_FACE_NOT_FOUND", "face_index": index})
        faces.append(face)
    return faces, None


@tool(
    name="create_static_study",
    description=(
        "Create a SOLIDWORKS Simulation static study on the active part and "
        "verify it through the study manager. With mesh_type 'solid' (the "
        "default) beam bodies of a weldment part are converted to solid "
        "bodies, because a beam study needs joints before it can be meshed."
    ),
    schema={"type": "object", "properties": {
        "name": {"type": "string", "minLength": 1},
        "mesh_type": {"type": "string", "enum": ["solid", "beam"],
                      "description": "Study mesh type; default 'solid'."},
    }, "required": ["name"]},
    operation_class=OperationClass.MUTATE,
)
def create_static_study(sw, name: str, mesh_type: str = "solid") -> dict:
    if not isinstance(name, str) or not name.strip():
        return sw._result(False, "Study name must be a non-empty string.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if mesh_type not in ("solid", "beam"):
        return sw._result(False, "mesh_type must be 'solid' or 'beam'.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    name = name.strip()
    model, error = _simulation_model(sw)
    if error:
        return error
    try:
        manager = com(model, "StudyManager")
        before = int(com(manager, "StudyCount"))
        errors = _int_byref()
        study = com(manager, "CreateNewStudy3", name, SW_SIM_STUDY_STATIC,
                    SW_SIM_MESH_SOLID, errors)
        if study is None:
            reason = SW_SIM_STUDY_ERRORS.get(int(errors.value), "unknown error")
            return sw._result(
                False, f"SolidWorks Simulation did not create the study: {reason}.",
                SwErrors.swSimulationError,
                {"code": "STUDY_NOT_CREATED",
                 "simulation_error_code": int(errors.value)})
        set_com(manager, "ActiveStudy", before)
        after = int(com(manager, "StudyCount"))
        read_name = str(com(study, "Name"))
        analysis_type = int(com(study, "AnalysisType"))
        stored = com(manager, "GetStudy", after - 1)
        stored_name = str(com(stored, "Name"))
        if (after != before + 1 or read_name != name
                or stored_name != name or analysis_type != SW_SIM_STUDY_STATIC):
            return sw._result(
                False, "The created study did not read back as requested.",
                SwErrors.swSimulationError,
                {"code": "STUDY_NOT_VERIFIED", "study_count_before": before,
                 "study_count_after": after, "read_name": read_name,
                 "stored_name": stored_name, "analysis_type": analysis_type})
        converted = 0
        if mesh_type == "solid":
            converted, error = _convert_beams_to_solid(sw, study)
            if error:
                return error
        read_mesh_type = int(com(study, "MeshType"))
        expected = SW_SIM_MESH_SOLID if mesh_type == "solid" else SW_SIM_MESH_BEAM
        if read_mesh_type != expected:
            return sw._result(
                False, f"The study mesh type is {read_mesh_type}, expected {expected}.",
                SwErrors.swSimulationError,
                {"code": "STUDY_MESH_TYPE_NOT_VERIFIED",
                 "mesh_type": read_mesh_type, "expected_mesh_type": expected})
        return sw._result(True, f"Created static study '{read_name}'.", data={
            "name": read_name, "index": after - 1,
            "study_count_before": before, "study_count_after": after,
            "analysis_type": analysis_type, "mesh_type": read_mesh_type,
            "requested_mesh_type": mesh_type,
            "beam_bodies_converted": converted,
        })
    except Exception as exc:
        return sw._result(False, f"Creating the static study failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


def _convert_beams_to_solid(sw, study):
    """
    Convert every beam body of a weldment study into a solid body.

    A weldment part is meshed with beam elements by default, but a beam study
    cannot be meshed before its beam joints are defined. Converting to solid
    bodies makes ``ICWStudy::MeshType`` read back as Solid, so the standard
    solid mesh workflow applies. Official flow: "Change Beam to Solid Body and
    Back" (cworksapi.chm).
    """
    try:
        manager = com(study, "BeamManager")
        if manager is None:
            return 0, None
        converted = 0
        for index in range(int(com(manager, "BeamCount"))):
            errors = _int_byref()
            body = com(manager, "GetBeamBodyAt", index, errors)
            if body is None:
                return 0, sw._result(
                    False, "The study reported a beam body that cannot be read.",
                    SwErrors.swSimulationError,
                    {"code": "SIMULATION_BEAM_BODY_UNAVAILABLE",
                     "simulation_error_code": int(errors.value)})
            if int(com(body, "BeamType")) == 0:
                com(body, "ConvertToSolidBody")
                converted += 1
        return converted, None
    except Exception as exc:
        return 0, sw._result(
            False, f"Converting beam bodies to solid bodies failed: {exc}",
            SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


@tool(
    name="apply_fixed_fixture",
    description=(
        "Apply a fixed restraint to planar faces of the active part for a "
        "Simulation study and verify the restraint count and type."
    ),
    schema={"type": "object", "properties": {
        "face_indices": {
            "type": "array", "minItems": 1, "items": {"type": "integer"},
            "description": "Planar-face indices from list_planar_faces."},
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
    }, "required": ["face_indices"]},
    operation_class=OperationClass.MUTATE,
)
def apply_fixed_fixture(sw, face_indices: List[int], study: Optional[str] = None) -> dict:
    error = _check_indices(sw, face_indices)
    if error:
        return error
    document, error = sw.get_active_doc()
    if error:
        return error
    faces, error = _faces(sw, document, face_indices)
    if error:
        return error
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        manager = com(target, "LoadsAndRestraintsManager")
        if manager is None:
            return sw._result(False, "The study has no loads and restraints manager.",
                              SwErrors.swSimulationError,
                              {"code": "SIMULATION_NO_LBC_MANAGER"})
        before = int(com(manager, "Count"))
        errors = _int_byref()
        restraint = com(manager, "AddRestraint", SW_SIM_RESTRAINT_FIXED,
                        _dispatch_array(faces), _null_dispatch(), errors)
        if restraint is None:
            reason = SW_SIM_RESTRAINT_ERRORS.get(int(errors.value), "unknown error")
            return sw._result(
                False, f"SolidWorks Simulation did not create the fixture: {reason}.",
                SwErrors.swSimulationError,
                {"code": "RESTRAINT_NOT_CREATED",
                 "simulation_error_code": int(errors.value)})
        after = int(com(manager, "Count"))
        restraint_type = int(com(restraint, "RestraintType"))
        if after != before + 1 or restraint_type != SW_SIM_RESTRAINT_FIXED:
            return sw._result(
                False, "The fixture did not read back as a fixed restraint.",
                SwErrors.swSimulationError,
                {"code": "RESTRAINT_NOT_VERIFIED", "count_before": before,
                 "count_after": after, "restraint_type": restraint_type})
        return sw._result(True, "Applied a fixed restraint.", data={
            "study": str(com(target, "Name")),
            "restraint_type": restraint_type,
            "face_count": len(faces),
            "count_before": before, "count_after": after,
        })
    except Exception as exc:
        return sw._result(False, f"Applying the fixed fixture failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


@tool(
    name="apply_force_load",
    description=(
        "Apply a normal force or a torque to planar faces of the active part "
        "and verify the load count, type and stored value. A force takes N, "
        "kN, kgf, kg or t; a torque takes N*m, kN*m, N*mm or kgf*m and needs a "
        "reference axis feature for the direction."
    ),
    schema={"type": "object", "properties": {
        "face_indices": {
            "type": "array", "minItems": 1, "items": {"type": "integer"},
            "description": "Planar-face indices from list_planar_faces."},
        "magnitude": {
            "type": "number", "exclusiveMinimum": 0,
            "description": "Load magnitude, interpreted with unit."},
        "load_type": {"type": "string", "enum": ["force", "torque"],
                      "description": "force (default, normal to the faces) or torque."},
        "unit": {
            "type": "string",
            "enum": sorted(set(SW_SIM_FORCE_UNITS) | set(SW_SIM_TORQUE_UNITS)),
            "description": ("Force: N, kN, kgf are forces; kg and t are masses "
                            "whose weight is used (m * 9.80665). Torque: N*m, "
                            "kN*m, N*mm, kgf*m. Default N.")},
        "reference": {
            "type": "string",
            "description": ("Name of an existing reference axis feature; required "
                            "for a torque, ignored for a force.")},
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
    }, "required": ["face_indices", "magnitude"]},
    operation_class=OperationClass.MUTATE,
)
def apply_force_load(sw, face_indices: List[int], magnitude: float,
                     unit: str = "N", load_type: str = "force",
                     reference: Optional[str] = None,
                     study: Optional[str] = None) -> dict:
    if load_type not in ("force", "torque"):
        return sw._result(False, "load_type must be 'force' or 'torque'.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if (not isinstance(magnitude, (int, float)) or isinstance(magnitude, bool)
            or not math.isfinite(float(magnitude)) or float(magnitude) <= 0):
        return sw._result(False, "magnitude must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    table = SW_SIM_FORCE_UNITS if load_type == "force" else SW_SIM_TORQUE_UNITS
    if not isinstance(unit, str) or unit.strip().casefold() not in table:
        return sw._result(
            False, f"A {load_type} unit must be one of "
                   + ", ".join(sorted(table)) + ".",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED", "unit": unit, "load_type": load_type})
    if load_type == "torque" and (not isinstance(reference, str)
                                  or not reference.strip()):
        return sw._result(
            False, "A torque needs reference: the name of a reference axis feature.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    unit_key = unit.strip().casefold()
    factor = table[unit_key]
    amount = float(magnitude)
    load_value = amount * factor
    if not math.isfinite(load_value) or load_value <= 0:
        return sw._result(False, "The converted load must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    force_type = SW_SIM_FORCE_NORMAL if load_type == "force" else SW_SIM_FORCE_TORQUE
    error = _check_indices(sw, face_indices)
    if error:
        return error
    document, error = sw.get_active_doc()
    if error:
        return error
    faces, error = _faces(sw, document, face_indices)
    if error:
        return error
    ref_geom = _null_dispatch()
    if load_type == "torque":
        ref_geom = _reference_axis(sw, document, reference.strip())
        if ref_geom is None:
            return sw._result(
                False, f"Reference axis not found: {reference.strip()}. Create one "
                       "with create_reference_axis first.",
                SwErrors.swSelectionError,
                {"code": "SIMULATION_REFERENCE_NOT_FOUND",
                 "reference": reference.strip()})
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        manager = com(target, "LoadsAndRestraintsManager")
        before = int(com(manager, "Count"))
        errors = _int_byref()
        force = com(manager, "AddForce2", force_type,
                    SW_SIM_SELECTION_FACE_EDGE_VERTEX_POINT,
                    _dispatch_array(faces), ref_geom, errors)
        if force is None:
            reason = SW_SIM_FORCE_ERRORS.get(int(errors.value), "unknown error")
            return sw._result(
                False, f"SolidWorks Simulation did not create the {load_type} load: "
                       f"{reason}.",
                SwErrors.swSimulationError,
                {"code": "FORCE_NOT_CREATED",
                 "simulation_error_code": int(errors.value)})
        com(force, "ForceBeginEdit")
        set_com(force, "NormalForceOrTorqueValue", load_value)
        end_code = int(com(force, "ForceEndEdit"))
        after = int(com(manager, "Count"))
        read_back = float(com(force, "NormalForceOrTorqueValue"))
        read_type = int(com(force, "ForceType"))
        if (end_code != 0 or after != before + 1 or read_type != force_type
                or abs(read_back - load_value) > max(1e-6, load_value * 1e-6)):
            return sw._result(
                False, f"The {load_type} load did not read back the requested value.",
                SwErrors.swSimulationError,
                {"code": "FORCE_NOT_VERIFIED", "count_before": before,
                 "count_after": after, "force_type": read_type,
                 "force_edit_error": end_code, "magnitude": amount,
                 "unit": unit_key, "load_type": load_type,
                 "load_value": load_value, "read_back": read_back})
        data = {
            "study": str(com(target, "Name")),
            "load_type": load_type, "magnitude": amount, "unit": unit_key,
            "conversion_factor": factor, "load_value": load_value,
            "read_back": read_back, "force_type": read_type,
            "face_count": len(faces),
            "count_before": before, "count_after": after,
        }
        if load_type == "force":
            data["force_newtons"] = load_value
            data["read_back_newtons"] = read_back
            data["reference"] = None
        else:
            data["torque_nm"] = load_value
            data["read_back_nm"] = read_back
            data["reference"] = reference.strip()
        return sw._result(True, f"Applied a {load_type} load.", data=data)
    except Exception as exc:
        return sw._result(False, f"Applying the {load_type} load failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


@tool(
    name="apply_pressure_load",
    description=(
        "Apply a normal pressure to planar faces of the active part and verify "
        "the pressure is stored on a new load. Accepts Pa, kPa, MPa, N/mm2, "
        "bar, kgf/cm2, psi or ksi; the value is handed to the solver in N/mm2."
    ),
    schema={"type": "object", "properties": {
        "face_indices": {
            "type": "array", "minItems": 1, "items": {"type": "integer"},
            "description": "Planar-face indices from list_planar_faces."},
        "magnitude": {
            "type": "number", "exclusiveMinimum": 0,
            "description": "Pressure magnitude, interpreted with unit."},
        "unit": {
            "type": "string",
            "enum": sorted(set(SW_SIM_PRESSURE_UNITS)
                           | set(SW_SIM_PRESSURE_UNIT_SPELLINGS)),
            "description": ("Pa, kPa, MPa, N/mm2, bar, kgf/cm2, psi or ksi. "
                            "MPa and N/mm2 are the same unit. Default MPa.")},
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
    }, "required": ["face_indices", "magnitude"]},
    operation_class=OperationClass.MUTATE,
)
def apply_pressure_load(sw, face_indices: List[int], magnitude: float,
                        unit: str = "MPa", study: Optional[str] = None) -> dict:
    if (not isinstance(magnitude, (int, float)) or isinstance(magnitude, bool)
            or not math.isfinite(float(magnitude)) or float(magnitude) <= 0):
        return sw._result(False, "magnitude must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(unit, str) or unit.strip().casefold() not in SW_SIM_PRESSURE_UNITS:
        return sw._result(
            False, "A pressure unit must be one of "
                   + ", ".join(sorted(SW_SIM_PRESSURE_UNITS)) + ".",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED", "unit": unit})
    unit_key = unit.strip().casefold()
    factor = SW_SIM_PRESSURE_UNITS[unit_key]
    amount = float(magnitude)
    pressure_pascal = amount * factor
    if not math.isfinite(pressure_pascal) or pressure_pascal <= 0:
        return sw._result(False, "The converted pressure must be a positive number.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    error = _check_indices(sw, face_indices)
    if error:
        return error
    document, error = sw.get_active_doc()
    if error:
        return error
    faces, error = _faces(sw, document, face_indices)
    if error:
        return error
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        manager = com(target, "LoadsAndRestraintsManager")
        before = int(com(manager, "Count"))
        errors = _int_byref()
        pressure = com(manager, "AddPressure", SW_SIM_PRESSURE_NORMAL,
                       _dispatch_array(faces), _null_dispatch(), errors)
        if pressure is None:
            reason = SW_SIM_PRESSURE_ERRORS.get(int(errors.value), "unknown error")
            return sw._result(
                False, "SolidWorks Simulation did not create the pressure load: "
                       f"{reason}.",
                SwErrors.swSimulationError,
                {"code": "PRESSURE_NOT_CREATED",
                 "simulation_error_code": int(errors.value)})
        # The load reports the unit the study uses; the add-in ignores writes to
        # Unit inside the edit block, so the value is expressed in that unit.
        unit_index = int(com(pressure, "Unit"))
        unit_factor = SW_SIM_PRESSURE_ADDIN_UNITS.get(unit_index)
        if unit_factor is None:
            return sw._result(
                False, f"The pressure load reports an unsupported unit index "
                       f"{unit_index}.",
                SwErrors.swSimulationError,
                {"code": "PRESSURE_UNIT_UNSUPPORTED", "unit_index": unit_index})
        stored_value = pressure_pascal / unit_factor
        com(pressure, "PressureBeginEdit")
        set_com(pressure, "Value", stored_value)
        end_code = int(com(pressure, "PressureEndEdit"))
        after = int(com(manager, "Count"))
        read_back = float(com(pressure, "Value"))
        read_unit = int(com(pressure, "Unit"))
        read_type = int(com(pressure, "PressureType"))
        if (end_code != 0 or after != before + 1 or read_unit != unit_index
                or read_type != SW_SIM_PRESSURE_NORMAL
                or abs(read_back - stored_value) > max(1e-9, stored_value * 1e-6)):
            return sw._result(
                False, "The pressure load did not read back the requested value.",
                SwErrors.swSimulationError,
                {"code": "PRESSURE_NOT_VERIFIED", "count_before": before,
                 "count_after": after, "pressure_type": read_type,
                 "unit_index": read_unit, "pressure_edit_error": end_code,
                 "magnitude": amount, "unit": unit_key,
                 "pressure_pascal": pressure_pascal,
                 "stored_value": stored_value, "read_back": read_back})
        return sw._result(True, "Applied a pressure load.", data={
            "study": str(com(target, "Name")),
            "magnitude": amount, "unit": unit_key, "conversion_factor": factor,
            "pressure_pascal": pressure_pascal,
            "pressure_n_per_mm2": pressure_pascal / 1e6,
            "unit_index": read_unit,
            "unit_name": SW_SIM_PRESSURE_UNIT_NAMES.get(read_unit, "unknown"),
            "stored_value": stored_value, "read_back": read_back,
            "read_back_pascal": read_back * unit_factor,
            "pressure_type": read_type,
            "face_count": len(faces),
            "count_before": before, "count_after": after,
        })
    except Exception as exc:
        return sw._result(False, f"Applying the pressure load failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


def _reference_axis(sw, document, name: str):
    """
    Return the named reference-axis feature as a torque direction reference.

    The add-in accepts the ``IFeature`` itself here; passing its specific
    feature (``IRefAxis``) raises DISP_E_ARRAYISLOCKED. A cylindrical face is
    accepted too but is not addressable by name.
    """
    feature = com(document, "FeatureByName", name)
    if feature is None:
        return None
    if str(com(feature, "GetTypeName2")) != "RefAxis":
        return None
    return feature


@tool(
    name="run_analysis",
    description=(
        "Mesh and run the Simulation study of the active part and report the "
        "mesh error, node and element counts and the analysis error code."
    ),
    schema={"type": "object", "properties": {
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
        "quality": {"type": "integer", "minimum": 0, "maximum": 1,
                    "description": "Mesh quality: 0 draft, 1 high. Default 1."},
    }, "required": []},
    operation_class=OperationClass.MUTATE,
)
def run_analysis(sw, study: Optional[str] = None, quality: int = 1) -> dict:
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    if not isinstance(quality, int) or isinstance(quality, bool) or quality not in (0, 1):
        return sw._result(False, "quality must be 0 (draft) or 1 (high).",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    try:
        mesh = com(target, "Mesh")
        if mesh is None:
            return sw._result(False, "The study has no mesh object.",
                              SwErrors.swSimulationError, {"code": "SIMULATION_NO_MESH"})
        set_com(mesh, "Quality", quality)
        element = _float_byref(1.0)
        tolerance = _float_byref(1.0)
        com(mesh, "GetDefaultElementSizeAndTolerance", SW_SIM_LINEAR_UNIT_MM,
            element, tolerance)
        mesh_code = int(com(target, "CreateMesh", SW_SIM_LINEAR_UNIT_MM,
                            float(element.value), float(tolerance.value)))
        if mesh_code != 0:
            reason = SW_SIM_MESH_ERRORS.get(mesh_code, "unknown error")
            return sw._result(False, f"Meshing failed: {reason}.",
                              SwErrors.swSimulationError,
                              {"code": "MESH_FAILED",
                               "simulation_error_code": mesh_code})
        nodes = int(com(mesh, "NodeCount"))
        elements = int(com(mesh, "ElementCount"))
        failed = int(com(mesh, "GetNoOfFailedComponents"))
        if nodes <= 0 or elements <= 0 or failed > 0:
            return sw._result(
                False, "The mesh is empty or has failed components.",
                SwErrors.swSimulationError,
                {"code": "MESH_INVALID", "node_count": nodes,
                 "element_count": elements, "failed_components": failed})
        run_code = int(com(target, "RunAnalysis"))
        if run_code != 0:
            reason = SW_SIM_RUN_ERRORS.get(run_code, "unknown error")
            code = ("ANALYSIS_AUTHORIZATION_FAILED" if run_code == 22
                    else "ANALYSIS_FAILED")
            return sw._result(False, f"Running the analysis failed: {reason}.",
                              SwErrors.swSimulationError,
                              {"code": code, "simulation_error_code": run_code,
                               "node_count": nodes, "element_count": elements})
        return sw._result(True, "Meshed and ran the analysis.", data={
            "study": str(com(target, "Name")),
            "node_count": nodes, "element_count": elements,
            "failed_components": failed,
            "solution_time_seconds": float(com(target, "GetTotalSolutionTime")),
            "mesh_error": mesh_code, "run_error": run_code,
        })
    except Exception as exc:
        return sw._result(False, f"Running the analysis failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


@tool(
    name="get_stress_results",
    description=(
        "Read the minimum and maximum stress of a Simulation study step and "
        "return the node indices and values."
    ),
    schema={"type": "object", "properties": {
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
        "component": {"type": "integer", "minimum": 0, "maximum": 13,
                      "description": "Stress component (swsStressComponent_e); default 9 = von Mises."},
        "step": {"type": "integer", "minimum": 1,
                 "description": "Solution step number; default 1 for static studies."},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def get_stress_results(sw, study: Optional[str] = None, component: int = 9,
                       step: int = 1) -> dict:
    for value, name in ((component, "component"), (step, "step")):
        if not isinstance(value, int) or isinstance(value, bool):
            return sw._result(False, f"{name} must be an integer.",
                              SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if step < 1:
        return sw._result(False, "step must be at least 1.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        results = com(target, "Results")
        if results is None:
            return sw._result(False, "The study has no results object.",
                              SwErrors.swSimulationError, {"code": "SIMULATION_NO_RESULTS"})
        available = int(com(results, "GetMaximumAvailableSteps"))
        if available < step:
            return sw._result(
                False, f"Step {step} is not available; the study has {available} step(s).",
                SwErrors.swSimulationError,
                {"code": "RESULTS_STEP_UNAVAILABLE", "available_steps": available})
        errors = _int_byref()
        values = com(results, "GetMinMaxStress", component, 0, step, _null_dispatch(),
                     SW_SIM_STRESS_UNIT_MPA, errors)
        if values is None or len(values) < 4:
            return sw._result(False, "The study returned no stress values.",
                              SwErrors.swSimulationError,
                              {"code": "RESULTS_NOT_AVAILABLE",
                               "simulation_error_code": int(errors.value),
                               "available_steps": available})
        node_min, stress_min = int(values[0]), float(values[1])
        node_max, stress_max = int(values[2]), float(values[3])
        if not math.isfinite(stress_max) or stress_max < 0:
            return sw._result(
                False, "The maximum stress is not a finite positive value.",
                SwErrors.swSimulationError,
                {"code": "RESULTS_NOT_VALID", "stress_max": stress_max,
                 "stress_min": stress_min})
        return sw._result(True, "Read the stress results.", data={
            "study": str(com(target, "Name")),
            "component": component, "step": step,
            "units": "MPa", "available_steps": available,
            "node_min": node_min, "stress_min_mpa": stress_min,
            "node_max": node_max, "stress_max_mpa": stress_max,
        })
    except Exception as exc:
        return sw._result(False, f"Reading the stress results failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


@tool(
    name="get_displacement_results",
    description=(
        "Read the minimum and maximum displacement of a Simulation study step "
        "and return the node indices and values. component 3 (the default) is "
        "the resultant URES; 0/1/2 are UX/UY/UZ and 8/9/10 are the rotations."
    ),
    schema={"type": "object", "properties": {
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
        "component": {
            "type": "integer", "minimum": 0, "maximum": 14,
            "description": ("Displacement component (swsDisplacementComponent_e): "
                            "0 UX, 1 UY, 2 UZ, 3 URES (default), 8-10 rotations.")},
        "unit": {
            "type": "string", "enum": sorted(SW_SIM_LINEAR_UNITS),
            "description": "Linear unit for the translation; default mm."},
        "step": {"type": "integer", "minimum": 1,
                 "description": "Solution step number; default 1 for static studies."},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def get_displacement_results(sw, study: Optional[str] = None, component: int = 3,
                             unit: str = "mm", step: int = 1) -> dict:
    for value, name in ((component, "component"), (step, "step")):
        if not isinstance(value, int) or isinstance(value, bool):
            return sw._result(False, f"{name} must be an integer.",
                              SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not 0 <= component <= 14:
        return sw._result(False, "component must be from 0 to 14.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if step < 1:
        return sw._result(False, "step must be at least 1.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(unit, str) or unit.strip().casefold() not in SW_SIM_LINEAR_UNITS:
        return sw._result(
            False, "A linear unit must be one of "
                   + ", ".join(sorted(SW_SIM_LINEAR_UNITS)) + ".",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED", "unit": unit})
    unit_key = unit.strip().casefold()
    unit_index = SW_SIM_LINEAR_UNITS[unit_key]
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        results = com(target, "Results")
        if results is None:
            return sw._result(False, "The study has no results object.",
                              SwErrors.swSimulationError, {"code": "SIMULATION_NO_RESULTS"})
        available = int(com(results, "GetMaximumAvailableSteps"))
        if available < step:
            return sw._result(
                False, f"Step {step} is not available; the study has {available} step(s).",
                SwErrors.swSimulationError,
                {"code": "RESULTS_STEP_UNAVAILABLE", "available_steps": available})
        errors = _int_byref()
        values = com(results, "GetMinMaxDisplacement", component, step,
                     _null_dispatch(), unit_index, errors)
        if values is None or len(values) < 4:
            return sw._result(
                False, "The study returned no displacement values.",
                SwErrors.swSimulationError,
                {"code": "RESULTS_NOT_AVAILABLE",
                 "simulation_error_code": int(errors.value),
                 "available_steps": available})
        node_min, displacement_min = int(values[0]), float(values[1])
        node_max, displacement_max = int(values[2]), float(values[3])
        if not (math.isfinite(displacement_min) and math.isfinite(displacement_max)):
            return sw._result(
                False, "The displacement values are not finite.",
                SwErrors.swSimulationError,
                {"code": "RESULTS_NOT_VALID", "displacement_min": displacement_min,
                 "displacement_max": displacement_max})
        return sw._result(True, "Read the displacement results.", data={
            "study": str(com(target, "Name")),
            "component": component,
            "component_name": SW_SIM_DISPLACEMENT_COMPONENTS.get(component, "unknown"),
            "step": step, "unit": unit_key, "unit_index": unit_index,
            "available_steps": available,
            "node_min": node_min, "displacement_min": displacement_min,
            "node_max": node_max, "displacement_max": displacement_max,
        })
    except Exception as exc:
        return sw._result(False, f"Reading the displacement results failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})


def _reaction_block(values: Sequence[float]) -> Dict[str, float]:
    """The eight reaction values of one selection: F components then M."""
    return {
        "force_x": values[0], "force_y": values[1], "force_z": values[2],
        "force_resultant": values[3],
        "moment_x": values[4], "moment_y": values[5], "moment_z": values[6],
        "moment_resultant": values[7],
    }


@tool(
    name="get_reaction_results",
    description=(
        "Read the reaction force and moment the solved restraints report. "
        "Pass face_indices (typically the restrained faces) to get the "
        "reaction on those faces; without it only the whole-model total is "
        "returned. A solved support must react exactly what was applied, so "
        "this is the value-level check for a force or torque. Units: N, lbf "
        "or kgf. The moment half is the add-in's nodal moment reaction and "
        "stays zero for a solid mesh, whose nodes carry no rotational degree "
        "of freedom; the physical moment reaction lives in the force "
        "distribution, so verify moments through the force components."
    ),
    schema={"type": "object", "properties": {
        "study": {"type": "string",
                  "description": "Study name; defaults to the newest study."},
        "face_indices": {
            "type": "array", "items": {"type": "integer", "minimum": 0},
            "description": ("Planar faces to report (e.g. the restrained "
                            "faces); omit for the whole model only.")},
        "unit": {
            "type": "string", "enum": sorted(SW_SIM_REACTION_UNITS),
            "description": "Force unit (swsForceUnit_e); default N."},
        "step": {"type": "integer", "minimum": 1,
                 "description": "Solution step number; default 1 for static studies."},
    }, "required": []},
    operation_class=OperationClass.READ,
)
def get_reaction_results(sw, study: Optional[str] = None, face_indices=None,
                         unit: str = "N", step: int = 1) -> dict:
    if not isinstance(step, int) or isinstance(step, bool) or step < 1:
        return sw._result(False, "step must be an integer of at least 1.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(unit, str) or unit.strip() not in SW_SIM_REACTION_UNITS:
        return sw._result(
            False, "A force unit must be one of "
                   + ", ".join(sorted(SW_SIM_REACTION_UNITS)) + ".",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED", "unit": unit})
    unit_key = unit.strip()
    unit_index = SW_SIM_REACTION_UNITS[unit_key]
    selected_objects = _null_dispatch()
    if face_indices is not None:
        error = _check_indices(sw, face_indices)
        if error:
            return error
        document, error = sw.get_active_doc()
        if error:
            return error
        faces, error = _faces(sw, document, face_indices)
        if error:
            return error
        selected_objects = _dispatch_array(faces)
    model, error = _simulation_model(sw)
    if error:
        return error
    target, error = _resolve_study(sw, model, study)
    if error:
        return error
    try:
        results = com(target, "Results")
        if results is None:
            return sw._result(False, "The study has no results object.",
                              SwErrors.swSimulationError, {"code": "SIMULATION_NO_RESULTS"})
        available = int(com(results, "GetMaximumAvailableSteps"))
        if available < step:
            return sw._result(
                False, f"Step {step} is not available; the study has {available} step(s).",
                SwErrors.swSimulationError,
                {"code": "RESULTS_STEP_UNAVAILABLE", "available_steps": available})
        errors = _int_byref()
        selected = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
        each = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
        # The add-in also returns the whole per-node reaction array as its
        # return value; only the two out arrays are read here.
        com(results, "GetReactionForcesAndMomentsWithSelections", step,
            _null_dispatch(), unit_index, selected_objects, selected, each, errors)
        values = selected.value
        if values is None or len(values) < 16:
            return sw._result(
                False, "The study returned no reaction forces.",
                SwErrors.swSimulationError,
                {"code": "RESULTS_NOT_AVAILABLE",
                 "simulation_error_code": int(errors.value),
                 "available_steps": available})
        numbers = [float(value) for value in values[:16]]
        if not all(math.isfinite(number) for number in numbers):
            return sw._result(
                False, "The reaction values are not finite.",
                SwErrors.swSimulationError,
                {"code": "RESULTS_NOT_VALID", "reaction": numbers})
        # The first eight values belong to the selected entities, the last
        # eight to the entire model.
        per_face = []
        whole = numbers[8:16]
        selection = _reaction_block(numbers[0:8]) if face_indices is not None else None
        if face_indices is not None:
            per_object = each.value
            if per_object is not None and len(per_object) == 8 * len(face_indices):
                flat = [float(value) for value in per_object]
                per_face = [
                    dict(_reaction_block(flat[offset:offset + 8]),
                         face_index=int(index))
                    for offset, index in zip(range(0, len(flat), 8), face_indices)]
        data = {
            "study": str(com(target, "Name")),
            "step": step, "unit": unit_key, "unit_index": unit_index,
            "moment_unit": SW_SIM_REACTION_MOMENT_UNITS.get(unit_index, "unknown"),
            "available_steps": available,
            "face_indices": list(face_indices) if face_indices is not None else None,
            "selection": selection,
            "per_face": per_face,
            "entire_model": _reaction_block(whole),
        }
        return sw._result(True, "Read the reaction results.", data=data)
    except Exception as exc:
        return sw._result(False, f"Reading the reaction results failed: {exc}",
                          SwErrors.swSimulationError, {"code": "SIMULATION_COM_ERROR"})
