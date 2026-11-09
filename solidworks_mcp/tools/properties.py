"""
Custom property tools (part R?): write a text custom property on the active
document or on a named configuration, then read it back to confirm the stored
value.

API notes (verified against the installed type library / API help, see
docs/api-findings.md):

* ``IModelDocExtension.CustomPropertyManager(configName)`` takes the
  configuration name, or an empty string for document-level properties.
* ``ICustomPropertyManager.Add3(FieldName, FieldType, FieldValue,
  OverwriteExisting)`` returns ``swCustomInfoAddResult_e`` (0 = added or
  changed, 1 = generic failure, 2 = existing property has another type,
  3 = value does not match the requested type, 4 = legacy architecture).
* ``ICustomPropertyManager.Get5(FieldName, UseCached, ValOut, ResolvedValOut,
  WasResolved)`` returns ``swCustomInfoGetResult_e`` (0 = cached value,
  1 = property not present, 2 = resolved value) and fills the ByRef VARIANTs.
"""

import logging

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")

# swCustomInfoType_e.swCustomInfoText.
SW_CUSTOM_INFO_TEXT = 30

# swCustomPropertyAddOption_e.
ADD_ONLY_IF_NEW = 0
ADD_REPLACE_VALUE = 2

# swCustomInfoAddResult_e.swCustomInfoAddResult_AddedOrChanged.
ADD_RESULT_ADDED_OR_CHANGED = 0

# swCustomInfoGetResult_e.swCustomInfoGetResult_NotPresent.
GET_RESULT_NOT_PRESENT = 1

_ADD_RESULT_REASONS = {
    1: "SolidWorks failed to add the custom property",
    2: "an existing custom property with the same name has a different type",
    3: "the value does not match the requested text type",
    4: "the property cannot be added to this legacy architecture",
}


def _read_property(manager, name):
    """Read one property through Get5; returns (result code, raw, resolved, was_resolved)."""
    raw = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    resolved = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    was_resolved = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    result = com(manager, "Get5", name, False, raw, resolved, was_resolved)
    return result, raw.value, resolved.value, bool(was_resolved.value)


@tool(
    name="set_custom_property",
    description=(
        "Set a text custom property on the active document, or on one named "
        "configuration, and read it back so the stored value is confirmed. "
        "Mutating."
    ),
    schema={"type": "object", "properties": {
        "name": {"type": "string", "minLength": 1,
                 "description": "Custom property name, for example 'PartNumber'."},
        "value": {"type": "string",
                  "description": "Text value to store in the property."},
        "configuration": {"type": "string",
                          "description": "Optional configuration name. Omit for a "
                                         "document-level property."},
        "overwrite": {"type": "boolean", "default": True,
                      "description": "Replace an existing value. When false the "
                                     "property is only added if it is new."},
    }, "required": ["name", "value"]},
    operation_class=OperationClass.MUTATE,
)
def set_custom_property(sw, name: str, value: str, configuration: str = None,
                        overwrite: bool = True) -> dict:
    """Write one text custom property and verify the value read back from SolidWorks."""
    if not isinstance(name, str) or not name.strip():
        return sw._result(False, "A non-empty property name is required.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(value, str):
        return sw._result(False, "The property value must be a string.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if configuration is not None and not isinstance(configuration, str):
        return sw._result(False, "The configuration name must be a string.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    if not isinstance(overwrite, bool):
        return sw._result(False, "overwrite must be a boolean.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    name = name.strip()
    config_name = configuration.strip() if configuration is not None else ""
    if configuration is not None and not config_name:
        return sw._result(False, "The configuration name must not be blank.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    document, error = sw.get_active_doc()
    if error:
        return error

    scope = "configuration" if config_name else "document"
    try:
        if config_name and com(document, "GetConfigurationByName", config_name) is None:
            return sw._result(
                False, f"Configuration not found: {config_name}.",
                SwErrors.swInvalidInput,
                {"code": "CONFIGURATION_NOT_FOUND", "configuration": config_name},
            )

        manager = com(com(document, "Extension"), "CustomPropertyManager", config_name)
        if manager is None:
            return sw._result(False, "SolidWorks returned no custom property manager.",
                              SwErrors.swFeatureError, {"code": "NO_PROPERTY_MANAGER"})

        option = ADD_REPLACE_VALUE if overwrite else ADD_ONLY_IF_NEW
        add_result = com(manager, "Add3", name, SW_CUSTOM_INFO_TEXT, value, option)
        if add_result != ADD_RESULT_ADDED_OR_CHANGED:
            reason = _ADD_RESULT_REASONS.get(add_result, f"result code {add_result}")
            return sw._result(
                False, f"SolidWorks did not set '{name}': {reason}.",
                SwErrors.swFeatureError,
                {"code": "PROPERTY_ADD_FAILED", "name": name, "add_result": add_result},
            )

        get_result, raw_value, resolved_value, was_resolved = _read_property(manager, name)
        data = {
            "name": name,
            "value": value,
            "scope": scope,
            "read_back": raw_value,
            "resolved_value": resolved_value,
            "was_resolved": was_resolved,
            "add_result": add_result,
            "get_result": get_result,
        }
        if config_name:
            data["configuration"] = config_name

        if get_result == GET_RESULT_NOT_PRESENT:
            return sw._result(
                False,
                f"SolidWorks reported success but '{name}' is not present after the write.",
                SwErrors.swFeatureError, dict(data, code="PROPERTY_NOT_PRESENT"),
            )

        if value not in (raw_value, resolved_value):
            hint = "" if overwrite else " Pass overwrite=true to replace an existing value."
            return sw._result(
                False,
                f"SolidWorks reported success but '{name}' reads back as "
                f"{raw_value!r} instead of {value!r}.{hint}",
                SwErrors.swFeatureError, dict(data, code="PROPERTY_NOT_REPLACED"),
            )

        target = f"{scope} '{config_name}'" if config_name else "the document"
        return sw._result(
            True, f"Set {target} custom property '{name}' to '{value}'.",
            data=dict(data, status="verified"),
        )
    except Exception as set_error:
        return sw._result(False, f"Setting custom property failed: {set_error}",
                          SwErrors.swFeatureError)
