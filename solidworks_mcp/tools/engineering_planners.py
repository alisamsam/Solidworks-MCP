"""CAD-independent concept calculations. No geometry or regulatory approval."""
import math
from ..registry import tool
from ..core.policy import OperationClass
from ..constants import SwErrors


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a finite positive number.')
    return value


def _reply(sw, missing, **data):
    return sw._result(True, 'Concept calculation; missing inputs require engineering review.' if missing else
        'Concept calculated; CAD geometry and compliance remain unverified.', data={
        'status': 'needs_inputs' if missing else 'calculated', 'geometry_verified': False,
        'compliance_verified': False, 'missing_inputs': missing,
        'missing_questions': [f'Please specify {name}.' for name in missing], **data})


def _error(sw, error):
    return sw._result(False, str(error), SwErrors.swInvalidInput, {'code': 'VALIDATION_FAILED'})


@tool(name='plan_stair', description='Calculate a stair concept from explicit riser count, tread and landing inputs; does not create CAD or certify compliance.',
    schema={'type': 'object', 'properties': {
        'total_height_mm': {'type': 'number'}, 'riser_count': {'type': 'integer'},
        'tread_depth_mm': {'type': 'number'}, 'width_mm': {'type': 'number'},
        'landing_lengths_mm': {'type': 'array', 'items': {'type': 'number'}}}, 'required': []},
    operation_class=OperationClass.READ)
def plan_stair(sw, total_height_mm=None, riser_count=None, tread_depth_mm=None, width_mm=None, landing_lengths_mm=None):
    try:
        values = locals().copy(); values.pop('sw')
        missing = [key for key, value in values.items() if value is None]
        for key in ('total_height_mm', 'tread_depth_mm', 'width_mm'):
            if values[key] is not None: _positive(values[key], key)
        if riser_count is not None and (type(riser_count) is not int or riser_count < 2):
            raise ValueError('riser_count must be an integer >= 2.')
        if landing_lengths_mm is not None:
            if not isinstance(landing_lengths_mm, list): raise ValueError('landing_lengths_mm must be a list; [] means no landings.')
            for length in landing_lengths_mm: _positive(length, 'landing length')
        if missing: return _reply(sw, missing, inputs=values)
        riser = total_height_mm / riser_count
        treads = riser_count - 1
        return _reply(sw, [], inputs=values, riser_height_mm=riser, tread_count=treads,
            developed_run_mm=treads * tread_depth_mm + sum(landing_lengths_mm),
            flight_angle_deg=math.degrees(math.atan2(riser, tread_depth_mm)),
            comfort_expression_2r_plus_t_mm=2 * riser + tread_depth_mm,
            assumptions=['Upper finished floor is final tread; landing lengths are additional developed travel.',
                'Landing elevations, flight distribution, headroom, loads and supports require separate design.'])
    except (ValueError, TypeError) as error: return _error(sw, error)


@tool(name='plan_railing', description='Calculate railing post spacing with an explicit height datum; no structural or CAD verification.',
    schema={'type': 'object', 'properties': {'clear_height_mm': {'type': 'number'},
        'height_reference': {'type': 'string', 'enum': ['finished_floor', 'stair_nosing_line']},
        'path_length_mm': {'type': 'number'}, 'max_post_spacing_mm': {'type': 'number'},
        'geometry_parameters': {'type': 'object'}}, 'required': []}, operation_class=OperationClass.READ)
def plan_railing(sw, clear_height_mm=None, height_reference=None, path_length_mm=None, max_post_spacing_mm=None, geometry_parameters=None):
    try:
        values = dict(clear_height_mm=clear_height_mm, height_reference=height_reference,
            path_length_mm=path_length_mm, max_post_spacing_mm=max_post_spacing_mm)
        missing = [key for key, value in values.items() if value is None]
        for key, value in values.items():
            if key != 'height_reference' and value is not None: _positive(value, key)
        if height_reference is not None and height_reference not in ('finished_floor', 'stair_nosing_line'):
            raise ValueError('height_reference must be finished_floor or stair_nosing_line; height is measured vertically.')
        if geometry_parameters is not None and not isinstance(geometry_parameters, dict):
            raise ValueError('geometry_parameters must be an object.')
        data = {'inputs': values, 'geometry_parameters': geometry_parameters or {}, 'height_direction': 'vertical',
            'open_design_questions': ['Specify infill, sections, corner layout, end conditions, anchorage and design loads.']}
        if not missing:
            bays = math.ceil(path_length_mm / max_post_spacing_mm)
            data.update(bay_count=bays, post_count=bays + 1, post_spacing_mm=path_length_mm / bays,
                assumptions=['Single straight or developed path with posts at both ends; corners need separate placement.'])
        return _reply(sw, missing, **data)
    except (ValueError, TypeError) as error: return _error(sw, error)


@tool(name='plan_segments', description='Calculate length-based concept segmentation from caller-supplied transport and galvanizing limits; invents no joints.',
    schema={'type': 'object', 'properties': {'total_length_mm': {'type': 'number'},
        'transport_max_length_mm': {'type': 'number'}, 'galvanizing_max_length_mm': {'type': 'number'},
        'joint_constraints': {'type': 'object'}}, 'required': []}, operation_class=OperationClass.READ)
