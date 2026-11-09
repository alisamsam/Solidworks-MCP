"""
Drawing tools (part F2): standard views and cut-list table on the active drawing.
"""

import logging
import os

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger("SolidWorksMCP")

SW_DOC_DRAWING = 3

# swAutodimEntities_e / swAutodimScheme_e / swAutodimHorizontalPlacement_e /
# swAutodimVerticalPlacement_e (swconst.tlb, verified for rev 33).
SW_AUTODIM_ENTITIES_BASED_ON_PRESELECT = 0
SW_AUTODIM_SCHEME_BASELINE = 1
SW_AUTODIM_HORIZONTAL_ABOVE = 1
SW_AUTODIM_VERTICAL_RIGHT = 1

_DEFAULT_ANGLE_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "templates",
    "weldment_cutlist_angles.sldwldtbt"
)


@tool(
    name="list_drawing_views",
    description="List the views on the active drawing sheet, by name. Read-only.",
    schema={"type": "object", "properties": {}, "required": []},
    operation_class=OperationClass.READ,
)
def list_drawing_views(sw) -> dict:
    """Enumerate views on the active drawing document."""
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 3:
        return sw._result(False, "Active document is not a drawing.",
                          SwErrors.swUnknownError)

    views = []
    v = com(doc, "GetFirstView")
    while v is not None:
        views.append(com(v, "GetName2"))
        v = com(v, "GetNextView")

    return sw._result(True, f"Found {len(views)} view(s).", data={"views": views})


@tool(
    name="add_standard_3_view",
    description=(
        "Add a standard 3-view (third-angle projection) of a model to the "
        "active drawing sheet. The model must already be open in SolidWorks. "
        "Modifies the active drawing."
    ),
    schema={
        "type": "object",
        "properties": {
            "model_name": {
                "type": "string",
                "description": "Title of the already-open model document (part/assembly), "
                                "e.g. as shown by list_open_documents."
            }
        },
        "required": ["model_name"]
    },
    operation_class=OperationClass.MUTATE,
)
def add_standard_3_view(sw, model_name: str) -> dict:
    """Insert front/top/right views of an open model onto the active drawing."""
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 3:
        return sw._result(False, "Active document is not a drawing.",
                          SwErrors.swUnknownError)

    try:
        ok = com(doc, "Create3rdAngleViews2", model_name)
    except Exception as e:
        logger.error(f"Create3rdAngleViews2 failed: {e}")
        return sw._result(False, f"Could not create standard views: {e}",
                          SwErrors.swUnknownError)

    if not ok:
        return sw._result(
            False,
            f"Create3rdAngleViews2 returned false for '{model_name}' — is it open "
            "and spelled exactly as in list_open_documents?",
            SwErrors.swUnknownError)

    return sw._result(True, f"Created standard 3-view of '{model_name}'.")


@tool(
    name="insert_cut_list_table",
    description=(
        "Insert a weldment cut-list table into a drawing view. The view must "
        "already show a weldment part with a cut list (see get_cut_list). "
        "Modifies the active drawing."
    ),
    schema={
        "type": "object",
        "properties": {
            "view_name": {
                "type": "string",
                "description": "Name of the drawing view to attach the table to, "
                                "from list_drawing_views."
            },
            "x": {"type": "number", "description": "Table anchor X position in meters.", "default": 0.05},
            "y": {"type": "number", "description": "Table anchor Y position in meters.", "default": 0.05},
            "template_path": {
                "type": "string",
                "description": "Full path to a .sldwldtbt table template. Optional; "
                                "empty uses the default template."
            }
        },
        "required": ["view_name"]
    },
    operation_class=OperationClass.MUTATE,
)
def insert_cut_list_table(sw, view_name: str, x: float = 0.05, y: float = 0.05,
                           template_path: str = "") -> dict:
    """Insert a cut-list table anchored at (x, y) into the named drawing view."""
    doc, err = sw.get_active_doc()
    if err:
        return err
    if com(doc, "GetType") != 3:
        return sw._result(False, "Active document is not a drawing.",
                          SwErrors.swUnknownError)

    view = None
    v = com(doc, "GetFirstView")
    while v is not None:
        if com(v, "GetName2") == view_name:
            view = v
            break
        v = com(v, "GetNextView")

    if view is None:
        return sw._result(False, f"View not found: {view_name}",
                          SwErrors.swUnknownError)

    effective_template = template_path or (
        _DEFAULT_ANGLE_TEMPLATE if os.path.isfile(_DEFAULT_ANGLE_TEMPLATE) else ""
    )

    try:
        table = view.InsertWeldmentTable(True, x, y, 1, "", effective_template)
    except Exception as e:
        logger.error(f"InsertWeldmentTable failed: {e}")
        return sw._result(False, f"Could not insert cut-list table: {e}",
                          SwErrors.swUnknownError)

    if table is None:
        return sw._result(
            False,
            f"InsertWeldmentTable returned nothing for view '{view_name}' — "
            "it likely has no cut list (not a weldment, or cut list not built).",
            SwErrors.swUnknownError)

    return sw._result(
        True,
        f"Inserted cut-list table on view '{view_name}' "
        f"({table.RowCount} row(s), {table.ColumnCount} column(s)).",
        data={"rows": table.RowCount, "columns": table.ColumnCount}
    )


