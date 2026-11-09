import unittest

from solidworks_mcp.automation.features import FeatureOperations


class Feature:
    def __init__(self, name, kind, next_feature=None):
        self.Name = name
        self._kind = kind
        self._next = next_feature

    def GetTypeName2(self):
        return self._kind

    def GetNextFeature(self):
        return self._next


class FeatureManager:
    def __init__(self):
        self.directions = []

    def FeatureCut3(self, *args):
        self.directions.append(args[2])
        return object() if args[2] else None

    def FeatureCut4(self, *args):
        return None


class Document:
    def __init__(self):
        self.FeatureManager = FeatureManager()


class Units:
    class Default:
        value = "mm"

    default_unit = Default()

    @staticmethod
    def to_meters(value, unit):
        return value / 1000


class Automation(FeatureOperations):
    def __init__(self, document):
        self.document = document
        self._units = Units()

    def get_active_doc(self):
        return self.document, None

    def _close_and_select_sketch(self, document):
        return True, "Sketch2", ""

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class FeatureCutDirectionTests(unittest.TestCase):
    def test_find_last_sketch_supports_method_style_com_members(self):
        second = Feature("Sketch2", "ProfileFeature")
        first = Feature("Boss-Extrude1", "Extrusion", second)

        self.assertEqual("Sketch2", FeatureOperations()._find_last_sketch(type("Doc", (), {"FirstFeature": first})()))

    def test_cut_retries_opposite_direction_when_default_returns_no_feature(self):
        document = Document()

        result = Automation(document).cut_extrude(through_all=True)

        self.assertTrue(result["success"])
        self.assertEqual([False, True], document.FeatureManager.directions)
        self.assertTrue(result["data"]["flip_direction"])

    def test_explicit_direction_does_not_try_the_other_direction(self):
        document = Document()

        result = Automation(document).cut_extrude(through_all=True, flip_direction=True)

        self.assertTrue(result["success"])
        self.assertEqual([True], document.FeatureManager.directions)


if __name__ == "__main__":
    unittest.main()
