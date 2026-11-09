import unittest

from solidworks_mcp.tools.assembly import list_components


class Component:
    def __init__(self, name, path, children=()):
        self.Name2 = name
        self.GetPathName = path
        self.IsFixed = False
        self.GetSuppression = 1
        self.IsVirtual = False
        self.GetChildren = list(children)
        self.ReferencedConfiguration = "Default"
        self.Transform2 = type("Transform", (), {"ArrayData": list(range(16))})()


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


class RecursiveComponentTests(unittest.TestCase):
    def test_lists_nested_instance_paths_without_deduplicating_repeated_parts(self):
        part1 = Component("Frame-1", "C:/output/frame.SLDPRT")
        part2 = Component("Frame-2", "C:/output/frame.SLDPRT")
        subassembly = Component("Sub-1", "C:/output/sub.SLDASM", (part1, part2))

        result = list_components(Automation(Assembly((subassembly,))))

        components = result["data"]["components"]
        self.assertEqual(["Sub-1", "Sub-1/Frame-1", "Sub-1/Frame-2"],
                         [component["instance_path"] for component in components])
        self.assertEqual(3, result["data"]["coverage"]["visited_count"])
        self.assertTrue(result["data"]["coverage"]["complete"])
        self.assertEqual("Default", components[1]["configuration"])
        self.assertEqual(list(range(16)), components[1]["transform"])

    def test_depth_limit_marks_coverage_truncated_without_visiting_grandchildren(self):
        leaf = Component("Leaf-1", "C:/output/leaf.SLDPRT")
        nested = Component("Nested-1", "C:/output/nested.SLDASM", (leaf,))
        top = Component("Top-1", "C:/output/top.SLDASM", (nested,))

        result = list_components(Automation(Assembly((top,))), depth=2)

        self.assertEqual(["Top-1", "Top-1/Nested-1"],
                         [item["instance_path"] for item in result["data"]["components"]])
        self.assertTrue(result["data"]["coverage"]["truncated"])
        self.assertFalse(result["data"]["coverage"]["complete"])

    def test_unavailable_component_path_is_retained_as_unresolved(self):
        component = Component("Virtual-1", "")
        del component.GetPathName
        component.IsVirtual = True

        result = list_components(Automation(Assembly((component,))))

        item = result["data"]["components"][0]
        self.assertIsNone(item["path"])
        self.assertTrue(item["virtual"])
        self.assertFalse(result["data"]["coverage"]["complete"])


if __name__ == "__main__":
    unittest.main()
