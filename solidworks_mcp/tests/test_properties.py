"""Custom property writes must be read back at the requested scope."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.properties import set_custom_property


class PropertyManager:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.result = 0

    def Add3(self, name, kind, value, option):
        self.calls.append((name, kind, value, option))
        if self.result:
            return self.result
        if option == 2 or name not in self.values:
            self.values[name] = value
        return 0

    def Get5(self, name, cached, raw, resolved, was_resolved):
        if name not in self.values:
            return 1
        raw.value = self.values[name]
        resolved.value = self.values[name]
        was_resolved.value = True
        return 2


class Extension:
    def __init__(self):
        self.managers = {"": PropertyManager(), "Default": PropertyManager()}

    def CustomPropertyManager(self, name):
        return self.managers[name]


class PropertyDocument(Document):
    def __init__(self):
        super().__init__()
        self.Extension = Extension()

    def GetConfigurationByName(self, name):
        return object() if name == "Default" else None


class PropertyTests(unittest.TestCase):
    def test_document_and_configuration_scopes_with_read_back(self):
        document = PropertyDocument()
        automation = Automation(document)
        doc_result = set_custom_property(automation, "PartNumber", "PN-42")
        cfg_result = set_custom_property(automation, "Revision", "B", "Default")
        self.assertTrue(doc_result["success"], doc_result["message"])
        self.assertTrue(cfg_result["success"], cfg_result["message"])
        self.assertEqual("PN-42", doc_result["data"]["read_back"])
        self.assertEqual("B", cfg_result["data"]["read_back"])
        self.assertEqual([("PartNumber", 30, "PN-42", 2)],
                         document.Extension.managers[""].calls)
        self.assertEqual([("Revision", 30, "B", 2)],
                         document.Extension.managers["Default"].calls)

    def test_no_overwrite_reports_mismatch(self):
        document = PropertyDocument()
        document.Extension.managers[""].values["Revision"] = "A"
        result = set_custom_property(Automation(document), "Revision", "B",
                                     overwrite=False)
        self.assertFalse(result["success"])
        self.assertEqual("PROPERTY_NOT_REPLACED", result["data"]["code"])
        self.assertEqual("A", document.Extension.managers[""].values["Revision"])

    def test_invalid_input_and_unknown_configuration(self):
        automation = Automation(PropertyDocument())
        self.assertFalse(set_custom_property(automation, "", "x")["success"])
        self.assertFalse(set_custom_property(automation, "n", 2)["success"])
        self.assertEqual(0, automation.active_doc_calls)
        unknown = set_custom_property(automation, "n", "x", "Unknown")
        self.assertFalse(unknown["success"])
        self.assertEqual("CONFIGURATION_NOT_FOUND", unknown["data"]["code"])

    def test_add_failure_is_not_reported_as_success(self):
        document = PropertyDocument()
        document.Extension.managers[""].result = 1
        result = set_custom_property(Automation(document), "n", "v")
        self.assertFalse(result["success"])
        self.assertEqual("PROPERTY_ADD_FAILED", result["data"]["code"])
