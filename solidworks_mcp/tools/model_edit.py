"""Read existing CAD drivers and edit only explicitly isolated documents."""
from __future__ import annotations

import math
from pathlib import Path
import re

import pythoncom

from ..comutil import com
from ..core.policy import OperationClass
from ..inspection.documents import inspect_feature_tree
from ..registry import tool
from .project_copy import _fail, require_editable_copy

EDIT_ARGS = {'configuration': {'type': 'string', 'description': 'Expected active configuration'},
             'edit_original': {'type': 'boolean', 'default': False,
                 'description': 'Edit the original; path policy still applies'}}
UNITS = {'mm': .001, 'cm': .01, 'm': 1., 'in': .0254, 'ft': .3048,
         'deg': math.pi / 180, 'rad': 1., 'scalar': 1.}


def _configuration(doc, expected):
    active = str(com(com(com(doc, 'ConfigurationManager'), 'ActiveConfiguration'), 'Name'))
    if not isinstance(expected, str) or expected != active:
        raise ValueError(f'Expected active configuration {expected!r}, found {active!r}.')
    return active


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Value must be a finite number.')
    return float(value)


def _factor(dim, unit):
    kind = int(com(dim, 'GetType'))
    # IDimension.GetType returns swDimensionParamType_e, NOT display types.
    allowed = {'deg', 'rad'} if kind == 1 else {'scalar'} if kind == 2 else set(UNITS) - {'deg', 'rad', 'scalar'} if kind == 0 else set()
    if unit not in allowed:
        raise ValueError(f'Unit {unit!r} is incompatible with dimension type {kind}.')
    return UNITS[unit]


def _dim_value(dim):
    result = com(dim, 'GetSystemValue3', 1, None)
    if not isinstance(result, (tuple, list)) or len(result) != 1:
        raise ValueError('Cannot read the dimension in the active configuration.')
    return _number(result[0])


def _rebuild_checked(doc):
    if not com(doc, 'EditRebuild3'):
        return False
    feature = com(doc, 'FirstFeature')
    retained = []
    while feature is not None:
        retained.append(feature)
        if len(retained) > 10000:
            raise ValueError('Feature verification limit exceeded.')
        if int(com(feature, 'GetErrorCode')) != 0:
            return False
        feature = com(feature, 'GetNextFeature')
    return True


def _equations(doc):
    manager = com(doc, 'GetEquationMgr')
    rows = []
    if manager is not None:
        for index in range(int(com(manager, 'GetCount'))):
            expression = com(manager, 'Equation', index)
            rows.append({'index': index, 'expression': expression,
                         'global_variable': bool(com(manager, 'GlobalVariable', index)),
                         'disabled': bool(com(manager, 'Disabled', index))})
    return manager, rows


def _lhs(expression):
    match = re.match(r'^\s*"([^"]+)"\s*=', expression or '')
    if not match:
        raise ValueError('Unsupported existing equation format.')
    return match.group(1)


def _canonical_dimension(name):
    # A FullName can carry @Document in addition to D1@Feature.
    return '@'.join(name.split('@')[:2]).casefold()


@tool(name='list_model_parameters', description=(
    'Read existing feature/display dimensions and equation definitions in the active document. '
    'Reports partial coverage; hidden/API-inaccessible drivers are not invented.'),
    schema={'type': 'object', 'properties': {}, 'required': []}, operation_class=OperationClass.READ)
