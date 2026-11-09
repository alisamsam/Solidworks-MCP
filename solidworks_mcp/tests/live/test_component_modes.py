"""Live fast vs detailed component traversal on a profile-built assembly.

The assembly is built from real weldment members (DIN IPE) rather than blocks,
so the tree has the shape a real project has: a top assembly that holds a part
and a sub-assembly, with the sub-assembly holding two further instances. The
fast mode is proven structurally: it must find every instance, recognise the
sub-assembly, and never read a transform or a configuration.
"""

import os
import unittest
from pathlib import Path
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tools.assembly import insert_component, list_components
from solidworks_mcp.tools.saving import save_document
from solidworks_mcp.tools.weldments import (
    create_structural_member, list_weldment_profiles)

PROFILE_NAME = "ipe.sldlfp"


@unittest.skipUnless(os.environ.get("SW_MCP_LIVE_TESTS") == "1",
                     "Set SW_MCP_LIVE_TESTS=1 to run SolidWorks COM tests.")
class LiveComponentModeTests(unittest.TestCase):
    def setUp(self):
        self.automation = SolidWorksAutomation()
        result = self.automation.connect()
        if not result["success"]:
            self.skipTest(result["message"])
        self.token = uuid4().hex[:8]
        self.root = Path(self.automation._path_policy.output_roots[0]) / "saved"
        self.root.mkdir(parents=True, exist_ok=True)
        self.titles = []

    def tearDown(self):
        for title in reversed(self.titles):
            try:
                self.automation.app.CloseDoc(title)
            except Exception:
                pass
        self.automation.disconnect()

    def _profile(self):
        profiles = list_weldment_profiles(self.automation, filter="ipe")
        self.assertTrue(profiles["success"], profiles["message"])
        items = profiles["data"]["profiles"]
        self.assertTrue(items, "No IPE weldment profile is installed.")
        chosen = next((item for item in items
                       if item["name"].casefold() == PROFILE_NAME
                       and item["folder"].casefold() == "din"), None)
        return chosen or items[0]

    def _beam(self, length_mm, suffix):
        """A saved weldment beam; real profile, real length."""
        created = self.automation.create_new_part()
        self.assertTrue(created["success"], created["message"])
        self.titles.append(created["data"]["name"])
        sketch = self.automation.create_sketch("Front", exact_geometry=True)
        self.assertTrue(sketch["success"], sketch["message"])
        self.assertTrue(self.automation.draw_line(0, 0, length_mm, 0, "mm")["success"])
        self.assertTrue(self.automation.exit_sketch()["success"])
        document, error = self.automation.get_active_doc()
        self.assertIsNone(error)
        name = None
        feature = com(document, "FirstFeature")
        while feature is not None:
            if com(feature, "GetTypeName2") == "ProfileFeature":
                name = str(com(feature, "Name"))
            feature = com(feature, "GetNextFeature")
        profile = self._profile()
        member = create_structural_member(self.automation, name, profile["path"])
        self.assertTrue(member["success"], member["message"])
        path = self.root / f"mcp_live_modes_{suffix}_{self.token}.SLDPRT"
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        self.titles[-1] = path.stem
        return path

    def _new_assembly(self):
        created = self.automation.create_new_assembly()
        self.assertTrue(created["success"], created["message"])
        self.titles.append(created["data"]["name"])
        return created["data"]["name"]

    def _save_assembly(self, path):
        saved = save_document(self.automation, path=str(path))
        self.assertTrue(saved["success"], saved["message"])
        self.titles[-1] = path.stem

    def test_fast_and_detailed_find_the_same_profile_instances(self):
        beam_a = self._beam(600.0, "a")
        beam_b = self._beam(300.0, "b")

        # Sub-assembly: two instances of the 300 mm member.
        self._new_assembly()
        for index, path in enumerate((beam_b, beam_b)):
            inserted = insert_component(self.automation, str(path),
                                        0.05 * index, 0.0, 0.0)
            self.assertTrue(inserted["success"], inserted["message"])
        sub_path = self.root / f"mcp_live_modes_sub_{self.token}.SLDASM"
        self._save_assembly(sub_path)

        # Top assembly: one 600 mm member and the sub-assembly.
        self._new_assembly()
        for index, path in enumerate((beam_a, sub_path)):
            inserted = insert_component(self.automation, str(path),
                                        0.05 * index, 0.0, 0.0)
            self.assertTrue(inserted["success"], inserted["message"])

        fast = list_components(self.automation, depth=32, mode="fast")
        detailed = list_components(self.automation, depth=32, mode="detailed")

        self.assertTrue(fast["success"], fast["message"])
        self.assertTrue(detailed["success"], detailed["message"])
        self.assertEqual("fast", fast["data"]["mode"])
        self.assertEqual("detailed", detailed["data"]["mode"])

        # Same tree, same instances, both complete.
        fast_paths = [item["instance_path"] for item in fast["data"]["components"]]
        detailed_paths = [item["instance_path"] for item in detailed["data"]["components"]]
        self.assertEqual(detailed_paths, fast_paths)
        self.assertEqual(4, len(fast_paths),
                         "one beam + one sub-assembly + two nested beams")
        self.assertTrue(fast["data"]["coverage"]["complete"])
        self.assertTrue(detailed["data"]["coverage"]["complete"])

        # The sub-assembly is recognised from its path, and its two children
        # were reached.
        subassemblies = [item for item in fast["data"]["components"]
                         if item["is_subassembly"]]
        self.assertEqual(1, len(subassemblies))
        self.assertTrue(subassemblies[0]["path"].casefold().endswith(".sldasm"))
        nested = [item for item in fast["data"]["components"]
                  if item["parent_path"] == subassemblies[0]["name"]]
        self.assertEqual(2, len(nested))
        for item in nested:
            self.assertFalse(item["is_subassembly"], "a beam part is a leaf")

        # Fast mode is cheap because it never asks for these members.
        for item in fast["data"]["components"]:
            self.assertNotIn("transform", item)
            self.assertNotIn("configuration", item)
            self.assertNotIn("suppression_state", item)

        # Detailed mode still provides them, so nothing was lost from the tool.
        with_transform = [item for item in detailed["data"]["components"]
                          if item["transform"]]
        self.assertTrue(with_transform, "detailed mode must read transforms")
        self.assertEqual(16, len(with_transform[0]["transform"]))
        self.assertTrue(all(item["suppression_state"] for item in
                            detailed["data"]["components"]))


if __name__ == "__main__":
    unittest.main()
