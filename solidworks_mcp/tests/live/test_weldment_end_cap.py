"""Live proof that an End Cap closes hollow library-profile member ends (W3).

The fixture is a plain ISO square tube built from a library profile, never the
user's own documents. Each test measures the total solid volume before and
after so the feature has to add material, not merely return a COM proxy, and
checks the envelope so the cap's side of the end face is provable.
"""

import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.weldments import (
    END_CAP_FEATURE_TYPES, create_structural_member, create_weldment_end_cap,
    list_weldment_profiles,
)


@live_only
class LiveWeldmentEndCapTests(ScratchPartTestCase):
    def _iso_square_tube(self):
        profiles = list_weldment_profiles(self.automation, filter="square tube")
        self.assertTrue(profiles["success"], profiles["message"])
        tube = [item["path"] for item in profiles["data"]["profiles"]
                if item["folder"].casefold().startswith("iso")]
        self.assertTrue(tube, "An installed ISO square-tube profile is required")
        return tube[0]

    def _one_hollow_member(self):
        """A fresh part with one hollow square tube along world Y; returns its
        body name and its bounding box in millimetres."""
        self.open_scratch_part()
        sketch = self.new_sketch()
        self.assertTrue(self.automation.draw_line(0, 0, 200, 0, "mm")["success"])
        self.exit_sketch()
        member = create_structural_member(self.automation, sketch,
                                          self._iso_square_tube())
        self.assertTrue(member["success"], member["message"])
        bodies = [self._keep(body) for body
                  in com(self.document(), "GetBodies2", 0, False) or []]
        self.assertEqual(1, len(bodies), "Fixture needs exactly one member body")
        return str(com(bodies[0], "Name")), self._box_mm(bodies[0])

    def _box_mm(self, body):
        return [round(float(value) * 1000, 3) for value in com(body, "GetBodyBox")]

    def _bodies(self):
        return [self._keep(body)
                for body in com(self.document(), "GetBodies2", 0, False) or []]

    def _box_of(self, name):
        matches = [body for body in self._bodies()
                   if str(com(body, "Name")) == name]
        self.assertEqual(1, len(matches), f"Body not found: {name}")
        return self._box_mm(matches[0])

    def _union_box_mm(self):
        boxes = [self._box_mm(body) for body in self._bodies()]
        self.assertTrue(boxes)
        return [min(box[i] for box in boxes) for i in range(3)] + \
               [max(box[i + 3] for box in boxes) for i in range(3)]

    def test_cap_direction_chooses_which_side_of_the_end_face(self):
        """outward protrudes, inward is flush, inset is recessed."""
        expectations = {
            "outward": dict(union=(-5.0, 205.0), cap_min=(-5.0, 200.0)),
            "inward": dict(union=(0.0, 200.0), cap_min=(0.0, 195.0)),
            "inset": dict(union=(0.0, 200.0), cap_min=(2.0, 193.0)),
        }
        for direction, expect in expectations.items():
            with self.subTest(direction=direction):
                name, before_box = self._one_hollow_member()
                self.assertAlmostEqual(0.0, before_box[1], delta=1.0)
                self.assertAlmostEqual(200.0, before_box[4], delta=1.0)
                before = self.total_volume_mm3()

                result = create_weldment_end_cap(
                    self.automation, name, depth_mm=5.0, direction=direction,
                    inset_mm=2.0)
                self.assertTrue(result["success"], result["message"])
                self.assertEqual(2, result["data"]["face_count"])
                self.assertIn(result["data"]["feature_type"],
                              END_CAP_FEATURE_TYPES, result["data"])
                self.assertGreater(result["data"]["added_mm3"], 100.0,
                                   result["data"])
                self.assertEqual(2, len(result["data"]["cap_bodies"]))
                self.assertAlmostEqual(before + result["data"]["added_mm3"],
                                       self.total_volume_mm3(),
                                       delta=50.0, msg=result["data"])

                com(self.document(), "ForceRebuild3", False)
                union = self._union_box_mm()
                self.assertAlmostEqual(expect["union"][0], union[1], delta=1.0,
                                       msg=f"{direction}: {union}")
                self.assertAlmostEqual(expect["union"][1], union[4], delta=1.0,
                                       msg=f"{direction}: {union}")
                cap_mins = sorted(self._box_of(cap)[1]
                                  for cap in result["data"]["cap_bodies"])
                for expected, measured in zip(expect["cap_min"], cap_mins):
                    self.assertAlmostEqual(expected, measured, delta=1.0,
                                           msg=f"{direction}: {cap_mins}")

        self.assert_unsaved()
        root = Path(self.automation._path_policy.output_roots[0])
        target = root / "saved" / f"mcp_live_weldment_end_cap_{uuid4().hex}.SLDPRT"
        saved = save_document(self.automation, path=str(target), overwrite=False)
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(target.stat().st_size, 0)
        self.created_titles[-1] = str(com(self.document(), "GetTitle"))

    def test_one_explicit_planar_face_caps_only_that_end(self):
        name, _before_box = self._one_hollow_member()
        listed = list_planar_faces(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        ends = [face for face in listed["data"]["faces"]
                if face["body"] == name and abs(face["normal"][1]) > 0.9]
        self.assertEqual(2, len(ends), f"Expected two Y-normal ends: {ends}")
        chosen = min(ends, key=lambda face: face["point_mm"][1])

        result = create_weldment_end_cap(self.automation, name,
                                         face_indices=[chosen["index"]],
                                         depth_mm=5.0, direction="inward")
        self.assertTrue(result["success"], result["message"])
        self.assertFalse(result["data"]["auto_detected_faces"])
        self.assertEqual(1, result["data"]["face_count"])
        self.assertEqual(1, len(result["data"]["cap_bodies"]))
        self.assertGreater(result["data"]["added_mm3"], 100.0, result["data"])
        self.assert_unsaved()


if __name__ == "__main__":
    unittest.main()
