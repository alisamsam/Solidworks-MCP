"""Shared scaffolding for the opt-in live SolidWorks COM tests.

Creating a scratch document is the slow part of a live test, so the tests in
this package build all of their geometry inside **one** scratch part per test
method and close that part without saving.

The tests are written as an explicit sequence of steps.  Every step owns a
rectangular zone of the sketch plane and keeps its geometry well inside that
zone, so the accumulating part never overlaps itself and a screenshot taken
after each step stays readable.  Screenshots are written to a review folder and
are deleted again at tear-down unless ``SW_MCP_KEEP_REVIEW=1``.

Every COM object returned by these helpers is parked in ``self.retained``:
pywin32 releases the proxy as soon as the last Python reference goes away, and
a released proxy makes later calls on unrelated objects fail.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.views import capture_view


LIVE_TESTS_ENABLED = os.environ.get("SW_MCP_LIVE_TESTS") == "1"

LIVE_TESTS_REASON = "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests."

#: Distance between two step zones on a sketch plane, in millimetres.
ZONE_PITCH_MM = 90


def live_only(test_case):
    """Mark a test case as opt-in, matching the other live test modules."""
    return unittest.skipUnless(LIVE_TESTS_ENABLED, LIVE_TESTS_REASON)(test_case)


def zone(column: int, row: int, columns: int = 4):
    """Centre of the step zone in the given grid cell, in millimetres."""
    x = (column - (columns - 1) / 2) * ZONE_PITCH_MM
    y = (2 - row) * ZONE_PITCH_MM
    return x, y


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def open_document_titles(automation) -> set:
    """Titles open right now; the baseline for close_new_documents."""
    documents = automation.list_open_documents()
    if not documents["success"]:
        return set()
    return {item["title"] for item in documents["data"]["documents"]}


def close_new_documents(automation, baseline: set) -> None:
    """Close, unsaved, every document a test opened since ``baseline``.

    Titles change during a test (``Draw3`` becomes ``<part> - Sheet1`` once a
    view is placed, ``Part12`` takes the file name on save), so closing by the
    title recorded at creation silently misses them and the leaked windows
    break later tests.  Only unsaved documents and files under the approved
    output roots are touched; drawings close before the parts they reference.
    """
    documents = automation.list_open_documents()
    if not documents["success"]:
        return
    roots = [str(Path(root).resolve()).casefold()
             for root in automation._path_policy.output_roots]
    order = {"Drawing": 0, "Assembly": 1}
    leaked = [item for item in documents["data"]["documents"]
              if item["title"] not in baseline
              and (not item["path"] or any(
                  str(Path(item["path"]).resolve()).casefold().startswith(root)
                  for root in roots))]
    for item in sorted(leaked, key=lambda item: order.get(item["type"], 2)):
        try:
            automation.app.CloseDoc(item["title"])
        except Exception:
            pass


class ScratchPartTestCase(unittest.TestCase):
    """One scratch part per test method; every part is closed unsaved."""

    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.created_titles = []
        self.review_artifacts = []
        self.retained = []
        self.baseline_titles = open_document_titles(self.automation)

    def tearDown(self):
        if os.environ.get("SW_MCP_KEEP_REVIEW") != "1":
            for path in self.review_artifacts:
                Path(path).unlink(missing_ok=True)
        for title in reversed(self.created_titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        close_new_documents(self.automation, self.baseline_titles)
        self.automation.disconnect()
        self.retained = []

    # -- documents ---------------------------------------------------------
    def open_scratch_part(self):
        """Create the one scratch part this test method works in."""
        result = self.automation.create_new_part()
        self.assertTrue(result["success"], result["message"])
        title = result["data"]["name"]
        self.created_titles.append(title)
        return title

    def document(self):
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return self._keep(document)

    def assert_unsaved(self):
        active, error = self.automation.capture_active_document_ref()
        self.assertIsNone(error)
        self.assertIsNone(active.path)

    def _keep(self, value):
        self.retained.append(value)
        return value

    # -- review screenshots ------------------------------------------------
    def review_dir(self):
        # Screenshots must land inside an allowed output root, otherwise the
        # guarded path policy denies the write.
        policy = getattr(self.automation, "_path_policy", None)
        roots = getattr(policy, "output_roots", None) if policy else None
        if roots:
            return Path(roots[0]) / "review"
        override = os.environ.get("SW_MCP_REVIEW_DIR")
        if override:
            return Path(override)
        return Path(__file__).resolve().parents[3] / "output" / "review"

    def capture(self, index, purpose):
        """Screenshot the active document so a human can review this step."""
        path = self.review_dir() / f"{index:02d}-{slug(purpose)}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        # The view was framed while the part was still empty, so re-fit it to
        # the geometry added so far, otherwise the step is a speck in a corner.
        com(self.document(), "ViewZoomtofit2")
        result = capture_view(self.automation, orientation="isometric",
                              width=1280, height=960, output_path=str(path))
        self.assertTrue(result["success"], result["message"])
        artifact = result["data"]["artifact"]["path"]
        self.review_artifacts.append(artifact)
        return Path(artifact)

    # -- feature tree ------------------------------------------------------
    def features(self):
        items = []
        feature = com(self.document(), "FirstFeature")
        while feature is not None:
            self._keep(feature)
            items.append(feature)
            feature = com(feature, "GetNextFeature")
        return items

    def sketch_names(self):
        return [com(feature, "Name") for feature in self.features()
                if com(feature, "GetTypeName2") == "ProfileFeature"]

    def feature_named(self, name):
        for feature in self.features():
            if com(feature, "Name") == name:
                return feature
        return None

    def solid_body_count(self):
        return len(com(self.document(), "GetBodies2", 0, True) or [])

    def body_box_mm(self):
        """Bounding box of every solid body as [x0, y0, z0, x1, y1, z1] in mm."""
        boxes = []
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            box = com(body, "GetBodyBox")
            boxes.append([round(float(value) * 1000, 3) for value in box])
        return boxes

    def feature_count(self, type_name):
        return sum(1 for feature in self.features()
                   if com(feature, "GetTypeName2") == type_name)

    def total_volume_mm3(self):
        total = 0.0
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            total += com(body, "GetMassProperties", 0.0)[3] * 1e9
        return total

    def total_solid_faces(self):
        """Face count across every solid body, the second geometric proof."""
        total = 0
        for body in com(self.document(), "GetBodies2", 0, True) or []:
            self._keep(body)
            total += len(com(body, "GetFaces") or [])
        return total

    # -- sketches ----------------------------------------------------------
    def new_sketch(self, plane="Front", exact_geometry=True):
        """Create one sketch and return its feature name.

        The name is read while the sketch is still open, because SolidWorks
        deletes an empty sketch again when the sketch is exited; the returned
        name therefore never depends on positional numbering.
        """
        result = self.automation.create_sketch(plane, exact_geometry=exact_geometry)
        self.assertTrue(result["success"], result["message"])
        names = self.sketch_names()
        self.assertTrue(names, "no sketch feature found after create_sketch")
        return names[-1]

    def exit_sketch(self):
        result = self.automation.exit_sketch()
        self.assertTrue(result["success"], result["message"])

    def close_sketch(self):
        """Leave sketch edit mode if a sketch is open, otherwise do nothing.

        ``exit_sketch`` toggles sketch mode, so calling it with no open sketch
        would start a new one.
        """
        manager = self.document().SketchManager
        if com(manager, "ActiveSketch") is not None:
            self.automation.exit_sketch()

    # -- sketch readers ----------------------------------------------------
    def _check(self, sketch, expectation):
        kind = expectation[0]
        if kind == "segments":
            self.assertEqual(expectation[1], self.segment_count(sketch))
        elif kind == "counter":
            self.assertEqual(expectation[2], self.counter(sketch, expectation[1]))
        elif kind == "min_lines":
            self.assertGreaterEqual(self.counts(sketch)[0], expectation[1])
        elif kind == "construction":
            self.assertEqual(expectation[1], self.construction_count(sketch))
        elif kind == "lengths":
            for expected, measured in zip(expectation[1],
                                          self.segment_lengths_mm(sketch)):
                self.assertAlmostEqual(expected, measured, places=2)
        else:  # pragma: no cover - guards a typo in a test case table
            raise AssertionError(f"unknown expectation {kind!r}")

    def sketch(self, name):
        feature = self.feature_named(name)
        self.assertIsNotNone(feature, f"sketch not found: {name}")
        return self._keep(com(feature, "GetSpecificFeature2"))

    def segment_count(self, name):
        segments = com(self.sketch(name), "GetSketchSegments")
        return 0 if segments is None else len(segments)

    def counts(self, name):
        sketch = self.sketch(name)
        return (int(com(sketch, "GetLineCount")), int(com(sketch, "GetArcCount")))

    def counter(self, name, getter):
        value = com(self.sketch(name), getter)
        return 0 if value is None else int(value)

    def construction_count(self, name):
        """Number of construction segments in a sketch."""
        total = 0
        for segment in com(self.sketch(name), "GetSketchSegments") or []:
            self._keep(segment)
            if com(segment, "ConstructionGeometry"):
                total += 1
        return total

    def centres_mm(self, name):
        """Arc and circle centres in the sketch's own 2D coordinate system."""
        points = []
        for segment in com(self.sketch(name), "GetSketchSegments") or []:
            self._keep(segment)
            if int(com(segment, "GetType")) == 0:
                continue
            point = com(segment, "GetCenterPoint")
            points.append((round(float(point[0]) * 1000, 3),
                           round(float(point[1]) * 1000, 3)))
        return points

    def segment_lengths_mm(self, name, descending=True):
        lengths = []
        for segment in com(self.sketch(name), "GetSketchSegments") or []:
            self._keep(segment)
            lengths.append(round(float(com(segment, "GetLength")) * 1000, 3))
        return sorted(lengths, reverse=descending)

    def sketch_transform(self, name):
        """The sketch frame; rotate/flip edits change this and not the segments."""
        transform = com(self.sketch(name), "ModelToSketchTransform")
        self._keep(transform)
        return tuple(round(float(value), 9)
                     for value in com(transform, "ArrayData"))