def _find_view(document, view_name):
    """Return the named drawing view, keeping every proxy alive until found."""
    retained = []
    view = com(document, "GetFirstView")
    while view is not None:
        retained.append(view)
        if com(view, "GetName2") == view_name:
            return view
        view = com(view, "GetNextView")
    return None


@tool(
    name="add_drawing_dimension",
    description=(
        "Auto-dimension one drawing view with baseline dimensions and report the "
        "resulting dimension count. Modifies the active drawing."
    ),
    schema={"type": "object", "properties": {
        "view_name": {"type": "string",
                      "description": "Drawing view name from list_drawing_views."},
    }, "required": ["view_name"]},
    operation_class=OperationClass.MUTATE,
)
def add_drawing_dimension(sw, view_name: str) -> dict:
    """Run IDrawingDoc.AutoDimension on the named view and prove the count grew."""
    if not isinstance(view_name, str) or not view_name.strip():
        return sw._result(False, "view_name must be a non-empty drawing view name.",
                          SwErrors.swInvalidInput, {"code": "VALIDATION_FAILED"})
    view_name = view_name.strip()

    document, error = sw.get_active_doc()
    if error:
        return error
    if com(document, "GetType") != SW_DOC_DRAWING:
        return sw._result(False, "A drawing dimension requires an active drawing.",
                          SwErrors.swUnknownError)

    view = _find_view(document, view_name)
    if view is None:
        return sw._result(False, f"View not found: {view_name}",
                          SwErrors.swUnknownError)

    before = com(view, "GetDimensionCount2")
    try:
        com(document, "ClearSelection2", True)
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        if not com(com(document, "Extension"), "SelectByID2", view_name,
                   "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, empty, 0):
            return sw._result(False, f"Could not select drawing view: {view_name}",
                              SwErrors.swSelectionError)
        # IDrawingDoc.AutoDimension(EntitiesToDimension, HorizontalScheme,
        # HorizontalPlacement, VerticalScheme, VerticalPlacement).
        status = com(document, "AutoDimension",
                     SW_AUTODIM_ENTITIES_BASED_ON_PRESELECT,
                     SW_AUTODIM_SCHEME_BASELINE,
                     SW_AUTODIM_HORIZONTAL_ABOVE,
                     SW_AUTODIM_SCHEME_BASELINE,
                     SW_AUTODIM_VERTICAL_RIGHT)
    except Exception as dimension_error:
        return sw._result(False, f"Auto-dimension failed: {dimension_error}",
                          SwErrors.swUnknownError)
    finally:
        com(document, "ClearSelection2", True)

    after = com(view, "GetDimensionCount2")
    added = after - before if isinstance(after, int) and isinstance(before, int) else None
    # In SW 2025 rev 33.1.1 AutoDimension returns 1 even when it adds
    # dimensions, so the return code is only diagnostic; the trustworthy
    # evidence is that the view's dimension count grew.
    if added is not None and added <= 0:
        return sw._result(
            False,
            f"Auto-dimension added no dimensions to '{view_name}' "
            f"(AutoDimension returned {status}). The view needs visible model "
            "geometry to dimension.",
            SwErrors.swUnknownError,
            {"code": "NO_DIMENSIONS_ADDED", "view_name": view_name,
             "autodim_status": status, "dimensions_before": before,
             "dimensions_after": after},
        )

    return sw._result(
        True,
        f"Added {added if added is not None else 'baseline'} dimension(s) to "
        f"'{view_name}'.",
        data={"view_name": view_name, "autodim_status": status,
              "dimensions_before": before, "dimensions_after": after,
              "dimensions_added": added},
    )
