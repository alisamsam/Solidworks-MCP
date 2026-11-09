import json
import tempfile
import unittest
from types import MethodType
from pathlib import Path
from unittest.mock import patch
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.manufacturing_package import build_manufacturing_package, update_drawing_package, _assembly_bom


class Document:
    def __init__(self, path, doc_type=1):
        self.path = str(path); self.doc_type = doc_type
        self.ConfigurationManager = type('Manager', (), {'ActiveConfiguration': type('Config', (), {'Name': 'Default'})()})()
    def GetPathName(self): return self.path
    def GetType(self): return self.doc_type
    def GetSaveFlag(self): return False
    def ForceRebuild3(self, top): return True
    def GetSheetNames(self): return ['Sheet1']


class SW:
    def __init__(self, root, path):
        self._path_policy = PathPolicy([Path(root)])
        self.doc = Document(path)
        self.opened = []
    def get_active_doc(self): return self.doc, None
    def open_document(self, path):
        self.opened.append(path); self.doc = Document(path, 3)
        return {'success': True}
    def save_document(self, path): return {'success': True}
    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, data=data or {})


class ManufacturingTests(unittest.TestCase):
    def test_flat_dxf_option_uses_existing_export_and_verifies_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            def copy(sw, source, destination, **kwargs):
                folder = Path(destination); folder.mkdir()
                copied = folder / 'copied.sldprt'; copied.write_bytes(b'part')
                (folder / '.solidworks-project-copy.json').write_text(json.dumps({
                    'schema_version': 1, 'status': 'verified', 'files': [{'copy': str(copied)}]}))
                return {'success': True}
            def flat(sw, output_path):
                Path(output_path).write_bytes(b'DXF'); return {'success': True}
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None), \
                 patch('solidworks_mcp.tools.manufacturing_package.copy_project', side_effect=copy), \
                 patch('solidworks_mcp.tools.manufacturing_package.get_cut_list', return_value={'success': True, 'data': {'items': []}}), \
                 patch('solidworks_mcp.tools.manufacturing_package.export_flat_pattern', side_effect=flat) as exported:
                result = build_manufacturing_package(sw, str(path), 'Default', str(Path(root) / 'package'), ['flat_dxf'])
            self.assertTrue(result['success'], result)
            exported.assert_called_once()
            artifact = result['data']['artifacts'][-1]
            self.assertEqual('flat_dxf', artifact['kind']); self.assertEqual(3, artifact['size_bytes'])
            self.assertTrue(artifact['sha256'])

    def test_final_progress_is_sent_only_after_final_verification(self):
        from solidworks_mcp.core.progress import progress_scope
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            def copy(sw, source, destination, **kwargs):
                folder = Path(destination); folder.mkdir()
                copied = folder / 'copied.sldprt'; copied.write_bytes(b'part')
                (folder / '.solidworks-project-copy.json').write_text(json.dumps({
                    'schema_version': 1, 'status': 'verified', 'files': [{'copy': str(copied)}]}))
                return {'success': True}
            def flat(sw, output_path):
                Path(output_path).write_bytes(b'DXF'); return {'success': True}
            for exports_ok in (True, False):
                sent = []
                with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None),                      patch('solidworks_mcp.tools.manufacturing_package.copy_project', side_effect=copy),                      patch('solidworks_mcp.tools.manufacturing_package.get_cut_list', return_value={'success': True, 'data': {'items': []}}),                      patch('solidworks_mcp.tools.manufacturing_package.export_flat_pattern',
                           side_effect=flat if exports_ok else (lambda sw, output_path: {'success': False})),                      patch('solidworks_mcp.core.progress.MIN_INTERVAL_S', 0),                      progress_scope(lambda *args: sent.append(args)):
                    package = Path(root) / ('ok' if exports_ok else 'bad')
                    build_manufacturing_package(sw, str(path), 'Default', str(package), ['flat_dxf'])
                with self.subTest(exports_ok=exports_ok):
                    self.assertTrue(sent)
                    if exports_ok:
                        self.assertEqual([3], [total for done, total, _ in sent if done >= total])
                        self.assertEqual('verified', sent[-1][2])
                    else:
                        self.assertFalse([1 for done, total, _ in sent if done >= total])

    def test_flat_dxf_rejected_for_assembly_before_native_copy(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldasm'; path.write_bytes(b'assembly'); sw = SW(root, path); sw.doc.doc_type = 2
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None), \
                 patch('solidworks_mcp.tools.manufacturing_package.copy_project') as copied:
                result = build_manufacturing_package(sw, str(path), 'Default', str(Path(root) / 'package'), ['flat_dxf'])
            self.assertFalse(result['success']); copied.assert_not_called()

    def test_bom_groups_same_file_configuration_and_excludes_suppressed(self):
        class Component:
            def __init__(self, path, config, suppressed=False, virtual=False, state=2):
                self.path=path; self.ReferencedConfiguration=config; self.state=0 if suppressed else state; self.IsVirtual=virtual
                self.Name2='occurrence'
            def GetPathName(self): return self.path
            def GetSuppression(self): return self.state
        class Assembly:
            def GetComponents(self, top_only): return components
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part')
            components = [Component(str(path), 'A'), Component(str(path), 'A'), Component(str(path), 'B'),
                Component(str(path), 'A', suppressed=True), Component('', 'A', virtual=True),
                Component(str(path), 'A', state=1)]
            result = _assembly_bom(Assembly())
            self.assertEqual([2, 1], [row['quantity'] for row in result['items']])
            self.assertEqual(['A', 'B'], [row['configuration'] for row in result['items']])
            self.assertEqual(1, len(result['suppressed_occurrences']))
            self.assertEqual(2, len(result['unresolved_occurrences']))
            self.assertFalse(result['complete'])

    def test_no_policy_or_manifest_denied_before_output(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part')
            sw = SW(root, path)
            r = build_manufacturing_package(sw, str(path), 'Default', str(Path(root) / 'package'))
            self.assertFalse(r['success']); self.assertFalse((Path(root) / 'package').exists())

    def test_stale_configuration_denied(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None):
                r = build_manufacturing_package(sw, str(path), 'Other', str(Path(root) / 'package'))
            self.assertFalse(r['success']); self.assertFalse((Path(root) / 'package').exists())

    def test_failed_export_is_recorded_in_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            def copy(sw, source, destination, **kwargs):
                folder = Path(destination); folder.mkdir()
                copied = folder / 'copied.sldprt'; copied.write_bytes(b'part')
                (folder / '.solidworks-project-copy.json').write_text(json.dumps({
                    'schema_version': 1, 'status': 'verified', 'files': [{'copy': str(copied)}]}))
                return {'success': True, 'data': {'status': 'verified'}}
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None), \
                 patch('solidworks_mcp.tools.manufacturing_package.copy_project', side_effect=copy), \
                 patch('solidworks_mcp.tools.manufacturing_package.get_cut_list', return_value={'success': True, 'data': {'items': []}}), \
                 patch('solidworks_mcp.tools.manufacturing_package.export_step', return_value={'success': False, 'message': 'failure'}):
                r = build_manufacturing_package(sw, str(path), 'Default', str(Path(root) / 'package'), ['step'])
            self.assertFalse(r['success'])
            manifest = json.loads((Path(root) / 'package' / 'manufacturing-manifest.json').read_text())
            self.assertEqual('partial', manifest['status'])
            self.assertEqual('failed', manifest['artifacts'][-1]['status'])

    def test_drawing_preflight_rejects_nonmember_before_open(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            r = update_drawing_package(sw, str(path), [str(Path(root) / 'other.slddrw')])
            self.assertFalse(r['success']); self.assertEqual([], sw.opened)

    def test_unsafe_output_denied_before_copy(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            with patch('solidworks_mcp.tools.manufacturing_package.copy_project') as copied:
                r = build_manufacturing_package(sw, str(path), 'Default', str(Path(root).parent / 'escape-package'))
            self.assertFalse(r['success']); copied.assert_not_called()

    def test_reported_native_success_without_artifact_is_partial(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part'); sw = SW(root, path)
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None), \
                 patch('solidworks_mcp.tools.manufacturing_package.copy_project', return_value={'success': True}):
                r = build_manufacturing_package(sw, str(path), 'Default', str(Path(root) / 'package'), [])
            self.assertFalse(r['success']); self.assertEqual('partial', r['data']['status'])

    def test_drawing_rebuild_failure_reports_partial_and_no_save(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'p.sldprt'; path.write_bytes(b'part')
            drawing = Path(root) / 'p.slddrw'; drawing.write_bytes(b'drawing')
            (Path(root) / '.solidworks-project-copy.json').write_text(json.dumps({'schema_version': 1,
                'status': 'verified', 'files': [{'copy': str(path)}, {'copy': str(drawing)}]}))
            sw = SW(root, path); sw.app = object()
            old_open = sw.open_document
            def opened(value):
                result = old_open(value)
                sw.doc.ForceRebuild3 = MethodType(lambda self, top: False, sw.doc)
                return result
            sw.open_document = opened
            with patch('solidworks_mcp.tools.manufacturing_package.require_editable_copy', return_value=None), \
                 patch('solidworks_mcp.tools.manufacturing_package._ensure_app', return_value=sw.app), \
                 patch('solidworks_mcp.tools.project_copy._graph', return_value={path: []}), \
                 patch('solidworks_mcp.tools.manufacturing_package._dependencies', return_value=[path]):
                r = update_drawing_package(sw, str(path), [str(drawing)], save=True)
            self.assertFalse(r['success']); self.assertEqual('partial', r['data']['status'])
            self.assertTrue(r['data']['possible_partial_modification'])
            self.assertFalse(r['data']['drawings'][0]['saved'])


if __name__ == '__main__': unittest.main()
