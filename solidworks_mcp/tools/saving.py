"""Guarded document saving (base roadmap item B18).

Exposes the automation-level save as an MCP tool and defaults to writing
inside the first approved output root, so drawings and models can be
persisted for review without an explicit path from the caller.
"""

import os
import re
from pathlib import Path

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .guard import require_output_write

SW_DOC_EXTENSIONS = {1: ".SLDPRT", 2: ".SLDASM", 3: ".SLDDRW"}
SW_DOC_LABELS = {1: "part", 2: "assembly", 3: "drawing"}
# A weldment profile is a part saved as a library feature part. SolidWorks
# accepts such a file as a structural-member profile only when the file itself
# carries the .sldlfp extension, so an explicit .sldlfp target is honoured for
# these document types instead of being corrected to the native extension.
LIBRARY_FEATURE_EXTENSION = ".SLDLFP"
SW_DOC_LIBRARY_EXTENSIONS = {1: LIBRARY_FEATURE_EXTENSION}
DEFAULT_SUBFOLDER = "saved"
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _output_root(sw):
    policy = getattr(sw, "_path_policy", None)
    roots = getattr(policy, "output_roots", ()) if policy is not None else ()
    return Path(roots[0]) if roots else None


def _safe_filename(title: str, extension: str) -> str:
    cleaned = _INVALID_FILENAME.sub("_", title).strip().strip(".")
    return (cleaned or "document") + extension


@tool(
    name="save_document",
    description=(
        "Save the active part, assembly or drawing as a native SolidWorks "
        "file. Without a path it saves into the first approved output root "
        "under 'subfolder', using the document title as the file name. "
        "Naming a .sldlfp path saves a part as a weldment profile; any other "
        "extension is corrected to the native one. "
        "Paths outside the approved output roots are denied."
    ),
    schema={"type": "object", "properties": {
        "path": {"type": "string",
                 "description": "Optional full destination path. Without it the "
                                "file goes to <output_root>/<subfolder>/<title>.<ext>. "
                                "Use a .sldlfp path to save a part as a weldment profile."},
        "subfolder": {"type": "string", "default": DEFAULT_SUBFOLDER,
                      "description": "Folder inside the first output root used when "
                                     "path is omitted."},
        "overwrite": {"type": "boolean", "default": True,
                      "description": "When false, an existing file is reported "
                                     "instead of replaced."},
    }, "required": []},
    operation_class=OperationClass.MUTATE,
    postflight="save",
)
def save_document(sw, path: str = None, subfolder: str = DEFAULT_SUBFOLDER,
                  overwrite: bool = True) -> dict:
    document, error = sw.get_active_doc()
    if error:
        return error

    doc_type = com(document, "GetType")
    extension = SW_DOC_EXTENSIONS.get(doc_type)
    if extension is None:
        return sw._result(
            False, f"Cannot save document type {doc_type} as a native file.",
            SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"},
        )

    if path is None or not str(path).strip():
        root = _output_root(sw)
        if root is None:
            return sw._result(
                False, "No approved output root is configured; pass an explicit path.",
                SwErrors.swInvalidInput, {"code": "NO_OUTPUT_ROOT"},
            )
        if not isinstance(subfolder, str) or not subfolder.strip():
            subfolder = DEFAULT_SUBFOLDER
        title = com(document, "GetTitle") or SW_DOC_LABELS[doc_type]
        target = root / subfolder.strip() / _safe_filename(str(title), extension)
    else:
        target = Path(str(path)).expanduser()
        if target.suffix.casefold() != extension.casefold():
            library_extension = SW_DOC_LIBRARY_EXTENSIONS.get(doc_type)
            if (
                library_extension is None
                or target.suffix.casefold() != library_extension.casefold()
            ):
                target = target.with_suffix(extension)

    denied = require_output_write(sw, str(target))
    if denied:
        return denied

    if target.exists() and not overwrite:
        return sw._result(
            False, f"Save path already exists: {target}", SwErrors.swFileSaveError,
            {"code": "OUTPUT_EXISTS", "path": str(target)},
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    saved = sw.save_document(str(target))
    if not saved.get("success"):
        return saved

    if not target.is_file():
        return sw._result(
            False, f"SolidWorks reported a save but no file was written: {target}",
            SwErrors.swFileSaveError, {"path": str(target)},
        )

    return sw._result(
        True, f"Saved {SW_DOC_LABELS[doc_type]} to {target}.",
        data={
            **saved.get("data", {}),
            "path": str(target),
            "document_type": SW_DOC_LABELS[doc_type],
            "size_bytes": os.path.getsize(target),
        },
    )
