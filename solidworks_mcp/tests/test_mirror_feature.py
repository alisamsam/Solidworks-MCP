import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.patterns import mirror_feature


class SelectData:
    Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Feature:
    def __init__(self, name, type_name=None, next_feature=None, error_code=0):
        self.Name = name
        self.type_name = type_name or "Boss-Extrude"
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


class FeatureManager:
    def __init__(self, created=True, error_code=0):
        self.created = created
        self.error_code = error_code
        self.mirror_args = None
        self.created_feature = None

    def InsertMirrorFeature2(self, *args):
        self.mirror_args = args
        if not self.created:
            return None
        self.created_feature = Feature("Mirror1", "MirrorPattern", error_code=self.error_code)
        return self.created_feature


class Document:
    def __init__(self, created=True, error_code=0):
        self.plane = Feature("Right Plane", "RefPlane")
        self.seed = Feature("Boss-Extrude1", next_feature=self.plane)
        self.FirstFeature = self.seed
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


class MirrorFeatureRegistrationTests(unittest.TestCase):
    def test_mirror_feature_is_registered_as_mutation(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("mirror_feature", tools)
        self.assertIs(OperationClass.MUTATE, operation_class_for("mirror_feature"))
        self.assertEqual(
            ["seed_feature", "mirror_plane"],
            tools["mirror_feature"].inputSchema["required"],
        )


class MirrorFeatureBehaviorTests(unittest.TestCase):
    def test_selects_seed_and_plane_with_required_marks(self):
        automation = Automation()

        result = mirror_feature(automation, "Boss-Extrude1", "Right Plane")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 1)], automation.document.seed.select_calls)
        self.assertEqual([(True, 2)], automation.document.plane.select_calls)
        self.assertEqual(
            (False, True, True, False, 0),
            automation.document.FeatureManager.mirror_args,
        )
        self.assertEqual([True, True], automation.document.clear_calls)
        self.assertEqual("Mirror1", result["data"]["feature_name"])

    def test_non_default_flags_are_forwarded(self):
        automation = Automation()

        result = mirror_feature(
            automation, "Boss-Extrude1", "Right Plane",
            geometry_pattern=False, merge=False,
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            (False, False, False, False, 0),
            automation.document.FeatureManager.mirror_args,
        )

    def test_invalid_arguments_are_rejected_before_com(self):
        cases = [
            ("", "Right Plane", True, True),
            ("Boss-Extrude1", "  ", True, True),
            ("Boss-Extrude1", "Right Plane", "yes", True),
        ]
        for seed, plane, geometry_pattern, merge in cases:
            with self.subTest(seed=seed, plane=plane):
                automation = Automation()
                result = mirror_feature(
                    automation, seed, plane,
                    geometry_pattern=geometry_pattern, merge=merge,
                )
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_missing_plane_stops_before_mirror_call(self):
        automation = Automation()

        result = mirror_feature(automation, "Boss-Extrude1", "Plane99")

        self.assertFalse(result["success"])
        self.assertIsNone(automation.document.FeatureManager.mirror_args)
        self.assertEqual([True], automation.document.clear_calls)

    def test_no_feature_returned_is_reported_as_failure(self):
        automation = Automation(Document(created=False))

        result = mirror_feature(automation, "Boss-Extrude1", "Right Plane")

        self.assertFalse(result["success"])
        self.assertEqual([True, True], automation.document.clear_calls)

    def test_rebuild_failed_mirror_is_removed_and_reported(self):
        automation = Automation(Document(error_code=1))

        result = mirror_feature(automation, "Boss-Extrude1", "Right Plane")

        self.assertFalse(result["success"])
        self.assertEqual("MIRROR_REBUILD_FAILED", result["data"]["code"])
        self.assertTrue(result["data"]["removed"])
        self.assertEqual(1, automation.document.edit_delete_calls)
        created = automation.document.FeatureManager.created_feature
        self.assertEqual([(False, 0)], created.select2_calls)


if __name__ == "__main__":
    unittest.main()
