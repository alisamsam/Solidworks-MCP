"""Independent projects must never keep references to original components."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType

from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.project_copy import inspect_project_references, copy_project, require_editable_copy


class App:
    def __init__(self):
        self.graph = {}
        self.open = {}
        self.replacements = []
        self.fail_replace = False

    def GetDocumentDependencies2(self, path, traverse, search, readonly):
        if path not in self.graph:
            # Our fixture stores dependency paths inside its copied byte payload.
            data = json.loads(Path(path).read_text())
            self.graph[path] = data['references']
        return tuple(x for p in self.graph[path] for x in (Path(p).name, p))

    def GetOpenDocumentByName(self, path):
        return self.open.get(path)

    def ReplaceReferencedDocument(self, path, old, new):
        self.replacements.append((path, old, new))
        if self.fail_replace:
            return False
        data = json.loads(Path(path).read_text())
        data['references'] = [new if p == old else p for p in data['references']]
        Path(path).write_text(json.dumps(data))
        self.graph[path] = data['references']
        return True


class Automation:
    def __init__(self, root):
        self.app = App()
        self._path_policy = PathPolicy([root / 'output'], [root / 'original'])
        self.is_connected = True

    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, error_code=error_code, data=data or {})


class ProjectCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sw = Automation(self.root)
        self.part = self.file('original/part.SLDPRT', [])
        self.external = self.file('external/part.SLDPRT', [])
        self.sub = self.file('original/sub.SLDASM', [self.external])
        self.source = self.file('original/main.SLDASM', [self.part, self.sub])
        self.destination = self.root / 'output' / 'copy'

    def file(self, name, refs):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'references': [str(p) for p in refs]}))
        return path

    def copy(self):
        return copy_project(self.sw, str(self.source), str(self.destination))

    def test_recursive_external_components_copied_and_relinked_without_changing_source(self):
        originals = {p: p.read_bytes() for p in [self.source, self.sub, self.part, self.external]}
        result = self.copy()
        self.assertTrue(result['success'], result)
        self.assertEqual(4, len(result['data']['files']))
        targets = [row['copy'] for row in result['data']['files']]
        self.assertEqual(4, len(set(Path(p).name.casefold() for p in targets)))
        for path in targets:
            self.assertTrue(Path(path).is_file())
            self.assertTrue(all(p in targets for p in self.sw.app.graph[path]))
            self.assertIsNone(require_editable_copy(self.sw, path))
        for p, before in originals.items():
            self.assertEqual(before, p.read_bytes())

    def test_copy_fails_closed_when_relink_fails(self):
        self.sw.app.fail_replace = True
        result = self.copy()
        self.assertFalse(result['success'])
        self.assertIsNotNone(require_editable_copy(self.sw, str(self.destination / 'unknown.SLDPRT')))
        self.assertEqual('failed', json.loads((self.destination / '.solidworks-project-copy.json').read_text())['status'])

    def test_missing_reference_and_dirty_source_rejected_before_destination_creation(self):
        self.external.unlink()
        self.assertFalse(self.copy()['success'])
        self.assertFalse(self.destination.exists())
        self.external.write_text('{"references":[]}')
        self.sw.app.open[str(self.part)] = SimpleNamespace(GetSaveFlag=lambda: True)
        self.assertFalse(self.copy()['success'])
        self.assertFalse(self.destination.exists())

    def test_explicit_saved_files_mode_ignores_unsaved_memory_and_reports_it(self):
        before = self.source.read_bytes()
        dirty = SimpleNamespace(GetSaveFlag=lambda: True)
        self.sw.app.open[str(self.source)] = dirty
        result = copy_project(self.sw, str(self.source), str(self.destination), source_state='saved_files')
        self.assertTrue(result['success'], result)
        self.assertEqual('saved_files', result['data']['source_state'])
        self.assertEqual([str(self.source)], result['data']['unsaved_documents_excluded'])
        self.assertTrue(result['data']['warnings'])
        self.assertEqual(before, self.source.read_bytes())
        self.assertTrue(dirty.GetSaveFlag())

    def test_unknown_source_state_rejected_before_any_copy(self):
        result = copy_project(self.sw, str(self.source), str(self.destination), source_state='snapshot')
        self.assertFalse(result['success'])
        self.assertFalse(self.destination.exists())

    def test_destination_cannot_overwrite_or_be_inside_source_folder(self):
        self.destination.mkdir(parents=True)
        self.assertFalse(self.copy()['success'])
        self.assertFalse(copy_project(self.sw, str(self.source), str(self.source.parent / 'copy'))['success'])

    def test_editing_original_or_non_manifest_file_denied_even_in_output_root(self):
        self.assertIsNotNone(require_editable_copy(self.sw, str(self.source)))
        unrelated = self.file('output/unrelated.SLDPRT', [])
        self.assertIsNotNone(require_editable_copy(self.sw, str(unrelated)))
        self.assertIsNone(require_editable_copy(self.sw, str(unrelated), edit_original=True))
        self.assertIsNotNone(require_editable_copy(self.sw, str(self.source), edit_original=True))

    def test_drawing_seed_copied_with_its_references(self):
        drawing = self.file('original/main.SLDDRW', [self.source])
        result = copy_project(self.sw, str(self.source), str(self.destination), drawings=[str(drawing)])
        self.assertTrue(result['success'], result)
        self.assertEqual(5, len(result['data']['files']))

    def test_related_drawings_in_source_folder_are_discovered_automatically(self):
        self.file('original/drawings/part.SLDDRW', [self.part])
        unrelated = self.file('original/unrelated.SLDDRW', [])
        result = self.copy()
        self.assertTrue(result['success'], result)
        self.assertEqual(5, len(result['data']['files']))
        self.assertNotIn(str(unrelated), [row['source'] for row in result['data']['files']])

    def test_reference_back_to_original_blocks_editing_previously_verified_copy(self):
        result = self.copy()
        copied = result['data']['root_document']
        self.sw.app.graph[copied] = [str(self.part)]
        self.assertIsNotNone(require_editable_copy(self.sw, copied))

    def test_two_copies_have_disjoint_basenames(self):
        first = self.copy()
        second = copy_project(self.sw, str(self.source), str(self.root / 'output' / 'second'))
        self.assertTrue(second['success'], second)
        self.assertFalse({Path(r['copy']).name for r in first['data']['files']} &
                         {Path(r['copy']).name for r in second['data']['files']})

    def test_unsaved_live_reference_to_original_blocks_editing(self):
        result = self.copy()
        copied = result['data']['root_document']
        component = SimpleNamespace()
        component.GetPathName = MethodType(lambda self: str(self_outer.part), component)
        self_outer = self
        opened = SimpleNamespace()
        opened.GetType = MethodType(lambda self: 2, opened)
        opened.GetComponents = MethodType(lambda self, top: [component], opened)
        self.sw.app.open[copied] = opened
        self.assertIsNotNone(require_editable_copy(self.sw, copied))


if __name__ == '__main__':
    unittest.main()
