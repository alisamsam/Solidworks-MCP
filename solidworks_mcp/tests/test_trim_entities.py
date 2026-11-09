import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sketch_edit import extend_entities, trim_entities


class Segment:
    def __init__(self, length):
        self.length = length

    def GetLength(self):
        return self.length


class Sketch:
    def __init__(self, document):
        self.document = document

    def GetSketchSegments(self):
        return [Segment(length) for length in self.document.lengths]


class SketchManager:
    def __init__(self, document, trim_returns=True, trim_changes=True,
                 extend_returns=True, extend_changes=True):
        self.document = document
        self.trim_returns = trim_returns
        self.trim_changes = trim_changes
        self.extend_returns = extend_returns
        self.extend_changes = extend_changes
        self.trim_calls = []
        self.extend_calls = []

    def SketchTrim(self, option, x, y, z):
        self.trim_calls.append((option, x, y, z))
        if self.trim_changes:
            self.document.lengths = self.document.lengths[:-1]
        return self.trim_returns

    def SketchExtend(self, x, y, z):
        self.extend_calls.append((x, y, z))
        if self.extend_changes:
            self.document.lengths = [self.document.lengths[0] + 10.0]
        return self.extend_returns


class Feature:
    def __init__(self, name, sketch_object=None, type_name="ProfileFeature",
                 next_feature=None):
        self.Name = name
        self.type_name = type_name
        self.sketch_object = sketch_object
        self.next_feature = next_feature
        self.select_calls = []

    def GetTypeName2(self):
        return self.type_name

    def GetNextFeature(self):
        return self.next_feature

    def GetSpecificFeature2(self):
        return self.sketch_object

    def Select2(self, append, mark):
        self.select_calls.append((append, mark))
        return True


class Extension:
    def __init__(self, select_ok=True):
        self.select_ok = select_ok
        self.select_calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout, options):
        self.select_calls.append((name, type_name, append))
        return self.select_ok


class Document:
    def __init__(self, select_ok=True, trim_returns=True, trim_changes=True,
                 extend_returns=True, extend_changes=True, edit_ok=True,
                 sketch="Sketch1"):
        self.lengths = [50.0, 40.0]
        self.sketch = Feature(sketch, Sketch(self))
        self.FirstFeature = self.sketch
        self.Extension = Extension(select_ok)
        self.SketchManager = SketchManager(
            self, trim_returns, trim_changes, extend_returns, extend_changes
        )
        self.edit_ok = edit_ok
        self.edit_calls = 0
        self.insert_sketch_calls = []
        self.clear_calls = []

    def GetType(self):
        return 1

    def EditSketch(self):
        self.edit_calls += 1
        return None if self.edit_ok else False

    def InsertSketch2(self, update_edit_rebuild):
        self.insert_sketch_calls.append(update_edit_rebuild)
        return True

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True


class Units:
    def to_meters(self, value, unit=None):
        return value * 0.001


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self.units = Units()
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


class SketchEditRegistrationTests(unittest.TestCase):
    def test_trim_and_extend_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("trim_entities", tools)
        self.assertIn("extend_entities", tools)
        self.assertIs(OperationClass.MUTATE, operation_class_for("trim_entities"))
        self.assertIs(OperationClass.MUTATE, operation_class_for("extend_entities"))
        self.assertEqual(
            ["sketch", "entities"],
            tools["trim_entities"].inputSchema["required"],
        )
        self.assertIn(
            "corner",
            tools["trim_entities"].inputSchema["properties"]["mode"]["enum"],
        )
        self.assertNotIn(
            "entities",
            tools["trim_entities"].inputSchema["properties"]["mode"]["enum"],
        )


