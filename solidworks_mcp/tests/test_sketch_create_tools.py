import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sketch_create import (
    create_3d_sketch, create_sketch_on_plane,
)


class Sketch:
    def __init__(self, is_3d):
        self.is_3d = is_3d

    def Is3D(self):
        return self.is_3d


class SketchManager:
    def __init__(self):
        self.calls = []
        self.AddToDB = None


class Feature:
    def __init__(self, name, type_name, next_feature=None):
        self.Name = name
        self.type_name = type_name
        self.next_feature = next_feature

    def GetTypeName2(self):
        return self.type_name

    def GetNextFeature(self):
        return self.next_feature


class Extension:
    def __init__(self, document, plane_ok=True):
        self.document = document
        self.plane_ok = plane_ok
        self.select_calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout,
                    options):
        self.select_calls.append((name, type_name))
        return self.plane_ok


class Document:
    def __init__(self, plane_ok=True, insert_is_3d=False, creates=True,
                 doc_type=1):
        self.doc_type = doc_type
        self.Extension = Extension(self, plane_ok)
        self.SketchManager = SketchManager()
        self.active = None
        self.creates = creates
        self.insert_is_3d = insert_is_3d
        self.insert_3d_is_3d = True
        self.insert_calls = []
        self.insert_3d_calls = []
        self.clear_calls = 0
        newest = Feature("3DSketch1", "3DProfileFeature",
                         Feature("Sketch1", "ProfileFeature"))
        self.FirstFeature = Feature("Front Plane", "RefPlane", newest)

    def GetType(self):
        return self.doc_type

    def ClearSelection2(self, clear_all):
        self.clear_calls += 1
        return True

    def InsertSketch2(self, update_edit_rebuild):
        self.insert_calls.append(update_edit_rebuild)
        if self.creates:
            self.active = Sketch(self.insert_is_3d)
        return True

    def Insert3DSketch2(self, update_edit_rebuild):
        self.insert_3d_calls.append(update_edit_rebuild)
        if self.creates:
            self.active = Sketch(self.insert_3d_is_3d)
        return True

    def GetActiveSketch2(self):
        return self.active


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


class SketchCreateRegistrationTests(unittest.TestCase):
    def test_both_tools_are_registered_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        for name in ("create_sketch_on_plane", "create_3d_sketch"):
            self.assertIn(name, tools)
            self.assertIs(OperationClass.MUTATE, operation_class_for(name))


class CreateSketchOnPlaneTests(unittest.TestCase):
    def test_a_plane_name_is_selected_and_the_sketch_name_returned(self):
        automation = Automation()

        result = create_sketch_on_plane(automation, "Right Plane")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([("Right Plane", "PLANE")],
                         automation.document.Extension.select_calls)
        self.assertEqual([True], automation.document.insert_calls)
        self.assertEqual("Sketch1", result["data"]["sketch"])
        self.assertFalse(result["data"]["is_3d"])

    def test_the_standard_plane_shorthands_are_expanded(self):
        for shorthand, full in (("front", "Front Plane"),
                                ("Top", "Top Plane"),
                                ("RIGHT", "Right Plane")):
            with self.subTest(shorthand=shorthand):
                automation = Automation()

                result = create_sketch_on_plane(automation, shorthand)

                self.assertTrue(result["success"], result["message"])
                self.assertEqual([(full, "PLANE")],
                                 automation.document.Extension.select_calls)

    def test_exact_geometry_sets_the_sketch_manager_flag(self):
        automation = Automation()

        create_sketch_on_plane(automation, "Front Plane", exact_geometry=True)

        self.assertTrue(automation.document.SketchManager.AddToDB)

    def test_a_missing_plane_is_reported(self):
        automation = Automation()
        automation.document.Extension.plane_ok = False

        result = create_sketch_on_plane(automation, "Plane9")

        self.assertFalse(result["success"])
        self.assertEqual("PLANE_NOT_FOUND", result["data"]["code"])
        self.assertEqual([], automation.document.insert_calls)

    def test_an_open_sketch_blocks_a_new_one(self):
        automation = Automation()
        automation.document.active = Sketch(False)

        result = create_sketch_on_plane(automation, "Front Plane")

        self.assertFalse(result["success"])
        self.assertEqual("SKETCH_ALREADY_OPEN", result["data"]["code"])
        self.assertEqual([], automation.document.Extension.select_calls)

    def test_a_3d_sketch_that_solidworks_returns_is_rejected(self):
        automation = Automation()
        automation.document.insert_is_3d = True

        result = create_sketch_on_plane(automation, "Front Plane")

        self.assertFalse(result["success"])
        self.assertEqual("UNEXPECTED_3D_SKETCH", result["data"]["code"])

    def test_validation_happens_before_com(self):
        cases = ({
            "plane": "",
        }, {
            "plane": "   ",
        }, {
            "plane": 5,
        }, {
            "plane": "Front Plane", "exact_geometry": "yes",
        })
        for arguments in cases:
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = create_sketch_on_plane(automation, **arguments)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_a_drawing_or_assembly_is_rejected(self):
        automation = Automation(Document(doc_type=3))

        result = create_sketch_on_plane(automation, "Front Plane")

        self.assertFalse(result["success"])


class Create3dSketchTests(unittest.TestCase):
    def test_a_3d_sketch_is_created_and_verified(self):
        automation = Automation()

        result = create_3d_sketch(automation)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([True], automation.document.insert_3d_calls)
        self.assertEqual([], automation.document.insert_calls)
        self.assertTrue(result["data"]["is_3d"])
        self.assertEqual("3DSketch1", result["data"]["sketch"])

    def test_a_2d_sketch_where_3d_was_asked_is_rejected(self):
        automation = Automation()
        automation.document.insert_3d_is_3d = False

        result = create_3d_sketch(automation)

        self.assertFalse(result["success"])
        self.assertEqual("NOT_A_3D_SKETCH", result["data"]["code"])

    def test_a_sketch_that_never_starts_is_reported(self):
        automation = Automation(Document(creates=False))

        result = create_3d_sketch(automation)

        self.assertFalse(result["success"])
        self.assertEqual("SKETCH_NOT_CREATED", result["data"]["code"])

    def test_an_open_sketch_blocks_a_new_one(self):
        automation = Automation()
        automation.document.active = Sketch(True)

        result = create_3d_sketch(automation)

        self.assertFalse(result["success"])
        self.assertEqual("SKETCH_ALREADY_OPEN", result["data"]["code"])
        self.assertEqual([], automation.document.insert_3d_calls)


if __name__ == "__main__":
    unittest.main()
