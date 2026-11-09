"""Neutral CAD import (STEP/IGES/Parasolid) with 3D Interconnect handling.

SolidWorks 2025 imports neutral formats through 3D Interconnect, which needs
interaction and makes a headless OpenDoc6 fail with error 0x200000
(see docs/api-findings.md section 20). Disabling the toggle first makes the
import work, and the previous setting is restored afterwards.
"""

import os
from pathlib import Path

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

# swUserPreferenceToggle_e.swMultiCAD_Enable3DInterconnect (swconst.tlb).
SW_MULTICAD_ENABLE_3D_INTERCONNECT = 691
# swFileLoadError_e.swFileRequiresRepairError (swconst.tlb).
SW_FILE_REQUIRES_REPAIR = 2097152
SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2

ALLOWED_EXTENSIONS = {
    ".step": SW_DOC_PART,
    ".stp": SW_DOC_PART,
    ".igs": SW_DOC_PART,
    ".iges": SW_DOC_PART,
    ".x_t": SW_DOC_PART,
    ".x_b": SW_DOC_PART,
    ".sat": SW_DOC_PART,
    ".sldprt": SW_DOC_PART,
    ".sldasm": SW_DOC_ASSEMBLY,
}


def _dynamic_app(app):
    """
    Late-bound wrapper for the SolidWorks application.

    The generated (typed) wrapper rejects VARIANT byref arguments for
    OpenDoc6, so the dynamic dispatch interface is used instead.
    """
    if hasattr(app, "_oleobj_"):
        return win32com.client.dynamic.Dispatch(app)
    return app


def _toggle_state(app, toggle_id):
    try:
        return bool(com(app, "GetUserPreferenceToggle", toggle_id))
    except Exception:
        return None


@tool(
    name="import_neutral_file",
    description=(
        "Open a neutral CAD file (STEP/STP/IGES/X_T/X_B/SAT) or an existing "
        "native part/assembly as a new SolidWorks document. Handles the 3D "
        "Interconnect toggle that otherwise makes a headless import fail."
    ),
    schema={
        "type": "object",
        "properties": {
            "filepath": {"type": "string",
                         "description": "Full path of the file to open."},
        },
        "required": ["filepath"],
    },
    operation_class=OperationClass.MUTATE,
)
def import_neutral_file(sw, filepath: str) -> dict:
    path = Path(str(filepath)).expanduser()
    extension = path.suffix.casefold()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return sw._result(
            False, f"Unsupported import type '{extension}'. Allowed: {allowed}.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
        )
    if not path.is_file():
        return sw._result(False, f"File not found: {path}",
                          SwErrors.swFileNotFoundError,
                          {"code": "FILE_NOT_FOUND"})

    app = _dynamic_app(sw.app)
    doc_type = ALLOWED_EXTENSIONS[extension]
    previous = _toggle_state(app, SW_MULTICAD_ENABLE_3D_INTERCONNECT)
    disabled = False
    if previous:
        com(app, "SetUserPreferenceToggle", SW_MULTICAD_ENABLE_3D_INTERCONNECT, False)
        disabled = True

    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    try:
        document = com(app, "OpenDoc6", str(path), doc_type, 0, "", errors, warnings)
    except Exception as open_error:
        return sw._result(False, f"Could not open {path.name}: {open_error}",
                          SwErrors.swFileLoadError)
    finally:
        if disabled:
            try:
                com(app, "SetUserPreferenceToggle",
                    SW_MULTICAD_ENABLE_3D_INTERCONNECT, True)
            except Exception:
                pass

    if document is None:
        detail = int(getattr(errors, "value", 0))
        if detail == SW_FILE_REQUIRES_REPAIR:
            return sw._result(
                False,
                f"SolidWorks wants to repair {path.name} before importing it "
                "(swFileRequiresRepairError); this cannot be confirmed from a "
                "headless call. Re-export the source file, or build the part "
                "from its dimensions instead.",
                SwErrors.swFileLoadError,
                {"code": "IMPORT_NEEDS_REPAIR", "load_error_code": detail},
            )
        return sw._result(
            False,
            f"SolidWorks could not load {path.name} (error {detail}).",
            SwErrors.swFileLoadError,
            {"code": "IMPORT_FAILED", "load_error_code": detail},
        )

    return sw._result(
        True, f"Opened {path.name}.",
        data={
            "title": str(com(document, "GetTitle")),
            "path": str(path),
            "load_error_code": int(getattr(errors, "value", 0)),
            "warning_code": int(getattr(warnings, "value", 0)),
            "three_d_interconnect_disabled": disabled,
        },
    )
