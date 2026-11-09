"""
Configuration tools (part R?): add one named configuration to the active
document, refuse to overwrite a configuration that already exists, and read the
stored configuration back.

API notes (verified against the installed SOLIDWORKS 2025 API Help, 2025 SP05;
see docs/api-findings.md):

* ``IConfigurationManager.AddConfiguration2(Name, Comment, AlternateName,
  Options, ParentConfigName, Description, Rebuild)`` creates a configuration and
  returns the new ``IConfiguration``. ``Rebuild`` is True to rebuild the model
  after adding the configuration, False to not. Available since SOLIDWORKS 2018.
  The superseded ``AddConfiguration(Name, Comment, AlternateName, Options,
  ParentConfigName, Description)`` -- same call without ``Rebuild``, obsolete
  since 2018 -- is the six-argument form already used live by
  ``tools/standard_parts.py``; this tool uses the current method.
* ``Options`` is a bitmask of ``swConfigurationOptions2_e``:
  ``swConfigOption_UseAlternateName`` (1), ``swConfigOption_DontShowPartsInBOM``
  (2), ``swConfigOption_SuppressByDefault`` (4), ``swConfigOption_HideByDefault``
  (8), ``swConfigOption_MinFeatureManager`` (16), ``swConfigOption_LinkToParent``
  (64), ``swConfigOption_DontActivate`` (128), ``swConfigOption_DoDisolveInBOM``
  (256), ``swConfigOption_UseDescriptionInBOM`` (512).
* ``IModelDoc2.GetConfigurationByName(Name)`` returns the ``IConfiguration`` or
  NULL if the operation fails. ``IConfiguration`` exposes ``Name``, ``Comment``,
  ``AlternateName`` and ``Description`` as read/write properties; there is no
  ``IsActive`` member, so the active configuration is read from
  ``IConfigurationManager.ActiveConfiguration.Name``.
* ``IModelDoc2.ShowConfiguration2(Name)`` activates the configuration; it can
  return False even when the configuration was activated, so the active name is
  read back from the configuration manager instead of trusting the return value.
"""

import logging

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")


def _configuration_state(configuration):
    """Read the stored fields of an IConfiguration into a plain dict."""
    return {
        "name": com(configuration, "Name"),
        "comment": com(configuration, "Comment"),
        "alternate_name": com(configuration, "AlternateName"),
        "description": com(configuration, "Description"),
    }


def _active_configuration_name(manager):
    """Name of the document's active configuration, or None."""
    active = com(manager, "ActiveConfiguration")
    return com(active, "Name") if active is not None else None


@tool(
    name="create_configuration",
    description=(
        "Add a named configuration to the active document (never overwrites) and read it back. Mutating."
    ),
    schema={"type": "object", "properties": {
        "name": {"type": "string", "minLength": 1,
                 "description": "New configuration name"},
        "comment": {"type": "string", "default": "",
                    "description": "Configuration Properties comment"},
        "description": {"type": "string", "default": "",
                        "description": "Configuration description"},
        "alternate_name": {"type": "string", "default": "",
                           "description": "Stored only with option bit 1 (UseAlternateName)"},
        "parent_configuration": {"type": "string", "default": "",
                                 "description": "Derive from; omit for top level"},
        "options": {"type": "integer", "minimum": 0, "default": 0,
                    "description": "swConfigurationOptions2_e bitmask; +128 keeps the active configuration"},
        "rebuild": {"type": "boolean", "default": False,
                    "description": "Rebuild after adding"},
        "activate": {"type": "boolean", "default": False,
                     "description": "Activate and verify"},
    }, "required": ["name"]},
    operation_class=OperationClass.MUTATE,
)
def create_configuration(sw, name: str, comment: str = "", description: str = "",
                         alternate_name: str = "", parent_configuration: str = "",
                         options: int = 0, rebuild: bool = False,
                         activate: bool = False) -> dict:
    """Create one configuration, then read it back from SolidWorks."""
    if not isinstance(name, str) or not name.strip():
        return sw._result(False, "A non-empty configuration name is required.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    for field_name, field_value in (("comment", comment),
                                    ("description", description),
                                    ("alternate_name", alternate_name),
                                    ("parent_configuration", parent_configuration)):
        if not isinstance(field_value, str):
            return sw._result(False, f"{field_name} must be a string.",
                              SwErrors.swInvalidInput,
                              {"code": "VALIDATION_FAILED", "field": field_name})
    if isinstance(options, bool) or not isinstance(options, int) or options < 0:
        return sw._result(False, "options must be a non-negative integer bitmask.",
                          SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "options"})
    if not isinstance(rebuild, bool):
        return sw._result(False, "rebuild must be a boolean.",
                          SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "rebuild"})
    if not isinstance(activate, bool):
        return sw._result(False, "activate must be a boolean.",
                          SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED", "field": "activate"})

    name = name.strip()
    parent = parent_configuration.strip()
    if parent and parent == name:
        return sw._result(False, "A configuration cannot be its own parent.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})

    document, error = sw.get_active_doc()
    if error:
        return error

    try:
        manager = com(document, "ConfigurationManager")
        if manager is None:
            return sw._result(False, "SolidWorks returned no configuration manager.",
                              SwErrors.swFeatureError,
                              {"code": "NO_CONFIGURATION_MANAGER"})

        # Never overwrite: an existing configuration of this name is an error.
        if com(document, "GetConfigurationByName", name) is not None:
            return sw._result(
                False, f"Configuration already exists: {name}.",
                SwErrors.swInvalidInput,
                {"code": "CONFIGURATION_EXISTS", "configuration": name})

        if parent and com(document, "GetConfigurationByName", parent) is None:
            return sw._result(
                False, f"Parent configuration not found: {parent}.",
                SwErrors.swInvalidInput,
                {"code": "CONFIGURATION_PARENT_NOT_FOUND", "parent": parent})

        created = com(manager, "AddConfiguration2", name, comment, alternate_name,
                      options, parent, description, rebuild)

        configuration = com(document, "GetConfigurationByName", name)
        if configuration is None:
            return sw._result(
                False,
                f"SolidWorks did not expose configuration '{name}' after the "
                "create call.",
                SwErrors.swFeatureError,
                {"code": "CONFIGURATION_NOT_READABLE", "configuration": name,
                 "created": created is not None})

        state = _configuration_state(configuration)
        if state["name"] != name:
            return sw._result(
                False,
                f"SolidWorks created a configuration named {state['name']!r} "
                f"instead of {name!r}.",
                SwErrors.swFeatureError,
                {"code": "CONFIGURATION_NAME_MISMATCH", "configuration": name,
                 "read_back": state})

        active_name = _active_configuration_name(manager)
        if activate and active_name != name:
            com(document, "ShowConfiguration2", name)  # may return False anyway
            active_name = _active_configuration_name(manager)
            if active_name != name:
                return sw._result(
                    False,
                    f"Configuration '{name}' was created but did not become active.",
                    SwErrors.swFeatureError,
                    {"code": "CONFIGURATION_NOT_ACTIVATED", "configuration": name,
                     "active_configuration": active_name, "read_back": state})

        data = {
            "configuration": name,
            "comment": comment,
            "description": description,
            "alternate_name": alternate_name,
            "parent_configuration": parent,
            "options": options,
            "rebuild": rebuild,
            "active": active_name == name,
            "active_configuration": active_name,
            "created": created is not None,
            "read_back": state,
        }
        return sw._result(True, f"Created configuration '{name}'.", data=data)
    except Exception as create_error:
        return sw._result(False, f"Creating configuration failed: {create_error}",
                          SwErrors.swFeatureError)
