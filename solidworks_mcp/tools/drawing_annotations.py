"""Drawing annotation tools: marked model dimensions and auto balloons (R5 / D1)."""

import pythoncom
import win32com.client

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool


SW_DOC_DRAWING = 3

# swInsertAnnotation_e.swInsertDimensionsMarkedForDrawing (swconst.tlb).
SW_INSERT_DIMENSIONS_MARKED_FOR_DRAWING = 32768

# swImportModelItemsSource_e.swImportModelItemsFromEntireModel (swconst.tlb).
SW_IMPORT_MODEL_ITEMS_FROM_ENTIRE_MODEL = 0

# swBalloonLayoutType_e.swDetailingBalloonLayout_Square-ish default used by the UI.
DEFAULT_BALLOON_LAYOUT = 1


def _active_drawing(sw):
    """Return (document, error_result) ensuring the active document is a drawing."""
    document, error = sw.get_active_doc()
    if error:
        return None, error
    if com(document, "GetType") != SW_DOC_DRAWING:
        return None, sw._result(False, "Active document is not a drawing.",
                                SwErrors.swUnknownError)
    return document, None


def _find_view(document, view_name):
    view = com(document, "GetFirstView")
    retained = []
    while view is not None:
        retained.append(view)
        if com(view, "GetName2") == view_name:
            return view
        view = com(view, "GetNextView")
    return None


def _select_view(document, view_name):
    empty_callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    return com(document.Extension, "SelectByID2", view_name, "DRAWINGVIEW",
               0.0, 0.0, 0.0, False, 0, empty_callout, 0)


def _annotation_count(view):
    count = 0
    retained = []
    annotation = com(view, "GetFirstAnnotation2")
    while annotation is not None:
        retained.append(annotation)
        count += 1
        annotation = com(annotation, "GetNext3")
    return count


def _invalid(sw, message):
    return sw._result(False, message, SwErrors.swInvalidInput,
                      {"code": "VALIDATION_FAILED"})


@tool(
    name="insert_marked_dimensions",
    description=(
        "Insert only the model dimensions marked 'Mark for Drawing' into one "
        "drawing view. Dimensions that are not marked for drawing are not "
        "imported. Modifies the active drawing."
    ),
    schema={"type": "object", "properties": {
        "view_name": {"type": "string"},
    }, "required": ["view_name"]},
    operation_class=OperationClass.MUTATE,
)
def insert_marked_dimensions(sw, view_name: str) -> dict:
    if not isinstance(view_name, str) or not view_name.strip():
        return _invalid(sw, "view_name must be a non-empty drawing view name.")
    view_name = view_name.strip()

    document, error = _active_drawing(sw)
    if error:
        return error

    view = _find_view(document, view_name)
    if view is None:
        return sw._result(False, f"View not found: {view_name}",
                          SwErrors.swUnknownError)

    before = com(view, "GetDimensionCount2")
    try:
        com(document, "ClearSelection2", True)
        if not _select_view(document, view_name):
            return sw._result(False, f"Could not select drawing view: {view_name}",
                              SwErrors.swSelectionError)
        # IDrawingDoc.InsertModelAnnotations4(Option, Types, AllViews,
        # DuplicateDims, HiddenFeatureDims, UsePlacementInSketch,
        # InsertAllAnnotations, InsertAllReferenceGeometry). Types filters the
        # import to swInsertAnnotation_e.swInsertDimensionsMarkedForDrawing; the
        # older InsertModelDimensions takes only 0..3 and cannot filter, so it
        # imports every dimension regardless of the mark.
        inserted = com(document, "InsertModelAnnotations4",
                       SW_IMPORT_MODEL_ITEMS_FROM_ENTIRE_MODEL,
                       SW_INSERT_DIMENSIONS_MARKED_FOR_DRAWING,
                       False, True, False, False, False, False)
    except Exception as insert_error:
        return sw._result(False, f"Inserting marked dimensions failed: {insert_error}",
                          SwErrors.swUnknownError)
    finally:
        com(document, "ClearSelection2", True)

    after = com(view, "GetDimensionCount2")
    imported = after - before if isinstance(after, int) and isinstance(before, int) else None
    if isinstance(inserted, (list, tuple)):
        imported_annotations = len(inserted)
    elif inserted is None:
        imported_annotations = 0
    else:
        imported_annotations = 1

    if imported_annotations <= 0 and (imported is None or imported <= 0):
        return sw._result(
            False,
            f"No dimensions marked 'Mark for Drawing' were imported into "
            f"'{view_name}'. Mark the model dimensions for drawing first.",
            SwErrors.swUnknownError,
            {"code": "NO_MARKED_DIMENSIONS", "view_name": view_name,
             "dimensions_before": before, "dimensions_after": after},
        )

    return sw._result(
        True,
        f"Imported {imported if imported is not None else imported_annotations} "
        f"dimension(s) into '{view_name}'.",
        data={
            "view_name": view_name,
            "dimensions_before": before,
            "dimensions_after": after,
            "imported": imported,
            "inserted_annotations": imported_annotations,
        },
    )


@tool(
    name="auto_balloon",
    description=(
        "Automatically add balloons to a drawing view, typically one per BOM/cut "
        "list row. Modifies the active drawing."
    ),
    schema={"type": "object", "properties": {
        "view_name": {"type": "string"},
        "layout": {"type": "integer", "default": 1,
                   "description": "Balloon layout value passed to the balloon options."},
        "ignore_multiple": {"type": "boolean", "default": False,
                            "description": "When true, balloons only one instance "
                                           "of repeated components."},
    }, "required": ["view_name"]},
    operation_class=OperationClass.MUTATE,
)
def auto_balloon(sw, view_name: str, layout: int = DEFAULT_BALLOON_LAYOUT,
                 ignore_multiple: bool = False) -> dict:
    if not isinstance(view_name, str) or not view_name.strip():
        return _invalid(sw, "view_name must be a non-empty drawing view name.")
    view_name = view_name.strip()
    if not isinstance(layout, int):
        return _invalid(sw, "layout must be an integer.")

    document, error = _active_drawing(sw)
    if error:
        return error

    view = _find_view(document, view_name)
    if view is None:
        return sw._result(False, f"View not found: {view_name}",
                          SwErrors.swUnknownError)

    before = _annotation_count(view)
    try:
        com(document, "ClearSelection2", True)
        if not _select_view(document, view_name):
            return sw._result(False, f"Could not select drawing view: {view_name}",
                              SwErrors.swSelectionError)
        options = com(document, "CreateAutoBalloonOptions")
        if options is None:
            return sw._result(False, "SolidWorks could not create auto-balloon options.",
                              SwErrors.swUnknownError)
        options.Layout = layout
        options.IgnoreMultiple = bool(ignore_multiple)
        created = com(document, "AutoBalloon5", options)
    except Exception as balloon_error:
        return sw._result(False, f"Auto balloon failed: {balloon_error}",
                          SwErrors.swUnknownError)
    finally:
        com(document, "ClearSelection2", True)

    after = _annotation_count(view)
    added = after - before if isinstance(after, int) and isinstance(before, int) else None

    if added is not None and added <= 0 and not created:
        return sw._result(
            False,
            f"No balloons were added to '{view_name}'. The view needs a BOM or "
            "cut list with visible items.",
            SwErrors.swUnknownError,
            {"code": "NO_BALLOONS_ADDED", "view_name": view_name},
        )

    return sw._result(
        True,
        f"Added {added if added is not None else 'auto'} balloon(s) to '{view_name}'.",
        data={
            "view_name": view_name,
            "annotations_before": before,
            "annotations_after": after,
            "balloons_added": added,
        },
    )
