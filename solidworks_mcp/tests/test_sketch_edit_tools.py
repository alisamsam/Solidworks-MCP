import math
import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.sketch_edit import (
    add_sketch_dimension, add_sketch_relation, delete_sketch_relations,
    get_sketch_relations, offset_entities, rotate_entities, scale_entities,
    sketch_chamfer, sketch_fillet, sketch_mirror, sketch_pattern_circular,
    sketch_pattern_linear, split_entities, toggle_construction,
)

# swConstraintType_e values for the legacy relation strings, written out here so
# the test does not read the table it is meant to pin down.
TYPE_BY_RELATION_STRING = {
    "sgHORIZONTAL": 4,
    "sgVERTICAL": 5,
    "sgTANGENT": 6,
    "sgPARALLEL": 7,
    "sgPERPENDICULAR": 8,
    "sgCOINCIDENT": 9,
    "sgCONCENTRIC": 10,
    "sgSYMMETRIC": 11,
    "sgSAMELENGTH": 14,
    "sgFIXED": 17,
    "sgCOLINEAR": 27,
}


class Segment:
    def __init__(self, length, type_code=0, centre=None, start=None, end=None,
                 construction=False):
        self.length = length
        self.type_code = type_code
        self.centre = centre
        self.start = start if start is not None else (0.0, 0.0, 0.0)
        self.end = end if end is not None else (0.0, 0.0, 0.0)
        self.ConstructionGeometry = construction

    def GetLength(self):
        return self.length

    def GetType(self):
        return self.type_code

    def GetCenterPoint(self):
        if self.centre is None:
            raise AttributeError("GetCenterPoint")
        return self.centre

    def GetStartPoint(self):
        return self.start

    def GetEndPoint(self):
        return self.end


class Sketch:
    def __init__(self, document):
        self.document = document

    def GetSketchSegments(self):
        return list(self.document.segments)

    @property
    def ModelToSketchTransform(self):
        return self.document.transform_object

    @property
    def RelationManager(self):
        return self.document.relation_manager

    def GetConstrainedStatus(self):
        return self.document.constrained_status


class Relation:
    def __init__(self, type_id):
        self.type_id = type_id

    def GetRelationType(self):
        return self.type_id


class RelationManager:
    def __init__(self, document):
        self.document = document
        self.delete_all_calls = 0
        self.delete_calls = []

    def GetRelations(self, filter_type):
        return list(self.document.relations)

    def GetRelationsCount(self, filter_type):
        return len(self.document.relations)

    def DeleteRelation(self, relation):
        self.delete_calls.append(relation)
        if relation in self.document.relations:
            self.document.relations.remove(relation)
            return True
        return False

    def DeleteAllRelations(self):
        self.delete_all_calls += 1
        self.document.relations = []
        return True


class Transform:
    """Stands in for IMathTransform on the fake sketch."""

    def __init__(self, document):
        self.document = document

    @property
    def ArrayData(self):
        return tuple(self.document.transform)


class SketchManager:
    def __init__(self, document, changes=True):
        self.document = document
        self.changes = changes
        self.calls = []

    def _record(self, name, arguments):
        self.calls.append((name, arguments))
        if self.changes:
            self.document.segments.append(Segment(9.0))

    def CreateFillet(self, radius, constrained_corners):
        self._record("CreateFillet", (radius, constrained_corners))
        return object()

    def CreateChamfer(self, chamfer_type, distance, second):
        self._record("CreateChamfer", (chamfer_type, distance, second))
        return object()

    def SketchOffset2(self, offset, both, chain, cap_ends, construction, dims):
        self._record("SketchOffset2", (offset, both, chain, cap_ends,
                                       construction, dims))
        return True

    def SplitOpenSegment(self, x, y, z):
        self._record("SplitOpenSegment", (x, y, z))
        return (object(), object())

    def SplitClosedSegment(self, x1, y1, z1, x2, y2, z2):
        self._record("SplitClosedSegment", (x1, y1, z1, x2, y2, z2))
        return (object(), object())

    def CreateLinearSketchStepAndRepeat(self, *arguments):
        self._record("CreateLinearSketchStepAndRepeat", arguments)
        return True

    def CreateCircularSketchStepAndRepeat(self, *arguments):
        self._record("CreateCircularSketchStepAndRepeat", arguments)
        return True


class Dimension:
    def __init__(self, document, segment):
        self.document = document
        self.segment = segment
        self.system_value = 0.0

    def SetSystemValue2(self, value, which_configurations):
        self.system_value = value
        if self.document.driven_dimension:
            return 3
        if self.segment is not None:
            # Live behaviour: a driving length dimension resizes the segment.
            self.segment.length = value * 1000.0
        return 0

    @property
    def SystemValue(self):
        return self.system_value

    def FullName(self):
        return "D1@Sketch1@Part1.Part"

    def ReadOnly(self):
        return self.document.driven_dimension


