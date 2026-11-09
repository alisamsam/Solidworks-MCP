"""Insert Part must import the source solid and prove the new geometry."""

import unittest
from unittest.mock import patch

from solidworks_mcp.tests.test_advanced_features import Automation, Feature
from solidworks_mcp.tests.test_delete_body import Body, BodyDocument
from solidworks_mcp.tools.body_features import insert_part

SOURCE = r"C:\temp\source.SLDPRT"


class StockFeature(Feature):
    def __init__(self, error_code=0):
        super().__init__("source", "Stock")
        self.error_code = error_code

    def GetErrorCode(self):
        return self.error_code


class InsertDocument(BodyDocument):
    def __init__(self, new_volume=250, error_code=0):
        super().__init__()
        self.bodies = []
        self.new_volume = new_volume
        self.error_code = error_code
        self.FeatureManager = self
        self.inserted = None

    def InsertPart3(self, path, options, configuration):
        self.inserted = (path, options, configuration)
        if self.new_volume > 0:
            self.bodies = [Body(self.new_volume)]
        return StockFeature(self.error_code)


class InsertPartTests(unittest.TestCase):
    @patch("solidworks_mcp.tools.body_features.os.path.isfile", return_value=True)
    def test_imports_source_solid_and_reports_stock_feature(self, _isfile):
        doc = InsertDocument()
        result = insert_part(Automation(doc), SOURCE)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, doc.inserted[1])  # swInsertPartImportSolids
        self.assertEqual("", doc.inserted[2])
        self.assertEqual("Stock", result["data"]["feature_type"])
        self.assertEqual(1, result["data"]["bodies_after"])
        self.assertAlmostEqual(250, result["data"]["volume_after_mm3"])
        self.assertTrue(result["data"]["source_path"].casefold().endswith("source.sldprt"))

    @patch("solidworks_mcp.tools.body_features.os.path.isfile", return_value=True)
    def test_feature_error_is_reported_as_failure(self, _isfile):
        doc = InsertDocument(error_code=1)
        result = insert_part(Automation(doc), SOURCE)

        self.assertFalse(result["success"])
        self.assertEqual(1, result["data"]["feature_error_code"])

    @patch("solidworks_mcp.tools.body_features.os.path.isfile", return_value=True)
    def test_no_added_geometry_is_rejected(self, _isfile):
        doc = InsertDocument(new_volume=0)
        result = insert_part(Automation(doc), SOURCE)

        self.assertFalse(result["success"])
        self.assertEqual("INSERT_PART_FAILED", result["data"]["code"])

    @patch("solidworks_mcp.tools.body_features.os.path.isfile", return_value=True)
    def test_same_body_count_is_not_a_new_stock_body(self, _isfile):
        doc = InsertDocument()
        doc.bodies = [Body(100)]
        result = insert_part(Automation(doc), SOURCE)

        self.assertFalse(result["success"])
        self.assertEqual((1, 1), (result["data"]["bodies_before"],
                                  result["data"]["bodies_after"]))

    def test_non_part_extension_is_rejected_before_com(self):
        sw = Automation(InsertDocument())
        result = insert_part(sw, r"C:\temp\source.txt")

        self.assertFalse(result["success"])
        self.assertEqual(0, sw.active_doc_calls)

    @patch("solidworks_mcp.tools.body_features.os.path.isfile", return_value=False)
    def test_missing_source_is_rejected_before_com(self, _isfile):
        sw = Automation(InsertDocument())
        result = insert_part(sw, SOURCE)

        self.assertFalse(result["success"])
        self.assertEqual("SOURCE_NOT_FOUND", result["data"]["code"])
        self.assertEqual(0, sw.active_doc_calls)


if __name__ == "__main__":
    unittest.main()