class TrimBehaviorTests(unittest.TestCase):
    def test_corner_trim_opens_sketch_selects_then_trims_and_closes(self):
        automation = Automation()

        result = trim_entities(automation, "Sketch1", ["Line1", "Line2"], "corner")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, automation.document.edit_calls)
        self.assertEqual([True], automation.document.insert_sketch_calls)
        self.assertEqual([(False, 0)], automation.document.sketch.select_calls)
        self.assertEqual(
            [("Line1", "SKETCHSEGMENT", False), ("Line2", "SKETCHSEGMENT", True)],
            automation.document.Extension.select_calls,
        )
        self.assertEqual([(1, 0.0, 0.0, 0.0)], automation.document.SketchManager.trim_calls)
        self.assertEqual(1, result["data"]["trim_option"])
        self.assertEqual(["Line1", "Line2"], result["data"]["entities"])
        self.assertTrue(result["data"]["geometry_changed"])
        self.assertTrue(result["data"]["references_invalidated"])

    def test_each_mode_maps_to_the_verified_enum_value(self):
        expected = {
            "closest": 0, "corner": 1, "twoentities": 2, "entitypoint": 3,
            "outside": 5, "inside": 6,
        }
        entity_sets = {
            "inside": ["Line1", "Line2", "Line3"],
            "outside": ["Line1", "Line2", "Line3"],
        }
        for mode, value in expected.items():
            with self.subTest(mode=mode):
                document = Document()
                automation = Automation(document)
                entities = entity_sets.get(mode, ["Line1", "Line2"])
                result = trim_entities(automation, "Sketch1", entities, mode)
                self.assertTrue(result["success"], result["message"])
                self.assertEqual(value, document.SketchManager.trim_calls[0][0])

    def test_pick_point_is_forwarded_in_metres(self):
        automation = Automation()

        result = trim_entities(
            automation, "Sketch1", ["Line1"], "closest", pick=[10, 5, 0]
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0, 0.01, 0.005, 0.0)], automation.document.SketchManager.trim_calls)

    def test_invalid_mode_is_rejected_before_com(self):
        automation = Automation()

        result = trim_entities(automation, "Sketch1", ["Line1"], "banana")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_unusable_entities_mode_is_rejected(self):
        automation = Automation()

        result = trim_entities(automation, "Sketch1", ["Line1"], "entities")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_too_few_entities_for_mode_is_rejected_before_com(self):
        for mode, entities in [
            ("corner", ["Line1"]),
            ("twoentities", ["Line1"]),
            ("inside", ["Line1", "Line2"]),
            ("outside", ["Line1", "Line2"]),
            ("corner", []),
        ]:
            with self.subTest(mode=mode, entities=entities):
                automation = Automation()
                result = trim_entities(automation, "Sketch1", entities, mode)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_missing_sketch_stops_before_opening_it(self):
        automation = Automation()

        result = trim_entities(automation, "Sketch9", ["Line1", "Line2"], "corner")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.document.edit_calls)
        self.assertEqual([], automation.document.SketchManager.trim_calls)

    def test_api_false_without_geometry_change_is_reported_and_sketch_closed(self):
        automation = Automation(Document(trim_returns=False, trim_changes=False))

        result = trim_entities(automation, "Sketch1", ["Line1", "Line2"], "corner")

        self.assertFalse(result["success"])
        self.assertEqual("TRIM_FAILED", result["data"]["code"])
        self.assertEqual([True], automation.document.insert_sketch_calls)

    def test_api_false_with_geometry_change_is_still_success(self):
        # swSketchTrimClosest returns False in SW 2025 even though it trims.
        automation = Automation(Document(trim_returns=False, trim_changes=True))

        result = trim_entities(
            automation, "Sketch1", ["Line1"], "closest", pick=[40, 0, 0]
        )

        self.assertTrue(result["success"], result["message"])
        self.assertTrue(result["data"]["geometry_changed"])

    def test_failed_edit_sketch_does_not_close_an_unopened_sketch(self):
        automation = Automation(Document(edit_ok=False))

        result = trim_entities(automation, "Sketch1", ["Line1", "Line2"], "corner")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.insert_sketch_calls)
        self.assertEqual([], automation.document.SketchManager.trim_calls)


class ExtendBehaviorTests(unittest.TestCase):
    def test_extend_opens_selects_and_extends_one_entity(self):
        automation = Automation()

        result = extend_entities(automation, "Sketch1", ["Line1"], pick=[0, 25, 0])

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(False, 0)], automation.document.sketch.select_calls)
        self.assertEqual(
            [("Line1", "SKETCHSEGMENT", False)],
            automation.document.Extension.select_calls,
        )
        self.assertEqual([(0.0, 0.025, 0.0)], automation.document.SketchManager.extend_calls)
        self.assertEqual([True], automation.document.insert_sketch_calls)
        self.assertTrue(result["data"]["geometry_changed"])

    def test_extend_requires_exactly_one_entity(self):
        for entities in ([], ["Line1", "Line2"]):
            with self.subTest(entities=entities):
                automation = Automation()
                result = extend_entities(automation, "Sketch1", entities)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_extend_without_geometry_change_is_reported(self):
        automation = Automation(Document(extend_returns=False, extend_changes=False))

        result = extend_entities(automation, "Sketch1", ["Line1"])

        self.assertFalse(result["success"])
        self.assertEqual("EXTEND_FAILED", result["data"]["code"])
        self.assertEqual([True], automation.document.insert_sketch_calls)


if __name__ == "__main__":
    unittest.main()