class DisplayDimension:
    def __init__(self, document, segment):
        self.dimension = Dimension(document, segment)

    def GetDimension(self):
        return self.dimension


class RunningCommand:
    def __init__(self, name=None, command_id=-3):
        self.name = name
        self.command_id = command_id
        self.preferences = {10: True}
        self.preference_calls = []

    def GetRunningCommandInfo(self):
        return (self.command_id, self.name or "", False)

    def GetUserPreferenceToggle(self, preference):
        return self.preferences[preference]

    def SetUserPreferenceToggle(self, preference, value):
        self.preference_calls.append((preference, value))
        self.preferences[preference] = value
        return None


class Feature:
    def __init__(self, name, sketch_object, next_feature=None):
        self.Name = name
        self.sketch_object = sketch_object
        self.next_feature = next_feature
        self.select_calls = []

    def GetNextFeature(self):
        return self.next_feature

    def GetSpecificFeature2(self):
        return self.sketch_object

    def Select2(self, append, mark):
        self.select_calls.append((append, mark))
        return True


class SelectionManager:
    def __init__(self, document):
        self.document = document

    def GetSelectedObjectCount2(self, mark):
        return len(self.document.selected)

    def GetSelectedObject6(self, index, mark):
        return self.document.selected[index - 1]


class Extension:
    def __init__(self, document, select_ok=True):
        self.document = document
        self.select_ok = select_ok
        self.select_calls = []

    def SelectByID2(self, name, type_name, x, y, z, append, mark, callout,
                    options):
        self.select_calls.append((name, type_name, append))
        if not self.select_ok:
            return False
        if type_name == "SKETCHPOINT":
            entity = self.document.points_by_name.get(name)
        else:
            entity = self.document.segments_by_name.get(name)
        if entity is None:
            return False
        if not append:
            self.document.selected = []
        self.document.selected.append(entity)
        return True


