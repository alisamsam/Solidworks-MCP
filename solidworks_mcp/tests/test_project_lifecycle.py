"""Lifecycle contracts exercised with real files and a closed-file dependency fake."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import patch

from solidworks_mcp.tests.test_project_copy import Automation
from solidworks_mcp.tools import project_lifecycle as lifecycle
from solidworks_mcp.tools.project_copy import MANIFEST, copy_project


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sw = Automation(self.root)
        self.part = self.file('original/part.SLDPRT', [])
        self.source = self.file('original/main.SLDASM', [self.part])
        self.dest = self.root / 'output' / 'copy'

    def file(self, name, refs):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'references': [str(p) for p in refs]}))
        return path

    def copy(self, folder=None):
        result = copy_project(self.sw, str(self.source), str(folder or self.dest), include_drawings=False)
        self.assertTrue(result['success'], result)
        return result['data']

    def test_compare_maps_source_identity_and_reports_only_saved_bytes(self):
        a = self.copy()
        bdir = self.root / 'output' / 'second'
        b = self.copy(bdir)
        row = next(x for x in b['files'] if x['source'] == str(self.part))
        Path(row['copy']).write_text('{"references": [], "dimension": 100}')
        result = lifecycle.compare_project_versions(self.sw, str(self.dest), str(bdir))
        self.assertTrue(result['success'], result)
        part = next(x for x in result['data']['documents'] if x['source_identity'] == str(self.part))
        self.assertEqual('changed', part['saved_bytes'])
        self.assertFalse(result['data']['semantic_comparison'])
        self.assertEqual(2, len(result['data']['documents']))

    def test_compare_rejects_manifest_escape(self):
        self.copy()
        marker = self.dest / MANIFEST
        data = json.loads(marker.read_text())
        data['files'][0]['copy'] = str(self.source)
        marker.write_text(json.dumps(data))
        self.assertFalse(lifecycle.compare_project_versions(self.sw, str(self.dest), str(self.dest))['success'])

    def test_checkpoint_is_isolated_and_existing_destination_rejected(self):
        result = lifecycle.checkpoint_project(self.sw, str(self.source), str(self.dest), include_drawings=False)
        self.assertTrue(result['success'], result)
        self.assertFalse(lifecycle.checkpoint_project(self.sw, str(self.source), str(self.dest), include_drawings=False)['success'])
        self.assertEqual(str(self.source), result['data']['source'])

    def test_rename_new_copy_relinks_and_preserves_sources(self):
        before = {p: p.read_bytes() for p in (self.source, self.part)}
        result = lifecycle.rename_project_documents(self.sw, str(self.source), str(self.dest),
            {str(self.source): 'renamed_main.SLDASM', str(self.part): 'renamed_part.SLDPRT'}, include_drawings=False)
        self.assertTrue(result['success'], result)
        self.assertEqual(str(self.dest / 'renamed_main.SLDASM'), result['data']['root_document'])
        self.assertEqual([str(self.dest / 'renamed_part.SLDPRT')], self.sw.app.graph[str(self.dest / 'renamed_main.SLDASM')])
        for p, content in before.items(): self.assertEqual(content, p.read_bytes())
        manifest = json.loads((self.dest / MANIFEST).read_text())
        self.assertEqual('verified', manifest['status'])

    def test_rename_collision_traversal_unknown_and_extension_rejected_before_copy(self):
        bad = [{str(self.source): '../escape.SLDASM'}, {str(self.source): 'a.SLDPRT'},
            {str(self.root / 'unknown.SLDPRT'): 'a.SLDPRT'},
            {str(self.source): 'same.SLDASM', str(self.part): 'SAME.SLDASM'},
            {str(self.source): 'CON.SLDASM'}, {str(self.source): 'main.SLDASM'}]
        for mapping in bad:
            with self.subTest(mapping=mapping):
                self.assertFalse(lifecycle.rename_project_documents(self.sw, str(self.source), str(self.dest), mapping, include_drawings=False)['success'])
                self.assertFalse(self.dest.exists())

    def test_failed_rename_relink_invalidates_manifest_with_partial_folder(self):
        # Copy phase succeeds; failure occurs on the rename-specific relink.
        original = self.sw.app.ReplaceReferencedDocument
        def replacement(path, old, new):
            if Path(new).name == 'renamed_part.SLDPRT': return False
            return original(path, old, new)
        self.sw.app.ReplaceReferencedDocument = MethodType(lambda app, *args: replacement(*args), self.sw.app)
        result = lifecycle.rename_project_documents(self.sw, str(self.source), str(self.dest),
            {str(self.part): 'renamed_part.SLDPRT'}, include_drawings=False)
        self.assertFalse(result['success'])
        self.assertEqual(str(self.dest), result['data']['partial_folder'])
        self.assertEqual('failed', json.loads((self.dest / MANIFEST).read_text())['status'])

    def test_independence_rejects_nested_stale_or_wrong_owner_before_copy(self):
        copied = self.copy()
        path = copied['root_document']
        component = SimpleNamespace(Name2='part-1', GetPathName=str(self.part), ReferencedConfiguration='Default')
        doc = SimpleNamespace(GetPathName=path, GetType=2, GetComponents=MethodType(lambda self, immediate: [component], self))
        self.sw.get_active_doc = lambda: (doc, None)
        new = self.root / 'output' / 'independent'
        for name, expected, owner in [('sub/part-1', str(self.part), path), ('part-1', path, path), ('part-1', str(self.part), str(self.source))]:
            with patch.object(lifecycle, 'require_editable_copy', return_value=None):
                result = lifecycle.make_component_independent(self.sw, name, expected, owner, 'Default', str(new))
            self.assertFalse(result['success'])
            self.assertFalse(new.exists())

    def test_independence_reuses_verified_copy_and_replaces_one_occurrence(self):
        copied = self.copy()
        path = copied['root_document']
        part_path = next(x['copy'] for x in copied['files'] if x['source'] == str(self.part))
        component = SimpleNamespace(Name2='part-1', GetPathName=part_path, ReferencedConfiguration='Default')
        doc = SimpleNamespace(GetPathName=path, GetType=2, GetComponents=MethodType(lambda self, immediate: [component], self))
        self.sw.get_active_doc = lambda: (doc, None)
        new = self.root / 'output' / 'independent'
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'replace_component', return_value={'success': True, 'data': {'saved': False}}) as replace:
            result = lifecycle.make_component_independent(self.sw, 'part-1', part_path, path, 'Default', str(new))
        self.assertTrue(result['success'], result)
        self.assertTrue(Path(result['data']['replacement_path']).is_file())
        self.assertFalse(replace.call_args.kwargs['all_instances'])
        self.assertFalse(result['data']['saved'])

    def test_presentation_rejects_wrong_activated_path_before_view_or_capture(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        self.sw.app.open[wanted] = doc
        wrong = SimpleNamespace(GetPathName=str(self.source))
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: wrong, self.sw.app)
        self.sw.app.ActiveDoc = wrong
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view') as view:
            result = lifecycle.present_result(self.sw, wanted)
        self.assertFalse(result['success'])
        view.assert_not_called()

    def test_presentation_capture_failure_keeps_honest_open_state(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        self.sw.app.open[wanted] = doc
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: doc, self.sw.app)
        self.sw.app.ActiveDoc = doc
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view', return_value={'success': True}), patch.object(lifecycle, 'zoom_fit', return_value={'success': True}), patch.object(lifecycle, 'capture_view', return_value={'success': False, 'message': 'hidden viewport'}):
            result = lifecycle.present_result(self.sw, wanted, capture=True)
        self.assertFalse(result['success'])
        self.assertTrue(result['data']['document_activated'])
        self.assertFalse(result['data']['saved'])

    def test_checkpoint_rejects_unapproved_and_source_child_destinations(self):
        for folder in [self.root / 'outside', self.source.parent / 'child']:
            result = lifecycle.checkpoint_project(self.sw, str(self.source), str(folder), include_drawings=False)
            self.assertFalse(result['success'])
            self.assertFalse(folder.exists())

    def test_compare_checkpoint_follows_original_lineage(self):
        first = self.copy()
        second = self.root / 'output' / 'checkpoint'
        result = lifecycle.checkpoint_project(self.sw, first['root_document'], str(second), include_drawings=False)
        self.assertTrue(result['success'], result)
        result = lifecycle.compare_project_versions(self.sw, str(self.dest), str(second))
        self.assertTrue(result['success'], result)
        self.assertEqual({str(self.source), str(self.part)}, {r['source_identity'] for r in result['data']['documents']})

    def test_presentation_silently_opens_exact_path_and_returns_capture(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        calls = []
        def open_doc(app, path, kind, options, config, errors, warnings):
            calls.append((path, kind, options))
            return doc
        self.sw.app.OpenDoc6 = MethodType(open_doc, self.sw.app)
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: doc, self.sw.app)
        self.sw.app.ActiveDoc = doc
        artifact = {'artifact': {'path': str(self.root / 'output' / 'view.png')}}
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view', return_value={'success': True}), patch.object(lifecycle, 'zoom_fit', return_value={'success': True}), patch.object(lifecycle, 'capture_view', return_value={'success': True, 'data': artifact}):
            result = lifecycle.present_result(self.sw, wanted, capture=True)
        self.assertTrue(result['success'], result)
        self.assertEqual([(wanted, 2, 1)], calls)
        self.assertEqual(artifact, result['data']['capture'])

    def test_independence_exception_after_attempt_reports_possible_modification(self):
        copied = self.copy()
        path = copied['root_document']
        part_path = next(x['copy'] for x in copied['files'] if x['source'] == str(self.part))
        component = SimpleNamespace(Name2='part-1', GetPathName=part_path, ReferencedConfiguration='Default')
        doc = SimpleNamespace(GetPathName=path, GetType=2, GetComponents=MethodType(lambda self, immediate: [component], self))
        self.sw.get_active_doc = lambda: (doc, None)
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'replace_component', side_effect=RuntimeError('COM lost')):
            result = lifecycle.make_component_independent(self.sw, 'part-1', part_path, path, 'Default', str(self.root / 'output' / 'independent'))
        self.assertFalse(result['success'])
        self.assertTrue(result['data']['document_may_be_modified'])
        self.assertTrue(Path(result['data']['partial_folder']).is_dir())

    def test_model_comparison_reports_dimensions_material_mass_and_configuration_scope(self):
        self.copy()
        second = self.root / 'output' / 'second'
        self.copy(second)
        left = {'complete': True, 'configuration': 'Default', 'dimensions': {'D1@Sketch': .1},
            'material': 'Steel', 'mass_kg': 1.0, 'configuration_names': ['Default']}
        right = {**left, 'dimensions': {'D1@Sketch': .2}, 'material': 'Aluminum', 'mass_kg': .5}
        with patch.object(lifecycle, '_model_snapshot', side_effect=lambda sw, path: left if path.parent == self.dest else right):
            result = lifecycle.compare_project_versions(self.sw, str(self.dest), str(second), include_model_parameters=True)
        self.assertTrue(result['success'], result)
        changes = result['data']['documents'][0]['model_changes']
        self.assertEqual(['D1@Sketch'], changes['dimensions_changed'])
        self.assertTrue(changes['material_changed'])
        self.assertEqual(-.5, changes['mass_delta_kg'])
        self.assertFalse(result['data']['semantic_comparison'])

    def test_model_snapshot_rejects_dirty_open_copy_before_inspection(self):
        copied = self.copy()
        wanted = copied['root_document']
        self.sw.app.open[wanted] = SimpleNamespace(GetPathName=wanted, GetSaveFlag=True)
        with patch.object(lifecycle, 'require_editable_copy', return_value=None):
            snapshot = lifecycle._model_snapshot(self.sw, Path(wanted))
        self.assertFalse(snapshot['complete'])
        self.assertIn('unsaved', ' '.join(snapshot['limitations']))

    def test_model_snapshot_reads_exact_saved_part_drivers_mass_and_material(self):
        copied = self.copy()
        wanted = next(x['copy'] for x in copied['files'] if x['source'] == str(self.part))
        doc = SimpleNamespace(GetPathName=wanted, GetSaveFlag=False, GetType=1,
            GetMaterialPropertyName2=MethodType(lambda self, config, database: 'Steel', self))
        self.sw.app.open[wanted] = doc
        self.sw.app.GetConfigurationNames = MethodType(lambda *args: ['Default'], self.sw.app)
        parameters = {'success': True, 'data': {'configuration': 'Default', 'dimensions':
            [{'name': 'D1@Sketch@part', 'system_value': .1}], 'equations': [], 'complete': True, 'unresolved': []}}
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'list_model_parameters', return_value=parameters), patch.object(lifecycle, 'get_mass_properties', return_value={'success': True, 'data': {'si': {'mass_kg': 1.2}}}):
            snapshot = lifecycle._model_snapshot(self.sw, Path(wanted))
        self.assertTrue(snapshot['complete'], snapshot)
        self.assertEqual({'d1@sketch': .1}, snapshot['dimensions'])
        self.assertEqual('Steel', snapshot['material'])
        self.assertEqual(1.2, snapshot['mass_kg'])

    def test_activate_copy_for_inspection_does_not_require_view_changes(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        self.sw.app.open[wanted] = doc
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: doc, self.sw.app)
        self.sw.app.ActiveDoc = doc
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view') as view, patch.object(lifecycle, 'zoom_fit') as zoom:
            result = lifecycle.present_result(self.sw, wanted, prepare_view=False)
        self.assertTrue(result['success'], result)
        view.assert_not_called()
        zoom.assert_not_called()
        self.assertFalse(result['data']['view_prepared'])

    def test_present_result_rebinds_exact_target_session(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        self.sw.app.open[wanted] = doc
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: doc, self.sw.app)
        self.sw.app.ActiveDoc = doc
        calls = []
        self.sw.bind_active_document = lambda: calls.append(wanted)
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view', return_value={'success': True}), patch.object(lifecycle, 'zoom_fit', return_value={'success': True}):
            result = lifecycle.present_result(self.sw, wanted)
        self.assertTrue(result['success'], result)
        self.assertEqual([wanted], calls)

    def test_present_result_rechecks_exact_path_after_capture_activation(self):
        copied = self.copy()
        wanted = copied['root_document']
        doc = SimpleNamespace(GetPathName=wanted, GetTitle=Path(wanted).name)
        self.sw.app.open[wanted] = doc
        self.sw.app.ActivateDoc3 = MethodType(lambda *args: doc, self.sw.app)
        self.sw.app.ActiveDoc = doc
        def capture(*args, **kwargs):
            self.sw.app.ActiveDoc = SimpleNamespace(GetPathName=str(self.source))
            return {'success': True, 'data': {'artifact': {'path': 'wrong.png'}}}
        with patch.object(lifecycle, 'require_editable_copy', return_value=None), patch.object(lifecycle, 'set_view', return_value={'success': True}), patch.object(lifecycle, 'zoom_fit', return_value={'success': True}), patch.object(lifecycle, 'capture_view', side_effect=capture):
            result = lifecycle.present_result(self.sw, wanted, capture=True)
        self.assertFalse(result['success'])

if __name__ == '__main__': unittest.main()
