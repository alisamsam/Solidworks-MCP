"""Explicit-scope packages built from verified saved copies, with honest manifests."""
import hashlib
import json
from pathlib import Path
from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..core.progress import report_progress
from ..registry import tool
from ..automation.document_safety import managed_operation
from .project_copy import MANIFEST, _path, _dependencies, _ensure_app, require_editable_copy, copy_project
from .cutlist import get_cut_list
from .export import export_step, export_stl, _export_native_model
from .sheetmetal import export_flat_pattern


def _failure(sw, error, **data):
    return sw._result(False, str(error), SwErrors.swInvalidInput, {'code': 'PACKAGE_FAILED', **data})


def _active(sw, path, configuration=None):
    doc, error = sw.get_active_doc()
    if error: raise ValueError(error.get('message', 'No active document.'))
    if _path(com(doc, 'GetPathName')) != path: raise ValueError('Active document differs from requested document_path.')
    if configuration is not None:
        actual = com(com(com(doc, 'ConfigurationManager'), 'ActiveConfiguration'), 'Name')
        if actual != configuration: raise ValueError('Active configuration differs from requested configuration; no switch performed.')
    return doc


def _policy(sw, path):
    policy = getattr(sw, '_path_policy', None)
    if policy is None: raise ValueError('An approved output path policy is required.')
    policy.require_write(path, OperationClass.EXPORT)


