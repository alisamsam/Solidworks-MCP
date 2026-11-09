import unittest

from solidworks_mcp.tools.inspection import list_planes


class Feature:
    def __init__(self, name, feature_type, next_feature=None):
        self.Name = name
        self.GetTypeName2 = feature_type
        self.GetNextFeature = next_feature


class Document:
    def __init__(self, first_feature):
        self.FirstFeature = first_feature


class Automation:
    def __init__(self, document):
        self.document = document

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "data": data or {}}


class InspectionToolTests(unittest.TestCase):
    def test_list_planes_includes_standard_and_reference_planes(self):
        custom = Feature("Offset 25", "RefPlane")
        result = list_planes(Automation(Document(custom)))

        self.assertTrue(result["success"])
        planes = result["data"]["planes"]
        self.assertEqual(["Front Plane", "Top Plane", "Right Plane", "Offset 25"],
                         [plane["name"] for plane in planes])
        self.assertEqual("reference", planes[-1]["kind"])

    def test_standard_planes_enumerated_as_ref_planes_are_not_duplicated(self):
        custom = Feature("Offset 25", "RefPlane")
        right = Feature("Right Plane", "RefPlane", custom)
        top = Feature("Top Plane", "RefPlane", right)
        front = Feature("Front Plane", "RefPlane", top)

        result = list_planes(Automation(Document(front)))

        self.assertEqual(["Front Plane", "Top Plane", "Right Plane", "Offset 25"],
                         [plane["name"] for plane in result["data"]["planes"]])


if __name__ == "__main__":
    unittest.main()
