"""Apply a material from an existing SOLIDWORKS material database."""

import math
from pathlib import Path

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


@tool(
    name="apply_material",
    description="Apply a named material from an absolute .sldmat database to the active part configuration and verify its mass and read-back.",
    schema={"type": "object", "properties": {
        "name": {"type": "string", "minLength": 1},
        "database": {"type": "string", "minLength": 1,
                     "description": "Absolute path to an installed .sldmat material database."},
    }, "required": ["name", "database"]},
    operation_class=OperationClass.MUTATE,
)
def apply_material(sw, name: str, database: str) -> dict:
    if (not isinstance(name, str) or not name.strip()
            or not isinstance(database, str) or not database.strip()):
        return sw._result(False, "Material name and database path must be non-empty strings.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    path = Path(database)
    if not path.is_absolute() or path.suffix.casefold() != ".sldmat" or not path.is_file():
        return sw._result(False, "Select an existing absolute .sldmat database path.",
                          SwErrors.swInvalidInput, {"code": "MATERIAL_DATABASE_NOT_FOUND"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "A material requires an active part.",
                          SwErrors.swInvalidFileType)
    try:
        configuration = str(com(com(document, "ConfigurationManager"),
                                "ActiveConfiguration").Name)
        before = com(document, "GetMassProperties", 0.0)
        com(document, "SetMaterialPropertyName2", configuration, str(path), name.strip())
        source = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        read_back = com(document, "GetMaterialPropertyName2", configuration, source)
        if read_back != name.strip() or not source.value:
            return sw._result(False, "SolidWorks did not apply the requested material.",
                              SwErrors.swFeatureError,
                              {"code": "MATERIAL_NOT_APPLIED", "read_back": read_back})
        after = com(document, "GetMassProperties", 0.0)
        volume, mass = float(after[3]), float(after[5])
        if (not math.isfinite(volume) or not math.isfinite(mass)
                or volume <= 0 or mass <= 0
                or abs(volume - float(before[3])) > max(1e-12, volume * 1e-6)):
            return sw._result(False, "Material mass properties are not valid for this solid.",
                              SwErrors.swFeatureError, {"code": "INVALID_MASS_PROPERTIES"})
        return sw._result(True, f"Applied {read_back} to {configuration}.", data={
            "name": read_back, "configuration": configuration,
            "database_read_back": str(source.value),
            "mass_before_kg": float(before[5]), "mass_after_kg": mass,
            "volume_m3": volume, "density_kg_m3": mass / volume,
        })
    except Exception as exc:
        return sw._result(False, f"Applying material failed: {exc}",
                          SwErrors.swFeatureError)
