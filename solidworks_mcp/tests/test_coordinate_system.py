"""Coordinate system from numeric offsets and rotations."""

import math
import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import operation_class_for, registered_tools
from solidworks_mcp.tools.reference_geometry import create_coordinate_system


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))


def _vec(a, v):
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))


def _transpose(a):
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))


def solidworks_transform(dx, dy, dz, use_rotation, ax, ay, az):
    """Reproduce the transform SW reports: M = Rx@Ry@Rz, t = -M^T @ delta."""
    rotation = _mul(_mul(_rx(ax if use_rotation else 0.0), _ry(ay if use_rotation else 0.0)),
                    _rz(az if use_rotation else 0.0))
    translation = _vec(_transpose(rotation), (-dx, -dy, -dz))
    return tuple(rotation[0]) + tuple(rotation[1]) + tuple(rotation[2]) \
        + translation + (1.0, 0.0, 0.0, 0.0)


class Feature:
    def __init__(self, name, type_name="CoordSys", transform=None):
        self.Name = name
        self.type_name = type_name
        self.transform = transform
        self.next = None

    def GetTypeName2(self):
        return self.type_name

    def GetNextFeature(self):
        return self.next


class FeatureManager:
    def __init__(self, document, create=True):
        self.document = document
        self.create = create
        self.calls = []

    def CreateCoordinateSystemUsingNumericalValues(
            self, use_location, dx, dy, dz, use_rotation, ax, ay, az):
        self.calls.append((use_location, dx, dy, dz, use_rotation, ax, ay, az))
        if not self.create:
            return None
        name = f"Coordinate System{len(self.calls)}"
        self.document.add_feature(Feature(
            name, "CoordSys", solidworks_transform(dx, dy, dz, use_rotation, ax, ay, az)))
        return self.document.feature_named(name)


class Document:
    def __init__(self, doc_type=1, create=True, transform_available=True,
                 existing_names=()):
        self.doc_type = doc_type
        self.transform_available = transform_available
        self.head = None
        self.clear_calls = []
        for name in existing_names:
            self.add_feature(Feature(name, "CoordSys", (1, 0, 0, 0, 1, 0, 0, 0, 1,
                                                        0, 0, 0, 1, 0, 0, 0)))
        self.FeatureManager = FeatureManager(self, create)

    def GetType(self):
        return self.doc_type

    def add_feature(self, feature):
        feature.next = self.head
        self.head = feature

    def feature_named(self, name):
        node = self.head
        while node is not None:
            if node.Name == name:
                return node
            node = node.next
        return None

    def FirstFeature(self):
        return self.head

    def ClearSelection2(self, clear_all):
        self.clear_calls.append(clear_all)
        return True

    def GetCoordinateSystemXformByName(self, name):
        feature = self.feature_named(name)
        if feature is None or not self.transform_available:
            return None
        return feature.transform


class Units:
    FACTORS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "inch": 0.0254}

    def to_meters(self, value, unit):
        return value * self.FACTORS[unit]


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


class CoordinateSystemRegistrationTests(unittest.TestCase):
    def test_coordinate_system_is_a_bounded_mutation_tool(self):
        tools = {item.name: item for item in registered_tools()}

        self.assertIn("create_coordinate_system", tools)
        self.assertIs(OperationClass.MUTATE,
                      operation_class_for("create_coordinate_system"))
        schema = tools["create_coordinate_system"].inputSchema
        self.assertEqual(0, schema["properties"]["x_offset"]["default"])
        self.assertEqual("mm", schema["properties"]["unit"]["default"])
        self.assertEqual("deg", schema["properties"]["angle_unit"]["default"])


