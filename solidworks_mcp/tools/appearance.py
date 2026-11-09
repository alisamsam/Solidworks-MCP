"""Part-level RGB appearance for the active configuration."""

import math
import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


@tool(
    name="set_appearance",
    description="Set part-level RGB color in the active configuration and read it back.",
    schema={"type": "object", "properties": {
        "red": {"type": "number", "minimum": 0, "maximum": 1},
        "green": {"type": "number", "minimum": 0, "maximum": 1},
        "blue": {"type": "number", "minimum": 0, "maximum": 1},
    }, "required": ["red", "green", "blue"]},
    operation_class=OperationClass.MUTATE,
)
def set_appearance(sw, red: float, green: float, blue: float) -> dict:
    rgb = (red, green, blue)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or not 0 <= value <= 1 for value in rgb):
        return sw._result(False, "RGB components must be finite numbers in [0,1].",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != 1:
        return sw._result(False, "Part appearance requires an active part.",
                          SwErrors.swInvalidFileType)
    try:
        previous = com(document, "MaterialPropertyValues")
        values = list(previous) if previous is not None and len(previous) == 9 else [
            0.7, 0.7, 0.7, 0.5, 0.8, 0.5, 0.5, 0.0, 0.0,
        ]
        values[:3] = [float(v) for v in rgb]
        # SW2025 IModelDoc2.MaterialPropertyValues is a writable 9-double
        # property: R,G,B,Ambient,Diffuse,Specular,Shininess,Transparency,Emission.
        document.MaterialPropertyValues = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, values)
        read_back = com(document, "MaterialPropertyValues")
        # SolidWorks stores display colors at 8-bit precision (e.g. 0.5 -> 127/255).
        if read_back is None or any(abs(float(read_back[i]) - rgb[i]) > 1 / 255 + 1e-6
                                    for i in range(3)):
            return sw._result(False, f"SolidWorks did not retain the RGB appearance: {read_back!r}.",
                              SwErrors.swFeatureError)
        com(document, "GraphicsRedraw2")
        return sw._result(True, "Set part appearance in the active configuration.", data={
            "rgb": [float(read_back[i]) for i in range(3)],
            "scope": "part_active_configuration",
        })
    except Exception as exc:
        return sw._result(False, f"Part appearance failed: {exc}",
                          SwErrors.swFeatureError)
