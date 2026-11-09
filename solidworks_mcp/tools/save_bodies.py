"""Native Save Bodies, with new-only outputs and persisted geometry readback."""
import hashlib
import logging
import math
from pathlib import Path

import pythoncom
from win32com.client import VARIANT

from ..comutil import com
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool

logger = logging.getLogger(__name__)


def _geometry(body):
    volume = com(body, 'GetMassProperties', 0.0)[3]
    box = tuple(com(body, 'GetBodyBox'))
    if (isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume <= 0
            or len(box) != 6 or any(not math.isfinite(x) for x in box)):
        raise ValueError('Solid body has invalid mass properties or bounding box.')
    return {'volume_m3': volume, 'box_m': box}


def _same_geometry(first, second):
    return (math.isclose(first['volume_m3'], second['volume_m3'], rel_tol=1e-8, abs_tol=1e-15)
            and all(abs(a-b) <= 1e-7 for a,b in zip(first['box_m'], second['box_m'])))


def _long():
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def _same_body_set(before, after):
    # Save Bodies renames the original bodies; GetBodies2 order is not stable.
    remaining = list(after)
    for geometry in before:
        match = next((i for i,g in enumerate(remaining) if _same_geometry(geometry,g)), None)
        if match is None:
            return False
        remaining.pop(match)
    return not remaining


def _close_outputs(app, paths):
    # Every path was absent and its title unoccupied at preflight. Never close by guess.
    for path in reversed(paths):
        opened = com(app, 'GetOpenDocumentByName', str(path))
        if opened is not None:
            if Path(com(opened, 'GetPathName')).resolve() != path:
                raise ValueError('Unexpected document while closing generated output.')
            com(app, 'CloseDoc', com(opened, 'GetTitle'))
    if any(com(app, 'GetOpenDocumentByName', str(p)) is not None for p in paths):
        raise ValueError('Generated documents remain loaded; persisted readback cannot be verified.')


def _activate_source(app, doc, source):
    error = _long()
    restored = com(app, 'ActivateDoc3', com(doc, 'GetTitle'), False, 0, error)
    active = com(app, 'ActiveDoc')
    if (restored is None or error.value or active is None
            or Path(com(active, 'GetPathName')).resolve() != source):
        raise ValueError('Could not restore the source document as active.')


def _read_saved(app, path, kind, reader):
    error, warning = _long(), _long()
    # Silent + read-only; only generated outputs are reopened, never originals.
    doc = com(app, 'OpenDoc6', str(path), kind, 3, '', error, warning)
    if (doc is None or error.value or com(doc, 'GetType') != kind
            or Path(com(doc, 'GetPathName')).resolve() != path):
        raise ValueError(f'Cannot reopen generated file {path.name}; error {error.value}.')
    try:
        return reader(doc), int(warning.value)
    finally:
        com(app, 'CloseDoc', com(doc, 'GetTitle'))


