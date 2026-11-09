"""SolidWorks session health: graphics memory report and a guarded restart.

SolidWorks does not return the graphics memory of a closed document window
until it exits: about 36 MB per document when the last window closes, about
8 MB while another window stays open.  A long session therefore grows its
dedicated GPU memory even with few documents open, until the system slows
down and COM calls start failing.  Only a restart releases it.
"""

from pathlib import Path

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass, WriteDeniedError
from ..core.session import DocumentSession
from ..registry import tool
from ..session_monitor import monitor

GPU_RESTART_THRESHOLD_MB = 4096
_SYNCHRONIZE = 0x00100000


def solidworks_process_id(sw):
    try:
        return int(com(sw.app, "GetProcessID"))
    except Exception:
        return None


def dedicated_gpu_mb(process_id):
    """Dedicated GPU memory of one process summed over all adapters, or None."""
    if not process_id:
        return None
    try:
        import win32pdh

        paths = win32pdh.ExpandCounterPath(
            rf"\GPU Process Memory(pid_{process_id}_*)\Dedicated Usage")
        query = win32pdh.OpenQuery()
        try:
            counters = [win32pdh.AddCounter(query, path) for path in paths]
            win32pdh.CollectQueryData(query)
            total = sum(win32pdh.GetFormattedCounterValue(counter, win32pdh.PDH_FMT_LARGE)[1]
                        for counter in counters)
        finally:
            win32pdh.CloseQuery(query)
        return round(total / 2**20, 1)
    except Exception:
        return None


def session_health(sw):
    """Process, graphics memory and open documents of the connected session."""
    try:
        connected = sw.is_connected
    except Exception:
        connected = False
    if not connected:
        return {"connected": False}
    process_id = solidworks_process_id(sw)
    gpu_mb = dedicated_gpu_mb(process_id)
    listed = sw.list_open_documents()
    documents = listed["data"]["documents"] if listed["success"] else None
    health = {
        "connected": True,
        "process_id": process_id,
        "gpu_dedicated_mb": gpu_mb,
        "gpu_restart_threshold_mb": GPU_RESTART_THRESHOLD_MB,
        "open_documents": len(documents) if documents is not None else None,
        "restart_recommended": gpu_mb is not None and gpu_mb >= GPU_RESTART_THRESHOLD_MB,
        "counters": monitor.snapshot(),
    }
    if health["restart_recommended"]:
        health["hint"] = ("SolidWorks keeps the graphics memory of closed documents until it "
                          "exits. Save the work, then restart it with restart_solidworks.")
    return health


def _restart_blockers(sw, documents):
    """Documents a restart would close without the user's consent."""
    blockers = []
    for document in documents:
        path = document.get("path")
        if not path:
            reason = "never saved"
        elif document.get("unsaved_changes") is not False:
            reason = "unsaved changes"
        else:
            try:
                sw._path_policy.require_write(Path(path), OperationClass.EXPORT)
                lifecycle = getattr(sw, 'document_lifecycle_status', None)
                if lifecycle is not None:
                    status = lifecycle(path)
                    if not status.get('managed') or not status.get('safe'):
                        blockers.append({'title': document.get('title'), 'path': path,
                                         'reason': 'user document or untracked edits'})
                        continue
                continue
            except WriteDeniedError:
                reason = "outside the approved output roots"
        blockers.append({"title": document.get("title"), "path": path or None, "reason": reason})
    return blockers


_HOLDER_SUFFIXES = (".SLDASM", ".SLDDRW")


def _current_document(sw, document):
    """The document's entry in a fresh listing, or None when it cannot be confirmed."""
    listed = sw.list_open_documents()
    if not listed["success"] or not listed["data"].get("complete"):
        return None
    for current in listed["data"]["documents"]:
        if current.get("path") == document["path"]:
            return current
    return None


def _wait_for_exit(process_id, timeout_s):
    import win32api
    import win32event

    try:
        handle = win32api.OpenProcess(_SYNCHRONIZE, False, process_id)
    except Exception:
        return True  # the process is already gone
    try:
        return win32event.WaitForSingleObject(handle, int(timeout_s * 1000)) == win32event.WAIT_OBJECT_0
    finally:
        win32api.CloseHandle(handle)