def plan_segments(sw, total_length_mm=None, transport_max_length_mm=None, galvanizing_max_length_mm=None, joint_constraints=None):
    try:
        values = dict(total_length_mm=total_length_mm, transport_max_length_mm=transport_max_length_mm,
            galvanizing_max_length_mm=galvanizing_max_length_mm)
        missing = [key for key, value in values.items() if value is None]
        for key, value in values.items():
            if value is not None: _positive(value, key)
        if joint_constraints is not None and not isinstance(joint_constraints, dict): raise ValueError('joint_constraints must be an object.')
        data = dict(inputs=values, joint_constraints=joint_constraints or {}, joint_designs=[],
            open_design_questions=['Confirm width, height, mass, lifting orientation, bath envelope, supports and joint load transfer.'])
        if not missing:
            limit = min(transport_max_length_mm, galvanizing_max_length_mm)
            count = math.ceil(total_length_mm / limit)
            if count > 10000: raise ValueError('Concept exceeds 10000 segments.')
            data.update(segment_count=count, segment_lengths_mm=[total_length_mm / count] * count,
                governing_length_limit_mm=limit, proposed_break_positions_mm=[total_length_mm * i / count for i in range(1, count)])
        return _reply(sw, missing, **data)
    except (ValueError, TypeError) as error: return _error(sw, error)


@tool(name='review_galvanizing', description='Review explicitly supplied cavity facts and immersion orientation; no automatic holes, geometry verification or compliance approval.',
    schema={'type': 'object', 'properties': {'members': {'type': 'array', 'items': {'type': 'object'}},
        'immersion_orientation': {'type': 'string'}, 'provider_document': {'type': 'string'}}, 'required': []},
    operation_class=OperationClass.READ)
def review_galvanizing(sw, members=None, immersion_orientation=None, provider_document=None):
    try:
        missing = []
        if members is None: missing.append('members')
        elif not isinstance(members, list) or any(not isinstance(row, dict) for row in members):
            raise ValueError('members must be a list of cavity fact objects.')
        if not immersion_orientation or not isinstance(immersion_orientation, str): missing.append('immersion_orientation')
        if not provider_document: missing.append('provider_document')
        findings = []
        ids = set()
        for index, row in enumerate(members or []):
            identifier = row.get('id')
            if not isinstance(identifier, str) or not identifier.strip() or identifier in ids:
                raise ValueError('Each member requires a unique non-empty id.')
            ids.add(identifier)
            if type(row.get('hollow')) is not bool: missing.append(f'{identifier}.hollow')
            if row.get('hollow') is True:
                for field in ('vent_open', 'drain_open', 'connected_to_exterior', 'extreme_end_openings_confirmed'):
                    if field not in row or type(row[field]) is not bool: missing.append(f'{identifier}.{field}')
                    elif row[field] is False:
                        findings.append({'member': identifier, 'rule': field, 'status': 'requires_review',
                            'message': 'Hollow cavity needs a confirmed vent/drain route to exterior at immersion extremes.'})
                if not isinstance(row.get('provider_detail'), str) or not row['provider_detail'].strip():
                    missing.append(f'{identifier}.provider_detail')
                dimensions = row.get('opening_dimensions_mm')
                if not isinstance(dimensions, list) or not dimensions:
                    missing.append(f'{identifier}.opening_dimensions_mm')
                else:
                    for dimension in dimensions: _positive(dimension, f'{identifier}.opening_dimensions_mm')
                if not isinstance(row.get('opening_locations'), str) or not row['opening_locations'].strip():
                    missing.append(f'{identifier}.opening_locations')
        return _reply(sw, missing, findings=findings, immersion_orientation=immersion_orientation,
            provider_document=provider_document, automatic_hole_placements=[],
            basis='Caller-supplied facts only; cavity topology and orientation are not extracted from CAD.',
            open_design_questions=['Confirm processed subassemblies, lifting, sealed overlaps, surface preparation, distortion and structural effects.',
                'Match each opening count, location and dimension to one provider detail; resolve conflicting tables with the provider.'])
    except (ValueError, TypeError) as error: return _error(sw, error)


@tool(name='plan_stair_turn',description='Plan explicit landing or equal-angle winder transition; separates transition element count from rises. Concept only, no CAD/structural validation.',
      schema={'type':'object','properties':{'turn_angle_deg':{'type':'number'},
       'transition_type':{'type':'string','enum':['landing','winders']},'element_count':{'type':'integer'}},
       'required':['turn_angle_deg','transition_type','element_count']},operation_class=OperationClass.READ)
def plan_stair_turn(sw,turn_angle_deg,transition_type,element_count):
    from ..stair_recipe import turn_concept
    try:return _reply(sw,[],**turn_concept(turn_angle_deg,transition_type,element_count))
    except (ValueError,TypeError) as error:return _error(sw,error)
