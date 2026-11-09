"""Safe saved-project lifecycle built on verified independent-copy manifests."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace
from pathlib import Path
import re

import pythoncom
import win32com.client

from ..comutil import com
from ..core.policy import OperationClass
from ..registry import tool
from .model_edit import replace_component, list_model_parameters, _canonical_dimension
from .measurements import get_mass_properties
from .imports import _dynamic_app
from .project_copy import (MANIFEST, NATIVE, _dependencies, _ensure_app, _fail,
    _hash, _path, _project_graph, _seeds, _within, copy_project, require_editable_copy)
from .views import capture_view, set_view, zoom_fit, _validate_orientation

COPY_PROPERTIES = {'source_path': {'type': 'string'}, 'destination_folder': {'type': 'string'},
    'drawings': {'type': 'array', 'items': {'type': 'string'}},
    'include_drawings': {'type': 'boolean', 'default': True}}


def _manifest(folder):
    root = _path(folder)
    data = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    if data.get('status') != 'verified' or data.get('schema_version') != 1:
        raise ValueError('A verified version-1 project-copy manifest is required.')
    rows = data.get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Manifest contains no documents.')
    seen = set()
    sources = set()
    for row in rows:
        path, source = _path(row['copy']), _path(row['source'])
        if not _within(path, root) or not path.is_file() or path.suffix.casefold() not in NATIVE:
            raise ValueError('Manifest member is missing or outside the project folder.')
        if path in seen or source in sources:
            raise ValueError('Duplicate manifest source or copy identity.')
        seen.add(path)
        sources.add(source)
    if _path(data['root_document']) not in seen:
        raise ValueError('Root document is not a manifest member.')
    return root, data


def _identity(source):
    """Follow saved-copy lineage, never infer identity from document basenames."""
    seen = set()
    current = _path(source)
    for _ in range(32):
        if current in seen:
            raise ValueError('Cyclic source lineage.')
        seen.add(current)
        marker = next((p / MANIFEST for p in current.parents if (p / MANIFEST).is_file()), None)
        if marker is None:
            return str(current)
        data = json.loads(marker.read_text(encoding='utf-8'))
        if data.get('status') != 'verified' or data.get('schema_version') != 1:
            raise ValueError('Source lineage manifest is not verified.')
        matches = [row for row in data.get('files', []) if _path(row['copy']) == current]
        if len(matches) != 1:
            raise ValueError('Source lineage identity is missing or ambiguous.')
        current = _path(matches[0]['source'])
    raise ValueError('Source lineage exceeds safety limit.')


def _model_snapshot(sw, path):
    snapshot = {'complete': False, 'limitations': [], 'path': str(path)}
    try:
        denied = require_editable_copy(sw, str(path))
        if denied: raise ValueError(denied['message'])
        app = _ensure_app(sw)
        doc = com(app, 'GetOpenDocumentByName', str(path))
        if doc is None:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            doc = com(_dynamic_app(app), 'OpenDoc6', str(path), {'.sldprt': 1, '.sldasm': 2, '.slddrw': 3}[path.suffix.casefold()], 1, '', errors, warnings)
            if doc is None or int(errors.value): raise ValueError('Could not open exact copied document for inspection.')
            snapshot['opened_for_inspection'] = True
        if _path(com(doc, 'GetPathName')) != path: raise ValueError('Inspection opened a different document.')
        if com(doc, 'GetSaveFlag'): raise ValueError('Copy has unsaved changes; saved model comparison refused.')
        denied = require_editable_copy(sw, str(path))
        if denied: raise ValueError(denied['message'])
        if int(com(doc, 'GetType')) == 3: raise ValueError('Drawing model drivers and mass are not supported.')
        # Existing inspection tools use this exact document, without activation.
        adapter = SimpleNamespace(get_active_doc=lambda: (doc, None), _result=sw._result)
        parameters = list_model_parameters(adapter)
        if not parameters['success']: raise ValueError(parameters['message'])
        data = parameters['data']
        snapshot.update(configuration=data['configuration'], dimensions={_canonical_dimension(r['name']): r['system_value'] for r in data['dimensions']},
            equations=data['equations'], configuration_names=list(com(app, 'GetConfigurationNames', str(path)) or []))
        snapshot['limitations'].extend(data.get('unresolved', []))
        mass = get_mass_properties(adapter)
        if not mass['success']: raise ValueError(mass['message'])
        snapshot['mass_kg'] = mass['data']['si']['mass_kg']
        if not math.isfinite(snapshot['mass_kg']): raise ValueError('Mass result is not finite.')
        snapshot['material'] = None
        if int(com(doc, 'GetType')) == 1:
            database = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, '')
            snapshot['material'] = com(doc, 'GetMaterialPropertyName2', data['configuration'], database)
            snapshot['material_database'] = str(database.value)
        else:
            snapshot['limitations'].append('Assembly material names are not compared; component part materials are inspected separately.')
        if com(doc, 'GetSaveFlag'): raise ValueError('Document became dirty during inspection; saved comparison is incomplete.')
        snapshot['complete'] = bool(data['complete'])
    except Exception as exc:
        snapshot['limitations'].append(str(exc))
    return snapshot


def _model_changes(left, right):
    if not left.get('complete') or not right.get('complete'):
        return {'comparable': False, 'reason': 'One or both model inspections are incomplete.'}
    if left['configuration'] != right['configuration']:
        return {'comparable': False, 'reason': 'Active configurations differ; configurations were not switched.'}
    a, b = left['dimensions'], right['dimensions']
    return {'comparable': True, 'configuration': left['configuration'],
        'dimensions_added': sorted(b.keys() - a.keys()), 'dimensions_removed': sorted(a.keys() - b.keys()),
        'dimensions_changed': sorted(k for k in a.keys() & b.keys() if not math.isclose(a[k], b[k], rel_tol=1e-9, abs_tol=1e-12)),
        'material_changed': left.get('material') != right.get('material'),
        'mass_delta_kg': right['mass_kg'] - left['mass_kg'],
        'configuration_names_changed': set(left['configuration_names']) != set(right['configuration_names'])}


@tool(name='compare_project_versions', description=(
    'Compare saved bytes, membership and manifest source hashes in two verified copied projects. '
    'Maps documents by source lineage. Optional model inspection compares active-configuration drivers/material/mass in saved copied models. No geometric equivalence claim.'),
    schema={'type': 'object', 'properties': {'left_folder': {'type': 'string'}, 'right_folder': {'type': 'string'}, 'include_model_parameters': {'type': 'boolean', 'default': False}},
            'required': ['left_folder', 'right_folder']}, operation_class=OperationClass.READ)
def compare_project_versions(sw, left_folder, right_folder, include_model_parameters=False):
    try:
        if not isinstance(include_model_parameters, bool): raise ValueError('include_model_parameters must be boolean.')
        left_root, left = _manifest(left_folder)
        right_root, right = _manifest(right_folder)
        def indexed(data):
            result = {}
            for row in data['files']:
                identity = _identity(row['source'])
                if identity in result:
                    raise ValueError('More than one document has the same source lineage; comparison is ambiguous.')
                result[identity] = {**row, 'saved_sha256': _hash(_path(row['copy']))}
            return result
        a, b = indexed(left), indexed(right)
        rows = []
        for identity in sorted(a.keys() | b.keys()):
            l, r = a.get(identity), b.get(identity)
            rows.append({'source_identity': identity, 'left': l, 'right': r,
                'saved_bytes': 'added' if l is None else 'removed' if r is None else
                    'unchanged' if l['saved_sha256'] == r['saved_sha256'] else 'changed',
                'source_hash_matches': l.get('source_sha256') == r.get('source_sha256') if l and r else None})
        if include_model_parameters:
            for row in rows:
                for side in ('left', 'right'):
                    if row[side]: row[side]['model_snapshot'] = _model_snapshot(sw, _path(row[side]['copy']))
                if row['left'] and row['right']:
                    row['model_changes'] = _model_changes(row['left']['model_snapshot'], row['right']['model_snapshot'])
        return sw._result(True, 'Saved project versions compared; see explicit inspection coverage.', data={
            'left_folder': str(left_root), 'right_folder': str(right_root), 'documents': rows,
            'semantic_comparison': False, 'model_parameters_inspected': include_model_parameters, 'unsaved_changes_included': False,
            'limitations': ['SHA256 differences include reference-path relinking and file metadata.',
                'Geometry, feature equivalence, mate correctness and inactive configuration drivers are not compared.']})
    except Exception as exc:
        return _fail(sw, str(exc), 'PROJECT_COMPARE_FAILED')


@tool(name='checkpoint_project', description=(
    'Create a verified independent saved-file checkpoint in a NEW approved folder. '
    'Unsaved source changes are rejected; no source save, overwrite or automatic activation.'),
    schema={'type': 'object', 'properties': COPY_PROPERTIES,
        'required': ['source_path', 'destination_folder']}, operation_class=OperationClass.PROJECT_WRITE)
def checkpoint_project(sw, source_path, destination_folder, drawings=None, include_drawings=True):
    result = copy_project(sw, source_path, destination_folder, drawings, include_drawings)
    if result['success']:
        result['data']['checkpoint_scope'] = 'saved reachable native CAD documents and discovered/explicit drawings'
    return result


@tool(name='make_component_independent', description=(
    'Duplicate one saved component/dependency graph into a NEW approved folder, then replace one '
    'immediate occurrence in the expected active verified copied assembly. Does not save the assembly; inspect mates.'),
    schema={'type': 'object', 'properties': {
        'component_name': {'type': 'string'}, 'expected_path': {'type': 'string'},
        'assembly_path': {'type': 'string'}, 'configuration': {'type': 'string'},
        'destination_folder': {'type': 'string'}, 'reattach_mates': {'type': 'boolean', 'default': True}},
        'required': ['component_name', 'expected_path', 'assembly_path', 'configuration', 'destination_folder']},
    operation_class=OperationClass.PROJECT_WRITE)
def make_component_independent(sw, component_name, expected_path, assembly_path, configuration,
                               destination_folder, reattach_mates=True):
    copied = None
    replacement_attempted = False
    try:
        if not isinstance(reattach_mates, bool): raise ValueError('reattach_mates must be boolean.')
        doc, error = sw.get_active_doc()
        if error: return error
        owner = _path(assembly_path)
        expected = _path(expected_path)
        if _path(com(doc, 'GetPathName')) != owner or int(com(doc, 'GetType')) != 2:
            raise ValueError('Expected assembly is not the active document.')
        if not isinstance(component_name, str) or not component_name.strip() or '/' in component_name:
            raise ValueError('An exact immediate component Name2 is required; activate the owning subassembly for nested occurrences.')
        denied = require_editable_copy(sw, str(owner))
        if denied: return denied
        matches = [c for c in com(doc, 'GetComponents', True) or [] if com(c, 'Name2') == component_name]
        if len(matches) != 1: raise ValueError('Immediate component name is missing or ambiguous.')
        if _path(com(matches[0], 'GetPathName')) != expected:
            raise ValueError('Component path changed; refresh before copying.')
        if com(matches[0], 'ReferencedConfiguration') != configuration:
            raise ValueError('Component configuration changed; refresh before copying.')
        copied = copy_project(sw, str(expected), destination_folder, include_drawings=False)
        if not copied['success']: return copied
        # Recheck owner after disk work; never replace in a different active assembly.
        active, error = sw.get_active_doc()
        if error or _path(com(active, 'GetPathName')) != owner:
            raise ValueError('Active assembly changed while copying; replacement was not attempted.')
        replacement = copied['data']['root_document']
        replacement_attempted = True
        result = replace_component(sw, component_name, replacement, str(expected), configuration,
            all_instances=False, reattach_mates=reattach_mates, edit_original=False)
        result.setdefault('data', {}).update(replacement_path=replacement, copy_manifest=copied['data'],
            assembly_path=str(owner), saved=False)
        if not result['success']: result['data']['partial_folder'] = str(_path(destination_folder))
        return result
    except Exception as exc:
        return _fail(sw, str(exc), 'COMPONENT_INDEPENDENCE_FAILED', saved=False, document_may_be_modified=replacement_attempted,
            partial_folder=str(_path(destination_folder)) if copied and copied['success'] else None)


def _rename_mapping(graph, mapping):
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('rename_map must be a non-empty mapping from exact source paths to new basenames.')
    normalized = {}
    names = set()
    original_names = {p.name.casefold() for p in graph}
    for source, name in mapping.items():
        path = _path(source)
        if path not in graph or path in normalized:
            raise ValueError('Rename source must uniquely match the saved project dependency graph.')
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or name.endswith(('.', ' '))):
            raise ValueError('Rename target must be a safe document basename without directories.')
        stem = name.split('.')[0].upper()
        if stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(COM|LPT)[1-9]', stem):
            raise ValueError('Reserved Windows document basename.')
        if Path(name).suffix.casefold() != path.suffix.casefold():
            raise ValueError('Renaming cannot change the document type/extension.')
        if name.casefold() in names or name.casefold() in original_names:
            raise ValueError('Rename collision: targets must be unique and distinct from original document basenames.')
        names.add(name.casefold())
        normalized[path] = name
    return normalized


@tool(name='rename_project_documents', description=(
    'Copy a saved CAD project into a NEW approved folder, rename selected closed COPIES by explicit '
    'source-path-to-basename mapping, relink and verify. Original/in-place renaming is never performed. '
    'Target basenames must be unique and distinct from original document names.'),
    schema={'type': 'object', 'properties': {**COPY_PROPERTIES,
        'rename_map': {'type': 'object', 'additionalProperties': {'type': 'string'}}},
        'required': ['source_path', 'destination_folder', 'rename_map']}, operation_class=OperationClass.PROJECT_WRITE)
def rename_project_documents(sw, source_path, destination_folder, rename_map, drawings=None, include_drawings=True):
    manifest = None
    destination = None
    try:
        source, seeds = _seeds(source_path, drawings)
        destination = _path(destination_folder)
        app = _ensure_app(sw)
        graph = _project_graph(app, source, seeds, include_drawings)
        names = _rename_mapping(graph, rename_map)
        result = copy_project(sw, source_path, destination_folder, drawings, include_drawings)
        if not result['success']: return result
        manifest = result['data']
        marker = destination / MANIFEST
        old = {_path(row['source']): _path(row['copy']) for row in manifest['files']}
        if set(old) != set(graph): raise ValueError('Dependency graph changed during copy.')
        final = {p: destination / names[p] if p in names else target for p, target in old.items()}
        if len({p.name.casefold() for p in final.values()}) != len(final): raise ValueError('Rename collides with generated copy filename.')
        for target in final.values():
            sw._path_policy.require_write(target, OperationClass.EXPORT)
            if target not in old.values() and target.exists(): raise ValueError('Rename target already exists.')
        manifest['status'] = 'renaming'
        marker.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        copy_graph = {path: _dependencies(app, path) for path in old.values()}
        for path in old.values():
            if com(app, 'GetOpenDocumentByName', str(path)) is not None:
                raise ValueError('Rename requires all copied documents to remain closed.')
        remap = {old[p]: final[p] for p in old}
        for path, target in remap.items():
            if target != path: path.rename(target)
        for path, refs in copy_graph.items():
            target = remap[path]
            for ref in refs:
                if ref not in remap: raise ValueError('Copied graph contains a reference outside the copy.')
                if remap[ref] != ref and not com(app, 'ReplaceReferencedDocument', str(target), str(ref), str(remap[ref])):
                    raise ValueError(f'Renamed copy relink failed: {target}')
            if set(_dependencies(app, target)) != {remap[ref] for ref in refs}:
                raise ValueError(f'Renamed copy reference verification failed: {target}')
        for row in manifest['files']:
            path = _path(row['source'])
            if _hash(path) != row['source_sha256']: raise ValueError('Source changed during rename; copy not verified.')
            row['copy'] = str(final[path])
        manifest.update(status='verified', root_document=str(final[source]),
            rename_map={str(p): name for p, name in names.items()},
            verification='closed-file renamed references and unchanged source SHA256')
        marker.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return sw._result(True, 'Project documents renamed in a new isolated copy; references verified.', data=manifest)
    except Exception as exc:
        if manifest is not None:
            manifest.update(status='failed', error=str(exc))
            try: (destination / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            except OSError: pass
        return _fail(sw, str(exc), 'PROJECT_RENAME_FAILED', partial_folder=str(destination) if manifest else None)


@tool(name='present_result', description=(
    'Open a specific verified copied native document silently, activate and verify its exact path, '
    'optionally set a standard view and zoom to fit (prepare_view=false activates for inspection only). Optional revision-bound PNG capture; does not save.'),
    schema={'type': 'object', 'properties': {'document_path': {'type': 'string'},
        'orientation': {'type': 'string', 'default': 'isometric'}, 'capture': {'type': 'boolean', 'default': False},
        'output_path': {'type': 'string'}, 'prepare_view': {'type':'boolean','default':True}}, 'required': ['document_path']}, operation_class=OperationClass.PROJECT_WRITE)
def present_result(sw, document_path, orientation='isometric', capture=False, output_path=None, prepare_view=True):
    activated = False
    opened = False
    try:
        path = _path(document_path)
        if path.suffix.casefold() not in NATIVE: raise ValueError('A native copied document is required.')
        if not isinstance(capture, bool): raise ValueError('capture must be boolean.')
        if not isinstance(prepare_view, bool): raise ValueError('prepare_view must be boolean.')
        normalized, error = _validate_orientation(sw, orientation)
        if error: return error
        if output_path is not None:
            output = _path(output_path)
            if not capture: raise ValueError('output_path requires capture=true.')
            if output.suffix.casefold() != '.png' or output.exists(): raise ValueError('Capture requires a new .png path.')
            sw._path_policy.require_write(output, OperationClass.EXPORT)
        denied = require_editable_copy(sw, str(path))
        if denied: return denied
        app = _ensure_app(sw)
        document = com(app, 'GetOpenDocumentByName', str(path))
        if document is None:
            errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            document = com(_dynamic_app(app), 'OpenDoc6', str(path), {'.sldprt': 1, '.sldasm': 2, '.slddrw': 3}[path.suffix.casefold()], 1, '', errors, warnings)
            opened = document is not None
            if document is None or int(errors.value): raise ValueError(f'Copied document open failed: {errors.value}.')
        if _path(com(document, 'GetPathName')) != path: raise ValueError('Opened document path does not match the requested copy.')
        returned = com(app, 'ActivateDoc3', com(document, 'GetTitle'), False, 1, 0)
        active = returned[0] if isinstance(returned, tuple) else returned
        if active is None or (isinstance(returned, tuple) and len(returned) > 1 and int(returned[1])):
            raise ValueError('Copied document activation failed.')
        if _path(com(active, 'GetPathName')) != path or _path(com(com(app, 'ActiveDoc'), 'GetPathName')) != path:
            raise ValueError('Activated document path does not match the requested copy.')
        activated = True
        if hasattr(sw, 'bind_active_document'): sw.bind_active_document()
        denied = require_editable_copy(sw, str(path))
        if denied: raise ValueError(denied['message'])
        if prepare_view:
            for step in (lambda: set_view(sw, normalized), lambda: zoom_fit(sw)):
                result = step()
                if not result['success']: raise ValueError(result['message'])
        image_result = capture_view(sw, normalized, output_path=output_path) if capture else None
        if image_result and not image_result['success']: raise ValueError(image_result['message'])
        if _path(com(com(app, 'ActiveDoc'), 'GetPathName')) != path:
            raise ValueError('Active document changed during presentation/capture; result not verified.')
        return sw._result(True, 'Copied result activated and presented.', data={'document_path': str(path),
            'document_opened': opened, 'document_activated': True, 'orientation': normalized, 'saved': False,
            'view_prepared': prepare_view,
            'capture': image_result['data'] if image_result else None})
    except Exception as exc:
        return _fail(sw, str(exc), 'RESULT_PRESENTATION_FAILED', document_opened=opened,
            document_activated=activated, saved=False)
