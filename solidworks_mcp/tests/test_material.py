import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for
from solidworks_mcp.tests.test_advanced_features import Automation, Document
from solidworks_mcp.tools.material import apply_material


class Configuration:
    Name = "Default"


class ConfigurationManager:
    ActiveConfiguration = Configuration()


class MaterialDocument(Document):
    def __init__(self, accepts=True):
        super().__init__()
        self.ConfigurationManager = ConfigurationManager()
        self.accepts = accepts
        self.name = ""
        self.database = ""
        self.calls = []

    def GetMassProperties(self, density):
        assert density == 0.0
        return (0., 0., 0., .000004, .0016, .0312 if self.name else .004)

    def SetMaterialPropertyName2(self, configuration, database, name):
        self.calls.append((configuration, database, name))
        if self.accepts:
            self.name, self.database = name, "SOLIDWORKS Materials"

    def GetMaterialPropertyName2(self, configuration, database_out):
        database_out.value = self.database
        return self.name


class MaterialTests(unittest.TestCase):
    def test_material_readback_and_density_from_mass_properties(self):
        with TemporaryDirectory() as root:
            database = Path(root) / "steel.sldmat"
            database.write_text("<materials />")
            document = MaterialDocument()
            result = apply_material(Automation(document), "Plain Carbon Steel", str(database))
        self.assertTrue(result["success"], result["message"])
        self.assertEqual("Default", result["data"]["configuration"])
        self.assertEqual("SOLIDWORKS Materials", result["data"]["database_read_back"])
        self.assertAlmostEqual(7800, result["data"]["density_kg_m3"])
        self.assertEqual("Plain Carbon Steel", document.calls[0][2])
        self.assertIs(OperationClass.MUTATE, operation_class_for("apply_material"))

    def test_rejects_invalid_arguments_before_com(self):
        automation = Automation(MaterialDocument())
        for name, database in (("", "x.sldmat"), ("Steel", "missing.sldmat"),
                               ("Steel", "test.txt"), (None, "x.sldmat")):
            with self.subTest(name=name, database=database):
                self.assertFalse(apply_material(automation, name, database)["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_void_setter_without_readback_is_failure(self):
        with TemporaryDirectory() as root:
            database = Path(root) / "steel.sldmat"
            database.write_text("<materials />")
            document = MaterialDocument(accepts=False)
            result = apply_material(Automation(document), "Plain Carbon Steel", str(database))
        self.assertFalse(result["success"])
        self.assertEqual("MATERIAL_NOT_APPLIED", result["data"]["code"])


if __name__ == "__main__":
    unittest.main()
