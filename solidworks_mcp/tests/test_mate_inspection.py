import unittest

from solidworks_mcp.constants import SwDocumentTypes, SwMateTypes
from solidworks_mcp.tools.assembly import list_mates


class Dimension:
    SystemValue = 0.025


class DisplayDimension:
    def GetDimension2(self, configuration):
        return Dimension()


class Component:
    def __init__(self, name):
        self.Name2 = name


class MateEntity:
    def __init__(self, component, reference_type, params):
        self.ReferenceComponent = Component(component) if component else None
        self.ReferenceType2 = reference_type
        self.EntityParams = params


class Mate:
    Type = int(SwMateTypes.swMateDISTANCE)
    Alignment = 1
    CanBeFlipped = True
    Flipped = False

    def __init__(self):
        self.entities = [
            MateEntity("Plate-1", 4, (0, 0, 0, 0, 0, 1, 0, 0)),
            MateEntity("Bracket-1", 4, (0, 0, .025, 0, 0, -1, 0, 0)),
        ]

    def GetMateEntityCount(self):
        return len(self.entities)

    def MateEntity(self, index):
        return self.entities[index]

    def DisplayDimension2(self, index):
        return DisplayDimension() if index == 0 else None


class Feature:
    Name = "Distance1"
    GetTypeName2 = "MateDistanceDim"
    GetID = 42
    IsSuppressed = False
    GetNextSubFeature = None

    def __init__(self, mate=None, error_code=0):
        self.mate = mate
        self.error_code = error_code

    def GetSpecificFeature2(self):
        return self.mate

    def GetErrorCode2(self, is_warning):
        is_warning.value = self.error_code != 0
        return self.error_code


class MateGroup:
    GetTypeName2 = "MateGroup"
    Name = "Mates"
    GetNextFeature = None

    def __init__(self, first):
        self.first = first

    def GetFirstSubFeature(self):
        return self.first


class Assembly:
    GetType = int(SwDocumentTypes.swDocASSEMBLY)

    def __init__(self, first):
        self.FirstFeature = MateGroup(first)


class Automation:
    def __init__(self, document):
        self.document = document

    def get_active_doc(self):
        return self.document, None

    def _result(self, success, message, error_code=0, data=None):
        return {"success": success, "message": message, "error_code": int(error_code),
                "data": data or {}}


class MateInspectionTests(unittest.TestCase):
    def test_reports_definition_entities_dimension_and_solver_state(self):
        result = list_mates(Automation(Assembly(Feature(Mate()))))

        self.assertTrue(result["success"])
        mate = result["data"]["mates"][0]
        self.assertEqual(42, mate["feature_id"])
        self.assertEqual("distance", mate["mate_type_name"])
        self.assertEqual({"system_value": 0.025, "unit": "m"}, mate["value"])
        self.assertEqual("Plate-1", mate["entities"][0]["component"])
        self.assertEqual([0, 0, 1], mate["entities"][0]["vector"])
        self.assertEqual("solved", mate["solver_status"]["state"])
        self.assertTrue(result["data"]["coverage"]["complete"])

    def test_preserves_unknown_or_broken_mate_as_unresolved(self):
        result = list_mates(Automation(Assembly(Feature(None, error_code=48))))

        mate = result["data"]["mates"][0]
        self.assertEqual("unavailable", mate["solver_status"]["state"])
        self.assertFalse(result["data"]["coverage"]["complete"])
        self.assertIn("Distance1", result["data"]["coverage"]["unresolved"][0])


if __name__ == "__main__":
    unittest.main()