class Document:
    def __init__(self, select_ok=True, changes=True,
                 seed_centre=(0.02, 0.0, 0.0)):
        self.changes = changes
        self.segments = [Segment(50.0), Segment(40.0)]
        self.transform = [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                          0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        self.transform_object = Transform(self)
        self.sketch = Feature("Sketch1", Sketch(self))
        self.FirstFeature = self.sketch
        self.selected = []
        self.segments_by_name = {
            "Line1": self.segments[0],
            "Line2": self.segments[1],
            "Arc1": Segment(31.4, type_code=1, centre=seed_centre,
                            start=(seed_centre[0] + 0.005, seed_centre[1], 0.0),
                            end=(seed_centre[0] + 0.005, seed_centre[1], 0.0)),
        }
        self.Extension = Extension(self, select_ok)
        self.SelectionManager = SelectionManager(self)
        self.SketchManager = SketchManager(self, changes)
        self.edit_calls = 0
        self.rebuild_calls = []
        self.insert_sketch_calls = []
        self.clear_calls = []
        self.mirror_calls = 0
        self.scale_calls = []
        self.rotate_calls = []
        self.constrained_status = 3
        self.relations = [Relation(4), Relation(4), Relation(9)]
        self.relation_manager = RelationManager(self)
        self.points_by_name = {"Point1": Segment(0.0, type_code=2)}
        self.constraint_calls = []
        self.dimension_calls = []
        self.display_dimension = None
        self.dimension_ok = True
        self.driven_dimension = False

    def AddDimension2(self, x, y, z):
        self.dimension_calls.append((x, y, z))
        if not self.dimension_ok:
            return None
        segment = self.selected[-1] if self.selected else None
        self.display_dimension = DisplayDimension(self, segment)
        return self.display_dimension

    def SketchAddConstraints(self, constraint_string):
        self.constraint_calls.append(constraint_string)
        if self.changes:
            self.relations.append(
                Relation(TYPE_BY_RELATION_STRING.get(constraint_string, 0)))
        return None

    def GetType(self):
        return 1

    def EditSketch(self):
        self.edit_calls += 1
        return None

    def EditRebuild3(self):
        self.rebuild_calls.append(True)
        return True

    def GetActiveSketch2(self):
        return self.sketch.sketch_object

    def InsertSketch2(self, update_edit_rebuild):
        self.insert_sketch_calls.append(update_edit_rebuild)
        return True

    def ClearSelection2(self, clear_all):
        self.selected = []
        self.clear_calls.append(clear_all)
        return True

    def SketchMirror(self):
        self.mirror_calls += 1
        self.segments.append(Segment(7.0))
        return None

    def SketchModifyScale(self, factor):
        self.scale_calls.append(factor)
        if self.changes:
            for segment in self.segments:
                segment.length *= factor
        return True

    def SketchModifyRotate(self, center_x, center_y, angle):
        self.rotate_calls.append((center_x, center_y, angle))
        if self.changes:
            # Live behaviour: only the sketch frame changes here, the segment
            # coordinates (and their lengths) stay as they were.
            self.transform[3:9] = [0.0, -1.0, 0.0, 1.0, 0.0, 0.0]
        return None


class Units:
    def to_meters(self, value, unit=None):
        return value * 0.001

    def from_meters(self, value, unit=None):
        return value * 1000.0


class Automation:
    def __init__(self, document=None):
        self.document = document or Document()
        self._units = Units()
        self.units = self._units
        self.app = RunningCommand()
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


def manager_calls(automation, name):
    return [arguments for call_name, arguments in
            automation.document.SketchManager.calls if call_name == name]


class RegistrationTests(unittest.TestCase):
    def test_new_sketch_edit_tools_are_registered_as_mutations(self):
        tools = {item.name: item for item in registered_tools()}
        for name in (
            "sketch_fillet", "sketch_chamfer", "offset_entities",
            "sketch_mirror", "split_entities", "sketch_pattern_linear",
            "sketch_pattern_circular", "scale_entities", "toggle_construction",
            "rotate_entities", "add_sketch_relation", "delete_sketch_relations",
            "add_sketch_dimension",
        ):
            with self.subTest(tool=name):
                self.assertIn(name, tools)
                self.assertIs(OperationClass.MUTATE, operation_class_for(name))

    def test_chamfer_schema_exposes_the_three_verified_modes(self):
        tools = {item.name: item for item in registered_tools()}
        self.assertEqual(
            ["distance_angle", "distance_distance", "distance_equal"],
            tools["sketch_chamfer"].inputSchema["properties"]["mode"]["enum"],
        )

    def test_circular_pattern_requires_a_count(self):
        tools = {item.name: item for item in registered_tools()}
        self.assertEqual(
            ["sketch", "entities", "count"],
            tools["sketch_pattern_circular"].inputSchema["required"],
        )


class FilletTests(unittest.TestCase):
    def test_fillet_selects_two_entities_and_passes_radius_in_metres(self):
        automation = Automation()

        result = sketch_fillet(
            automation, "Sketch1", ["Line1", "Line2"], radius=8
        )

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, automation.document.edit_calls)
        self.assertEqual(
            [("Line1", "SKETCHSEGMENT", False), ("Line2", "SKETCHSEGMENT", True)],
            automation.document.Extension.select_calls,
        )
        self.assertEqual(
            [(0.008, True)],
            manager_calls(automation, "CreateFillet"),
        )
        self.assertEqual([True], automation.document.insert_sketch_calls)
        self.assertTrue(result["data"]["references_invalidated"])

    def test_fillet_rejects_a_single_entity_before_touching_com(self):
        for entities in ([], ["Line1"], ["Line1", "Line1"], ["Line1", "Line2",
                                                             "Line3"]):
            with self.subTest(entities=entities):
                automation = Automation()
                result = sketch_fillet(automation, "Sketch1", entities, radius=5)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_fillet_rejects_a_non_positive_radius(self):
        for radius in (0, -3, "big", True):
            with self.subTest(radius=radius):
                automation = Automation()
                result = sketch_fillet(automation, "Sketch1",
                                       ["Line1", "Line2"], radius=radius)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_fillet_without_geometry_change_is_a_failure(self):
        automation = Automation(Document(changes=False))

        result = sketch_fillet(automation, "Sketch1", ["Line1", "Line2"], radius=8)

        self.assertFalse(result["success"])
        self.assertEqual("FILLET_FAILED", result["data"]["code"])
        self.assertEqual([True], automation.document.insert_sketch_calls)

    def test_fillet_reports_boolean_constrained_corners(self):
        automation = Automation()

        result = sketch_fillet(automation, "Sketch1", ["Line1", "Line2"],
                               radius=4, constrained_corners=0)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0.004, False)], manager_calls(automation, "CreateFillet"))


