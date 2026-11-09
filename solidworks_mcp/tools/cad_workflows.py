"""Bounded existing-CAD workflows. No raw COM/property mutation interface."""
from __future__ import annotations

import base64
import math
from pathlib import Path

import pythoncom
from win32com.client import VARIANT

from ..comutil import com, set_com
from ..core.policy import OperationClass
from ..inspection.documents import inspect_dependencies
from ..registry import tool
from .model_edit import EDIT_ARGS, _configuration, _rebuild_checked, _number, set_model_dimension
from .project_copy import _fail, require_editable_copy

FEATURE_TYPES = {'Boss', 'Cut', 'Fillet', 'Chamfer', 'Shell', 'HoleWzd', 'LPattern', 'CirPattern'}
MATE_TYPES = {'MateCoincident', 'MateConcentric', 'MateDistanceDim', 'MatePlanarAngleDim', 'MateParallel', 'MatePerpendicular', 'MateTangent'}
PATTERN_TYPES = {'LocalLPattern', 'LocalCirPattern'}
SUPPRESSION_SCHEMA = {'type': 'object', 'properties': {
    'feature_name': {'type': 'string'}, 'expected_type': {'type': 'string'},
    'suppressed': {'type': 'boolean'}, 'expected_suppressed': {'type': 'boolean'}, **EDIT_ARGS},
    'required': ['feature_name', 'expected_type', 'suppressed', 'expected_suppressed', 'configuration']}
DEFINITION_SCHEMA = {'type': 'object', 'properties': {**SUPPRESSION_SCHEMA['properties'],
    'action': {'type': 'string', 'enum': ['suppression', 'extrusion'], 'default': 'suppression'},
    'depth_mm': {'type': 'number', 'exclusiveMinimum': 0}, 'expected_depth_mm': {'type': 'number'},
    'end_condition': {'type': 'string', 'enum': ['blind', 'mid_plane']},
    'expected_end_condition': {'type': 'string', 'enum': ['blind', 'mid_plane']}},
    'required': ['feature_name', 'expected_type', 'configuration'], 'allOf': [
        {'if': {'properties': {'action': {'const': 'extrusion'}}, 'required': ['action']},
         'then': {'required': ['depth_mm', 'expected_depth_mm', 'end_condition', 'expected_end_condition']},
         'else': {'required': ['suppressed', 'expected_suppressed']}}]}
PATTERN_SCHEMA = {'type': 'object', 'properties': {**SUPPRESSION_SCHEMA['properties'],
    'action': {'type': 'string', 'enum': ['suppression', 'linear_count', 'spacing_dimension'], 'default': 'suppression'},
    'instances': {'type': 'integer', 'minimum': 2}, 'expected_instances': {'type': 'integer', 'minimum': 2},
    'dimension_name': {'type': 'string'}, 'spacing_mm': {'type': 'number', 'exclusiveMinimum': 0},
    'expected_spacing_mm': {'type': 'number'}}, 'required': ['feature_name', 'expected_type', 'configuration'],
    'allOf': [
        {'if': {'properties': {'action': {'const': 'linear_count'}}, 'required': ['action']},
         'then': {'required': ['instances', 'expected_instances']}},
        {'if': {'properties': {'action': {'const': 'spacing_dimension'}}, 'required': ['action']},
         'then': {'required': ['dimension_name', 'spacing_mm', 'expected_spacing_mm']}},
        {'if': {'anyOf': [{'not': {'required': ['action']}}, {'properties': {'action': {'const': 'suppression'}}}]},
         'then': {'required': ['suppressed', 'expected_suppressed']}}]}
MATE_SCHEMA = {'type': 'object', 'properties': {**SUPPRESSION_SCHEMA['properties'],
    'action': {'type': 'string', 'enum': ['suppression', 'dimension'], 'default': 'suppression'},
    'dimension_name': {'type': 'string'}, 'value': {'type': 'number'}, 'expected_value': {'type': 'number'},
    'unit': {'type': 'string', 'enum': ['mm', 'cm', 'm', 'in', 'ft', 'deg', 'rad']}},
    'required': ['feature_name', 'expected_type', 'configuration'], 'allOf': [
        {'if': {'properties': {'action': {'const': 'dimension'}}, 'required': ['action']},
         'then': {'required': ['dimension_name', 'value', 'expected_value', 'unit']},
         'else': {'required': ['suppressed', 'expected_suppressed']}}]}


