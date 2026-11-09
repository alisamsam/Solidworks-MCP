import unittest
from unittest.mock import patch

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.advanced_features import shell_feature


class Feature:
    def __init__(self, name, type_name):
        self.Name = name
        self.type_name = type_name
        self.next_feature = None

    def GetTypeName2(self):
        return self.type_name

    def GetNextFeature(self):
        return self.next_feature


class SelectData:
    def __init__(self):
        self.Mark = 0


class SelectionManager:
    def CreateSelectData(self):
        return SelectData()


class Face:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.select_calls = []

    def Select4(self, append, select_data):
        self.select_calls.append((append, select_data.Mark))
        return self.succeeds


class Document:
    def __init__(self, create_shell=True):
        self.SelectionManager = SelectionManager()
        self.features = [Feature("Boss-Extrude1", "Extrusion")]
        self.create_shell = create_shell
        self.shell_calls = []
        self.clear_calls = []

    def FirstFeature(self):
        self._link_features()
        return self.features[0]

    def GetType(self):
        return 1

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True

    def InsertFeatureShell(self, thickness_m, outward):
        self.shell_calls.append((thickness_m, outward))
        if self.create_shell:
            self.features.append(Feature("Shell1", "Shell"))

    def _link_features(self):
        for current, following in zip(self.features, self.features[1:]):
            current.next_feature = following
        self.features[-1].next_feature = None


class Units:
    @staticmethod
    def to_meters(value, unit):
        return value * {"mm": 0.001, "cm": 0.01, "m": 1.0, "inch": 0.0254}[unit]


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self._units = Units()
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


class AdvancedFeatureRegistrationTests(unittest.TestCase):
    def test_shell_feature_declares_thickness_faces_and_direction(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("shell_feature", tools)
        self.assertIs(OperationClass.MUTATE, operation_class_for("shell_feature"))
        schema = tools["shell_feature"].inputSchema
        self.assertEqual(["thickness"], schema["required"])
        self.assertEqual(0, schema["properties"]["thickness"]["exclusiveMinimum"])
        self.assertEqual("array", schema["properties"]["remove_face_indices"]["type"])


class ShellFeatureBehaviorTests(unittest.TestCase):
    @patch("solidworks_mcp.tools.advanced_features._get_planar_face_by_index")
    def test_selects_removable_faces_with_mark_one_and_creates_shell(self, get_face):
        faces = [Face(), Face()]
        get_face.side_effect = faces
        automation = Automation()

        result = shell_feature(
            automation, 2, "mm", remove_face_indices=[3, 7], outward=True
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0.002, True)], automation.document.shell_calls)
        self.assertEqual([(False, 1)], faces[0].select_calls)
        self.assertEqual([(True, 1)], faces[1].select_calls)
        self.assertEqual([True, True], automation.document.clear_calls)
        self.assertEqual("Shell1", result["data"]["feature_name"])

    def test_invalid_arguments_are_rejected_before_com(self):
        for thickness, indices in [(0, []), (float("nan"), []), (2, [-1]), (2, [1, 1])]:
            with self.subTest(thickness=thickness, indices=indices):
                automation = Automation()
                result = shell_feature(
                    automation, thickness, remove_face_indices=indices
                )
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    @patch("solidworks_mcp.tools.advanced_features._get_planar_face_by_index", return_value=None)
    def test_missing_current_face_stops_before_shell_call(self, _get_face):
        automation = Automation()

        result = shell_feature(automation, 2, remove_face_indices=[99])

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.shell_calls)
        self.assertEqual([True, True], automation.document.clear_calls)

    def test_void_com_call_is_not_success_without_new_shell_feature(self):
        automation = Automation(Document(create_shell=False))

        result = shell_feature(automation, 2)

        self.assertFalse(result["success"])
        self.assertEqual([(0.002, False)], automation.document.shell_calls)
        self.assertEqual([True, True], automation.document.clear_calls)


if __name__ == "__main__":
    unittest.main()
