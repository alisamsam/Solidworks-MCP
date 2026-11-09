import unittest

from solidworks_mcp.core.contracts import DocumentRef
from solidworks_mcp.core.session import DocumentSession
from solidworks_mcp.tools.inspection import inspect_document


class Component:
    def __init__(self, name, path, configuration):
        self.Name2 = name
        self.GetPathName = path
        self.ReferencedConfiguration = configuration
        self.Transform2 = type("Transform", (), {"ArrayData": list(range(16))})()
        self.IsFixed = False
        self.GetSuppression = 2
        self.IsVirtual = False
        self.GetChildren = []


class Assembly:
    GetType = 2

    def __init__(self, components):
        self.GetComponents = components


class Automation:
    def __init__(self, assembly):
        self.assembly = assembly
        self._document_session = DocumentSession()
        self.target = DocumentRef(
            "root-doc", "C:/project/top.SLDASM", "assembly", "Default", "mcp:0"
        )

    def get_active_doc(self):
        return self.assembly, None

    def capture_active_document_ref(self):
        return self.target, None

    def _result(self, success, message, error_code=0, data=None):
        return {
            "success": success,
            "message": message,
            "error_code": int(error_code),
            "error_name": "test",
            "data": data or {},
        }


class InspectionGraphTests(unittest.TestCase):
    def test_same_document_in_two_configurations_keeps_two_instances(self):
        assembly = Assembly((
            Component("Frame-1", "C:/project/frame.SLDPRT", "Default"),
            Component("Frame-2", "C:/project/frame.SLDPRT", "Long"),
        ))
        automation = Automation(assembly)

        first = inspect_document(
            automation, sections=["summary", "assembly", "dependencies"], page_size=1
        )
        cursor = first["data"]["snapshot"]["coverage"]["next_cursor"]
        second = inspect_document(automation, cursor=cursor, page_size=1)

        self.assertTrue(first["success"])
        self.assertEqual(2, len(first["data"]["snapshot"]["documents"]))
        self.assertEqual("Default", first["data"]["snapshot"]["instances"][0]["configuration"])
        self.assertEqual("Long", second["data"]["snapshot"]["instances"][0]["configuration"])
        self.assertEqual(
            first["data"]["snapshot"]["instances"][0]["document_id"],
            second["data"]["snapshot"]["instances"][0]["document_id"],
        )

    def test_stale_cursor_is_returned_as_structured_error(self):
        automation = Automation(Assembly((
            Component("Frame-1", "C:/project/frame.SLDPRT", "Default"),
            Component("Frame-2", "C:/project/frame.SLDPRT", "Default"),
        )))
        first = inspect_document(automation, sections=["assembly"], page_size=1)
        cursor = first["data"]["snapshot"]["coverage"]["next_cursor"]
        automation.target = DocumentRef(
            "root-doc", "C:/project/top.SLDASM", "assembly", "Default", "mcp:1"
        )

        result = inspect_document(automation, cursor=cursor, page_size=1)

        self.assertFalse(result["success"])
        self.assertEqual("STALE_REFERENCE", result["data"]["code"])

    def test_feature_and_parameter_sections_are_exposed_as_sourced_observations(self):
        feature = type("Feature", (), {
            "Name": "Imported1",
            "GetTypeName2": "UnknownFeature",
            "IsSuppressed": False,
            "GetFirstSubFeature": None,
            "GetNextFeature": None,
            "GetFirstDisplayDimension": None,
        })()
        document = type("Part", (), {"FirstFeature": feature, "GetEquationMgr": None})()
        automation = Automation(document)
        automation.target = DocumentRef("part-1", None, "part", "Default", "mcp:0")

        result = inspect_document(automation, sections=["features", "parameters"])

        observations = result["data"]["snapshot"]["observations"]
        self.assertEqual("features", observations[0]["section"])
        self.assertEqual("UnknownFeature", observations[0]["value"][0]["type"])
        self.assertEqual("parameters", observations[1]["section"])
        self.assertEqual([], observations[1]["value"]["equations"])

    def test_document_dependencies_add_graph_edges_and_keep_missing_references(self):
        extension = type("Extension", (), {
            "GetDependencies": lambda self, *args: (
                "DrawingView", r"C:\project\model.SLDPRT", "MissingView", ""
            ),
        })()
        document = type("Drawing", (), {"Extension": extension})()
        automation = Automation(document)
        automation.target = DocumentRef(
            "drawing-1", r"C:\project\sheet.SLDDRW", "drawing", "Default", "mcp:0"
        )

        result = inspect_document(automation, sections=["dependencies"])

        snapshot = result["data"]["snapshot"]
        self.assertEqual(2, len(snapshot["documents"]))
        self.assertEqual("document_reference", snapshot["dependency_edges"][0]["kind"])
        self.assertEqual("known", snapshot["dependency_edges"][0]["state"])
        self.assertIsNone(snapshot["dependency_edges"][1]["target"])
        self.assertEqual("unresolved", snapshot["dependency_edges"][1]["state"])
        self.assertFalse(snapshot["coverage"]["complete"])
        self.assertIn("MissingView", snapshot["coverage"]["unresolved"][0])

    def test_mates_section_is_exposed_as_sourced_observation(self):
        mate_group = type("MateGroup", (), {
            "GetTypeName2": "MateGroup",
            "GetFirstSubFeature": None,
            "GetNextFeature": None,
        })()
        assembly = Assembly(())
        assembly.FirstFeature = mate_group
        automation = Automation(assembly)

        result = inspect_document(automation, sections=["mates"])

        snapshot = result["data"]["snapshot"]
        self.assertEqual("mates", snapshot["observations"][0]["section"])
        self.assertEqual("SolidWorks IMate2", snapshot["observations"][0]["source"])
        self.assertEqual([], snapshot["observations"][0]["value"])


if __name__ == "__main__":
    unittest.main()
