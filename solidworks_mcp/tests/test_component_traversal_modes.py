"""Unit tests for the fast and detailed component traversal modes (B20).

``fast`` exists because each COM member access on an instance inside a
sub-assembly costs about 0.08 s in SolidWorks, so the cost is the number of
calls. These tests count the member accesses on the fakes, which is exactly
what the mode is supposed to reduce.
"""

import unittest

from solidworks_mcp.tools.assembly import list_components


class CountingComponent:
    """A component that records every COM member access made on it."""

    def __init__(self, name, path, children=()):
        object.__setattr__(self, "_data", {
            "Name2": name,
            "GetPathName": path,
            "GetChildren": list(children),
            "IsFixed": False,
            "GetSuppression": 2,
            "IsVirtual": False,
            "ReferencedConfiguration": "Default",
            "Transform2": type("Transform", (), {"ArrayData": list(range(16))})(),
        })
        object.__setattr__(self, "accesses", [])

    def __getattr__(self, member):
        data = object.__getattribute__(self, "_data")
        if member not in data:
            raise AttributeError(member)
        object.__getattribute__(self, "accesses").append(member)
        return data[member]


class Assembly:
    def __init__(self, components):
        self.GetComponents = list(components)
        self.GetType = 2


class Automation:
    def __init__(self, assembly):
        self.assembly = assembly

    def get_active_doc(self):
        return self.assembly, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


def beam_tree():
    """Two part instances inside one sub-assembly, mirroring a real assembly."""
    frame_left = CountingComponent("Frame-1", "C:/output/frame.SLDPRT")
    frame_right = CountingComponent("Frame-2", "C:/output/frame.SLDPRT")
    subassembly = CountingComponent("Sub-1", "C:/output/sub.SLDASM",
                                    (frame_left, frame_right))
    return subassembly, (frame_left, frame_right)


class FastTraversalTests(unittest.TestCase):
    def test_fast_mode_reads_only_name_and_path_on_leaf_parts(self):
        subassembly, leaves = beam_tree()

        result = list_components(Automation(Assembly((subassembly,))), mode="fast")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual("fast", result["data"]["mode"])
        self.assertEqual(["Sub-1", "Sub-1/Frame-1", "Sub-1/Frame-2"],
                         [item["instance_path"] for item in result["data"]["components"]])
        for leaf in leaves:
            self.assertEqual(["Name2", "GetPathName"], leaf.accesses,
                             "A leaf part must not be queried any further.")

    def test_fast_mode_skips_transform_suppression_and_configuration(self):
        subassembly, _leaves = beam_tree()

        result = list_components(Automation(Assembly((subassembly,))), mode="fast")

        for item in result["data"]["components"]:
            self.assertNotIn("transform", item)
            self.assertNotIn("suppression_state", item)
            self.assertNotIn("configuration", item)
            self.assertIn("is_subassembly", item)
        self.assertFalse(result["data"]["components"][0]["is_subassembly"] is False,
                         "The sub-assembly must be recognised as one.")
        self.assertTrue(result["data"]["components"][0]["is_subassembly"])
        self.assertFalse(result["data"]["components"][1]["is_subassembly"])

    def test_fast_mode_still_marks_a_depth_limit_as_truncated(self):
        subassembly, leaves = beam_tree()

        result = list_components(Automation(Assembly((subassembly,))), depth=1,
                                 mode="fast")

        self.assertEqual(["Sub-1"],
                         [item["instance_path"] for item in result["data"]["components"]])
        self.assertTrue(result["data"]["coverage"]["truncated"])
        self.assertFalse(result["data"]["coverage"]["complete"])
        for leaf in leaves:
            self.assertEqual([], leaf.accesses,
                             "Children below the depth limit must not be touched.")

    def test_fast_mode_descends_into_a_component_without_a_resolved_path(self):
        # An unresolved path may hide a sub-assembly, so it is not treated as a
        # leaf; the nested part must still be found.
        inner = CountingComponent("Inner-1", "C:/output/inner.SLDPRT")
        virtual = CountingComponent("Virtual-1", "", (inner,))

        result = list_components(Automation(Assembly((virtual,))), mode="fast")

        self.assertEqual(["Virtual-1", "Virtual-1/Inner-1"],
                         [item["instance_path"] for item in result["data"]["components"]])
        self.assertIsNone(result["data"]["components"][0]["is_subassembly"],
                          "An unresolved path must be reported as unknown.")

    def test_only_a_part_path_is_treated_as_a_leaf(self):
        part = CountingComponent("Part-1", "C:/output/part.SLDPRT")
        upper = CountingComponent("Part-1", "C:/output/part.SLDPRT".upper())

        result = list_components(Automation(Assembly((part, upper))), mode="fast")

        for item in result["data"]["components"]:
            self.assertFalse(item["is_subassembly"])
        self.assertFalse(result["data"]["coverage"]["truncated"])

    def test_invalid_mode_is_rejected(self):
        subassembly, _leaves = beam_tree()

        result = list_components(Automation(Assembly((subassembly,))), mode="quick")

        self.assertFalse(result["success"])
        self.assertEqual("VALIDATION_FAILED", result["data"]["code"])


class DetailedTraversalTests(unittest.TestCase):
    def test_detailed_mode_is_the_default_and_keeps_the_full_record(self):
        subassembly, _leaves = beam_tree()

        result = list_components(Automation(Assembly((subassembly,))))

        self.assertEqual("detailed", result["data"]["mode"])
        nested = result["data"]["components"][1]
        self.assertEqual("Default", nested["configuration"])
        self.assertEqual(list(range(16)), nested["transform"])
        self.assertEqual("resolved", nested["suppression_state"])
        self.assertFalse(nested["is_fixed"])

    def test_detailed_mode_reads_every_member(self):
        subassembly, leaves = beam_tree()

        list_components(Automation(Assembly((subassembly,))), mode="detailed")

        self.assertEqual(
            ["Name2", "GetPathName", "GetSuppression", "IsVirtual",
             "ReferencedConfiguration", "Transform2", "IsFixed", "GetChildren"],
            leaves[0].accesses)


if __name__ == "__main__":
    unittest.main()