def _feature(doc, name, expected_type=None, allowed=None):
    if not isinstance(name, str) or not name.strip(): raise ValueError('Exact feature name is required.')
    feature = com(doc, 'FeatureByName', name)
    if feature is None: raise ValueError(f'Feature not found: {name}')
    kind = str(com(feature, 'GetTypeName2'))
    if expected_type is not None and kind != expected_type: raise ValueError('Feature type changed; refresh the target.')
    if allowed is not None and kind not in allowed: raise ValueError(f'Unsupported feature type: {kind}')
    return feature, kind


def _suppressed(feature):
    values = com(feature, 'IsSuppressed2', 1, None)
    if not isinstance(values, (tuple, list)) or len(values) != 1 or not isinstance(values[0], bool):
        raise ValueError('Active-configuration suppression state is unavailable.')
    return values[0]


def _walk(doc):
    """Traverse top-level and nested features; retain wrappers and bound traversal."""
    retained = []; seen = set(); pending = [(com(doc, 'FirstFeature'), False)]
    while pending:
        feature, sub = pending.pop()
        if feature is None: continue
        if id(feature) in seen: raise ValueError('Cyclic feature traversal cannot be reported as complete.')
        seen.add(id(feature)); retained.append(feature)
        if len(retained) > 10000: raise ValueError('Feature traversal limit exceeded.')
        pending.append((com(feature, 'GetNextSubFeature' if sub else 'GetNextFeature'), sub))
        pending.append((com(feature, 'GetFirstSubFeature'), True))
        yield feature


