"""Bounded undo and redo tools for the active SolidWorks document."""

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


_STEPS_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": 20,
    "default": 1,
    "description": "Number of SolidWorks history steps to request.",
}


def _history_command(sw, action: str, method_name: str, steps: int) -> dict:
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 20:
        return sw._result(
            False,
            "steps must be an integer from 1 through 20.",
            SwErrors.swInvalidInput,
            {"code": "VALIDATION_FAILED"},
        )

    document, error = sw.get_active_doc()
    if error:
        return error

    try:
        com(document, method_name, steps)
    except Exception as command_error:
        return sw._result(
            False,
            f"SolidWorks {action} command failed: {command_error}",
            SwErrors.swUnknownError,
        )

    return sw._result(
        True,
        f"SolidWorks {action} command issued for {steps} step(s).",
        data={
            "action": action,
            "steps": steps,
            "status": "command_issued",
            "api": f"IModelDoc2.{method_name}",
            "verification": (
                "SolidWorks does not expose the affected history item through this command; "
                "inspect the document after the operation."
            ),
        },
    )


@tool(
    name="undo",
    description="Request one or more undo steps on the bound active document without saving it.",
    schema={"type": "object", "properties": {"steps": _STEPS_SCHEMA}, "required": []},
    operation_class=OperationClass.MUTATE,
)
def undo(sw, steps: int = 1) -> dict:
    return _history_command(sw, "undo", "EditUndo2", steps)


@tool(
    name="redo",
    description="Request one or more redo steps on the bound active document without saving it.",
    schema={"type": "object", "properties": {"steps": _STEPS_SCHEMA}, "required": []},
    operation_class=OperationClass.MUTATE,
)
def redo(sw, steps: int = 1) -> dict:
    return _history_command(sw, "redo", "EditRedo2", steps)