def list_model_parameters(sw):
    doc, error = sw.get_active_doc()
    if error: return error
    try:
        tree = inspect_feature_tree(doc, max_depth=16)
        manager, equations = _equations(doc)
        dimensions = {}
        unresolved = list(tree['unresolved'])
        def visit(features):
            for feature in features:
                for row in feature['parameters']:
                    name = row['name']
                    if name in dimensions: continue
                    try:
                        dim = com(doc, 'Parameter', name)
                        kind = int(com(dim, 'GetType'))
                        unit = 'deg' if kind == 1 else 'scalar' if kind == 2 else 'mm' if kind == 0 else None
                        value = _dim_value(dim)
                        controlled = any(_canonical_dimension(_lhs(eq['expression'])) == _canonical_dimension(name)
                                         for eq in equations if not eq['disabled'])
                        dimensions[name] = {'name': name, 'feature': feature['name'], 'dimension_type': kind,
                            'value': value / UNITS[unit] if unit else None, 'unit': unit, 'system_value': value,
                            'read_only': bool(com(dim, 'ReadOnly')), 'driven_state': int(com(dim, 'DrivenState')),
                            'equation_controlled': controlled}
                    except Exception as exc:
                        unresolved.append(f'{name}: {exc}')
                visit(feature['children'])
        visit(tree['features'])
        return sw._result(True, 'Existing model drivers inspected; no CAD changes.', data={
            'path': com(doc, 'GetPathName'),
            'configuration': com(com(com(doc, 'ConfigurationManager'), 'ActiveConfiguration'), 'Name'),
            'dimensions': list(dimensions.values()), 'equations': equations,
            'complete': not unresolved, 'coverage': 'feature display dimensions and equation manager',
            'unresolved': unresolved})
    except Exception as exc:
        return _fail(sw, str(exc), 'PARAMETER_INSPECTION_FAILED')


@tool(name='set_model_dimension', description=(
    'Set one existing driving dimension in the ACTIVE configuration of a verified copy; '
    'requires expected old value and explicit units, rebuilds and reads back. Does not save.'),
    schema={'type': 'object', 'properties': {
        'name': {'type': 'string'}, 'value': {'type': 'number'}, 'unit': {'type': 'string', 'enum': list(UNITS)},
        'expected_value': {'type': 'number'}, **EDIT_ARGS},
        'required': ['name', 'value', 'unit', 'expected_value', 'configuration']},
    operation_class=OperationClass.MUTATE)