def _artifact(path, kind):
    if not path.is_file() or path.stat().st_size <= 0: raise ValueError(f'Missing or empty {kind} artifact: {path}')
    return {'kind': kind, 'path': str(path), 'status': 'verified_file',
        'size_bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _assembly_bom(document):
    """Inventory all occurrence levels, never resolving/switching configurations."""
    grouped = {}; suppressed = []; unresolved = []
    components = com(document, 'GetComponents', False)
    if components is None:
        return {'complete': False, 'items': [], 'suppressed_occurrences': [],
            'unresolved_occurrences': [{'reason': 'GetComponents returned no readable inventory.'}]}
    for index, component in enumerate(components):
        row = {'occurrence_index': index}
        try:
            row['instance_name'] = str(com(component, 'Name2'))
            state = com(component, 'GetSuppression')
            row['suppression_state'] = state
            if state == 0:
                suppressed.append(row); continue
            if state != 2:
                row['reason'] = 'Occurrence is lightweight, unresolved or has an unknown suppression state.'
                unresolved.append(row); continue
            virtual = com(component, 'IsVirtual')
            if virtual:
                row.update(reason='Virtual component has no independently verified saved document.', virtual=True)
                unresolved.append(row); continue
            value = com(component, 'GetPathName')
            configuration = com(component, 'ReferencedConfiguration')
            if not isinstance(configuration, str) or not configuration.strip():
                raise ValueError('Missing referenced configuration.')
            path = _path(value)
            if not path.is_file() or path.suffix.casefold() not in ('.sldprt', '.sldasm'):
                raise ValueError('Missing or unsupported component document.')
            key = (str(path).casefold(), configuration)
            item = grouped.setdefault(key, {'document_path': str(path), 'configuration': configuration,
                'document_type': 'assembly' if path.suffix.casefold() == '.sldasm' else 'part',
                'quantity': 0, 'occurrences': []})
            item['quantity'] += 1
            item['occurrences'].append(row)
        except Exception as error:
            row['reason'] = str(error); unresolved.append(row)
    return {'complete': not unresolved, 'items': list(grouped.values()),
        'suppressed_occurrences': suppressed, 'unresolved_occurrences': unresolved,
        'scope': 'All resolved non-suppressed occurrences, including subassemblies and their children; not a purchasing rollup.',
        'configuration_source': 'ReferencedConfiguration per occurrence; no configuration switches or resolutions.'}


@tool(name='build_manufacturing_package', description='Build a native copy, part cut-list or assembly occurrence BOM JSON, and selected STEP/STL/PDF/flat-DXF exports from an exact saved independent-copy document/configuration; report partial failures in a manifest.',
    schema={'type': 'object', 'properties': {'document_path': {'type': 'string'},
        'configuration': {'type': 'string'}, 'output_folder': {'type': 'string'},
        'formats': {'type': 'array', 'items': {'type': 'string', 'enum': ['step', 'stl', 'pdf', 'flat_dxf']}, 'default': ['step']}},
        'required': ['document_path', 'configuration', 'output_folder']}, operation_class=OperationClass.PROJECT_WRITE)
def build_manufacturing_package(sw, document_path, configuration, output_folder, formats=None):
    folder = None; created = False
    manifest = {'schema_version': 1, 'status': 'preparing', 'artifacts': [],
        'manufacturing_ready_verified': False, 'geometry_verified': False}
    try:
        path = _path(document_path); folder = _path(output_folder)
        _policy(sw, folder)
        if folder.exists(): raise ValueError('output_folder must be a new folder.')
        denied = require_editable_copy(sw, str(path))
        if denied: return denied
        if not isinstance(configuration, str) or not configuration.strip(): raise ValueError('An exact configuration is required.')
        formats = ['step'] if formats is None else formats
        if not isinstance(formats, list) or any(f not in ('step', 'stl', 'pdf', 'flat_dxf') for f in formats) or len(set(formats)) != len(formats):
            raise ValueError('formats must be a unique list of step, stl, pdf or flat_dxf.')
        doc = _active(sw, path, configuration)
        doc_type = int(com(doc, 'GetType'))
        if doc_type not in (1, 2, 3): raise ValueError('Unsupported document type.')
        if ('pdf' in formats and doc_type != 3) or (doc_type == 3 and any(f != 'pdf' for f in formats)):
            raise ValueError('PDF requires a drawing; STEP/STL require a part or assembly.')
        if 'flat_dxf' in formats and doc_type != 1: raise ValueError('flat_dxf requires a sheet-metal part.')
        if com(doc, 'GetSaveFlag'): raise ValueError('Save copied document explicitly before packaging; package represents saved state.')
        manifest.update(document_path=str(path), configuration=configuration,
            requested_artifacts=['native_copy'] + (['cut_list'] if doc_type == 1 else ['component_bom'] if doc_type == 2 else []) + formats,
            limitations=['Cut lists apply only to the active part; assembly BOM is an occurrence inventory with explicit unresolved/suppressed rows.',
                'File hashes establish artifact integrity, not drawing accuracy or manufacturing suitability.'])
        folder.mkdir(parents=True, exist_ok=False); created = True
        native = copy_project(sw, str(path), str(folder / 'native'), include_drawings=True)
        if not native.get('success'): raise ValueError('Native copy failed: ' + native.get('message', 'unknown failure'))
        steps_total = 1 + (1 if doc_type in (1, 2) else 0) + len(formats)
        steps_done = 1
        report_progress(min(steps_done, steps_total - 1), steps_total, 'native copy')
        native_manifest = folder / 'native' / MANIFEST
        if not native_manifest.is_file(): raise ValueError('Native copy did not produce its verification manifest.')
        native_data = json.loads(native_manifest.read_text(encoding='utf-8'))
        if native_data.get('status') != 'verified' or native_data.get('schema_version') != 1 or not native_data.get('files'):
            raise ValueError('Native copy manifest is incomplete or unverified.')
        native_root = (folder / 'native').resolve()
        for file_row in native_data['files']:
            copied_path = _path(file_row['copy'])
            if native_root not in copied_path.parents: raise ValueError('Native artifact escapes package.')
            _policy(sw, copied_path)
            manifest['artifacts'].append(_artifact(copied_path, 'native_document'))
        manifest['artifacts'].append({'kind': 'native_copy', 'path': str(folder / 'native'),
            'status': 'verified_references', 'verification': native.get('data', {})})
        manifest['artifacts'].append(_artifact(native_manifest, 'native_copy_manifest'))
        if doc_type == 1:
            cut = get_cut_list(sw)
            if not cut.get('success'): raise ValueError('Cut-list read failed: ' + cut.get('message', 'unknown failure'))
            cut_path = folder / 'cut-list.json'
            cut_path.write_text(json.dumps(cut, indent=2, ensure_ascii=False), encoding='utf-8')
            manifest['artifacts'].append(_artifact(cut_path, 'cut_list'))
            if 'stale' in cut.get('message', '').lower(): raise ValueError('Cut-list refresh failed; values may be stale.')
            steps_done += 1
            report_progress(min(steps_done, steps_total - 1), steps_total, 'cut list')
        bom = None
        if doc_type == 2:
            _active(sw, path, configuration)
            bom = _assembly_bom(doc)
            bom_path = folder / 'component-bom.json'
            bom_path.write_text(json.dumps(bom, indent=2, ensure_ascii=False), encoding='utf-8')
            artifact = _artifact(bom_path, 'component_bom')
            artifact['inventory_complete'] = bom['complete']
            manifest['artifacts'].append(artifact)
            steps_done += 1
            report_progress(min(steps_done, steps_total - 1), steps_total, 'component BOM')
        for fmt in formats:
            _active(sw, path, configuration)
            target = folder / ('flat-pattern.dxf' if fmt == 'flat_dxf' else f'model.{fmt}')
            exported = (export_step(sw, str(target)) if fmt == 'step' else export_stl(sw, str(target)) if fmt == 'stl'
                else export_flat_pattern(sw, str(target)) if fmt == 'flat_dxf'
                else _export_native_model(sw, str(target), {'.pdf'}, 'PDF'))
            if not exported.get('success'):
                manifest['artifacts'].append({'kind': fmt, 'path': str(target), 'status': 'failed', 'result': exported})
                raise ValueError(f'{fmt} export failed.')
            manifest['artifacts'].append(_artifact(target, fmt))
            steps_done += 1
            report_progress(min(steps_done, steps_total - 1), steps_total, f'{fmt} export')
        if bom is not None and not bom['complete']:
            raise ValueError('Assembly component inventory has virtual/unresolved occurrences; see component-bom.json.')
        report_progress(steps_total, steps_total, 'verified')
        manifest['status'] = 'complete'
    except Exception as error:
        if not created: return _failure(sw, error)
        manifest.update(status='partial', error=str(error), possible_partial_modification=True)
    manifest_path = folder / 'manufacturing-manifest.json'
    try:
        _policy(sw, manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as error:
        return _failure(sw, error, status='partial', package=manifest, manifest_written=False)
    return sw._result(manifest['status'] == 'complete', 'Manufacturing artifact package ' + manifest['status'] + '.',
        data={**manifest, 'manifest_path': str(manifest_path), 'saved_native_source_unchanged': True})


@tool(name='update_drawing_package', description='Rebuild explicitly related copied drawings, read back sheets and save only on request; exact copy isolation preflight, partial writes reported.',
    schema={'type': 'object', 'properties': {'document_path': {'type': 'string'},
        'drawing_paths': {'type': 'array', 'items': {'type': 'string'}},
        'save': {'type': 'boolean', 'default': False}}, 'required': ['document_path']}, operation_class=OperationClass.PROJECT_WRITE)
def update_drawing_package(sw, document_path, drawing_paths=None, save=False):
    rows = []; started = False
    try:
        if type(save) is not bool: raise ValueError('save must be a boolean.')
        path = _path(document_path)
        denied = require_editable_copy(sw, str(path))
        if denied: return denied
        marker = next((p / MANIFEST for p in path.parents if (p / MANIFEST).is_file()), None)
        if marker is None: raise ValueError('Verified copy manifest required.')
        manifest = json.loads(marker.read_text(encoding='utf-8'))
        members = {_path(row['copy']) for row in manifest['files']}
        # Related means referencing the requested model (directly or via its saved dependency graph).
        from .project_copy import _graph
        model_graph = set(_graph(_ensure_app(sw), [path]))
        related = {p for p in members if p.suffix.casefold() == '.slddrw' and
            (p == path or set(_dependencies(sw.app, p)) & model_graph)}
        if drawing_paths is None: drawings = sorted(related, key=str)
        elif not isinstance(drawing_paths, list): raise ValueError('drawing_paths must be a list.')
        else: drawings = [_path(value) for value in drawing_paths]
        if len(set(drawings)) != len(drawings): raise ValueError('Duplicate drawing paths.')
        for drawing in drawings:
            if drawing not in related: raise ValueError('Drawing is not a related member of the verified copy.')
            denied = require_editable_copy(sw, str(drawing))
            if denied: return denied
        for drawing in drawings:
            opened = sw.open_document(str(drawing))
            if not opened.get('success'): raise ValueError(opened.get('message', 'Drawing open failed.'))
            doc = _active(sw, drawing)
            if int(com(doc, 'GetType')) != 3: raise ValueError('Opened target is not a drawing.')
            before = list(com(doc, 'GetSheetNames') or [])
            if not before: raise ValueError('Drawing has no readable sheets.')
            with managed_operation(sw):
                bound = sw.bind_active_document() if hasattr(sw, 'bind_active_document') else None
                started = True
                rebuilt = bool(com(doc, 'ForceRebuild3', False))
                after = list(com(doc, 'GetSheetNames') or [])
                row = {'path': str(drawing), 'rebuilt': rebuilt, 'sheets_before': before, 'sheets_after': after,
                    'saved': False, 'drawing_content_verified': False}
                rows.append(row)
                if not rebuilt or after != before: raise ValueError('Drawing rebuild or sheet readback failed.')
                if bound is not None:
                    sw.mark_active_document_mutated(bound)
                if save:
                    saved = sw.save_document(str(drawing))
                    if not saved.get('success'): raise ValueError(saved.get('message', 'Drawing save failed.'))
                    _active(sw, drawing)
                    if com(doc, 'GetSaveFlag'): raise ValueError('Drawing still reports unsaved changes after save.')
                    row.update(saved=True, file=_artifact(drawing, 'drawing'))
        return sw._result(True, 'Related drawings rebuilt and sheets read back; content requires visual review.',
            data={'status': 'complete', 'drawings': rows, 'saved': save, 'active_document_changed': bool(drawings),
                'drawing_content_verified': False})
    except Exception as error:
        return _failure(sw, error, status='partial' if started else 'failed', drawings=rows,
            possible_partial_modification=started, rollback_performed=False)
