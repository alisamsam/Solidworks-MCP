import unittest

from solidworks_mcp.automation.features import FeatureOperations


class Feature:
    def __init__(self, name, feature_type, suppressed, next_feature=None):
        self.Name = name
        self.GetTypeName2 = feature_type
        self.IsSuppressed = suppressed
        self.GetNextFeature = next_feature


class Document:
    def __init__(self, feature):
        self.FirstFeature = feature


class Automation(FeatureOperations):
    def __init__(self, document):
        self.document = document

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class FeatureInspectionTests(unittest.TestCase):
    def test_list_features_reports_suppression_without_dropping_unknown_types(self):
        unknown = Feature("Imported oddity", "UnknownFeature", True)
        extrusion = Feature("Boss-Extrude1", "BossExtrude", False, unknown)

        result = Automation(Document(extrusion)).list_features()

        self.assertTrue(result["success"])
        self.assertEqual(
            [("Boss-Extrude1", "BossExtrude", False), ("Imported oddity", "UnknownFeature", True)],
            [(item["name"], item["type"], item["suppressed"])
             for item in result["data"]["features"]],
        )


if __name__ == "__main__":
    unittest.main()