class ChamferTests(unittest.TestCase):
    def test_distance_angle_uses_type_zero_and_radians(self):
        automation = Automation()

        result = sketch_chamfer(automation, "Sketch1", ["Line1", "Line2"],
                                distance=6, angle_deg=30)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [(0, 0.006, math.radians(30))],
            manager_calls(automation, "CreateChamfer"),
        )

    def test_distance_distance_uses_the_second_length(self):
        automation = Automation()

        result = sketch_chamfer(automation, "Sketch1", ["Line1", "Line2"],
                                distance=6, mode="distance_distance",
                                distance2=9)

        self.assertTrue(result["success"], result["message"])
        arguments = manager_calls(automation, "CreateChamfer")[0]
        self.assertEqual(1, arguments[0])
        self.assertAlmostEqual(0.006, arguments[1])
        self.assertAlmostEqual(0.009, arguments[2])
        self.assertEqual(9, result["data"]["distance2"])

    def test_distance_equal_repeats_the_distance_instead_of_zero(self):
        automation = Automation()

        result = sketch_chamfer(automation, "Sketch1", ["Line1", "Line2"],
                                distance=6, mode="distance_equal")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(2, 0.006, 0.006)],
                         manager_calls(automation, "CreateChamfer"))

    def test_distance_distance_without_distance2_is_rejected(self):
        automation = Automation()

        result = sketch_chamfer(automation, "Sketch1", ["Line1", "Line2"],
                                distance=6, mode="distance_distance")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_angle_must_stay_below_ninety_degrees(self):
        for angle in (0, 90, 120):
            with self.subTest(angle=angle):
                automation = Automation()
                result = sketch_chamfer(automation, "Sketch1",
                                        ["Line1", "Line2"], distance=6,
                                        angle_deg=angle)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_unknown_mode_is_rejected(self):
        automation = Automation()

        result = sketch_chamfer(automation, "Sketch1", ["Line1", "Line2"],
                                distance=6, mode="vertex")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


class OffsetTests(unittest.TestCase):
    def test_offset_forwards_flags_and_metres(self):
        automation = Automation()

        result = offset_entities(automation, "Sketch1", ["Line1"], offset=5,
                                 both_directions=True, cap_ends=True)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [(0.005, True, True, 1, False, False)],
            manager_calls(automation, "SketchOffset2"),
        )

    def test_offset_allows_a_negative_distance(self):
        automation = Automation()

        result = offset_entities(automation, "Sketch1", ["Line1"], offset=-2.5)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(-0.0025, manager_calls(automation, "SketchOffset2")[0][0])

    def test_zero_offset_is_rejected(self):
        automation = Automation()

        result = offset_entities(automation, "Sketch1", ["Line1"], offset=0)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_offset_needs_at_least_one_entity(self):
        automation = Automation()

        result = offset_entities(automation, "Sketch1", [], offset=5)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


class MirrorTests(unittest.TestCase):
    def test_mirror_selects_the_entities_then_the_axis(self):
        automation = Automation()

        result = sketch_mirror(automation, "Sketch1", ["Arc1"],
                               mirror_entity="Line1")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [("Arc1", "SKETCHSEGMENT", False), ("Line1", "SKETCHSEGMENT", True)],
            automation.document.Extension.select_calls,
        )
        self.assertEqual(1, automation.document.mirror_calls)

    def test_axis_must_not_be_one_of_the_mirrored_entities(self):
        automation = Automation()

        result = sketch_mirror(automation, "Sketch1", ["Line1", "Line2"],
                               mirror_entity="Line2")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_mirror_requires_a_named_axis(self):
        automation = Automation()

        result = sketch_mirror(automation, "Sketch1", ["Arc1"], mirror_entity="  ")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


class SplitTests(unittest.TestCase):
    def test_split_forwards_the_pick_point_in_metres(self):
        automation = Automation()

        result = split_entities(automation, "Sketch1", ["Line1"], x=10, y=0)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0.01, 0.0, 0.0)],
                         manager_calls(automation, "SplitOpenSegment"))
        self.assertTrue(result["data"]["references_invalidated"])

    def test_split_requires_exactly_one_entity(self):
        for entities in ([], ["Line1", "Line2"]):
            with self.subTest(entities=entities):
                automation = Automation()
                result = split_entities(automation, "Sketch1", entities, x=1, y=1)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_split_needs_numeric_coordinates(self):
        automation = Automation()

        result = split_entities(automation, "Sketch1", ["Line1"], x="ten", y=0)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


