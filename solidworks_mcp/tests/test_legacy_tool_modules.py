import unittest

from solidworks_mcp.core.policy import OperationClass
from solidworks_mcp.registry import _TOOLS, _load, operation_class_for, tool_module_for

READ, SESSION, MUTATE = OperationClass.READ, OperationClass.SESSION, OperationClass.MUTATE


class MovedToolTests(unittest.TestCase):
    def assertMoved(self, module, expected):
        _load()
        for name, (operation_class, postflight) in expected.items():
            with self.subTest(tool=name):
                self.assertEqual(f"solidworks_mcp.tools.{module}", tool_module_for(name))
                self.assertIs(operation_class, operation_class_for(name))
                self.assertEqual(postflight, _TOOLS[name]["postflight"])

    def test_features_basic(self):
        self.assertMoved("features_basic", {
            "extrude_sketch": (MUTATE, None), "cut_extrude": (MUTATE, None),
            "revolve_sketch": (MUTATE, None), "fillet_edges": (MUTATE, None),
            "chamfer_edges": (MUTATE, None), "list_features": (READ, None),
        })


    def test_sketch_basic(self):
        names = ("create_sketch", "create_sketch_on_face", "draw_line", "draw_circle",
                 "draw_rectangle", "draw_arc", "draw_polygon", "draw_spline",
                 "draw_arc_3point", "draw_slot", "close_sketch")
        expected = {name: (MUTATE, None) for name in names}
        expected["get_sketch_status"] = (READ, None)
        self.assertMoved("sketch_basic", expected)

    def test_documents(self):
        self.assertMoved("documents", {
            "create_new_part": (SESSION, "bind"), "create_new_assembly": (SESSION, "bind"),
            "open_document": (SESSION, "bind"), "close_document": (MUTATE, "none"),
            "get_document_info": (READ, None), "list_open_documents": (READ, None),
        })

    def test_connection(self):
        self.assertMoved("connection", {
            "get_modeling_guide": (READ, None), "get_solidworks_info": (READ, None),
            "get_capabilities": (READ, None), "connect_solidworks": (SESSION, None),
            "set_units": (SESSION, None), "bind_active_document": (SESSION, "bound"),
            "execute_python": (OperationClass.RAW_EXECUTION, None),
        })


if __name__ == "__main__":
    unittest.main()
