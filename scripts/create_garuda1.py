"""Create a concept model of the GARUDA-1 fixed-wing VTOL drone in SolidWorks.

The model is intentionally a lightweight concept model with separate solid
bodies for the airframe components. Dimensions are in millimetres.
"""

from __future__ import annotations

import os
import sys
import glob
from typing import Iterable, Sequence

import pythoncom
import win32com.client


MM = 0.001


def point(x: float, y: float) -> tuple[float, float]:
    return x * MM, y * MM


def connect():
    try:
        app = win32com.client.GetObject(Class="SldWorks.Application")
    except Exception:
        app = win32com.client.Dispatch("SldWorks.Application")
    app.Visible = True
    return app


def select_plane(doc, name: str) -> None:
    doc.ClearSelection2(True)
    empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    if not doc.Extension.SelectByID2(
        name, "PLANE", 0, 0, 0, False, 0, empty, 0
    ):
        raise RuntimeError(f"Could not select {name}")
    doc.InsertSketch2(True)


def draw_polygon(doc, vertices: Sequence[tuple[float, float]]) -> None:
    if len(vertices) < 3:
        raise ValueError("A closed polygon needs at least three vertices")
    sketch = doc.SketchManager
    for first, second in zip(vertices, vertices[1:] + vertices[:1]):
        x1, y1 = point(*first)
        x2, y2 = point(*second)
        sketch.CreateLine(x1, y1, 0, x2, y2, 0)


def draw_circle(doc, x: float, y: float, radius: float) -> None:
    cx, cy = point(x, y)
    r = radius * MM
    doc.SketchManager.CreateCircle(cx, cy, 0, cx + r, cy, 0)


def close_and_select_last_sketch(doc) -> str:
    doc.InsertSketch2(True)
    doc.ClearSelection2(True)
    last_name = None
    feature = doc.FirstFeature
    while feature is not None:
        try:
            if feature.GetTypeName2 == "ProfileFeature":
                last_name = feature.Name
        except Exception:
            pass
        try:
            feature = feature.GetNextFeature
        except Exception:
            break
    if not last_name:
        raise RuntimeError("The sketch was not added to the feature tree")
    empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    if not doc.Extension.SelectByID2(
        last_name, "SKETCH", 0, 0, 0, False, 0, empty, 0
    ):
        raise RuntimeError(f"Could not select sketch {last_name}")
    return last_name


def extrude(doc, depth: float, merge: bool = False) -> None:
    depth_m = depth * MM
    manager = doc.FeatureManager
    # FeatureExtrusion2 is supported by SolidWorks 2023-2025. The 20
    # parameter fallback keeps the macro usable with older installations.
    args = (
        True, False, False, 6, 0, depth_m, depth_m,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False, merge, True, True, 0, 0.0, False,
    )
    try:
        feature = manager.FeatureExtrusion2(*args)
    except Exception:
        feature = None
    if feature is None:
        try:
            feature = manager.FeatureExtrusion3(
                True, False, False, 6, 0, depth_m, depth_m,
                False, False, False, False, 0.0, 0.0,
                False, False, False, False, merge, True, True,
                0, 0.0, False,
            )
        except Exception:
            feature = None
    if feature is None:
        try:
            feature = manager.FeatureExtrusion2(
                True, False, False, 6, 0, depth_m, depth_m,
                False, False, False, False, 0.0, 0.0,
                False, False, False, merge, True, True, True,
            )
        except Exception:
            feature = None
    if feature is None:
        feature = manager.FeatureExtrusion2(
            True, False, False, 0, 0, depth_m, depth_m,
            False, False, False, False, 0.0, 0.0,
            False, False, False, merge, True, True, True,
        )
    if feature is None:
        raise RuntimeError("Extrusion failed")


def make_polygon_body(doc, plane: str, vertices: Sequence[tuple[float, float]],
                      thickness: float, merge: bool = False) -> None:
    select_plane(doc, plane)
    draw_polygon(doc, vertices)
    close_and_select_last_sketch(doc)
    extrude(doc, thickness, merge=merge)


def make_circle_body(doc, plane: str, x: float, y: float, radius: float,
                     thickness: float, merge: bool = False) -> None:
    select_plane(doc, plane)
    draw_circle(doc, x, y, radius)
    close_and_select_last_sketch(doc)
    extrude(doc, thickness, merge=merge)


def save_and_show(doc, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not doc.SaveAs(path):
        raise RuntimeError(f"Could not save {path}")
    doc.ShowNamedView2("*Isometric", 7)
    doc.ViewZoomtofit2()


def create_model(output_path: str) -> None:
    pythoncom.CoInitialize()
    app = connect()
    templates = glob.glob(
        r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS *\templates\Part.PRTDOT"
    )
    template = templates[0] if templates else ""
    doc = app.NewDocument(template or "", 0, 0, 0)
    if doc is None:
        raise RuntimeError("SolidWorks could not create a new part")

    # Main fuselage: 2600 mm long, 500 mm maximum width, 260 mm thick.
    fuselage = [
        (-1300, 0), (-1190, 145), (-920, 230), (-450, 250),
        (250, 225), (850, 165), (1250, 85), (1300, 0),
        (1250, -85), (850, -165), (250, -225), (-450, -250),
        (-920, -230), (-1190, -145),
    ]
    make_polygon_body(doc, "Top Plane", fuselage, 260)

    # Tapered main wings: 5 m total span and moderate sweep.
    right_wing = [(0, 220), (470, 245), (420, 2500), (80, 2500),
                  (-180, 900), (-260, 350)]
    left_wing = [(x, -y) for x, y in right_wing]
    make_polygon_body(doc, "Top Plane", right_wing, 90)
    make_polygon_body(doc, "Top Plane", left_wing, 90)

    # Horizontal tailplane and twin end plates.
    right_tail = [(760, 60), (1200, 70), (1140, 720), (850, 660)]
    left_tail = [(x, -y) for x, y in right_tail]
    make_polygon_body(doc, "Top Plane", right_tail, 60)
    make_polygon_body(doc, "Top Plane", left_tail, 60)

    # Vertical tail on the front plane, represented by a swept fin.
    vertical_tail = [(820, 0), (1230, 0), (1160, 560), (1000, 760), (900, 520)]
    make_polygon_body(doc, "Front Plane", vertical_tail, 70)

    # Two lift motor nacelles and the rear pusher nacelle.
    make_circle_body(doc, "Top Plane", -30, 1780, 150, 300)
    make_circle_body(doc, "Top Plane", -30, -1780, 150, 300)
    make_circle_body(doc, "Top Plane", 1160, 0, 170, 240)

    # VTOL motor caps and the rear motor hub.
    make_circle_body(doc, "Top Plane", -30, 1780, 105, 340)
    make_circle_body(doc, "Top Plane", -30, -1780, 105, 340)
    make_circle_body(doc, "Top Plane", 1260, 0, 95, 280)

    # Forward sensor blister.
    make_circle_body(doc, "Top Plane", -1080, 0, 125, 90)

    save_and_show(doc, output_path)
    print(f"Created GARUDA-1 concept model: {output_path}")


if __name__ == "__main__":
    destination = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.getcwd(), "GARUDA-1.sldprt"
    )
    create_model(os.path.abspath(destination))
