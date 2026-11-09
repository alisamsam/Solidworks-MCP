import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.reference_geometry import create_reference_plane


class Extension:
    def __init__(self, select_succeeds=True):
        self.select_succeeds = select_succeeds
        self.select_calls = []

    def SelectByID2(self, *args):
        self.select_calls.append(args)
        return self.select_succeeds


class FeatureManager:
    def __init__(self, result=None):
        self.result = object() if result is None else result
        self.calls = []

    def InsertRefPlane(self, *args):
        self.calls.append(args)
        return self.result


class Document:
    def __init__(self, select_succeeds=True, plane_result=None):
        self.Extension = Extension(select_succeeds)
        self.FeatureManager = FeatureManager(plane_result)
        self.clear_calls = []

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True


class Units:
    @staticmethod
    def to_meters(value, unit):
        factors = {"mm": 0.001, "cm": 0.01, "m": 1.0, "inch": 0.0254}
        return value * factors[unit]


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


class ReferencePlaneRegistrationTests(unittest.TestCase):
    def test_offset_reference_plane_is_a_bounded_mutation_tool(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("create_reference_plane", tools)
        self.assertIs(
            OperationClass.MUTATE, operation_class_for("create_reference_plane")
        )
        schema = tools["create_reference_plane"].inputSchema
        self.assertEqual(["base_plane", "offset"], schema["required"])
        self.assertEqual(0, schema["properties"]["offset"]["exclusiveMinimum"])


class ReferencePlaneBehaviorTests(unittest.TestCase):
    def test_creates_distance_plane_with_offset_converted_to_meters(self):
        automation = Automation()

        result = create_reference_plane(automation, "Front Plane", 25, "mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual((8, 0.025, 0, 0, 0, 0), automation.document.FeatureManager.calls[0])
        select = automation.document.Extension.select_calls[0]
        self.assertEqual(("Front Plane", "PLANE"), select[:2])
        self.assertEqual([True, True], automation.document.clear_calls)
        self.assertEqual("Front Plane", result["data"]["base_plane"])

    def test_reverse_direction_uses_reverse_distance_constraint(self):
        automation = Automation()

        result = create_reference_plane(
            automation, "Top Plane", 1, "cm", reverse_direction=True
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual((264, 0.01, 0, 0, 0, 0), automation.document.FeatureManager.calls[0])

    def test_non_positive_offset_is_rejected_before_com(self):
        automation = Automation()

        result = create_reference_plane(automation, "Front Plane", 0)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_missing_base_plane_stops_before_insert_and_clears_selection(self):
        automation = Automation(Document(select_succeeds=False))

        result = create_reference_plane(automation, "Missing Plane", 10)

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.FeatureManager.calls)
        self.assertEqual([True, True], automation.document.clear_calls)


if __name__ == "__main__":
    unittest.main()
