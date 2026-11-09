import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools.assembly import _open_part_for_insert


class ComponentPreloadTests(unittest.TestCase):
    def test_native_part_and_assembly_use_matching_open_document_types(self):
        for filename, document_type in [('plate.SLDPRT', 1), ('module.SLDASM', 2)]:
            with self.subTest(filename=filename):
                app = object()
                with patch('solidworks_mcp.tools.assembly.com', return_value='loaded') as invoke:
                    self.assertEqual(_open_part_for_insert(SimpleNamespace(app=app), filename), 'loaded')
                args = invoke.call_args.args
                self.assertEqual(args[:4], (app, 'OpenDoc6', filename, document_type))
                self.assertEqual(args[4], 3)  # silent and read-only

    def test_drawing_is_not_preloaded_as_a_component(self):
        with patch('solidworks_mcp.tools.assembly.com') as invoke:
            self.assertIsNone(_open_part_for_insert(SimpleNamespace(app=object()), 'layout.SLDDRW'))
        invoke.assert_not_called()


if __name__ == '__main__':
    unittest.main()
