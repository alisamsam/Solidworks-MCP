import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.advanced_features import loft_sketches, sweep_sketch


class SelectData:
    Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Feature:
    def __init__(self, name, type_name=None, next_feature=None, error_code=0):
        self.Name = name
        self.type_name = type_name or "ProfileFeature"
        self.next_feature = next_feature
        self.error_code = error_code
        self.select_calls = []
        self.select2_calls = []

    def GetTypeName2(self):
        return self.type_name

    def GetErrorCode(self):
        return self.error_code

    def GetNextFeature(self):
        return self.next_feature

    def Select4(self, append, select_data):
        self.select_calls.append((append, select_data.Mark))
        return True

    def Select2(self, append, mark):
        self.select2_calls.append((append, mark))
        return True


class FeatureData:
    pass


class FeatureManager:
    def __init__(self, created=True, error_code=0):
        self.created = created
        self.error_code = error_code
        self.definition_types = []
        self.create_feature_calls = 0
        self.blend_args = None

    def CreateDefinition(self, feature_type):
        self.definition_types.append(feature_type)
        return FeatureData()

    def CreateFeature(self, _feature_data):
        self.create_feature_calls += 1
        if not self.created:
            return None
        return Feature("Sweep1", "Sweep", error_code=self.error_code)

    def InsertProtrusionBlend2(self, *args):
        self.blend_args = args
        if not self.created:
            return None
        return Feature("Loft1", "Blend", error_code=self.error_code)


class Document:
    def __init__(self, created=True, error_code=0):
        self.profile = Feature("Sketch1")
        self.path = Feature("Sketch2", next_feature=self.profile)
        self.FirstFeature = self.path
        self.SelectionManager = SelectionManager()
        self.FeatureManager = FeatureManager(created, error_code)
        self.clear_calls = []
        self.edit_delete_calls = 0

    def GetType(self):
        return 1

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True

    def EditDelete(self):
        self.edit_delete_calls += 1
        return True


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self.active_doc_calls = 0

    def get_active_doc(self):
        self.active_doc_calls += 1
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "data": data or {},
        }


class SweepLoftRegistrationTests(unittest.TestCase):
    def test_sweep_and_loft_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("sweep_sketch", tools)
        self.assertIn("loft_sketches", tools)
        self.assertIs(OperationClass.MUTATE, operation_class_for("sweep_sketch"))
        self.assertIs(OperationClass.MUTATE, operation_class_for("loft_sketches"))
        self.assertEqual(
            ["profile_sketch", "path_sketch"],
            tools["sweep_sketch"].inputSchema["required"],
        )
        self.assertEqual(2, tools["loft_sketches"].inputSchema["properties"]
                         ["profile_sketches"]["minItems"])


class SweepBehaviorTests(unittest.TestCase):
    def test_sweep_selects_profile_mark_one_and_path_mark_four(self):
        automation = Automation()

        result = sweep_sketch(automation, "Sketch1", "Sketch2")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], automation.document.profile.select_calls)
        self.assertEqual([(True, 4)], automation.document.path.select_calls)
        self.assertEqual([17], automation.document.FeatureManager.definition_types)
        self.assertEqual(1, automation.document.FeatureManager.create_feature_calls)
        self.assertEqual("Sweep1", result["data"]["feature_name"])

    def test_sweep_invalid_arguments_are_rejected_before_com(self):
        for profile, path in [("", "Sketch2"), ("Sketch1", " "), ("Sketch1", "Sketch1")]:
            with self.subTest(profile=profile, path=path):
                automation = Automation()
                result = sweep_sketch(automation, profile, path)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_sweep_missing_path_stops_before_creation(self):
        automation = Automation()

        result = sweep_sketch(automation, "Sketch1", "Sketch9")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.FeatureManager.definition_types)

    def test_sweep_rebuild_failure_is_removed_and_reported(self):
        automation = Automation(Document(error_code=1))

        result = sweep_sketch(automation, "Sketch1", "Sketch2")

        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_REBUILD_FAILED", result["data"]["code"])
        self.assertEqual(1, automation.document.edit_delete_calls)


class LoftBehaviorTests(unittest.TestCase):
    def test_loft_selects_all_profiles_in_order_with_mark_one(self):
        automation = Automation()

        # feature tree order only matters for lookup, not for the call order
        result = loft_sketches(automation, ["Sketch1", "Sketch2"])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], automation.document.profile.select_calls)
        self.assertEqual([(True, 1)], automation.document.path.select_calls)
        args = automation.document.FeatureManager.blend_args
        self.assertEqual(18, len(args))
        self.assertEqual((False, True, True), args[:3])
        self.assertEqual(3, args[-1])
        self.assertEqual("Loft1", result["data"]["feature_name"])

    def test_loft_requires_two_distinct_names(self):
        for names in ([], ["Sketch1"], ["Sketch1", "Sketch1"], ["", "Sketch2"]):
            with self.subTest(names=names):
                automation = Automation()
                result = loft_sketches(automation, names)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_loft_rebuild_failure_is_removed_and_reported(self):
        automation = Automation(Document(error_code=1))

        result = loft_sketches(automation, ["Sketch1", "Sketch2"])

        self.assertFalse(result["success"])
        self.assertEqual("FEATURE_REBUILD_FAILED", result["data"]["code"])
        self.assertEqual(1, automation.document.edit_delete_calls)


if __name__ == "__main__":
    unittest.main()
