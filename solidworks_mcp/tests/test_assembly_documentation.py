import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import MethodType
from .test_manufacturing_package import SW, Document
from solidworks_mcp.tools.assembly_documentation import plan_assembly_documentation


class Component:
    def __init__(self, path, name, cfg='Default', state=2, virtual=False):
        self.path = str(path); self.Name2 = name
        self.ReferencedConfiguration = cfg; self.state = state; self.IsVirtual = virtual
    def GetPathName(self): return self.path
    def GetSuppression(self): return self.state
    def GetModelDoc2(self): return Document(self.path)


class PlannerTests(unittest.TestCase):
    def test_fingerprint_stable_for_native_traversal_reordering(self):
        self.rows=[Component(self.part,'p-1'),Component(self.part,'p-2'),Component(self.part,'old',state=0)]
        first=self.run_plan();self.assertTrue(first['success'],first)
        self.folder=self.root/'reordered';self.rows.reverse()
        second=self.run_plan();self.assertTrue(second['success'],second)
        self.assertEqual(first['data']['plan_fingerprint'],second['data']['plan_fingerprint'])
    def test_fingerprint_includes_external_master_dependency(self):
        master=self.root/'master.sldprt';master.write_bytes(b'old master')
        self.graph_mock.return_value={self.path:[self.part],self.part:[master],master:[]}
        self.rows=[Component(self.part,'p-1')]
        first=self.run_plan();self.assertTrue(first['success'],first)
        master.write_bytes(b'changed master');self.folder=self.root/'changed-master'
        second=self.run_plan();self.assertTrue(second['success'],second)
        self.assertNotEqual(first['data']['plan_fingerprint'],second['data']['plan_fingerprint'])
    def test_plan_fingerprint_binds_exact_identity_and_quantity(self):
        self.rows=[Component(self.part,'part-1')]
        first=self.run_plan();self.assertTrue(first['success'],first)
        self.folder=self.root/'plan-two';self.rows.append(Component(self.part,'part-2'))
        second=self.run_plan();self.assertTrue(second['success'],second)
        self.assertNotEqual(first['data']['plan_fingerprint'],second['data']['plan_fingerprint'])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'root.sldasm'; self.path.write_bytes(b'assembly')
        self.part = self.root / 'part.sldprt'; self.part.write_bytes(b'part')
        self.sw = SW(self.root, self.path); self.sw.doc.doc_type = 2
        self.sw.app=object()
        graph_patch=patch('solidworks_mcp.tools.assembly_documentation._graph',return_value={self.path:[self.part],self.part:[]})
        self.graph_mock=graph_patch.start();self.addCleanup(graph_patch.stop)
        self.rows = []
        self.components_mock = Mock(side_effect=lambda top: self.rows)
        self.sw.doc.GetComponents = MethodType(lambda doc, top: self.components_mock(top), self.sw.doc)
        self.stamp_mock = Mock(return_value=7)
        self.sw.doc.GetUpdateStamp = MethodType(lambda doc: self.stamp_mock(), self.sw.doc)
        self.folder = self.root / 'plan'
    def run_plan(self):
        return plan_assembly_documentation(self.sw, str(self.path), 'Default', str(self.folder))
    def test_quantities_exact_configuration_and_physical_occurrences(self):
        self.rows = [Component(self.part, 'sub-1/p-1'), Component(self.part, 'sub-2/p-1', state=3),
                     Component(self.part, 'p-3', cfg='Other'), Component(self.part, 'old-1', state=0)]
        result = self.run_plan(); self.assertTrue(result['success'], result)
        data = json.loads((self.folder/'00_Pregled/package-plan.json').read_text(encoding='utf-8'))
        self.assertEqual([2, 1], [r['quantity'] for r in data['items']])
        self.assertEqual(1, len(data['suppressed_occurrences']))
        self.assertEqual(3, data['active_occurrence_count'])
        self.assertFalse(data['exports_created']); self.assertFalse(data['manufacturing_ready'])
        self.assertEqual(3, len(list(self.folder.rglob('*.*'))))
        self.assertEqual(b'assembly', self.path.read_bytes())
    def test_unresolved_and_virtual_are_visible(self):
        self.rows = [Component(self.part, 'light', state=1), Component(self.part, 'virtual', virtual=True)]
        result = self.run_plan(); self.assertTrue(result['success'], result)
        self.assertFalse(result['data']['inventory_complete'])
        self.assertEqual(2, len(result['data']['unresolved_occurrences']))
    def test_empty_inventory_is_not_silently_complete(self):
        self.components_mock.return_value = None; self.components_mock.side_effect = None
        result = self.run_plan()
        self.assertFalse(result['success']); self.assertFalse(self.folder.exists())
    def test_refuses_wrong_configuration_without_writes(self):
        self.sw.doc.ConfigurationManager.ActiveConfiguration.Name = 'Other'
        self.addCleanup(setattr, self.sw.doc.ConfigurationManager.ActiveConfiguration, 'Name', 'Default')
        self.assertFalse(self.run_plan()['success']); self.assertFalse(self.folder.exists())
    def test_existing_folder_refused_before_native_read(self):
        self.folder.mkdir(); self.assertFalse(self.run_plan()['success'])
        self.components_mock.assert_not_called()
    def test_source_change_refuses_success_before_writing(self):
        self.stamp_mock.side_effect = [7, 8]
        self.assertFalse(self.run_plan()['success']); self.assertFalse(self.folder.exists())
    def test_dirty_document_refused(self):
        self.sw.doc.GetSaveFlag = MethodType(lambda doc: True, self.sw.doc)
        self.assertFalse(self.run_plan()['success']); self.assertFalse(self.folder.exists())
    def test_no_geometry_or_body_manufacturing_claims(self):
        self.rows = [Component(self.part, 'plate-1')]
        result = self.run_plan(); self.assertTrue(result['success'], result)
        row = result['data']['items'][0]
        self.assertEqual('needs_review', row['make_buy'])
        self.assertEqual('not_inspected', row['body_classification'])
        self.assertFalse(any(a['path'].endswith('.dxf') for a in row['proposed_artifacts']))
        self.assertTrue(any(a['path'].endswith('.step') for a in row['proposed_artifacts']))
    def test_dirty_loaded_child_rejects_saved_state_plan(self):
        child = Component(self.part, 'child')
        child.GetModelDoc2 = MethodType(lambda obj: type('Dirty', (), {'GetSaveFlag': True})(), child)
        self.rows = [child]
        self.assertFalse(self.run_plan()['success']); self.assertFalse(self.folder.exists())
    def test_suppressed_parent_excludes_resolved_children(self):
        self.rows = [Component(self.part, 'sub', state=0), Component(self.part, 'sub/child')]
        result = self.run_plan(); self.assertTrue(result['success'], result)
        self.assertEqual(0, result['data']['active_occurrence_count'])
        self.assertEqual(2, len(result['data']['suppressed_occurrences']))
    def test_unreadable_parent_excludes_descendants(self):
        parent = Component(self.part, 'sub')
        def broken(obj): raise ValueError('unreadable state')
        parent.GetSuppression = MethodType(broken, parent)
        self.rows = [parent, Component(self.part, 'sub/child')]
        result = self.run_plan(); self.assertTrue(result['success'], result)
        self.assertEqual(0, result['data']['active_occurrence_count'])
        self.assertEqual(2, len(result['data']['unresolved_occurrences']))
    def test_partial_write_reports_failed_package(self):
        with patch('solidworks_mcp.tools.assembly_documentation.csv.writer', side_effect=OSError('disk full')):
            result = self.run_plan()
        self.assertFalse(result['success'])
        self.assertEqual('failed', result['data']['status'])
        self.assertTrue(result['data']['partial_output_paths'])
        data = json.loads((self.folder/'00_Pregled/package-plan.json').read_text(encoding='utf-8'))
        self.assertEqual('failed', data['status'])


if __name__ == '__main__': unittest.main()