def _edit_suppression(sw, feature_name, expected_type, suppressed, expected_suppressed,
                      configuration, edit_original, allowed, assembly=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False
    try:
        denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
        if denied: return denied
        _configuration(doc, configuration)
        if assembly and int(com(doc, 'GetType')) != 2: raise ValueError('An active assembly is required.')
        if not isinstance(suppressed, bool) or not isinstance(expected_suppressed, bool):
            raise ValueError('Suppression inputs must be booleans.')
        feature, kind = _feature(doc, feature_name, expected_type, allowed)
        before = _suppressed(feature)
        if before != expected_suppressed: raise ValueError('Suppression state changed; refresh before editing.')
        if before != suppressed:
            changed = True
            if not com(feature, 'SetSuppression2', 0 if suppressed else 1, 1, None):
                raise ValueError('SolidWorks rejected suppression change.')
            if not _rebuild_checked(doc): raise ValueError('Rebuild or feature errors prevented verification.')
        after = _suppressed(feature)
        _configuration(doc, configuration)
        if after != suppressed: raise ValueError('Suppression readback did not match request.')
        return sw._result(True, 'Suppression state verified; document not saved.', data={
            'feature_name': feature_name, 'type': kind, 'before': before, 'after': after,
            'configuration': configuration, 'scope': 'active_configuration', 'saved': False,
            'supported_operation': 'suppression_only'})
    except Exception as exc:
        return _fail(sw, str(exc), 'CAD_EDIT_FAILED', document_may_be_modified=changed, saved=False)


@tool(name='edit_feature_definition', description="Edit depth and blind/mid-plane end condition of a Boss/Cut part copy, or suppress supported features. Verifies readback; does not save.", schema=DEFINITION_SCHEMA, operation_class=OperationClass.MUTATE)
def edit_feature_definition(sw, feature_name, expected_type, suppressed=None, expected_suppressed=None, configuration=None, edit_original=False,
                            action='suppression', depth_mm=None, expected_depth_mm=None, end_condition=None, expected_end_condition=None):
    if action == 'extrusion':
        return _edit_definition(sw, feature_name, expected_type, configuration, edit_original, action,
            depth_mm=depth_mm, expected_depth_mm=expected_depth_mm, end_condition=end_condition, expected_end_condition=expected_end_condition)
    if action != 'suppression': return _fail(sw, 'Unsupported feature action.', 'UNSUPPORTED_FEATURE_ACTION', document_may_be_modified=False)
    return _edit_suppression(sw, feature_name, expected_type, suppressed, expected_suppressed, configuration, edit_original, FEATURE_TYPES)


@tool(name='edit_mate', description="Edit a named distance/angle mate driver, or suppress a supported mate, in a verified assembly copy. Rejects driven dimensions. Does not save.", schema=MATE_SCHEMA, operation_class=OperationClass.MUTATE)
def edit_mate(sw, feature_name, expected_type, suppressed=None, expected_suppressed=None, configuration=None, edit_original=False,
              action='suppression', dimension_name=None, value=None, expected_value=None, unit=None):
    if action == 'dimension':
        doc, error = sw.get_active_doc()
        if error: return error
        try:
            if int(com(doc, 'GetType')) != 2: raise ValueError('Active assembly required.')
            feature, kind = _feature(doc, feature_name, expected_type, {'MateDistanceDim', 'MatePlanarAngleDim'})
            if not isinstance(dimension_name, str) or dimension_name.split('@')[1:] != [feature_name]:
                raise ValueError('Exact mate driver name Dn@MateFeature is required.')
            units = {'deg', 'rad'} if kind == 'MatePlanarAngleDim' else {'mm', 'cm', 'm', 'in', 'ft'}
            if unit not in units: raise ValueError('Dimension units do not match the mate type.')
            _number(value); _number(expected_value)
        except Exception as exc: return _fail(sw, str(exc), 'MATE_DIMENSION_EDIT_FAILED', document_may_be_modified=False)
        return set_model_dimension(sw, dimension_name, value, unit, expected_value, configuration, edit_original)
    if action != 'suppression': return _fail(sw, 'Unsupported mate action.', 'UNSUPPORTED_MATE_ACTION', document_may_be_modified=False)
    return _edit_suppression(sw, feature_name, expected_type, suppressed, expected_suppressed, configuration, edit_original, MATE_TYPES, True)


@tool(name='edit_component_pattern', description="Edit instance count or spacing of a LocalLPattern in an assembly copy, or suppress a LocalLPattern/LocalCirPattern. Verifies readback; does not save.", schema=PATTERN_SCHEMA, operation_class=OperationClass.MUTATE)
def edit_component_pattern(sw, feature_name, expected_type, suppressed=None, expected_suppressed=None, configuration=None, edit_original=False,
                           action='suppression', instances=None, expected_instances=None, dimension_name=None, spacing_mm=None, expected_spacing_mm=None):
    if action == 'linear_count':
        return _edit_definition(sw, feature_name, expected_type, configuration, edit_original, action,
                                instances=instances, expected_instances=expected_instances)
    if action == 'spacing_dimension':
        doc, error = sw.get_active_doc()
        if error: return error
        try:
            if int(com(doc, 'GetType')) != 2: raise ValueError('Active assembly required.')
            _feature(doc, feature_name, expected_type, {'LocalLPattern'})
            if not isinstance(dimension_name, str) or dimension_name.split('@')[1:] != [feature_name]:
                raise ValueError('Exact local pattern spacing driver name Dn@Feature is required.')
            if _number(spacing_mm) <= 0: raise ValueError('Spacing must be positive.')
        except Exception as exc: return _fail(sw, str(exc), 'PATTERN_DIMENSION_EDIT_FAILED', document_may_be_modified=False)
        return set_model_dimension(sw, dimension_name, spacing_mm, 'mm', expected_spacing_mm, configuration, edit_original)
    if action != 'suppression': return _fail(sw, 'Unsupported pattern action.', 'UNSUPPORTED_PATTERN_ACTION', document_may_be_modified=False)
    return _edit_suppression(sw, feature_name, expected_type, suppressed, expected_suppressed, configuration, edit_original, PATTERN_TYPES, True)


def _edit_definition(sw, feature_name, expected_type, configuration, edit_original, action, **values):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False; accessed = False; data = None; result = None
    try:
        denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
        if denied: return denied
        _configuration(doc, configuration)
        if list(com(doc, 'GetConfigurationNames') or []) != [configuration]:
            raise ValueError('Definition writes support single-configuration documents only.')
        extrusion = action == 'extrusion'
        if int(com(doc, 'GetType')) != (1 if extrusion else 2): raise ValueError('Wrong document type for definition edit.')
        feature, kind = _feature(doc, feature_name, expected_type, {'Boss', 'Cut'} if extrusion else {'LocalLPattern'})
        if _suppressed(feature): raise ValueError('Unsuppress the target before editing its definition.')
        data = com(feature, 'GetDefinition')
        if data is None: raise ValueError('Feature definition unavailable.')
        if extrusion:
            conditions = {'blind': 0, 'mid_plane': 6}
            if values['end_condition'] not in conditions or values['expected_end_condition'] not in conditions:
                raise ValueError('Only blind/mid-plane end conditions are supported.')
            new_depth = _number(values['depth_mm']) / 1000
            expected_depth = _number(values['expected_depth_mm']) / 1000
            if new_depth <= 0: raise ValueError('Depth must be positive.')
            if bool(com(data, 'BothDirections')) or bool(com(data, 'IsThinFeature')):
                raise ValueError('Bidirectional and thin extrusions are unsupported.')
            before = {'depth_mm': float(com(data, 'GetDepth', True)) * 1000,
                      'end_condition': int(com(data, 'GetEndCondition', True))}
            if before['end_condition'] != conditions[values['expected_end_condition']] or not math.isclose(before['depth_mm'] / 1000, expected_depth, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError('Extrusion definition changed; refresh before editing.')
        else:
            count = values['instances']; expected = values['expected_instances']
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 2 or v > 10000 for v in (count, expected)):
                raise ValueError('Pattern count must be an integer from 2 to 10000.')
            before = {'instances': int(com(data, 'D1TotalInstances'))}
            if before['instances'] != expected: raise ValueError('Pattern instance count changed; refresh before editing.')
        accessed = bool(com(data, 'AccessSelections', doc, None))
        if not accessed: raise ValueError('Feature selections unavailable.')
        changed = True
        if extrusion:
            com(data, 'SetEndCondition', True, conditions[values['end_condition']])
            com(data, 'SetDepth', True, new_depth)
        else: set_com(data, 'D1TotalInstances', count)
        if not com(feature, 'ModifyDefinition', data, doc, None): raise ValueError('Definition modification rejected.')
        accessed = False
        if not _rebuild_checked(doc): raise ValueError('Definition rebuild verification failed.')
        readback = com(feature, 'GetDefinition')
        if extrusion:
            after = {'depth_mm': float(com(readback, 'GetDepth', True)) * 1000,
                     'end_condition': int(com(readback, 'GetEndCondition', True))}
            if after['end_condition'] != conditions[values['end_condition']] or not math.isclose(after['depth_mm'] / 1000, new_depth, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError('Extrusion definition readback differs from request.')
        else:
            after = {'instances': int(com(readback, 'D1TotalInstances'))}
            if after['instances'] != count: raise ValueError('Pattern count readback differs from request.')
        _configuration(doc, configuration)
        result = sw._result(True, 'Feature definition changed and read back; not saved.', data={
            'feature_name': feature_name, 'type': kind, 'action': action, 'before': before, 'after': after,
            'configuration': configuration, 'scope': 'single_configuration_document', 'saved': False})
    except Exception as exc:
        result = _fail(sw, str(exc), 'FEATURE_DEFINITION_EDIT_FAILED', document_may_be_modified=changed, saved=False)
    finally:
        if accessed:
            try: com(data, 'ReleaseSelectionAccess')
            except Exception as exc:
                result = _fail(sw, f'Selection/rollback cleanup failed: {exc}', 'DEFINITION_CLEANUP_FAILED', document_may_be_modified=True, saved=False)
    return result


@tool(name='manage_configurations', description='List existing configurations or explicitly activate one on a verified copy after matching the prior active configuration. Creation/deletion unsupported. Does not save.', schema={'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['inspect', 'activate'], 'default': 'inspect'},
    'name': {'type': 'string'}, 'configuration': {'type': 'string'},
    'edit_original': EDIT_ARGS['edit_original']}, 'required': []}, operation_class=OperationClass.PROJECT_WRITE)
def manage_configurations(sw, action='inspect', name=None, configuration=None, edit_original=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False
    try:
        if action not in {'inspect', 'activate'}: raise ValueError('Only inspect and activate are supported.')
        names = list(com(doc, 'GetConfigurationNames') or [])
        active = str(com(com(com(doc, 'ConfigurationManager'), 'ActiveConfiguration'), 'Name'))
        if action == 'activate':
            if hasattr(sw, 'has_bound_document') and sw.has_bound_document():
                sw.require_bound_active_document()
            denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
            if denied: return denied
            _configuration(doc, configuration)
            if name not in names: raise ValueError('Exact existing target configuration is required.')
            changed = True
            com(doc, 'ShowConfiguration2', name)  # Readback is authoritative, even after False return.
            _configuration(doc, name)
            if not _rebuild_checked(doc): raise ValueError('Activated configuration failed rebuild verification.')
            active = name
            if hasattr(sw, 'bind_active_document'): sw.bind_active_document()
        return sw._result(True, 'Existing configurations inspected/explicit activation verified; not saved.', data={
            'configurations': names, 'active': active, 'saved': False})
    except Exception as exc:
        return _fail(sw, str(exc), 'CONFIGURATION_OPERATION_FAILED', document_may_be_modified=changed, saved=False)


@tool(name='inspect_model_health', description='Read feature error codes and dependency paths without rebuilding. Reports unknown health when APIs are unavailable; not a full geometry/manufacturing validation.', schema={'type': 'object', 'properties': {}, 'required': []}, operation_class=OperationClass.READ)
def inspect_model_health(sw):
    doc, error = sw.get_active_doc()
    if error: return error
    rows = []; unresolved = []
    try:
        for feature in _walk(doc):
            row = {'name': str(com(feature, 'Name')), 'type': str(com(feature, 'GetTypeName2'))}
            try: row['error_code'] = int(com(feature, 'GetErrorCode'))
            except Exception as exc: row['error_code'] = None; unresolved.append(f'{row["name"]}: {exc}')
            rows.append(row)
    except Exception as exc: unresolved.append(str(exc))
    dependencies = inspect_dependencies(doc)
    unresolved.extend(dependencies['unresolved'])
    missing = [row['path'] for row in dependencies['dependencies'] if row['path'] and not Path(row['path']).is_file()]
    errors = [row for row in rows if row['error_code'] not in (None, 0)]
    healthy = False if errors or missing else None if unresolved else True
    return sw._result(True, 'Available model health evidence inspected; no rebuild performed.', data={
        'healthy': healthy, 'features': rows, 'feature_errors': errors, 'missing_dependency_files': missing,
        'dependencies': dependencies, 'complete': not unresolved, 'unresolved': unresolved,
        'coverage': 'feature error codes and dependency file existence only'})


@tool(name='check_interferences', description='Calculate active assembly interferences with current manager options; reports volumes and participating components and cleans up the manager. Does not infer engineering clearance.', schema={'type': 'object', 'properties': {'configuration': EDIT_ARGS['configuration']}, 'required': ['configuration']}, operation_class=OperationClass.STATEFUL_READ)
def check_interferences(sw, configuration):
    doc, error = sw.get_active_doc()
    if error: return error
    manager = None; rows = []; failure = None
    try:
        _configuration(doc, configuration)
        if int(com(doc, 'GetType')) != 2: raise ValueError('Interference detection requires an assembly.')
        manager = com(doc, 'InterferenceDetectionManager')
        if manager is None: raise ValueError('Interference detection manager is unavailable.')
        options = {}; unavailable_options = []
        for key in ('IgnoreHiddenBodies', 'IncludeMultibodyPartInterferences', 'ShowIgnoredInterferences', 'TreatCoincidenceAsInterference', 'TreatSubAssembliesAsComponents'):
            try: options[key] = bool(com(manager, key))
            except Exception: unavailable_options.append(key)
        for interference in com(manager, 'GetInterferences') or []:
            volume = float(com(interference, 'Volume'))
            if not math.isfinite(volume) or volume < 0: raise ValueError('Invalid interference volume.')
            rows.append({'volume_m3': volume, 'volume_mm3': volume * 1e9,
                'components': [str(com(c, 'Name2')) for c in com(interference, 'Components') or []],
                'api_is_fastener': bool(com(interference, 'IsFastener'))})
        _configuration(doc, configuration)
    except Exception as exc: failure = str(exc)
    finally:
        if manager is not None:
            try: com(manager, 'Done')
            except Exception as exc: failure = f'{failure or ""} Interference cleanup failed: {exc}'.strip()
    if failure: return _fail(sw, failure, 'INTERFERENCE_INSPECTION_FAILED', partial_interferences=rows)
    return sw._result(True, 'Interferences calculated with reported manager settings.', data={
        'configuration': configuration, 'interferences': rows, 'count': len(rows),
        'options': options, 'unavailable_options': unavailable_options,
        'complete': not unavailable_options, 'coverage': 'active assembly/current detection options; no minimum clearance check'})


@tool(name='replace_structural_profile', description='Replace the library profile of one WeldMemberFeat in a single-configuration verified part copy; requires exact prior profile path, verifies definition readback/rebuild. Does not save.', schema={'type': 'object', 'properties': {
    'feature_name': {'type': 'string'}, 'expected_profile_path': {'type': 'string'},
    'profile_path': {'type': 'string'}, **EDIT_ARGS},
    'required': ['feature_name', 'expected_profile_path', 'profile_path', 'configuration']}, operation_class=OperationClass.MUTATE)
def replace_structural_profile(sw, feature_name, expected_profile_path, profile_path, configuration, edit_original=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False; accessed = False; definition = None; result = None
    try:
        denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
        if denied: return denied
        _configuration(doc, configuration)
        if int(com(doc, 'GetType')) != 1: raise ValueError('Structural profile replacement requires a part.')
        # ModifyDefinition has no configuration scope parameter. Reject ambiguity.
        if list(com(doc, 'GetConfigurationNames') or []) != [configuration]:
            raise ValueError('Profile replacement supports a single-configuration part only.')
        feature, kind = _feature(doc, feature_name, 'WeldMemberFeat', {'WeldMemberFeat'})
        if not isinstance(profile_path, str) or not profile_path.strip(): raise ValueError('Profile path is required.')
        path = Path(profile_path).expanduser().resolve()
        if path.suffix.casefold() not in {'.sldlfp', '.sldflp'} or not path.is_file():
            raise ValueError('Existing SolidWorks weldment library profile file required.')
        definition = com(feature, 'GetDefinition')
        before = str(com(definition, 'WeldmentProfilePath'))
        if before != expected_profile_path: raise ValueError('Profile path changed; refresh before editing.')
        if str(com(definition, 'ConfigurationName')): raise ValueError('Configured custom profiles are not supported.')
        accessed = bool(com(definition, 'AccessSelections', doc, None))
        if not accessed: raise ValueError('Structural definition selections unavailable.')
        changed = True
        set_com(definition, 'WeldmentProfilePath', str(path))
        if not com(feature, 'ModifyDefinition', definition, doc, None): raise ValueError('Profile modification rejected.')
        accessed = False  # ModifyDefinition releases rollback/selection access.
        if not _rebuild_checked(doc): raise ValueError('Profile rebuild verification failed.')
        after = str(com(com(feature, 'GetDefinition'), 'WeldmentProfilePath'))
        if Path(after).resolve() != path: raise ValueError('Profile readback differs from request.')
        _configuration(doc, configuration)
        result = sw._result(True, 'Structural profile changed and read back; not saved.', data={
            'feature_name': feature_name, 'before': before, 'after': after, 'configuration': configuration,
            'scope': 'single_configuration_document', 'saved': False})
    except Exception as exc:
        result = _fail(sw, str(exc), 'STRUCTURAL_PROFILE_EDIT_FAILED', document_may_be_modified=changed, saved=False)
    finally:
        if accessed:
            try: com(definition, 'ReleaseSelectionAccess')
            except Exception as exc:
                result = _fail(sw, f'Structural definition selection/rollback cleanup failed: {exc}',
                    'STRUCTURAL_PROFILE_CLEANUP_FAILED', document_may_be_modified=True, saved=False)
    return result


def _resolve(doc, reference):
    if not isinstance(reference, dict): raise ValueError('Reference must be an object.')
    if str(com(doc, 'GetPathName')).casefold() != str(reference.get('path', '')).casefold():
        raise ValueError('Persistent reference belongs to another document path.')
    _configuration(doc, reference.get('configuration'))
    payload = base64.b64decode(reference.get('base64', ''), validate=True)
    if not payload or len(payload) > 65536: raise ValueError('Invalid persistent reference size.')
    status = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    array = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_UI1, payload)
    obj = com(com(doc, 'Extension'), 'GetObjectByPersistReference3', array, status)
    if int(status.value) != 0 or obj is None: raise ValueError(f'Persistent target unavailable (state {status.value}).')
    return obj


@tool(name='create_persistent_reference', description='Create and immediately resolve a document/configuration-bound persistent reference to one exact existing feature. Returns portable base64 bytes; no CAD save.', schema={'type': 'object', 'properties': {
    'feature_name': {'type': 'string'}, 'configuration': EDIT_ARGS['configuration']}, 'required': ['feature_name', 'configuration']}, operation_class=OperationClass.READ)
def create_persistent_reference(sw, feature_name, configuration):
    doc, error = sw.get_active_doc()
    if error: return error
    try:
        _configuration(doc, configuration)
        if not com(doc, 'GetPathName'): raise ValueError('Saved document path required for a bound reference.')
        feature, kind = _feature(doc, feature_name)
        raw = com(com(doc, 'Extension'), 'GetPersistReference3', feature)
        reference = {'path': str(com(doc, 'GetPathName')), 'configuration': configuration,
                     'base64': base64.b64encode(bytes(raw)).decode('ascii')}
        resolved = _resolve(doc, reference)
        if str(com(resolved, 'Name')) != feature_name or str(com(resolved, 'GetTypeName2')) != kind:
            raise ValueError('Persistent reference roundtrip returned a different feature.')
        return sw._result(True, 'Feature persistent reference created and resolved.', data={'reference': reference, 'feature_name': feature_name, 'type': kind})
    except Exception as exc: return _fail(sw, str(exc), 'PERSISTENT_REFERENCE_FAILED')


@tool(name='resolve_persistent_reference', description='Resolve a base64 persistent reference only in its exact document path and active configuration; reports missing/deleted targets without substituting another feature.', schema={'type': 'object', 'properties': {'reference': {'type': 'object', 'properties': {
    'path': {'type': 'string'}, 'configuration': {'type': 'string'}, 'base64': {'type': 'string'}},
    'required': ['path', 'configuration', 'base64']}}, 'required': ['reference']}, operation_class=OperationClass.READ)
def resolve_persistent_reference(sw, reference):
    doc, error = sw.get_active_doc()
    if error: return error
    try:
        obj = _resolve(doc, reference)
        return sw._result(True, 'Persistent feature reference resolved.', data={
            'feature_name': str(com(obj, 'Name')), 'type': str(com(obj, 'GetTypeName2')), 'state': 0})
    except Exception as exc: return _fail(sw, str(exc), 'PERSISTENT_REFERENCE_UNRESOLVED')


@tool(name='inspect_holes_and_fasteners', description='Inventory native HoleWzd/HoleSeries features in the active document. Does not identify hardware from diameter/name or infer bolt fit; assembly child documents are not traversed.', schema={'type': 'object', 'properties': {}, 'required': []}, operation_class=OperationClass.READ)
def inspect_holes_and_fasteners(sw):
    doc, error = sw.get_active_doc()
    if error: return error
    rows = []; unresolved = []
    try:
        for feature in _walk(doc):
            kind = str(com(feature, 'GetTypeName2'))
            if kind in {'HoleWzd', 'HoleSeries'}:
                rows.append({'name': str(com(feature, 'Name')), 'type': kind})
    except Exception as exc: unresolved.append(str(exc))
    return sw._result(True, 'Native hole feature inventory inspected; fastener identity remains unresolved.', data={
        'hole_features': rows, 'identified_fasteners': [], 'hardware_identification_complete': False,
        'complete': not unresolved, 'unresolved': unresolved,
        'coverage': 'active document native hole features; no cylindrical-face recognition or child-document traversal',
        'missing_evidence': ['Fastener standard/part number metadata and geometric placement validation']})


@tool(name='manage_external_references', description='Inspect dependency paths and available in-context reference count. Lock/unlock/break/relink are rejected because status/configuration-scoped readback is not yet validated.', schema={'type': 'object', 'properties': {'action': {'type': 'string', 'enum': ['inspect'], 'default': 'inspect'}}, 'required': []}, operation_class=OperationClass.READ)
def manage_external_references(sw, action='inspect'):
    doc, error = sw.get_active_doc()
    if error: return error
    if action != 'inspect': return _fail(sw, 'Only reference inspection is supported; no write attempted.', 'UNSUPPORTED_REFERENCE_ACTION', document_may_be_modified=False)
    data = inspect_dependencies(doc)
    try: data['in_context_reference_count'] = int(com(com(doc, 'Extension'), 'ListExternalFileReferencesCount'))
    except Exception as exc:
        data['in_context_reference_count'] = None; data['unresolved'].append(str(exc)); data['complete'] = False
    data['reference_statuses_verified'] = False
    return sw._result(True, 'External reference evidence inspected; no CAD changes.', data=data)
