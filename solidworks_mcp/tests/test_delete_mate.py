import unittest
from types import SimpleNamespace
from unittest.mock import patch
from solidworks_mcp.tools import assembly


def _sw():
    return SimpleNamespace(_result=lambda ok, msg, error=None, data=None: {'success': ok, 'msg': msg, 'data': data})


class Mate:
    def __init__(self, name, kind):
        self.Name = name
        self.kind = kind

    def GetTypeName2(self):
        return self.kind


class DeleteMateTests(unittest.TestCase):
    def case(self, noop=False, selectable=True):
        mates = {'Coincident1': Mate('Coincident1', 'MateCoincident'),
                 'Distance1': Mate('Distance1', 'MateDistanceDim')}
        selected = []

        class FakeExtension:
            def SelectByID2(self, name, kind, *rest):
                if kind == 'MATE' and name in mates and selectable:
                    selected.append(name)
                    return True
                return False

            def DeleteSelection2(self, options):
                if not noop:
                    for name in selected:
                        mates.pop(name, None)
                return True

        class Document:
            Extension = FakeExtension()

            def ClearSelection2(self, *a): pass

            def FeatureByName(self, name): return mates.get(name)

        return mates, Document(), _sw()

    def run_tool(self, doc, sw, name, kind):
        with patch.object(assembly, '_require_assembly', return_value=(doc, None)):
            return assembly.delete_mate(sw, name, kind)

    def test_deletes_only_the_named_mate(self):
        mates, doc, sw = self.case()
        r = self.run_tool(doc, sw, 'Coincident1', 'MateCoincident')
        self.assertTrue(r['success'], r)
        self.assertEqual(list(mates), ['Distance1'])

    def test_refuses_mate_group_and_reference_features(self):
        mates, doc, sw = self.case()
        mates['Mates'] = Mate('Mates', 'MateGroup')
        mates['Ref'] = Mate('Ref', 'MateReference')
        for name, kind in [('Mates', 'MateGroup'), ('Ref', 'MateReference')]:
            r = self.run_tool(doc, sw, name, kind)
            self.assertFalse(r['success'])
            self.assertIn(name, mates)

    def test_fails_when_mate_still_present(self):
        mates, doc, sw = self.case(noop=True)
        r = self.run_tool(doc, sw, 'Coincident1', 'MateCoincident')
        self.assertFalse(r['success'])
        self.assertTrue(r['data']['document_may_be_modified'])

    def test_rejects_wrong_type_unknown_name_and_non_mate_without_modifying(self):
        for name, kind in [('Coincident1', 'MateDistanceDim'), ('Nope', 'MateCoincident'), ('Coincident1', 'Boss')]:
            mates, doc, sw = self.case()
            r = self.run_tool(doc, sw, name, kind)
            self.assertFalse(r['success'])
            self.assertEqual(len(mates), 2)
            self.assertFalse(r['data']['document_may_be_modified'])

    def test_selection_failure_does_not_delete(self):
        mates, doc, sw = self.case(selectable=False)
        r = self.run_tool(doc, sw, 'Coincident1', 'MateCoincident')
        self.assertFalse(r['success'])
        self.assertEqual(len(mates), 2)


if __name__ == '__main__':
    unittest.main()