class LinearPatternTests(unittest.TestCase):
    def test_linear_pattern_forwards_counts_spacings_and_angles(self):
        automation = Automation()

        result = sketch_pattern_linear(
            automation, "Sketch1", ["Arc1"], spacing_x=20, spacing_y=15,
            count_x=2, count_y=3,
        )

        self.assertTrue(result["success"], result["message"])
        arguments = manager_calls(automation, "CreateLinearSketchStepAndRepeat")[0]
        self.assertEqual(
            (2, 3, 0.02, 0.015, 0.0, math.radians(90), "",
             False, False, False, False, False),
            arguments,
        )
        self.assertEqual(6, result["data"]["instances"])

    def test_linear_pattern_exposes_the_seed_rotation_angles(self):
        automation = Automation()

        result = sketch_pattern_linear(
            automation, "Sketch1", ["Arc1"], spacing_x=10, count_x=3,
            angle_x_deg=45, angle_y_deg=0,
        )

        self.assertTrue(result["success"], result["message"])
        arguments = manager_calls(automation, "CreateLinearSketchStepAndRepeat")[0]
        self.assertAlmostEqual(math.radians(45), arguments[4])
        self.assertAlmostEqual(0.0, arguments[5])

    def test_a_single_instance_pattern_is_rejected(self):
        automation = Automation()

        result = sketch_pattern_linear(automation, "Sketch1", ["Arc1"],
                                       spacing_x=10, count_x=1, count_y=1)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)

    def test_spacing_is_required_for_each_direction_with_several_instances(self):
        cases = [
            {"spacing_x": 0, "count_x": 2},
            {"spacing_x": 10, "count_x": 2, "spacing_y": 0, "count_y": 2},
        ]
        for case in cases:
            with self.subTest(case=case):
                automation = Automation()
                result = sketch_pattern_linear(automation, "Sketch1", ["Arc1"],
                                               **case)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_non_integral_counts_are_rejected(self):
        for count_x in (0, -1, 2.5, True):
            with self.subTest(count_x=count_x):
                automation = Automation()
                result = sketch_pattern_linear(automation, "Sketch1", ["Arc1"],
                                               spacing_x=10, count_x=count_x)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)


class CircularPatternTests(unittest.TestCase):
    def test_full_circle_pattern_derives_radius_and_angle_from_the_seed(self):
        automation = Automation()

        result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"],
                                         count=4, center_x=0, center_y=0)

        self.assertTrue(result["success"], result["message"])
        arguments = manager_calls(
            automation, "CreateCircularSketchStepAndRepeat"
        )[0]
        self.assertAlmostEqual(0.02, arguments[0])
        self.assertAlmostEqual(math.pi, arguments[1])
        self.assertEqual(4, arguments[2])
        self.assertEqual(0.0, arguments[3])
        self.assertFalse(arguments[4])
        self.assertEqual("", arguments[5])
        self.assertEqual(20.0, result["data"]["arc_radius"])
        self.assertAlmostEqual(180.0, result["data"]["arc_angle_deg"])

    def test_partial_angle_spacing_is_negative_to_step_counter_clockwise(self):
        automation = Automation()

        result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"],
                                         count=3, total_angle_deg=90)

        self.assertTrue(result["success"], result["message"])
        arguments = manager_calls(
            automation, "CreateCircularSketchStepAndRepeat"
        )[0]
        self.assertAlmostEqual(-math.radians(90) / 3, arguments[3])

    def test_seed_reference_uses_the_centres_of_the_selected_geometry(self):
        # Two seed circles at (20, 0) and (0, 30) mm average to (10, 15) mm.
        automation = Automation()
        document = automation.document
        document.segments_by_name["Arc2"] = Segment(
            31.4, type_code=1, centre=(0.0, 0.03, 0.0)
        )

        result = sketch_pattern_circular(automation, "Sketch1", ["Arc1", "Arc2"],
                                         count=2, center_x=0, center_y=0)

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(10.0, result["data"]["seed_center"][0])
        self.assertAlmostEqual(15.0, result["data"]["seed_center"][1])
        arguments = manager_calls(
            automation, "CreateCircularSketchStepAndRepeat"
        )[0]
        self.assertAlmostEqual(math.hypot(0.01, 0.015), arguments[0])
        # The pattern centre is the seed plus radius in the ArcAngle
        # direction, so ArcAngle is the seed bearing turned through 180 deg.
        self.assertAlmostEqual(
            math.atan2(0.015, 0.01) + math.pi, arguments[1]
        )

    def test_seed_on_the_centre_is_rejected(self):
        automation = Automation()

        result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"],
                                         count=4, center_x=20, center_y=0)

        self.assertFalse(result["success"])
        self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
        self.assertEqual([True], automation.document.insert_sketch_calls)

    def test_selection_failure_stops_the_pattern(self):
        automation = Automation(Document(select_ok=False))

        result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"], count=4)

        self.assertFalse(result["success"])

    def test_count_must_be_at_least_two(self):
        for count in (1, 0, -2, 2.5, True):
            with self.subTest(count=count):
                automation = Automation()
                result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"],
                                                 count=count)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_total_angle_must_be_within_a_full_circle(self):
        for angle in (0, 361, -10):
            with self.subTest(angle=angle):
                automation = Automation()
                result = sketch_pattern_circular(automation, "Sketch1", ["Arc1"],
                                                 count=4,
                                                 total_angle_deg=angle)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_missing_sketch_stops_before_opening_it(self):
        automation = Automation()

        result = sketch_pattern_circular(automation, "Sketch9", ["Arc1"], count=4)

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.document.edit_calls)


