"""Harness-independent MCP access to the same local project register as the GUI."""

from __future__ import annotations

from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from ..workspace.parameter_store import Conflict, ParameterStore, ValidationError


@tool(
    name="read_parameter_workspace",
    description="Read local parameter projects or one project's owners, values, drafts, missing data, requests and history. No CAD connection.",
    schema={"type": "object", "properties": {
        "project_id": {"type": "string", "description": "Omit to list projects; supply exact project ID for its snapshot."}
    }, "additionalProperties": False},
    operation_class=OperationClass.READ,
)
def read_parameter_workspace(sw, project_id=None):
    try:
        store = ParameterStore()
        data = store.snapshot(project_id) if project_id else {"projects": store.list_projects()}
        return sw._result(True, "Parameter workspace read; no CAD operation executed.", SwErrors.swSuccess, data)
    except ValidationError as error:
        return sw._result(False, str(error), SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})


@tool(
    name="write_parameter_workspace",
    description="Edit only the local project register: create project/owner/parameter, save draft or queue a request. Never changes CAD.",
    schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["create_project", "add_owner", "add_parameter", "set_draft", "discard_draft", "add_request", "update_request", "queue_cad_job", "cancel_cad_job"]},
        "project_id": {"type": "string", "description": "Required except when creating a project."},
        "payload": {"type": "object", "description": "Typed fields for the selected action."},
        "expected_revision": {"type": "integer", "minimum": 0,
                              "description": "Recommended optimistic project revision for all edits in an existing project."}
    }, "required": ["action", "payload"], "additionalProperties": False},
    operation_class=OperationClass.PROJECT_WRITE,
)
def write_parameter_workspace(sw, action, payload, project_id=None, expected_revision=None):
    try:
        if not isinstance(payload, dict):
            raise ValidationError("Payload mora biti objekt.")
        store = ParameterStore()
        if action == "create_project":
            result = (store.create_stair_railing_project(payload.get("name"))
                      if payload.get("template") == "stairs_railing" else
                      store.create_project(payload.get("name")))
        else:
            if not project_id:
                raise ValidationError("Manjka ID projekta.")
            if action == "add_owner":
                result = store.add_owner(project_id, payload, expected_revision)
            elif action == "add_parameter":
                result = store.add_parameter(project_id, payload, expected_revision)
            elif action == "set_draft":
                result = store.set_draft(project_id, payload.get("parameter_id"),
                                         payload.get("value"), expected_revision)
            elif action == "discard_draft":
                result = store.discard_draft(project_id, payload.get("parameter_id"), expected_revision)
            elif action == "add_request":
                result = store.add_request(project_id, payload.get("text"),
                                           payload.get("owner_id"), expected_revision)
            elif action == "update_request":
                result = store.update_request(project_id, payload.get("request_id"),
                                              payload.get("status"), expected_revision)
            elif action == "queue_cad_job":
                result = store.queue_cad_job(project_id, expected_revision)
            elif action == "cancel_cad_job":
                result = store.cancel_cad_job(project_id, payload.get("job_id"), expected_revision)
            else:
                raise ValidationError("Nepodprta operacija registra.")
        return sw._result(True, "Project register updated; CAD was not changed.",
                          SwErrors.swSuccess, result)
    except Conflict as error:
        return sw._result(False, str(error), SwErrors.swInvalidInput,
                          {"code": "REVISION_CONFLICT"})
    except ValidationError as error:
        return sw._result(False, str(error), SwErrors.swInvalidInput,
                          {"code": "VALIDATION_FAILED"})
