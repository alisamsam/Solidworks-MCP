"""
Cut list tools (part F1): read cut-list items from a weldment part.
"""

import logging

import pythoncom
import win32com.client

from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")

_KNOWN_FIELDS = {"LENGTH", "QUANTITY", "DESCRIPTION", "MATERIAL", "ANGLE1", "ANGLE2"}


def _read_property(cpm, name: str) -> str:
    raw = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    val = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    ok = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
    cpm.Get5(name, False, raw, val, ok)
    return val.value


def _parse_float(text):
    if not text:
        return None
    try:
        return float(text.rstrip("°"))
    except ValueError:
        return None


def _parse_int(text):
    value = _parse_float(text)
    return int(value) if value is not None else None


@tool(
    name="get_cut_list",
    description=(
        "Read cut-list items from the active weldment part: description, "
        "quantity, length (mm), material, cut angles, and all other "
        "custom properties per item. Forces a cut-list refresh on each "
        "folder before reading, so data reflects the current model. "
        "Read-only."
    ),
    schema={
        "type": "object",
        "properties": {
            "include_properties": {
                "type": "boolean",
                "description": "Include the full raw custom-property map per item, in "
                                "addition to the typed fields. Default true.",
                "default": True
            }
        },
        "required": []
    },
    operation_class=OperationClass.STATEFUL_READ,
)
def get_cut_list(sw, include_properties: bool = True) -> dict:
    """Walk the active part's feature tree and read every visible cut-list folder."""
    doc, err = sw.get_active_doc()
    if err:
        return err

    items = []
    refresh_failures = []
    feat = com(doc, "FirstFeature")
    while feat is not None:
        if com(feat, "GetTypeName2") == "CutListFolder":
            bf = com(feat, "GetSpecificFeature2")
            name = com(feat, "Name")
            try:
                com(bf, "UpdateCutList")
            except Exception as e:
                logger.warning(f"UpdateCutList failed for {name}: {e}")
                refresh_failures.append(name)

            if com(bf, "GetBodyCount") > 0:
                cpm = com(feat, "CustomPropertyManager")
                prop_names = com(cpm, "GetNames") or []
                raw_props = {n: _read_property(cpm, n) for n in prop_names}

                item = {
                    "folder": name,
                    "description": raw_props.get("DESCRIPTION", name),
                    "quantity": _parse_int(raw_props.get("QUANTITY")),
                    "length_mm": _parse_float(raw_props.get("LENGTH")),
                    "material": raw_props.get("MATERIAL"),
                    "angle1_deg": _parse_float(raw_props.get("ANGLE1")),
                    "angle2_deg": _parse_float(raw_props.get("ANGLE2")),
                }
                if include_properties:
                    item["properties"] = raw_props
                items.append(item)
        feat = com(feat, "GetNextFeature")

    message = f"Found {len(items)} cut-list item(s)."
    if refresh_failures:
        message += (
            f" WARNING: cut-list refresh failed for {refresh_failures} — "
            "these values may be stale."
        )

    return sw._result(True, message, data={"items": items})
