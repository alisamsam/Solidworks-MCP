"""Expose packaged expert knowledge without executing CAD or accepting file paths."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
EXPERT = ROOT / 'solidworks-2025-expert'
URI_PREFIX = 'solidworks://guides/'

TOPIC_TOOLS = {
    'workflow/part': ('create_new_part', 'create_sketch', 'draw_rectangle', 'draw_circle',
                      'add_sketch_dimension', 'add_sketch_relation', 'get_sketch_relations',
                      'close_sketch', 'extrude_sketch', 'cut_extrude', 'linear_pattern',
                      'fillet_edges', 'list_features', 'list_planar_faces', 'get_mass_properties'),
    'workflow/assembly': ('list_open_documents', 'bind_active_document', 'list_components',
                          'inspect_document', 'create_new_assembly', 'insert_component',
                          'list_component_faces', 'mate_coincident', 'mate_concentric',
                          'mate_distance', 'list_mates', 'list_standard_parts',
                          'get_standard_part_sizes', 'insert_standard_part'),
    'workflow/weldment': ('create_3d_sketch', 'draw_line', 'close_sketch', 'list_weldment_profiles',
                          'create_structural_member', 'list_planar_faces', 'list_body_edges',
                          'trim_weldment_members', 'create_weldment_end_cap', 'create_weldment_gusset',
                          'create_cosmetic_weld_bead', 'get_cut_list', 'get_mass_properties'),
    'workflow/drawing': ('get_cut_list', 'add_standard_3_view', 'list_drawing_views',
                         'insert_cut_list_table', 'insert_marked_dimensions', 'add_drawing_dimension',
                         'auto_balloon', 'save_document', 'export_step', 'export_face_to_dxf',
                         'get_sheet_metal_info', 'export_flat_pattern'),
    'workflow/learning': (),
    'workflow/operating': ('connect_solidworks', 'get_solidworks_info', 'list_open_documents',
                           'inspect_document', 'bind_active_document', 'get_sketch_status',
                           'get_capabilities', 'list_planes', 'list_planar_faces', 'list_features',
                           'restart_solidworks'),
    'workflow/parameter-ui': ('read_parameter_workspace', 'write_parameter_workspace',
                            'import_parameter_workspace', 'process_parameter_workspace_job'),
    'workflow/engineering-package': ('apply_parameter_changes','inspect_parameter_dependencies',
        'import_parameter_workspace','process_parameter_workspace_job','make_component_independent',
        'inspect_model_health','check_interferences','edit_mate','manage_configurations',
        'edit_feature_definition','edit_component_pattern','replace_structural_profile',
        'compare_project_versions','rename_project_documents','checkpoint_project','present_result',
        'inspect_holes_and_fasteners','manage_external_references','build_manufacturing_package',
        'update_drawing_package','plan_stair','plan_railing','plan_segments','review_galvanizing'),
    'workflow/project-copy': ('inspect_project_references', 'copy_project', 'list_model_parameters',
                             'set_model_dimension', 'update_model_equation', 'replace_component',
                             'list_components', 'open_document', 'bind_active_document', 'save_document'),
}


def _entries() -> dict[str, Path]:
    entries = {'expert': EXPERT / 'SKILL.md'}
    for path in sorted((EXPERT / 'references').glob('*.md')):
        entries['reference/' + path.stem] = path
    for path in sorted((EXPERT / 'references' / 'modules').glob('*.md')):
        entries['modules/' + path.stem] = path
    for path in sorted((EXPERT / 'workflows').glob('*.md')):
        entries['workflow/' + path.stem] = path
    return entries


def catalog() -> list[dict]:
    result = []
    for topic, path in _entries().items():
        content = path.read_text(encoding='utf-8')
        heading = re.search(r'^# (.+)$', content, re.MULTILINE)
        result.append({'id': topic, 'title': heading.group(1) if heading else topic,
                       'uri': URI_PREFIX + topic})
    return result


def server_instructions() -> str:
    return (ROOT / 'server-instructions.txt').read_text(encoding='utf-8').strip()


def topic_for_uri(uri: str) -> str:
    parsed = urlsplit(str(uri))
    if parsed.scheme != 'solidworks' or parsed.netloc != 'guides' or parsed.query or parsed.fragment:
        raise ValueError('Unknown modeling guide resource URI.')
    topic = parsed.path.removeprefix('/')
    if topic != 'index' and topic not in _entries():
        raise ValueError('Unknown modeling guide resource URI.')
    return topic


def _evidence(tool_names: set[str]) -> dict:
    """Recorded test history is reported as history, never a current live check."""
    source = ROOT.parents[1] / 'scripts' / 'capability_requirements.json'
    if not source.is_file():
        return {'source': None, 'note': 'No recorded capability evidence installed.', 'requirements': []}
    try:
        rows = json.loads(source.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'source': str(source), 'note': 'Recorded capability evidence is unavailable.', 'requirements': []}
    selected = []
    for row in rows:
        if row.get('tool_name') not in tool_names:
            continue
        evidence = row.get('evidence', [])
        first = str(evidence[0]) if evidence else ''
        selected.append({'id': row.get('requirement_id'), 'tool': row.get('tool_name'),
                         'recorded_status': row.get('verification_status', 'unknown'),
                         'evidence_excerpt': first[:320],
                         'evidence_truncated': len(evidence) > 1 or len(first) > 320})
    return {'source': 'scripts/capability_requirements.json',
            'note': 'Recorded evidence for individual requirements; not a new live check or validation of this complete workflow.',
            'requirements': selected}


def read_topic(topic: str, available_tools: set[str]) -> dict:
    if not isinstance(topic, str):
        raise ValueError('topic must be an ID from the modeling guide index.')
    if topic == 'index':
        return {'topic': 'index', 'topics': catalog(),
                'note': 'Load only the relevant topic. Guides do not execute CAD. Module notes are teaching guidance, not an MCP capability guarantee.'}
    entries = _entries()
    if topic not in entries:
        raise ValueError('Unknown guide topic. Read get_modeling_guide(topic="index") first.')
    path = entries[topic].resolve()
    if not path.is_relative_to(EXPERT.resolve()):
        raise ValueError('Guide path escapes the packaged knowledge directory.')
    raw = path.read_text(encoding='utf-8')
    # Resources have no local working directory: map Markdown file links to resource IDs.
    paths = {p.resolve(): key for key, p in entries.items()}
    def resource_link(match):
        if urlsplit(match.group(2)).scheme or match.group(2).startswith('#'):
            return match.group(0)
        target = (path.parent / match.group(2)).resolve()
        key = paths.get(target)
        return '[' + match.group(1) + '](' + URI_PREFIX + key + ')' if key else match.group(0)
    content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', resource_link, raw)
    recommended = set(TOPIC_TOOLS.get(topic, ()))
    return {'topic': topic, 'uri': URI_PREFIX + topic,
            'content': content, 'content_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'guide_status': 'guidance_not_live_workflow_verification',
            'available_tools': sorted(recommended & available_tools),
            'unavailable_tools': sorted(recommended - available_tools),
            'recorded_tool_evidence': _evidence(recommended),
            'related_topics': sorted(k for k in entries if k != topic) if topic == 'expert' else ['index', 'expert']}