def set_model_dimension(sw, name, value, unit, expected_value, configuration, edit_original=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False
    try:
        denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
        if denied: return denied
        active = _configuration(doc, configuration)
        if not isinstance(name, str) or not name.strip(): raise ValueError('An exact dimension name is required.')
        dim = com(doc, 'Parameter', name)
        if dim is None: raise ValueError(f'Dimension not found: {name}')
        factor = _factor(dim, unit)
        new = _number(value) * factor
        expected = _number(expected_value) * factor
        if int(com(dim, 'GetType')) == 2 and not new.is_integer(): raise ValueError('Integer dimension requires a whole number.')
        if not math.isfinite(new) or not math.isfinite(expected): raise ValueError('Converted value must be finite.')
        before = _dim_value(dim)
        if not math.isclose(before, expected, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError('Dimension value changed; refresh before editing.')
        if com(dim, 'ReadOnly') or int(com(dim, 'DrivenState')) != 2:
            raise ValueError('Dimension is read-only, driven or not confirmed driving.')
        _, equations = _equations(doc)
        if any(_canonical_dimension(_lhs(row['expression'])) == _canonical_dimension(name)
               for row in equations if not row['disabled']):
            raise ValueError('Dimension is equation-controlled; edit its equation or upstream variable.')
        changed = True  # Even a rejected API write may have side effects; never promise rollback.
        status = int(com(dim, 'SetSystemValue3', new, 1, None))
        if status != 0: raise ValueError(f'SolidWorks rejected dimension write (status {status}).')
        rebuilt = _rebuild_checked(doc)
        after = _dim_value(dim)
        if not rebuilt or not math.isclose(after, new, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError('Rebuild/read-back did not verify the requested dimension.')
        _configuration(doc, active)
        return sw._result(True, 'Existing dimension changed and read back; document not saved.', data={
            'name': name, 'before': before / factor, 'after': after / factor, 'unit': unit,
            'configuration': active, 'scope': 'active_configuration', 'saved': False,
            'impact': 'All assembly occurrences sharing this document and configuration use the changed geometry.'})
    except Exception as exc:
        return _fail(sw, str(exc), 'DIMENSION_EDIT_FAILED', document_may_be_modified=changed, saved=False)


def _put_equation(manager, index, text):
    # Exact indexed PROPERTYPUT from the installed type library. No delete/re-add.
    dispatch_id = manager._oleobj_.GetIDsOfNames('Equation')
    manager._oleobj_.Invoke(dispatch_id, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, index, text)


@tool(name='update_model_equation', description=(
    'Update an existing equation RHS after matching its old expression. Preserves LHS, '
    'targets active configuration and verifies evaluation/rebuild. Does not save.'),
    schema={'type': 'object', 'properties': {
        'index': {'type': 'integer', 'minimum': 0}, 'rhs': {'type': 'string'},
        'expected_expression': {'type': 'string'}, **EDIT_ARGS},
        'required': ['index', 'rhs', 'expected_expression', 'configuration']},
    operation_class=OperationClass.MUTATE)
def update_model_equation(sw, index, rhs, expected_expression, configuration, edit_original=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False
    try:
        denied = require_editable_copy(sw, com(doc, 'GetPathName'), edit_original=edit_original)
        if denied: return denied
        active = _configuration(doc, configuration)
        if not isinstance(index, int) or isinstance(index, bool) or index < 0: raise ValueError('Invalid equation index.')
        if not isinstance(rhs, str) or not rhs.strip() or len(rhs) > 2000 or any(x in rhs for x in ('=', '\n', '\r', ';')):
            raise ValueError('RHS must be one non-empty expression without additional assignments.')
        if rhs.strip().casefold() in {'nan', 'inf', '-inf', 'infinity'}: raise ValueError('Expression must be finite.')
        manager, equations = _equations(doc)
        if index >= len(equations): raise ValueError('Equation index does not exist.')
        row = equations[index]
        if row['expression'] != expected_expression: raise ValueError('Equation changed; refresh before editing.')
        if row['disabled']: raise ValueError('Disabled equations cannot be updated by this tool.')
        text = f'"{_lhs(row["expression"])}" = {rhs.strip()}'
        configs = com(doc, 'GetConfigurationNames') or []
        changed = True
        if len(configs) == 1:
            _put_equation(manager, index, text)
        else:
            status = com(manager, 'SetEquationAndConfigurationOption', index, text, 1, None)
            if status != index:
                raise ValueError('Configuration-scoped equation update failed; no unsafe all-configurations fallback used.')
        com(manager, 'EvaluateAll')
        rebuilt = _rebuild_checked(doc)
        after = com(manager, 'Equation', index)
        status = int(com(manager, 'Status', index))
        if not rebuilt or re.sub(r'\s+', '', after) != re.sub(r'\s+', '', text) or status != 0:
            raise ValueError(f'Equation evaluation/rebuild/read-back failed (status {status}).')
        _configuration(doc, active)
        return sw._result(True, 'Existing equation updated and evaluated; document not saved.', data={
            'index': index, 'before': expected_expression, 'after': after, 'configuration': active,
            'resolved_value': com(manager, 'Value', index), 'scope': 'active_configuration', 'saved': False})
    except Exception as exc:
        return _fail(sw, str(exc), 'EQUATION_EDIT_FAILED', document_may_be_modified=changed, saved=False)


@tool(name='replace_component', description=(
    'Replace an exact occurrence in a verified copied assembly with another verified copied '
    'model. Defaults to one occurrence; optionally all occurrences of that document/configuration. '
    'Checks paths after rebuild; does not save or guarantee mate repair.'),
    schema={'type': 'object', 'properties': {
        'component_name': {'type': 'string'}, 'replacement_path': {'type': 'string'},
        'expected_path': {'type': 'string'}, 'configuration': {'type': 'string'},
        'all_instances': {'type': 'boolean', 'default': False}, 'reattach_mates': {'type': 'boolean', 'default': True},
        'edit_original': EDIT_ARGS['edit_original']},
        'required': ['component_name', 'replacement_path', 'expected_path', 'configuration']},
    operation_class=OperationClass.MUTATE)
def replace_component(sw, component_name, replacement_path, expected_path, configuration,
                      all_instances=False, reattach_mates=True, edit_original=False):
    doc, error = sw.get_active_doc()
    if error: return error
    changed = False
    try:
        if not all(isinstance(x, bool) for x in (all_instances, reattach_mates, edit_original)):
            raise ValueError('Flags must be boolean.')
        if com(doc, 'GetType') != 2: raise ValueError('Active document must be an assembly.')
        for path in [com(doc, 'GetPathName'), replacement_path]:
            denied = require_editable_copy(sw, path, edit_original=edit_original)
            if denied: return denied
        replacement = Path(replacement_path).resolve()
        expected = Path(expected_path).resolve()
        if not replacement.is_file() or replacement.suffix.casefold() not in {'.sldprt', '.sldasm'}:
            raise ValueError('Replacement must be a saved native part or assembly.')
        if replacement == expected: raise ValueError('Replacement is already the selected source document.')
        configs = com(sw.app, 'GetConfigurationNames', str(replacement)) or []
        if not isinstance(configuration, str) or configuration not in configs:
            raise ValueError('Replacement does not contain the requested configuration.')
        components = list(com(doc, 'GetComponents', True) or [])
        matches = [c for c in components if com(c, 'Name2') == component_name]
        if len(matches) != 1: raise ValueError('Exact, unambiguous component Name2 is required.')
        selected = matches[0]
        if '/' in component_name:
            raise ValueError('Nested occurrence: activate its immediate owning subassembly before replacement.')
        if Path(com(selected, 'GetPathName')).resolve() != expected:
            raise ValueError('Component reference changed; refresh before replacement.')
        if com(selected, 'ReferencedConfiguration') != configuration:
            raise ValueError('Expected component configuration does not match. Replacement uses name matching.')
        before = {com(c, 'Name2'): Path(com(c, 'GetPathName')).resolve() for c in components}
        before_configurations = {com(c, 'Name2'): com(c, 'ReferencedConfiguration') for c in components}
        if all_instances and any(Path(com(c, 'GetPathName')).resolve() == expected and
                                 com(c, 'ReferencedConfiguration') != configuration for c in components):
            raise ValueError('All-instance replacement spans different configurations; replace explicitly selected occurrences instead.')
        affected = {name for name, path in before.items() if path == expected} if all_instances else {component_name}
        com(doc, 'ClearSelection2', True)
        select_data = com(com(doc, 'SelectionManager'), 'CreateSelectData')
        if not com(selected, 'Select4', False, select_data, False): raise ValueError('Component selection failed.')
        changed = True
        success = com(doc, 'ReplaceComponents2', str(replacement), configuration, all_instances, 1, reattach_mates)
        rebuilt = _rebuild_checked(doc)
        after_components = list(com(doc, 'GetComponents', True) or [])
        after = {com(c, 'Name2'): Path(com(c, 'GetPathName')).resolve() for c in after_components}
        after_configurations = {com(c, 'Name2'): com(c, 'ReferencedConfiguration') for c in after_components}
        old_config_count = sum(path == replacement and before_configurations[name] == configuration
                               for name, path in before.items())
        new_config_count = sum(path == replacement and after_configurations[name] == configuration
                               for name, path in after.items())
        configurations_match = new_config_count == old_config_count + len(affected)
        # Names may change during replacement. Unaffected occurrences must stay
        # intact, and exactly the intended number of references must be replaced.
        remaining = sum(path == expected for path in after.values())
        prior = sum(path == expected for path in before.values())
        replacement_before = sum(path == replacement for path in before.values())
        replacement_after = sum(path == replacement for path in after.values())
        untouched = all(after.get(name) == path and after_configurations.get(name) == before_configurations[name]
                        for name, path in before.items() if name not in affected)
        if not success or not rebuilt or not untouched or not configurations_match or remaining != prior - len(affected) or replacement_after != replacement_before + len(affected):
            raise ValueError('Replacement/rebuild did not verify the intended occurrence scope.')
        return sw._result(True, 'Component reference replaced and scope verified; inspect mates before saving.', data={
            'before': str(expected), 'after': str(replacement), 'affected_occurrences': sorted(affected),
            'scope': 'all_instances' if all_instances else 'selected_occurrence', 'saved': False,
            'mate_validation': 'rebuild checked; geometric mate correctness requires inspection'})
    except Exception as exc:
        return _fail(sw, str(exc), 'COMPONENT_REPLACE_FAILED', document_may_be_modified=changed, saved=False)
    finally:
        try: com(doc, 'ClearSelection2', True)
        except Exception: pass