class SplitClosedTests(unittest.TestCase):
    def test_two_points_split_a_closed_entity_in_metres(self):
        automation = Automation()

        result = split_entities(automation, "Sketch1", ["Arc1"], x=10, y=0,
                                x2=0, y2=10)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(
            [(0.01, 0.0, 0.0, 0.0, 0.01, 0.0)],
            manager_calls(automation, "SplitClosedSegment"),
        )
        self.assertTrue(result["data"]["closed"])
        self.assertEqual([10, 0, 0, 10], result["data"]["pick"])

    def test_one_closed_point_is_rejected_before_com(self):
        for extra in ({"x2": 0}, {"y2": 10}):
            with self.subTest(extra=extra):
                automation = Automation()
                result = split_entities(automation, "Sketch1", ["Arc1"], x=10,
                                        y=0, **extra)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_an_open_split_still_calls_the_open_segment_api(self):
        automation = Automation()

        result = split_entities(automation, "Sketch1", ["Line1"], x=25, y=0)

        self.assertTrue(result["success"], result["message"])
        self.assertFalse(result["data"]["closed"])
        self.assertEqual(1, len(manager_calls(automation, "SplitOpenSegment")))
        self.assertEqual([], manager_calls(automation, "SplitClosedSegment"))


class ScaleTests(unittest.TestCase):
    def test_scale_passes_the_factor_and_scales_the_selected_entities(self):
        automation = Automation()

        result = scale_entities(automation, "Sketch1", ["Line1", "Line2"], 2.0)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([2.0], automation.document.scale_calls)
        self.assertEqual([100.0, 80.0],
                         [segment.GetLength()
                          for segment in automation.document.segments])
        self.assertEqual(
            [("Line1", "SKETCHSEGMENT", False), ("Line2", "SKETCHSEGMENT", True)],
            automation.document.Extension.select_calls,
        )

    def test_a_factor_of_one_is_rejected_before_com(self):
        for factor in (1, 0, -2, "2", None):
            with self.subTest(factor=factor):
                automation = Automation()
                result = scale_entities(automation, "Sketch1", ["Line1"], factor)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_unchanged_geometry_is_reported_as_a_failure(self):
        automation = Automation()
        automation.document.changes = False
        automation.document.SketchManager.changes = False

        result = scale_entities(automation, "Sketch1", ["Line1"], 2.0)

        self.assertFalse(result["success"])
        self.assertEqual("SCALE_FAILED", result["data"]["code"])


class ToggleConstructionTests(unittest.TestCase):
    def test_forcing_true_marks_the_entities_as_construction(self):
        automation = Automation()

        result = toggle_construction(automation, "Sketch1", ["Line1"],
                                     construction=True)

        self.assertTrue(result["success"], result["message"])
        self.assertIs(True,
                      automation.document.segments_by_name["Line1"]
                      .ConstructionGeometry)
        self.assertIs(True, result["data"]["construction"])

    def test_a_second_forced_true_reports_no_change(self):
        automation = Automation()
        toggle_construction(automation, "Sketch1", ["Line1"], construction=True)

        result = toggle_construction(automation, "Sketch1", ["Line1"],
                                     construction=True)

        self.assertFalse(result["success"])
        self.assertEqual("CONSTRUCTION_FAILED", result["data"]["code"])

    def test_omitting_the_state_flips_each_entity(self):
        automation = Automation()

        first = toggle_construction(automation, "Sketch1", ["Line1", "Line2"])
        self.assertTrue(first["success"], first["message"])
        flags = [automation.document.segments_by_name[name].ConstructionGeometry
                 for name in ("Line1", "Line2")]
        self.assertEqual([True, True], flags)

        second = toggle_construction(automation, "Sketch1", ["Line1"])
        self.assertTrue(second["success"], second["message"])
        self.assertIs(False,
                      automation.document.segments_by_name["Line1"]
                      .ConstructionGeometry)
        self.assertIs(True,
                      automation.document.segments_by_name["Line2"]
                      .ConstructionGeometry)

    def test_a_non_boolean_state_is_rejected_before_com(self):
        automation = Automation()

        result = toggle_construction(automation, "Sketch1", ["Line1"],
                                     construction="yes")

        self.assertFalse(result["success"])
        self.assertEqual(0, automation.active_doc_calls)


