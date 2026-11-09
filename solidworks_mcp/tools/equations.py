"""
Equation tools (part M2.5): add one named global variable with a text or
numeric expression to the active document, then read the stored equation back
to confirm it.

API notes (verified against the installed SOLIDWORKS 2025 API Help, 2025):

* ``IModelDoc2.GetEquationMgr()`` returns the ``IEquationMgr``.
* ``IEquationMgr.Add3(Index, Equation, Solve, WhichConfigurations, ConfigNames)``
  returns the 0-based index of the new equation, or -1 on error. ``Index`` is
  -1 to append at the end. ``Solve`` is True to solve immediately, False to
  solve later. ``ConfigNames`` is a ``System.Object`` array that is only read
  when ``WhichConfigurations`` is ``swSpecifyConfiguration``.
* A global variable assignment must be added with ``WhichConfigurations`` set
  to ``swInConfigurationOpts_e.swAllConfiguration`` (2); ``ConfigNames`` is
  then ignored and may be null. Adding a global variable that already exists
  is an error.
* The ``Equation`` string is the text entered in the Equations dialog: the
  variable name is wrapped in double quotes, for example ``"B" = 2`` for a
  numeric value or ``"B" = "text"`` for a text value.
* ``IEquationMgr.GetCount()`` returns the number of equations,
  ``IEquationMgr.Equation(Index)`` returns the stored equation string and
  ``IEquationMgr.GlobalVariable(Index)`` returns True when that equation is a
  global variable assignment.
"""

import logging
import math

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")

# swInConfigurationOpts_e.swAllConfiguration.
SW_ALL_CONFIGURATION = 2


def _normalize(equation):
    """Whitespace- and case-insensitive form of an equation string."""
    return "".join(str(equation).split()).casefold()


def _right_hand_side(value):
    """
    Build the right-hand side of a global variable assignment.

    A number becomes a numeric expression; a string becomes a quoted text
    expression. Returns ``(right_hand_side, error_message)``.
    """
    if isinstance(value, bool):
        return None, "value must be a number or a string, not a boolean."
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None, "value must be a finite number."
        return str(value), None
    if isinstance(value, str):
        if '"' in value:
            return None, ("value must not contain a double quote; pass the raw "
                          "text without surrounding quotes.")
        return '"' + value + '"', None
    return None, "value must be a number or a string."


@tool(
    name="add_equation",
    description=(
        "Add one named global variable with a text or numeric expression to "
        "the active document, then read the stored equation back to confirm "
        "it. Mutating."
    ),
    schema={"type": "object", "properties": {
        "name": {"type": "string", "minLength": 1,
                 "description": "Global variable name, without the surrounding "
                                "quotes, for example 'B'."},
        "value": {"type": ["number", "string"],
                  "description": "Numeric value (number) or text value "
                                 "(string). A string is stored as a quoted "
                                 "text expression."},
        "solve": {"type": "boolean", "default": True,
                  "description": "Solve the equation immediately. False delays "
                                 "evaluation until the model is rebuilt."},
    }, "required": ["name", "value"]},
    operation_class=OperationClass.MUTATE,
)
def add_equation(sw, name: str, value, solve: bool = True) -> dict:
    """Add one global variable, then verify the stored equation read back."""
    if not isinstance(name, str) or not name.strip():
        return sw._result(False, "A non-empty global variable name is required.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    name = name.strip()
    if '"' in name:
        return sw._result(False, 'The global variable name must not contain a double quote.',
                          SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "name"})
    if not isinstance(solve, bool):
        return sw._result(False, "solve must be a boolean.",
                          SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "solve"})

    right_hand_side, value_error = _right_hand_side(value)
    if value_error:
        return sw._result(False, value_error, SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "value"})

    expression = f'"{name}" = {right_hand_side}'

    document, error = sw.get_active_doc()
    if error:
        return error

    try:
        manager = com(document, "GetEquationMgr")
        if manager is None:
            return sw._result(False, "SolidWorks returned no equation manager.",
                              SwErrors.swFeatureError,
                              {"code": "NO_EQUATION_MANAGER"})

        # Add3 only works on parts with multiple configurations (SW2025 Help).
        # Single-configuration parts require Add2 instead.
        configurations = com(document, "GetConfigurationNames") or []
        if len(configurations) > 1:
            index = com(manager, "Add3", -1, expression, solve,
                        SW_ALL_CONFIGURATION, None)
        else:
            index = com(manager, "Add2", -1, expression, solve)
        if index is None or index < 0:
            return sw._result(
                False,
                f"SolidWorks did not add the global variable '{name}'; Add3 "
                "returned an error (the variable may already exist).",
                SwErrors.swFeatureError,
                {"code": "EQUATION_ADD_FAILED", "name": name,
                 "expression": expression, "add_result": index},
            )

        read_back = com(manager, "Equation", index)
        is_global_variable = bool(com(manager, "GlobalVariable", index))
        count = com(manager, "GetCount")

        data = {
            "name": name,
            "value": value,
            "expression": expression,
            "index": index,
            "read_back": read_back,
            "is_global_variable": is_global_variable,
            "equation_count": count,
        }

        if read_back is None:
            if not solve:
                # Add3 with Solve=False defers evaluation until the model is
                # rebuilt, so the equation may not be readable yet.
                return sw._result(
                    True,
                    f"Added global variable '{name}' = {right_hand_side}; "
                    "read-back is deferred until the model is rebuilt.",
                    data=dict(data, status="added_pending_solve"),
                )
            return sw._result(
                False,
                f"SolidWorks added '{name}' but the equation at index {index} "
                "cannot be read back.",
                SwErrors.swFeatureError, dict(data, code="EQUATION_NOT_READABLE"),
            )

        if not is_global_variable:
            return sw._result(
                False,
                f"The equation at index {index} is not a global variable "
                "assignment.",
                SwErrors.swFeatureError,
                dict(data, code="EQUATION_NOT_GLOBAL_VARIABLE"),
            )

        if _normalize(read_back) != _normalize(expression):
            return sw._result(
                False,
                f"SolidWorks reported success but the equation reads back as "
                f"{read_back!r} instead of {expression!r}.",
                SwErrors.swFeatureError,
                dict(data, code="EQUATION_MISMATCH"),
            )

        return sw._result(
            True, f"Added global variable '{name}' = {right_hand_side}.",
            data=dict(data, status="verified"),
        )
    except Exception as add_error:
        return sw._result(False, f"Adding the equation failed: {add_error}",
                          SwErrors.swFeatureError)
