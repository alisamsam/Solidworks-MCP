"""RT2 instance read proof on a task-created assembly with a native library flange."""
import hashlib
import os
from pathlib import Path
import unittest
import pythoncom
import win32com.client

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.tests.live._scratch import live_only
from solidworks_mcp.tools.routing_components import get_component_connection_points


@live_only
class LiveRoutingComponentPointTests(unittest.TestCase):
    def test_rotated_library_fitting_matches_native_math_transform_without_mutation(self):
        self.assertEqual("true", os.environ.get("SW_MCP_ROUTING_ENABLED"))
        sw = SolidWorksAutomation()
        self.assertTrue(sw.connect()["success"])
        doc = sw.app.ActiveDoc
        self.assertEqual(2, com(doc, "GetType"))
        self.assertFalse(com(doc, "GetPathName"), "Only a task-created scratch assembly.")
        components = list(com(doc, "GetComponents", True) or [])
        self.assertEqual(1, len(components))
        component = components[0]
        name = com(component, "Name2")
        self.assertEqual("slip on weld flange-1", name)
        source = Path(com(component, "GetPathName"))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        part = com(component, "GetModelDoc2")
        transform = com(component, "Transform2")
        before = (com(doc, "GetTitle"), com(doc, "GetSaveFlag"),
                  com(part, "GetSaveFlag"),
                  com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1),
                  tuple(com(transform, "ArrayData")),
                  com(com(com(part, "Extension"), "CreateMassProperty"), "Volume"))
        result = get_component_connection_points(sw, name)
        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertEqual(1, data["count"])
        self.assertTrue(data["coverage"]["complete"])
        point = data["connection_points"][0]
        utility = com(sw.app, "GetMathUtility")
        xyz = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                      [v/1000 for v in point["position_mm"]])
        def native_method(obj, member, *args):
            ole = obj._oleobj_
            return win32com.client.Dispatch(ole.Invoke(ole.GetIDsOfNames(member), 0,
                                                       pythoncom.DISPATCH_METHOD, True, *args))
        native_point = native_method(native_method(utility, "CreatePoint", xyz), "MultiplyTransform", transform)
        direction = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                            point["direction"])
        native_vector = native_method(native_method(utility, "CreateVector", direction), "MultiplyTransform", transform)
        for actual, expected in zip(point["assembly_position_mm"], com(native_point, "ArrayData")):
            self.assertAlmostEqual(expected*1000, actual, places=6)
        for actual, expected in zip(point["assembly_direction"], com(native_vector, "ArrayData")):
            self.assertAlmostEqual(expected, actual, places=6)
        after = (com(sw.app.ActiveDoc, "GetTitle"), com(doc, "GetSaveFlag"),
                 com(part, "GetSaveFlag"),
                 com(com(doc, "SelectionManager"), "GetSelectedObjectCount2", -1),
                 tuple(com(com(component, "Transform2"), "ArrayData")),
                 com(com(com(part, "Extension"), "CreateMassProperty"), "Volume"))
        self.assertEqual(before, after)
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
