"""Ordered live surface checks in one saved part; run the whole class."""

import math
import os
import unittest
from pathlib import Path
from uuid import uuid4

import pythoncom
import win32com.client

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.reference_geometry import create_reference_plane
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.surface_features import (
    extend_surface, extrude_surface, filled_surface, knit_surface,
    loft_surface, offset_surface, planar_surface, revolve_surface,
    ruled_surface, sweep_surface, thicken_surface,
)
from solidworks_mcp.tools.sketch_entities import draw_centerline


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveGroupedSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.automation = SolidWorksAutomation()
        cls.title = None
        cls.path = None
        cls.stage = 0
        connected = cls.automation.connect()
        if not connected["success"]:
            raise unittest.SkipTest(connected["message"])
        try:
            created = cls.automation.create_new_part()
            if not created["success"]:
                raise AssertionError(created["message"])
            cls.title = created["data"]["name"]
            cls.path = (Path(cls.automation._path_policy.output_roots[0]) / "saved" /
                        f"mcp_live_grouped_surfaces_{uuid4().hex}.SLDPRT")
        except BaseException:
            cls._close_and_disconnect()
            raise

    @classmethod
    def _close_and_disconnect(cls):
        try:
            if cls.title is not None:
                cls.automation.app.CloseDoc(cls.title)
        finally:
            cls.automation.disconnect()

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.title is not None and cls.path is not None:
                saved = save_document(cls.automation, path=str(cls.path))
                if not saved["success"]:
                    raise AssertionError(saved["message"])
                # SaveAs renames the document; track the new title so the
                # finally-block closes it instead of leaking the window.
                cls.title = cls.path.stem
                if cls.path.stat().st_size == 0:
                    raise AssertionError("Shared surface part was saved empty.")
        finally:
            cls._close_and_disconnect()

    def _part(self):
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return part

    def _sheets(self):
        return com(self._part(), "GetBodies2", 1, True) or []

    def _area(self):
        return sum(com(face, "GetArea") * 1e6 for body in self._sheets()
                   for face in (com(body, "GetFaces") or []))

    def _volume(self):
        return sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                   for body in (com(self._part(), "GetBodies2", 0, True) or []))

    def _sketch_name(self):
        part = self._part()
        last = None
        feature = com(part, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "ProfileFeature":
                last = str(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        self.assertIsNotNone(last)
        return last

    def _sketch(self):
        result = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(result["success"], result["message"])

    def _sketch_on_plane(self, name):
        part = self._part()
        com(part, "ClearSelection2", True)
        empty = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        selected = com(com(part, "Extension"), "SelectByID2", name, "PLANE",
                       0., 0., 0., False, 0, empty, 0)
        self.assertTrue(selected, f"Could not select plane {name}.")
        com(part, "InsertSketch2", True)

    def _close_sketch(self):
        com(self._part(), "InsertSketch2", True)
        return self._sketch_name()

    def _require_stage(self, value):
        if type(self).stage != value:
            self.skipTest(f"Earlier surface operation did not reach checkpoint {value}.")

    def test_01_planar_surface_area(self):
        self._sketch()
        drawn = self.automation.draw_rectangle(-20, -20, 20, 20, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        sketch = self._close_sketch()
        result = planar_surface(self.automation, sketch)
        self.assertTrue(result["success"], result["message"])
        type(self).planar_name = result["data"]["feature_name"]
        self.assertEqual(1, len(self._sheets()))
        self.assertAlmostEqual(1600, self._area(), delta=.2)
        type(self).stage = 1

    def test_02_offset_surface_doubles_sheet_area(self):
        self._require_stage(1)
        before = self._area()
        result = offset_surface(self.automation, type(self).planar_name, 5)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(2, len(self._sheets()))
        self.assertAlmostEqual(before, self._area() - before, delta=.5)
        type(self).stage = 2

    def test_03_thicken_both_sides_creates_solid(self):
        self._require_stage(2)
        before = self._volume()
        result = thicken_surface(self.automation, type(self).planar_name, 2, side="both")
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(6400, self._volume() - before, delta=.5)
        type(self).stage = 3

    def test_04_extrude_open_surface_area(self):
        self._require_stage(3)
        before = self._area()
        self._sketch()
        drawn = self.automation.draw_line(-20, 100, 20, 100, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        result = extrude_surface(self.automation, self._close_sketch(), 10)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(400, self._area() - before, delta=.5)
        self.assertAlmostEqual(6400, self._volume(), delta=.5)
        type(self).stage = 4

    def test_05_filled_surface_area(self):
        self._require_stage(4)
        before = self._area()
        self._sketch()
        drawn = self.automation.draw_rectangle(85, 85, 115, 115, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        result = filled_surface(self.automation, self._close_sketch())
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(4, result["data"]["boundary_segments"])
        self.assertAlmostEqual(900, self._area() - before, delta=1)
        type(self).stage = 5

    def test_06_revolve_surface_area(self):
        self._require_stage(5)
        before = self._area()
        self._sketch()
        drawn = self.automation.draw_line(210, -10, 210, 10, "mm")
        self.assertTrue(drawn["success"], drawn["message"])
        axis = draw_centerline(self.automation, 200, -15, 200, 15)
        self.assertTrue(axis["success"], axis["message"])
        result = revolve_surface(self.automation, self._close_sketch())
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(400 * math.pi, self._area() - before, delta=1)
        type(self).stage = 6

    def test_07_loft_surface_area(self):
        self._require_stage(6)
        before = self._area()
        self._sketch()
        result = self.automation.draw_rectangle(290, -10, 310, 10, "mm")
        self.assertTrue(result["success"], result["message"])
        first = self._close_sketch()
        plane = create_reference_plane(self.automation, "Front Plane", 30, "mm")
        self.assertTrue(plane["success"], plane["message"])
        self._sketch_on_plane("Plane1")
        result = self.automation.draw_rectangle(290, -10, 310, 10, "mm")
        self.assertTrue(result["success"], result["message"])
        second = self._close_sketch()
        result = loft_surface(self.automation, [first, second])
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(2400, self._area() - before, delta=1)
        type(self).stage = 7

    def test_08_knit_two_adjacent_sheets(self):
        self._require_stage(7)
        before = self._area()
        names = []
        for left, right in ((380, 400), (400, 420)):
            self._sketch()
            result = self.automation.draw_rectangle(left, -20, right, 20, "mm")
            self.assertTrue(result["success"], result["message"])
            result = planar_surface(self.automation, self._close_sketch())
            self.assertTrue(result["success"], result["message"])
            names.append(result["data"]["feature_name"])
        before_knit = len(self._sheets())
        self.assertAlmostEqual(1600, self._area() - before, delta=.5)
        result = knit_surface(self.automation, names)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(before_knit - 1, len(self._sheets()))
        self.assertAlmostEqual(1600, self._area() - before, delta=.5)
        type(self).stage = 8

    def _new_remote_square(self, center):
        before = self._area()
        self._sketch()
        result = self.automation.draw_rectangle(center - 20, -20, center + 20, 20, "mm")
        self.assertTrue(result["success"], result["message"])
        result = planar_surface(self.automation, self._close_sketch())
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(1600, self._area() - before, delta=.5)
        # Resolve the fresh sheet by position rather than assuming the body
        # array retains an insertion order after a rebuild.
        sheets = self._sheets()
        candidates = [i for i, body in enumerate(sheets)
                      if abs(com(body, "GetBodyBox")[1] - (center - 20) / 1000) < .001]
        self.assertEqual(1, len(candidates))
        return candidates[0]

    def test_09_extend_remote_sheet_edge(self):
        self._require_stage(8)
        index = self._new_remote_square(500)
        before = self._area()
        result = extend_surface(self.automation, index, 0, 5)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(200, self._area() - before, delta=.5)
        type(self).stage = 9

    def test_10_ruled_remote_sheet_edge(self):
        self._require_stage(9)
        index = self._new_remote_square(600)
        before = self._area()
        result = ruled_surface(self.automation, index, 0, 5)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(200, self._area() - before, delta=.5)
        type(self).stage = 10

    def test_11_sweep_surface_area(self):
        self._require_stage(10)
        before = self._area()
        self._sketch()
        circle = self.automation.draw_circle(0, 0, 2, "mm")
        self.assertTrue(circle["success"], circle["message"])
        profile = self._close_sketch()
        result = self.automation.create_sketch("Top", exact_geometry=True)
        self.assertTrue(result["success"], result["message"])
        line = self.automation.draw_line(0, 0, 0, 50, "mm")
        self.assertTrue(line["success"], line["message"])
        path = self._close_sketch()
        result = sweep_surface(self.automation, profile, path)
        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(200 * math.pi, self._area() - before, delta=1)
        type(self).stage = 11

    def test_12_save_and_close_surface_part(self):
        self._require_stage(11)
        saved = save_document(self.automation, path=str(self.path))
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(self.path.stat().st_size, 0)
        title = str(com(self._part(), "GetTitle"))
        self.automation.app.CloseDoc(title)
        type(self).title = None
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        self.assertNotIn(title, [d["title"] for d in documents["data"]["documents"]])
