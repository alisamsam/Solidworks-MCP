"""Live proof for the weldment gusset tool (W4).

Fixture is a T-joint of two hollow ISO square tubes: one through member and one
member butting into its face, so the through member continues past the joint and
the two supporting faces meet at a real edge. This mirrors the confirmed manual
Gusset1 in the user's Part200. Only scratch parts are used.
"""

import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import ScratchPartTestCase, live_only
from solidworks_mcp.tools.export import list_planar_faces
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.weldments import (
    GUSSET_FEATURE_TYPES, create_structural_member, create_weldment_gusset,
    list_weldment_profiles,
)


@live_only
class LiveWeldmentGussetTests(ScratchPartTestCase):
    def _iso_square_tube(self):
        profiles = list_weldment_profiles(self.automation, filter="square tube")
        self.assertTrue(profiles["success"], profiles["message"])
        tube = [item["path"] for item in profiles["data"]["profiles"]
                if item["folder"].casefold().startswith("iso")]
        self.assertTrue(tube, "An installed ISO square-tube profile is required")
        return tube[0]

    def _member(self, lines, profile_path):
        sketch = self.new_sketch()
        for x0, y0, x1, y1 in lines:
            result = self.automation.draw_line(x0, y0, x1, y1, "mm")
            self.assertTrue(result["success"], result["message"])
        self.exit_sketch()
        member = create_structural_member(self.automation, sketch, profile_path)
        self.assertTrue(member["success"], member["message"])

    def _t_joint(self):
        """Through member Y 0..150 plus a member butting into its top at Y 130."""
        self.open_scratch_part()
        profile = self._iso_square_tube()
        self._member([(0, 0, 150, 0)], profile)
        self._member([(140, 10, 140, 160)], profile)
        names = sorted(str(com(body, "Name"))
                       for body in com(self.document(), "GetBodies2", 0, False) or [])
        self.assertEqual(2, len(names))
        return names

    def _outer_face_index(self, body, normal):
        """Index of the outermost planar face of `body` whose normal matches.

        The outer face is the one whose plane point has the greatest projection
        on the normal; this distinguishes e.g. the outer top wall from the
        inner bottom wall, which share a normal.
        """
        listed = list_planar_faces(self.automation)
        self.assertTrue(listed["success"], listed["message"])
        candidates = []
        for face in listed["data"]["faces"]:
            if face["body"] != body:
                continue
            dot = sum(a * b for a, b in zip(face["normal"], normal))
            if dot < 0.99:
                continue
            projection = sum(a * b for a, b in zip(face["point_mm"], face["normal"]))
            candidates.append((projection, face["index"], face["normal"]))
        self.assertTrue(candidates, f"No {normal} face on {body}")
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _volumes(self):
        result = {}
        for body in com(self.document(), "GetBodies2", 0, False) or []:
            self._keep(body)
            result[str(com(body, "Name"))] = (
                float(com(body, "GetMassProperties", 0.0)[3]) * 1e9)
        return result

    def test_gusset_between_a_through_member_and_a_butting_member(self):
        names = self._t_joint()
        through, butt = names[0], names[1]
        face_a = self._outer_face_index(through, [0.0, 0.0, 1.0])
        face_b = self._outer_face_index(butt, [0.0, -1.0, 0.0])
        before = self._volumes()

        result = create_weldment_gusset(self.automation, face_a, face_b)
        self.assertTrue(result["success"], result["message"])
        self.assertIn(result["data"]["feature_type"], GUSSET_FEATURE_TYPES,
                      result["data"])
        self.assertEqual(1, len(result["data"]["gusset_bodies"]))
        self.assertGreater(result["data"]["added_mm3"], 100.0, result["data"])

        com(self.document(), "ForceRebuild3", False)
        self.assertIsNotNone(self.feature_named(result["data"]["feature"]))
        after = self._volumes()
        # The gusset is its own body; the two members keep their volume.
        for name, volume in before.items():
            self.assertAlmostEqual(volume, after[name], delta=1.0, msg=name)
        self.assertAlmostEqual(result["data"]["added_mm3"],
                               after[result["data"]["gusset_bodies"][0]],
                               delta=1.0)
        self.assert_unsaved()

        root = Path(self.automation._path_policy.output_roots[0])
        target = root / "saved" / f"mcp_live_weldment_gusset_{uuid4().hex}.SLDPRT"
        saved = save_document(self.automation, path=str(target), overwrite=False)
        self.assertTrue(saved["success"], saved["message"])
        self.assertGreater(target.stat().st_size, 0)
        self.created_titles[-1] = str(com(self.document(), "GetTitle"))

    def test_thickness_side_and_chamfer_modes_each_build_a_gusset(self):
        cases = [("inner side", dict(direction="inner")),
                 ("outer side", dict(direction="outer")),
                 ("chamfered", dict(chamfer=True))]
        for label, kwargs in cases:
            with self.subTest(label=label):
                names = self._t_joint()
                through, butt = names[0], names[1]
                face_a = self._outer_face_index(through, [0.0, 0.0, 1.0])
                face_b = self._outer_face_index(butt, [0.0, -1.0, 0.0])
                result = create_weldment_gusset(self.automation, face_a, face_b,
                                                **kwargs)
                self.assertTrue(result["success"], result["message"])
                self.assertGreater(result["data"]["added_mm3"], 100.0,
                                   result["data"])
                com(self.document(), "ForceRebuild3", False)
                self.assertIsNotNone(self.feature_named(
                    result["data"]["feature"]))

    def test_parallel_supporting_faces_are_refused_before_any_feature(self):
        names = self._t_joint()
        through, butt = names[0], names[1]
        face_a = self._outer_face_index(through, [0.0, 0.0, 1.0])
        # The butting member's own top-facing wall is parallel to face_a.
        face_b = self._outer_face_index(butt, [0.0, 0.0, -1.0])
        before = self.total_volume_mm3()
        result = create_weldment_gusset(self.automation, face_a, face_b)
        self.assertFalse(result["success"], result)
        # Volume readback carries floating-point noise near 1e-11 mm^3.
        self.assertAlmostEqual(before, self.total_volume_mm3(), delta=1e-6)


if __name__ == "__main__":
    unittest.main()
