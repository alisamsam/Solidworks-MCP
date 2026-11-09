import unittest

from solidworks_mcp.inspection.documents import inspect_feature_tree


class Dimension:
    FullName = "D1@Sketch1"
    SystemValue = 0.125


class DisplayDimension:
    GetDimension2 = Dimension()


class Feature:
    def __init__(self, name, feature_type, child=None, next_sub=None, dimension=None):
        self.Name = name
        self.GetTypeName2 = feature_type
        self.IsSuppressed = False
        self.GetFirstSubFeature = child
        self.GetNextSubFeature = next_sub
        self.GetNextFeature = None
        self.GetFirstDisplayDimension = dimension

    def GetNextDisplayDimension(self, current):
        return None


class EquationManager:
    Count = 1

    def Equation(self, index):
        return '"Width" = 0.125'

    def Value(self, index):
        return 0.125

    def GlobalVariable(self, index):
        return True


class Document:
    def __init__(self, first_feature):
        self.FirstFeature = first_feature
        self.GetEquationMgr = EquationManager()


class LinkedDisplayDimension:
    def __init__(self, index):
        self.index = index

    @property
    def GetDimension2(self):
        dimension = type("LinkedDimension", (), {})()
        dimension.FullName = f"D{self.index + 1}@Sketch1"
        dimension.SystemValue = (self.index + 1) / 1000
        return dimension


class LinkedFeature(Feature):
    def __init__(self):
        super().__init__("Sketch1", "ProfileFeature")

    @property
    def GetFirstDisplayDimension(self):
        return LinkedDisplayDimension(0)

    @GetFirstDisplayDimension.setter
    def GetFirstDisplayDimension(self, value):
        pass

    def GetNextDisplayDimension(self, current):
        if current.index == 7:
            return None
        return LinkedDisplayDimension(current.index + 1)


class FeatureTreeInspectionTests(unittest.TestCase):
    def test_walks_all_dimensions_when_next_returns_transient_wrappers(self):
        result = inspect_feature_tree(Document(LinkedFeature()))
        names = [row["name"] for row in result["features"][0]["parameters"]]
        self.assertEqual([f"D{i}@Sketch1" for i in range(1, 9)], names)

    def test_preserves_unknown_subfeature_dimensions_and_equations(self):
        child = Feature("Imported oddity", "UnknownFeature")
        parent = Feature(
            "Boss-Extrude1", "BossExtrude", child=child,
            dimension=DisplayDimension(),
        )

        result = inspect_feature_tree(Document(parent))

        self.assertEqual("Imported oddity", result["features"][0]["children"][0]["name"])
        self.assertEqual("UnknownFeature", result["features"][0]["children"][0]["type"])
        dimension = result["features"][0]["parameters"][0]
        self.assertEqual("D1@Sketch1", dimension["name"])
        self.assertIsNone(dimension["raw_value"])
        self.assertEqual(0.125, dimension["resolved_value_m"])
        self.assertEqual('"Width" = 0.125', result["equations"][0]["raw_expression"])
        self.assertTrue(result["equations"][0]["global_variable"])


if __name__ == "__main__":
    unittest.main()