class CoordinateSystemBehaviorTests(unittest.TestCase):
    def test_translation_only_places_origin_without_rotation(self):
        automation = Automation()

        result = create_coordinate_system(automation, x_offset=25, y_offset=-4,
                                          z_offset=2, unit="mm")

        self.assertTrue(result["success"], result["message"])
        call = automation.document.FeatureManager.calls[0]
        self.assertEqual((True, 0.025, -0.004, 0.002, False, 0.0, 0.0, 0.0), call)
        self.assertEqual([25.0, -4.0, 2.0], result["data"]["origin"])
        self.assertEqual([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                         result["data"]["axes"])

    def test_rotation_pre_rotates_delta_so_origin_lands_where_requested(self):
        automation = Automation()

        result = create_coordinate_system(automation, x_offset=10, unit="mm",
                                          rotate_z=90)

        self.assertTrue(result["success"], result["message"])
        call = automation.document.FeatureManager.calls[0]
        self.assertTrue(call[4])
        self.assertAlmostEqual(-0.01, call[1], places=12)
        self.assertAlmostEqual(0.0, call[2], places=12)
        self.assertAlmostEqual(0.0, call[3], places=12)
        self.assertAlmostEqual(math.pi / 2, call[7], places=12)
        self.assertAlmostEqual(10.0, result["data"]["origin"][0], places=9)
        self.assertAlmostEqual(0.0, result["data"]["origin"][1], places=9)
        axes = result["data"]["axes"]
        self.assertAlmostEqual(0.0, axes[0][0], places=9)
        self.assertAlmostEqual(-1.0, axes[0][1], places=9)
        self.assertAlmostEqual(1.0, axes[1][0], places=9)

    def test_combined_xyz_rotation_pre_rotates_delta_by_m_squared(self):
        automation = Automation()
        offsets = (7.0, -3.0, 11.0)
        angles = (20.0, -35.0, 50.0)

        result = create_coordinate_system(
            automation, x_offset=offsets[0], y_offset=offsets[1],
            z_offset=offsets[2], unit="mm",
            rotate_x=angles[0], rotate_y=angles[1], rotate_z=angles[2])

        self.assertTrue(result["success"], result["message"])
        rad = tuple(math.radians(value) for value in angles)
        expected = _mul(_mul(_rx(rad[0]), _ry(rad[1])), _rz(rad[2]))
        for row, expected_row in zip(result["data"]["axes"], expected):
            for value, expected_value in zip(row, expected_row):
                self.assertAlmostEqual(expected_value, value, places=9)
        for value, offset in zip(result["data"]["origin"], offsets):
            self.assertAlmostEqual(offset, value, places=9)
        # SW reads DeltaX/Y/Z in the rotated frame, so the call must pass M^2 @ O.
        call = automation.document.FeatureManager.calls[0]
        delta = _vec(_mul(expected, expected), tuple(value / 1000.0 for value in offsets))
        for got, want in zip(call[1:4], delta):
            self.assertAlmostEqual(want, got, places=12)

    def test_radian_angles_are_passed_through(self):
        automation = Automation()

        result = create_coordinate_system(automation, rotate_y=math.pi / 3,
                                          angle_unit="rad")

        self.assertTrue(result["success"], result["message"])
        self.assertAlmostEqual(math.pi / 3,
                               automation.document.FeatureManager.calls[0][6], places=12)

    def test_named_feature_is_renamed_and_read_back_by_name(self):
        automation = Automation()

        result = create_coordinate_system(automation, x_offset=5, name="MCP_Frame")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual("MCP_Frame", result["data"]["feature_name"])
        self.assertIsNotNone(automation.document.feature_named("MCP_Frame"))

    def test_invalid_input_is_rejected_before_com(self):
        for arguments in (
            {"x_offset": float("nan")},
            {"x_offset": float("inf")},
            {"rotate_x": float("nan")},
            {"angle_unit": "gradians"},
            {"name": "   "},
        ):
            automation = Automation()
            result = create_coordinate_system(automation, **arguments)
            self.assertFalse(result["success"], arguments)
            self.assertEqual("VALIDATION_FAILED", result["data"]["code"])
            self.assertEqual(0, automation.active_doc_calls, arguments)

    def test_duplicate_name_is_rejected_before_creation(self):
        automation = Automation(Document(existing_names=("MCP_Frame",)))

        result = create_coordinate_system(automation, name="MCP_Frame")

        self.assertFalse(result["success"])
        self.assertEqual("NAME_IN_USE", result["data"]["code"])
        self.assertEqual([], automation.document.FeatureManager.calls)

    def test_non_part_document_is_rejected(self):
        automation = Automation(Document(doc_type=2))

        result = create_coordinate_system(automation, x_offset=1)

        self.assertFalse(result["success"])
        self.assertEqual("A coordinate system requires a part.", result["message"])
        self.assertEqual([], automation.document.FeatureManager.calls)

    def test_missing_feature_reports_error(self):
        automation = Automation(Document(create=False))

        result = create_coordinate_system(automation, x_offset=1)

        self.assertFalse(result["success"])
        self.assertIn("did not create", result["message"])

    def test_missing_transform_reports_error(self):
        automation = Automation(Document(transform_available=False))

        result = create_coordinate_system(automation, x_offset=1)

        self.assertFalse(result["success"])
        self.assertIn("transform", result["message"])


if __name__ == "__main__":
    unittest.main()
