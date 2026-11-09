"""create_configuration must refuse to overwrite and read the configuration back."""

import unittest

from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.configurations import create_configuration


class Configuration:
    def __init__(self, name, comment="", alternate_name="", description=""):
        self.Name = name
        self.Comment = comment
        self.AlternateName = alternate_name
        self.Description = description


class ConfigurationManager:
    def __init__(self, activate_on_add=False):
        self.configurations = {"Default": Configuration("Default")}
        self.ActiveConfiguration = self.configurations["Default"]
        self.activate_on_add = activate_on_add
        self.register_on_add = True
        self.calls = []

    def AddConfiguration2(self, name, comment, alternate_name, options, parent,
                          description, rebuild):
        self.calls.append((name, comment, alternate_name, options, parent,
                           description, rebuild))
        if not self.register_on_add:
            return None
        configuration = Configuration(name, comment, alternate_name, description)
        self.configurations[name] = configuration
        if self.activate_on_add:
            self.ActiveConfiguration = configuration
        return configuration


class ConfigurationDocument(Document):
    def __init__(self, activate_on_add=False, activate_works=True):
        super().__init__()
        self.ConfigurationManager = ConfigurationManager(activate_on_add)
        self.activate_works = activate_works
        self.show_calls = []

    def GetConfigurationByName(self, name):
        return self.ConfigurationManager.configurations.get(name)

    def ShowConfiguration2(self, name):
        self.show_calls.append(name)
        configuration = self.ConfigurationManager.configurations.get(name)
        if configuration is None or not self.activate_works:
            return False
        self.ConfigurationManager.ActiveConfiguration = configuration
        return True


class CreateConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.document = ConfigurationDocument()
        self.automation = Automation(self.document)

    def create(self, **kwargs):
        return create_configuration(self.automation, **kwargs)

    def test_creates_and_reads_back_named_configuration(self):
        result = self.create(name="Flanged", comment="PN-42",
                             description="flanged variant")
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([("Flanged", "PN-42", "", 0, "", "flanged variant", False)],
                         self.document.ConfigurationManager.calls)
        self.assertEqual("Flanged", result["data"]["read_back"]["name"])
        self.assertEqual("PN-42", result["data"]["read_back"]["comment"])
        self.assertIn("Flanged", self.document.ConfigurationManager.configurations)

    def test_existing_configuration_is_never_overwritten(self):
        self.document.ConfigurationManager.configurations["Flanged"] = \
            Configuration("Flanged", comment="keep me")
        result = self.create(name="Flanged", comment="replacement")
        self.assertFalse(result["success"])
        self.assertEqual("CONFIGURATION_EXISTS", result["data"]["code"])
        self.assertEqual([], self.document.ConfigurationManager.calls)
        self.assertEqual("keep me",
                         self.document.ConfigurationManager.configurations["Flanged"].Comment)

    def test_stored_metadata_is_read_back(self):
        result = self.create(name="Flanged", comment="c", alternate_name="Flange A",
                             description="d", options=1)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual({"name": "Flanged", "comment": "c",
                          "alternate_name": "Flange A", "description": "d"},
                         result["data"]["read_back"])

    def test_parent_options_and_rebuild_are_forwarded(self):
        result = self.create(name="Flanged", parent_configuration="Default",
                             options=64, rebuild=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([("Flanged", "", "", 64, "Default", "", True)],
                         self.document.ConfigurationManager.calls)
        self.assertEqual("Default", result["data"]["parent_configuration"])

    def test_activate_verifies_the_configuration_becomes_active(self):
        result = self.create(name="Flanged", activate=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(["Flanged"], self.document.show_calls)
        self.assertTrue(result["data"]["active"])
        self.assertEqual("Flanged", result["data"]["active_configuration"])

    def test_already_active_configuration_needs_no_show_call(self):
        document = ConfigurationDocument(activate_on_add=True)
        result = create_configuration(Automation(document), name="Flanged",
                                      activate=True)
        self.assertTrue(result["success"], result["message"])
        self.assertEqual([], document.show_calls)
        self.assertTrue(result["data"]["active"])

    def test_activation_that_does_not_stick_is_reported(self):
        self.document.activate_works = False
        result = self.create(name="Flanged", activate=True)
        self.assertFalse(result["success"])
        self.assertEqual("CONFIGURATION_NOT_ACTIVATED", result["data"]["code"])
        self.assertEqual("Default", result["data"]["active_configuration"])
        self.assertIn("Flanged", self.document.ConfigurationManager.configurations)

    def test_dont_activate_option_leaves_the_active_configuration(self):
        result = self.create(name="Flanged", options=128)
        self.assertTrue(result["success"], result["message"])
        self.assertFalse(result["data"]["active"])
        self.assertEqual("Default", result["data"]["active_configuration"])
        self.assertEqual([], self.document.show_calls)

    def test_create_result_that_cannot_be_read_back_fails(self):
        self.document.ConfigurationManager.register_on_add = False
        result = self.create(name="Flanged")
        self.assertFalse(result["success"])
        self.assertEqual("CONFIGURATION_NOT_READABLE", result["data"]["code"])
        self.assertFalse(result["data"]["created"])

    def test_missing_parent_is_rejected_before_creating(self):
        result = self.create(name="Flanged", parent_configuration="NoSuchConfig")
        self.assertFalse(result["success"])
        self.assertEqual("CONFIGURATION_PARENT_NOT_FOUND", result["data"]["code"])
        self.assertEqual([], self.document.ConfigurationManager.calls)

    def test_validation_rejects_bad_input_without_touching_solidworks(self):
        for kwargs in (
            {"name": ""},
            {"name": "   "},
            {"name": "Flanged", "comment": 7},
            {"name": "Flanged", "description": None},
            {"name": "Flanged", "alternate_name": 1},
            {"name": "Flanged", "parent_configuration": 2},
            {"name": "Flanged", "options": True},
            {"name": "Flanged", "options": -1},
            {"name": "Flanged", "rebuild": 1},
            {"name": "Flanged", "activate": "yes"},
            {"name": "Flanged", "parent_configuration": "Flanged"},
        ):
            with self.subTest(kwargs=kwargs):
                result = self.create(**kwargs)
                self.assertFalse(result["success"])
                self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
        self.assertEqual(0, self.automation.active_doc_calls)


if __name__ == "__main__":
    unittest.main()
