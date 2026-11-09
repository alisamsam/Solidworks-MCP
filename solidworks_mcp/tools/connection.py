"""Session tools: connection, capability report, modeling guide, units, raw execution."""

import io
import json
import logging
import sys
import traceback
from typing import Dict

from ..config import get_config
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..knowledge import library as modeling_guidance
from ..registry import tool
from ..utils import get_solidworks_info, set_default_unit

logger = logging.getLogger("SolidWorksMCP")


@tool(
    name="get_modeling_guide",
    description=(
        "Read SolidWorks expert guidance and ordered modeling workflows. "
        "Use topic='index' to choose a topic before modeling; returns relevant "
        "currently advertised tools and recorded evidence. Read-only, no CAD connection needed."
    ),
    schema={"type": "object", "properties": {
        "topic": {"type": "string", "default": "index",
                  "description": "Exact topic ID from index, e.g. workflow/part, workflow/weldment, expert."}
    }, "additionalProperties": False},
    operation_class=OperationClass.READ,
    com=False,
)
def get_modeling_guide(sw, topic="index"):
    from .. import catalog

    try:
        payload = modeling_guidance.read_topic(topic, catalog.advertised_tool_names())
    except ValueError as error:
        return sw._result(False, str(error), SwErrors.swInvalidInput)
    return sw._result(True, "Modeling guide loaded; no CAD operations executed.",
                      SwErrors.swSuccess, payload)


@tool(
    name="connect_solidworks",
    description="Connect to SolidWorks. Launches if not running.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.SESSION,
)
def connect_solidworks(sw):
    return sw.connect()


@tool(
    name="get_solidworks_info",
    description=(
        "Get SolidWorks installation information and, when connected, session health: "
        "process id, dedicated GPU memory, open document count and a restart hint."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def solidworks_info(sw):
    from .session import session_health  # lazy: session registers a tool, and connection tools must list first

    info = get_solidworks_info()
    info["session"] = session_health(sw)
    return {
        "success": info["found"],
        "message": f"SolidWorks {'found' if info['found'] else 'not found'}",
        "error_code": 0 if info["found"] else 105,
        "error_name": "swSuccess" if info["found"] else "swSolidWorksNotFound",
        "data": info,
    }


@tool(
    name="get_capabilities",
    description="Report the currently advertised tools, guarded-mode state, and known blocked capabilities.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def get_capabilities(sw):
    from .. import catalog

    guarded = get_config().guarded_mode
    blocked = [{
        "name": "pack_and_go",
        "status": "blocked",
        "reason": "pywin32 cannot marshal the required BYREF IDispatch Pack-and-Go out parameter.",
    }]
    if guarded:
        blocked.append({
            "name": "execute_python",
            "status": "blocked",
            "reason": "Raw execution is disabled in guarded mode.",
        })
    sw_build = None
    if sw.is_connected:
        try:
            revision = sw.app.RevisionNumber
            sw_build = revision() if callable(revision) else revision
        except Exception:
            sw_build = "unavailable"
    return {
        "success": True,
        "message": "Capability report generated.",
        "error_code": 0,
        "error_name": "swSuccess",
        "data": {
            "guarded_mode": guarded,
            "solidworks_build": sw_build,
            "advertised_tools": [item.name for item in catalog.advertised_tools()],
            "blocked_capabilities": blocked,
            "toolsets": {"enabled": catalog.enabled_toolsets(),
                         "available": sorted(catalog.TOOLSETS),
                         "routing_enabled": catalog.routing_enabled()},
            "modeling_guidance": {"tool": "get_modeling_guide", "topic": "index",
                                  "resource": "solidworks://guides/index"},
        },
    }


@tool(
    name="bind_active_document",
    description=(
        "Explicitly bind the current SolidWorks ActiveDoc and configuration "
        "as the target for subsequent mutating operations."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.SESSION,
    postflight="bound",
)
def bind_active_document(sw):
    document = sw.bind_active_document()
    return sw._result(True, "Active document bound to this MCP session.",
                      SwErrors.swSuccess, document.to_dict())


@tool(
    name="set_units",
    description="Set default unit for dimensions.",
    schema={
        "type": "object",
        "properties": {
            "unit": {
                "type": "string",
                "enum": ["mm", "inch", "m", "cm"],
                "description": "Default unit"
            }
        },
        "required": ["unit"]
    },
    operation_class=OperationClass.SESSION,
)
def set_units(sw, unit="mm"):
    set_default_unit(unit)
    sw._units.default_unit = unit
    return {
        "success": True,
        "message": f"Default unit set to: {unit}",
        "error_code": 0,
        "error_name": "swSuccess",
        "data": {"unit": unit},
    }


@tool(
    name="execute_python",
    description="Execute custom Python code with stdout capture. Access 'sw' (app), 'doc' (active document). Use print() for debug output.",
    schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"}
        },
        "required": ["code"]
    },
    operation_class=OperationClass.RAW_EXECUTION,
)
def execute_python(sw, code=""):
    if get_config().guarded_mode:
        return sw._result(False, "execute_python is unavailable in guarded mode.",
                          SwErrors.swInvalidInput)
    if not code:
        return sw._result(False, "Code is required", SwErrors.swInvalidInput)
    return _execute_python(sw, code)


def _execute_python(sw, code: str) -> Dict:
    """
    Execute custom Python code with access to SolidWorks.
    FIXED: Now captures stdout, stderr, and 'result' variable.
    """
    try:
        if not sw.is_connected:
            r = sw.connect()
            if not r["success"]:
                return r
        
        import win32com.client
        import pythoncom
        import math
        import os as os_module
        
        # Prepare execution context with many useful objects
        exec_globals = {
            # SolidWorks objects
            'sw': sw.app,
            'doc': sw.app.ActiveDoc if sw.app else None,
            'automation': sw,
            
            # COM libraries
            'win32com': win32com,
            'pythoncom': pythoncom,
            
            # Standard libraries
            'math': math,
            'os': os_module,
            'json': json,
            
            # Result placeholder
            'result': None,
        }
        
        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        
        try:
            sys.stdout = captured_stdout
            sys.stderr = captured_stderr
            
            # Execute the code
            exec(code, exec_globals)
            
        finally:
            # Always restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        
        # Get captured output
        stdout_text = captured_stdout.getvalue()
        stderr_text = captured_stderr.getvalue()
        result_val = exec_globals.get('result')
        
        # Build response message
        message_parts = []
        
        if stdout_text:
            message_parts.append(f"=== Output ===\n{stdout_text.rstrip()}")
        
        if stderr_text:
            message_parts.append(f"=== Stderr ===\n{stderr_text.rstrip()}")
        
        if result_val is not None:
            message_parts.append(f"=== Result ===\n{result_val}")
        
        if not message_parts:
            message_parts.append("Code executed successfully (no output)")
        
        return {
            "success": True,
            "message": "\n\n".join(message_parts),
            "error_code": 0,
            "error_name": "swSuccess",
            "data": {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "result": str(result_val) if result_val is not None else None
            }
        }
        
    except SyntaxError as e:
        return {
            "success": False,
            "message": f"Syntax error: {e}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {"error_type": "SyntaxError", "details": str(e)}
        }
        
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "success": False,
            "message": f"Execution error: {e}\n\nTraceback:\n{tb}",
            "error_code": 999,
            "error_name": "swUnknownError",
            "data": {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": tb
            }
        }