@tool(
    name='save_bodies',
    description=('Save selected visible solids as new linked parts and an assembly. Adds a Save Bodies feature '
                 'to a clean saved working copy; native SW may save it. Reopens outputs to verify geometry. '
                 'Paths must be approved and absent; source remains active. One Save Bodies feature per source; no property transfer.'),
    schema={'type':'object','properties':{
        'body_indices':{'type':'array','minItems':1,'maxItems':64,'uniqueItems':True,
                        'items':{'type':'integer','minimum':0},
                        'description':'Fresh visible body_index from get_cut_list_body_map or list_body_edges.'},
        'output_paths':{'type':'array','minItems':1,'maxItems':64,
                        'items':{'type':'string'},'description':'Absolute new .SLDPRT paths, one per index in the same order.'},
        'assembly_path':{'type':'string','description':'Absolute new .SLDASM path; required by this workflow.'},
    },'required':['body_indices','output_paths','assembly_path']},
    operation_class=OperationClass.MUTATE,
)
def save_bodies(sw, body_indices, output_paths, assembly_path):
    data = {'document_may_be_modified': False, 'parts': [], 'created_paths': []}
    doc = app = None
    paths = []
    failure = None
    try:
        if (not isinstance(body_indices, (list, tuple)) or not 1 <= len(body_indices) <= 64
                or any(type(i) is not int or i < 0 for i in body_indices)
                or len(set(body_indices)) != len(body_indices)
                or not isinstance(output_paths, (list, tuple)) or len(output_paths) != len(body_indices)):
            raise ValueError('Supply 1 to 64 distinct nonnegative body indices and matching output paths.')
        for value, suffix in [(p, '.sldprt') for p in output_paths] + [(assembly_path, '.sldasm')]:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Output paths must be nonempty strings.')
            path = Path(value).expanduser()
            if not path.is_absolute() or path.suffix.casefold() != suffix:
                raise ValueError('Use absolute .SLDPRT paths and an absolute .SLDASM assembly path.')
            paths.append(path.resolve())
        if len({p.name.casefold() for p in paths}) != len(paths):
            raise ValueError('All output filenames must be distinct, even across folders.')
        policy = getattr(sw, '_path_policy', None)
        if policy is None:
            raise ValueError('An approved output path policy is required.')
        for path in paths:
            policy.require_write(path, OperationClass.EXPORT)
            if path.exists():
                raise ValueError(f'Output already exists; no overwrite: {path}')
        doc, error = sw.get_active_doc()
        if error:
            return error
        if com(doc, 'GetType') != 1:
            raise ValueError('Save Bodies requires a part.')
        source_name = com(doc, 'GetPathName')
        if not source_name:
            raise ValueError('Save a working copy of the source part first.')
        source = Path(source_name).resolve()
        policy.require_write(source, OperationClass.MUTATE)
        if not source.is_file() or com(doc, 'GetSaveFlag'):
            raise ValueError('Source must be saved and clean; save the working copy first.')
        current = com(doc, 'FirstFeature')
        for _ in range(10000):
            if current is None:
                break
            if com(current, 'GetTypeName2') == 'CreateAssemFeat':
                raise ValueError('Source already has Save Bodies; updating/repeating it is not supported. Use a working copy before Save Bodies.')
            current = com(current, 'GetNextFeature')
        else:
            raise ValueError('Source feature scan incomplete; Save Bodies refused.')
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        app = sw.app
        occupied = {str(com(d, 'GetTitle')).casefold() for d in com(app, 'GetDocuments') or []}
        # SW titles may omit their extension. Reject either spelling before creating anything.
        if any(p.name.casefold() in occupied or p.stem.casefold() in occupied for p in paths):
            raise ValueError('An output filename collides with an open document title.')
        visible = list(com(doc, 'GetBodies2', 0, True) or [])
        if any(i >= len(visible) for i in body_indices):
            raise ValueError('Body index missing; re-read list_body_edges.')
        selected = [visible[i] for i in body_indices]
        expected = [_geometry(b) for b in selected]
        all_before = [_geometry(b) for b in com(doc, 'GetBodies2', 0, False) or []]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
        data.update(source_path=str(source), source_save_required=True)
        data['document_may_be_modified'] = True
        data['stage'] = 'create_native_feature'
        feature = com(com(doc, 'FeatureManager'), 'CreateSaveBodyFeature',
                      VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, selected),
                      VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [str(p) for p in paths[:-1]]),
                      str(paths[-1]), False, False)
        data['stage'] = 'rebuild_source'
        _activate_source(app, doc, source)
        if feature is None or com(doc, 'EditRebuild3') is not True:
            raise ValueError('Save Bodies feature creation or rebuild failed.')
        name = com(feature, 'Name')
        data['stage'] = 'verify_native_feature'
        persisted = com(doc, 'FeatureByName', name)
        warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
        if (persisted is None or com(persisted, 'GetTypeName2') != 'CreateAssemFeat'
                or com(persisted, 'GetErrorCode2', warning) != 0 or warning.value):
            raise ValueError('Native Save Bodies feature is missing or has an error/warning.')
        data['feature_name'] = name
        data['stage'] = 'verify_source_geometry'
        all_after = [_geometry(b) for b in com(doc, 'GetBodies2', 0, False) or []]
        if not _same_body_set(all_before, all_after):
            raise ValueError('Source body geometry changed unexpectedly.')
        data['source_file_changed'] = hashlib.sha256(source.read_bytes()).hexdigest() != source_hash
        if any(not p.is_file() or p.stat().st_size == 0 for p in paths):
            raise ValueError('Native feature did not write every requested output file.')
        _close_outputs(app, paths)
        data['stage'] = 'verify_saved_parts'
        for index, path, original in zip(body_indices, paths[:-1], expected):
            def read_part(child):
                solids = list(com(child, 'GetBodies2', 0, False) or [])
                if len(solids) != 1:
                    raise ValueError(f'{path.name} does not contain exactly one solid.')
                return _geometry(solids[0])
            actual, warning_code = _read_saved(app, path, 1, read_part)
            if not _same_geometry(original, actual):
                raise ValueError(f'Persisted geometry mismatch: {path.name}.')
            data['parts'].append({'body_index': index, 'path': str(path),
                                  'volume_mm3': actual['volume_m3']*1e9,
                                  'box_mm': [x*1000 for x in actual['box_m']],
                                  'open_warning': warning_code,
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        def read_assembly(assembly):
            return [str(Path(com(c, 'GetPathName')).resolve()).casefold()
                    for c in com(assembly, 'GetComponents', False) or []]
        refs, warning_code = _read_saved(app, paths[-1], 2, read_assembly)
        if sorted(refs) != sorted(str(p).casefold() for p in paths[:-1]):
            raise ValueError('Saved assembly does not reference exactly the exported parts.')
        data.update(assembly_path=str(paths[-1]), assembly_open_warning=warning_code,
                    source_geometry_unchanged=True, geometry_verified=True,
                    linked_to_source=True, custom_properties_transferred=False)
        data['stage'] = 'verified'
    except Exception as exc:
        logger.debug('Save Bodies failed at %s', data.get('stage', 'preflight'), exc_info=True)
        failure = str(exc)
    finally:
        if data['document_may_be_modified'] and app is not None:
            data['created_paths'] = [str(p) for p in paths if p.is_file()]
            try:
                _close_outputs(app, paths)
                _activate_source(app, doc, source)
                data['source_reactivated'] = True
                data['source_save_required'] = bool(com(doc, 'GetSaveFlag'))
                data['source_file_changed'] = hashlib.sha256(source.read_bytes()).hexdigest() != source_hash
            except Exception as exc:
                data['restore_error'] = str(exc)
                failure = f'{failure + "; " if failure else ""}{exc}'
    if failure:
        data['geometry_verified'] = False
        return sw._result(False, failure, SwErrors.swFeatureError if data['document_may_be_modified'] else SwErrors.swInvalidInput, data)
    return sw._result(True, 'Saved bodies and verified reopened geometry; check source_save_required.', data=data)