@tool(
    name="restart_solidworks",
    description=(
        "Exit and relaunch SolidWorks to release graphics memory that closed "
        "documents keep until exit (see get_solidworks_info session.gpu_dedicated_mb). "
        "Refuses while any open document is unsaved, modified or outside the "
        "approved output roots; saved output documents are closed. Requires "
        "confirm=true after the user agreed."
    ),
    schema={
        "type": "object",
        "properties": {
            "confirm": {"type": "boolean", "default": False,
                        "description": "True only after the user agreed to the restart."},
            "exit_timeout_s": {"type": "number", "default": 60, "minimum": 5, "maximum": 300},
        },
        "additionalProperties": False,
    },
    operation_class=OperationClass.SESSION,
)
def restart_solidworks(sw, confirm=False, exit_timeout_s=60):
    if not sw.is_connected:
        return sw._result(False, "Not connected to SolidWorks; nothing to restart.",
                          SwErrors.swConnectionError)
    listed = sw.list_open_documents()
    if not listed["success"] or not listed["data"].get("complete"):
        return sw._result(False, "Open documents could not be listed completely; restart refused.",
                          SwErrors.swInvalidInput, listed.get("data"))
    documents = listed["data"]["documents"]
    blockers = _restart_blockers(sw, documents)
    if blockers:
        return sw._result(False, "Restart refused: save or close these documents first.",
                          SwErrors.swInvalidInput, {"blockers": blockers})
    before = session_health(sw)
    closing = [document["title"] for document in documents]
    if not confirm:
        return sw._result(False, "Restart needs confirm=true after the user agreed.",
                          SwErrors.swInvalidInput, {"would_close": closing, "before": before})
    process_id = before.get("process_id")
    if not process_id:
        return sw._result(False, "SolidWorks process id is unavailable; restart refused.",
                          SwErrors.swUnknownError)

    com(sw.app, "ExitApp")
    sw.disconnect()
    sw._document_session = DocumentSession()
    if not _wait_for_exit(process_id, exit_timeout_s):
        return sw._result(False, f"SolidWorks did not exit within {exit_timeout_s} s; "
                          "a dialog may be open. It was not terminated.",
                          SwErrors.swUnknownError, {"process_id": process_id})
    connected = sw.connect()
    if not connected["success"]:
        return sw._result(False, f"SolidWorks exited but did not restart: {connected['message']}",
                          SwErrors.swConnectionError, {"closed": closing, "before": before})
    return sw._result(True, "SolidWorks restarted.", SwErrors.swSuccess,
                      {"closed": closing, "before": before, "after": session_health(sw)})


@tool(
    name="close_saved_outputs",
    description=(
        "Close open documents that are saved, unmodified and inside the approved "
        "output roots, to slow graphics memory growth in a long session. Never "
        "closes unsaved, modified or user documents. Lists only unless confirm=true."
    ),
    schema={
        "type": "object",
        "properties": {
            "confirm": {"type": "boolean", "default": False,
                        "description": "True to close; false only lists."},
        },
        "additionalProperties": False,
    },
    operation_class=OperationClass.SESSION,
)
def close_saved_outputs(sw, confirm=False):
    if not sw.is_connected:
        return sw._result(False, "Not connected to SolidWorks.", SwErrors.swConnectionError)
    listed = sw.list_open_documents()
    if not listed["success"] or not listed["data"].get("complete"):
        return sw._result(False, "Open documents could not be listed completely; nothing closed.",
                          SwErrors.swInvalidInput, listed.get("data"))
    documents = listed["data"]["documents"]
    kept = _restart_blockers(sw, documents)
    kept_titles = {item["title"] for item in kept}
    closable = [document for document in documents if document.get("title") not in kept_titles]
    unsaved = [item["title"] for item in kept if item["reason"] in ("never saved", "unsaved changes")]
    if unsaved:
        # Closing an assembly or drawing would also drop a part that is only loaded through it.
        holders = [d for d in closable if Path(d.get("path") or "").suffix.upper() in _HOLDER_SUFFIXES]
        kept += [{"title": d["title"], "path": d["path"],
                  "reason": "depends on unsaved " + ", ".join(unsaved)} for d in holders]
        closable = [d for d in closable if d not in holders]
    closable.sort(key=lambda d: Path(d.get("path") or "").suffix.upper() not in _HOLDER_SUFFIXES)
    if not confirm:
        return sw._result(True, f"{len(closable)} saved output document(s) can be closed.",
                          SwErrors.swSuccess,
                          {"would_close": [{"title": d["title"], "path": d["path"]} for d in closable],
                           "kept": kept})
    attempted = []
    for document in closable:
        current = _current_document(sw, document)
        if current is None or current.get("unsaved_changes") is not False:
            kept.append({"title": document["title"], "path": document["path"],
                         "reason": "changed since listing"})
            continue
        # Ownership/native stamp may have changed while closing earlier documents.
        if _restart_blockers(sw, [current]):
            kept.append({'title': document['title'], 'path': document['path'],
                         'reason': 'ownership or edit state changed since listing'})
            continue
        com(sw.app, "CloseDoc", document["path"])
        attempted.append(document)
    remaining = sw.list_open_documents()
    if not remaining["success"] or not remaining["data"].get("complete"):
        return sw._result(False, "Open documents could not be listed after closing; "
                          "check list_open_documents before continuing.",
                          SwErrors.swUnknownError, {"attempted": [d["title"] for d in attempted],
                                                    "kept": kept})
    still_open = {d.get("path") for d in remaining["data"]["documents"]}
    closed = [d for d in attempted if d["path"] not in still_open]
    kept += [{"title": d["title"], "path": d["path"], "reason": "still loaded (referenced)"}
             for d in attempted if d["path"] in still_open]
    return sw._result(True, f"Closed {len(closed)} saved output document(s). "
                      "Rebind the target document before the next change.",
                      SwErrors.swSuccess,
                      {"closed": [document["title"] for document in closed], "kept": kept})
