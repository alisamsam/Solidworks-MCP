import math
import unittest

from solidworks_mcp.tools.patterns import circular_pattern, linear_pattern


class SelectData:
    Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Feature:
    def __init__(self, name, next_feature=None):
        self.Name = name
        self.GetNextFeature = next_feature
        self.marks = []

    def Select4(self, append, select_data):
        self.marks.append(select_data.Mark)
        return True


class FeatureManager:
    def __init__(self):
        self.circular_args = None
        self.linear_args = None

    def FeatureCircularPattern4(self, *args):
        self.circular_args = args
        return object()

    def FeatureLinearPattern4(self, *args):
        self.linear_args = args
        return object()


class Document:
    def __init__(self):
        self.axis = Feature("Axis1")
        self.seed = Feature("Cut-Extrude1", self.axis)
        self.FirstFeature = self.seed
        self.SelectionManager = SelectionManager()
        self.FeatureManager = FeatureManager()

    def ClearSelection2(self, clear_all):
        return True


class Automation:
    def __init__(self):
        self.document = Document()
        self._units = type("Units", (), {"to_meters": staticmethod(lambda value, unit: value / 1000)})()

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class PatternToolTests(unittest.TestCase):
    def test_circular_pattern_selects_seed_and_axis_with_required_marks(self):
        sw = Automation()

        result = circular_pattern(sw, "Cut-Extrude1", "Axis1", 60, 360)

        self.assertTrue(result["success"])
        self.assertEqual([4], sw.document.seed.marks)
        self.assertEqual([1], sw.document.axis.marks)
        self.assertEqual((60, 2 * math.pi, False, "NULL", True, True, False),
                         sw.document.FeatureManager.circular_args)

    def test_linear_pattern_calls_documented_feature_api(self):
        sw = Automation()

        result = linear_pattern(sw, "Cut-Extrude1", "Axis1", 4, 25)

        self.assertTrue(result["success"])
        args = sw.document.FeatureManager.linear_args
        self.assertEqual((4, 0.025), args[:2])
        self.assertEqual(20, len(args))


if __name__ == "__main__":
    unittest.main()