class RotateTests(unittest.TestCase):
    def test_rotate_passes_the_centre_in_metres_and_the_angle_in_radians(self):
        automation = Automation()

        result = rotate_entities(automation, "Sketch1", ["Line1", "Line2"],
                                 angle_deg=90, center_x=10, center_y=-5,
                                 unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0.01, -0.005, math.pi / 2)],
                         automation.document.rotate_calls)
        self.assertEqual(90, result["data"]["angle_deg"])

    def test_rotate_succeeds_even_though_the_segment_lengths_do_not_change(self):
        """The live call rotates the sketch frame, not the segment coordinates."""
        automation = Automation()
        before = [segment.GetLength()
                  for segment in automation.document.segments]

        result = rotate_entities(automation, "Sketch1", ["Line1"], angle_deg=45)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(before, [segment.GetLength()
                                  for segment in automation.document.segments])
        self.assertTrue(result["data"]["geometry_changed"])

    def test_a_full_turn_and_bad_angles_are_rejected_before_com(self):
        for angle in (0, 360, -360, "90", None):
            with self.subTest(angle=angle):
                automation = Automation()
                result = rotate_entities(automation, "Sketch1", ["Line1"],
                                         angle_deg=angle)
                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_an_unchanged_frame_is_reported_as_a_failure(self):
        automation = Automation()
        automation.document.changes = False

        result = rotate_entities(automation, "Sketch1", ["Line1"], angle_deg=90)

        self.assertFalse(result["success"])
        self.assertEqual("ROTATE_FAILED", result["data"]["code"])


class SketchRelationTests(unittest.TestCase):
    def test_add_relation_sends_the_legacy_string_and_proves_the_change(self):
        automation = Automation()
        automation.document.relations = []

        result = add_sketch_relation(automation, "Sketch1", ["Line1", "Line2"],
                                     "parallel")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(["sgPARALLEL"], automation.document.constraint_calls)
        self.assertEqual(["parallel"], result["data"]["relations"])
        self.assertEqual(1, result["data"]["relation_count"])
        self.assertEqual(1, len(automation.document.relations))

    def test_a_redundant_relation_is_reported_as_a_failure(self):
        automation = Automation()
        automation.document.changes = False

        result = add_sketch_relation(automation, "Sketch1", ["Line1", "Line2"],
                                     "parallel")

        self.assertFalse(result["success"])
        self.assertEqual("RELATION_NOT_ADDED", result["data"]["code"])

    def test_relation_names_map_to_the_verified_strings(self):
        for relation, expected in (("same_length", "sgSAMELENGTH"),
                                   ("colinear", "sgCOLINEAR"),
                                   ("tangent", "sgTANGENT")):
            with self.subTest(relation=relation):
                automation = Automation()
                automation.document.relations = []

                result = add_sketch_relation(automation, "Sketch1", ["Line1"],
                                             relation)

                self.assertTrue(result["success"], result["message"])
                self.assertEqual([expected],
                                 automation.document.constraint_calls)

    def test_an_unknown_relation_and_an_empty_list_never_reach_com(self):
        for arguments in ({"entities": ["Line1"], "relation": "equal"},
                          {"entities": [], "relation": "parallel"},
                          {"entities": ["Line1"], "relation": "same length"}):
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = add_sketch_relation(automation, "Sketch1", **arguments)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)
                self.assertEqual([], automation.document.constraint_calls)

    def test_get_relations_reports_types_counts_and_the_defined_state(self):
        automation = Automation()
        automation.document.relations = [Relation(4), Relation(4), Relation(14)]
        automation.document.constrained_status = 3

        result = get_sketch_relations(automation, "Sketch1")

        self.assertTrue(result["success"], result["message"])
        data = result["data"]
        self.assertEqual(3, data["relation_count"])
        self.assertEqual({"horizontal": 2, "same_length": 1},
                         data["relation_counts"])
        self.assertEqual("fully_constrained", data["constrained_status"])
        self.assertTrue(data["fully_defined"])
        self.assertTrue(all(entry["type_id"] in (4, 14)
                            for entry in data["relations"]))

    def test_get_relations_flags_an_under_constrained_sketch(self):
        automation = Automation()
        automation.document.constrained_status = 2

        result = get_sketch_relations(automation, "Sketch1")

        self.assertFalse(result["data"]["fully_defined"])
        self.assertEqual("under_constrained", result["data"]["constrained_status"])

    def test_delete_all_relations_deletes_and_reports_the_remainder(self):
        automation = Automation()

        result = delete_sketch_relations(automation, "Sketch1", all=True)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(1, automation.document.relation_manager
                         .delete_all_calls)
        self.assertEqual([], automation.document.relations)
        self.assertEqual(0, result["data"]["relation_count"])

    def test_deleting_one_relation_type_leaves_the_others(self):
        automation = Automation()
        automation.document.relations = [Relation(4), Relation(7), Relation(4)]

        result = delete_sketch_relations(automation, "Sketch1",
                                         relation="horizontal")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([7], [relation.type_id
                               for relation in automation.document.relations])
        self.assertEqual(1, result["data"]["relation_count"])

    def test_delete_needs_exactly_one_target(self):
        for arguments in ({}, {"all": True, "relation": "parallel"}):
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = delete_sketch_relations(automation, "Sketch1",
                                                 **arguments)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)

    def test_deleting_a_relation_that_is_not_there_is_a_failure(self):
        automation = Automation()
        automation.document.relations = [Relation(7)]

        result = delete_sketch_relations(automation, "Sketch1",
                                         relation="horizontal")

        self.assertFalse(result["success"])
        self.assertEqual("RELATION_NOT_DELETED", result["data"]["code"])


