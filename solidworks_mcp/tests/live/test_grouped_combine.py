"""Keep all three Combine modes as features of one saved multibody part."""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.advanced_features import dome
from solidworks_mcp.tools.body_features import combine_bodies
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.saving import save_document


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveGroupedCombineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.automation = SolidWorksAutomation()
        cls.title = None
        cls.stage = 0
        cls.path = None
        connected = cls.automation.connect()
        if not connected["success"]:
            raise unittest.SkipTest(connected["message"])
        try:
            created = cls.automation.create_new_part()
            if not created["success"]:
                raise AssertionError(created["message"])
            cls.title = created["data"]["name"]
            cls.path = (Path(cls.automation._path_policy.output_roots[0]) / "saved" /
                        f"mcp_live_grouped_combine_{uuid4().hex}.SLDPRT")
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
                    raise AssertionError("Shared Combine part was saved empty.")
        finally:
            cls._close_and_disconnect()

    def _part(self):
        part, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        return part

    def _bodies(self):
        return com(self._part(), "GetBodies2", 0, True) or []

    def _volume(self):
        return sum(com(body, "GetMassProperties", 0.0)[3] * 1e9
                   for body in self._bodies())

    def _add_block(self, left, right, *, first=False):
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        rectangle = self.automation.draw_rectangle(left, 0, right, 20, "mm")
        self.assertTrue(rectangle["success"], rectangle["message"])
        if first:
            result = self.automation.extrude_sketch(10, False, "mm")
            self.assertTrue(result["success"], result["message"])
        else:
            part = self._part()
            selected, sketch, message = self.automation._close_and_select_sketch(part)
            self.assertTrue(selected, message)
            feature = com(com(part, "FeatureManager"), "FeatureExtrusion2",
                          True, False, False, 0, 0, .01, .01,
                          False, False, False, False, 0.0, 0.0,
                          False, False, False, False,
                          False, True, True, 0, 0.0, False)
            self.assertIsNotNone(feature)

    def _require_stage(self, value):
        if type(self).stage != value:
            self.skipTest(f"Earlier Combine mode did not reach checkpoint {value}.")

    def test_01_add_union_volume(self):
        self._add_block(0, 20, first=True)
        self._add_block(10, 30)
        self.assertEqual(2, len(self._bodies()))
        self.assertAlmostEqual(8000, self._volume(), delta=1)
        result = combine_bodies(self.automation, 0, 1, "add")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, len(self._bodies()))
        self.assertAlmostEqual(6000, self._volume(), delta=1)
        type(self).stage = 1

    def test_02_subtract_overlapping_block(self):
        self._require_stage(1)
        self._add_block(20, 40)
        bodies = self._bodies()
        self.assertEqual(2, len(bodies))
        target = max(range(2), key=lambda i: com(bodies[i], "GetMassProperties", 0.0)[3])
        self.assertAlmostEqual(10000, self._volume(), delta=1)
        result = combine_bodies(self.automation, target, 1 - target, "subtract")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, len(self._bodies()))
        self.assertAlmostEqual(4000, self._volume(), delta=1)
        type(self).stage = 2

    def test_03_common_overlap_volume(self):
        self._require_stage(2)
        self._add_block(10, 30)
        bodies = self._bodies()
        self.assertEqual(2, len(bodies))
        self.assertAlmostEqual(8000, self._volume(), delta=1)
        result = combine_bodies(self.automation, 0, 1, "common")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, len(self._bodies()))
        self.assertAlmostEqual(2000, self._volume(), delta=1)
        type(self).stage = 3

    def test_04_dome_on_remaining_solid(self):
        self._require_stage(3)
        before = self._volume()
        faces = list_planar_faces(self.automation)
        self.assertTrue(faces["success"], faces["message"])
        cap = next((face for face in faces["data"]["faces"]
                    if abs(face["area_mm2"] - 200) < .1
                    and face["normal"][0] > .9), None)
        self.assertIsNotNone(cap)
        result = dome(self.automation, cap["index"], height=2, unit="mm")
        self.assertTrue(result["success"], result["message"])
        self.assertGreater(self._volume(), before + 1)
        self.assertEqual(1, len(self._bodies()))
        type(self).stage = 4

    def test_05_save_and_close_shared_part(self):
        self._require_stage(4)
        saved = save_document(self.automation, path=str(self.path))
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(self.path.stat().st_size, 0)
        title = str(com(self._part(), "GetTitle"))
        self.automation.app.CloseDoc(title)
        type(self).title = None
        documents = self.automation.list_open_documents()
        self.assertTrue(documents["success"], documents["message"])
        self.assertNotIn(title, [item["title"] for item in documents["data"]["documents"]])