class SketchDimensionTests(unittest.TestCase):
    def test_a_driving_dimension_resizes_the_line(self):
        automation = Automation()

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(0.03, 0.005, 0.0)],
                         automation.document.dimension_calls)
        self.assertEqual(30.0, automation.document.segments[0].length)
        self.assertTrue(result["data"]["geometry_changed"])
        self.assertEqual(30.0, result["data"]["dimension_value"])
        self.assertEqual("D1@Sketch1@Part1.Part",
                         result["data"]["dimension_name"])
        self.assertFalse(result["data"]["read_only"])

    def test_the_dimension_is_committed_with_a_rebuild(self):
        automation = Automation()

        add_sketch_dimension(automation, "Sketch1", ["Line1"], 30, 5,
                             value=30, unit="mm")

        # One rebuild commits the dimension, the second applies the value.
        self.assertEqual(2, len(automation.document.rebuild_calls))

    def test_the_input_dialog_preference_is_disabled_then_restored(self):
        automation = Automation()

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual([(10, False), (10, True)],
                         automation.app.preference_calls)
        self.assertTrue(automation.app.preferences[10])

    def test_the_input_dialog_preference_is_restored_when_creation_fails(self):
        automation = Automation()
        automation.document.dimension_ok = False

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual([(10, False), (10, True)],
                         automation.app.preference_calls)
        self.assertTrue(automation.app.preferences[10])

    def test_placing_a_dimension_without_a_value_succeeds(self):
        automation = Automation()

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, unit="mm")

        self.assertTrue(result["success"], result["message"])
        self.assertFalse(result["data"]["geometry_changed"])
        self.assertIsNone(result["data"]["value"])
        self.assertEqual(0.0, automation.document
                         .display_dimension.dimension.system_value)
        self.assertEqual(50.0, automation.document.segments[0].length)

    def test_a_driven_dimension_is_reported_precisely(self):
        automation = Automation()
        automation.document.driven_dimension = True

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual("DIMENSION_VALUE_REJECTED", result["data"]["code"])
        self.assertEqual("driven_dimension",
                         result["data"]["set_value_status"])

    def test_a_leftover_running_command_is_never_success(self):
        automation = Automation()
        automation.app.name = "Dimension"
        automation.app.command_id = 17

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual("DIMENSION_NOT_COMMITTED", result["data"]["code"])
        self.assertEqual("Dimension", result["data"]["running_command"])

    def test_the_stale_edit_sketch_report_is_not_a_failure(self):
        # SolidWorks reports the just-closed sketch as a running "Edit Sketch"
        # command; that is not a dialog waiting for the user.
        automation = Automation()
        automation.app.name = "Edit Sketch"
        automation.app.command_id = 17

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertTrue(result["success"], result["message"])

    def test_a_dimension_that_solidworks_does_not_create_fails(self):
        automation = Automation()
        automation.document.dimension_ok = False

        result = add_sketch_dimension(automation, "Sketch1", ["Line1"],
                                      30, 5, value=30, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual("DIMENSION_FAILED", result["data"]["code"])

    def test_validation_happens_before_com(self):
        cases = (
            {"entities": ["Line1"], "x": 30, "y": 5, "value": 0},
            {"entities": ["Line1"], "x": 30, "y": 5, "value": -1},
            {"entities": ["Line1"], "x": "a", "y": 5},
            {"entities": ["Line1", "Line2", "Arc1"], "x": 30, "y": 5},
            {"entities": ["Line1", "Line1"], "x": 30, "y": 5},
            {"entities": [], "x": 30, "y": 5},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                automation = Automation()

                result = add_sketch_dimension(automation, "Sketch1",
                                              **arguments)

                self.assertFalse(result["success"])
                self.assertEqual(0, automation.active_doc_calls)
                self.assertEqual([], automation.document.dimension_calls)

    def test_an_unknown_sketch_fails_without_touching_the_model(self):
        automation = Automation()

        result = add_sketch_dimension(automation, "Nope", ["Line1"], 30, 5,
                                      value=30, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual([], automation.document.dimension_calls)


if __name__ == "__main__":
    unittest.main()
