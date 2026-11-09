"""Shared Hole Wizard mappings and the generated (never live Toolbox) library."""
import json
import math
import os
from pathlib import Path

HOLE_STANDARDS={
    'ansi_metric':{'index':1,'prefix':'AM','fasteners':{'drill':39,'counterbore':33,'countersink':35}},
    'din':{'index':4,'prefix':'DIN','fasteners':{'drill':72,'counterbore':67,'countersink':68}},
    'iso':{'index':8,'prefix':'ISO','fasteners':{'drill':143,'counterbore':139,'countersink':140}},
}

def catalog_path():
    root=Path(os.environ['SW_MCP_STANDARD_LIBRARY']) if os.environ.get('SW_MCP_STANDARD_LIBRARY') else Path(__file__).parent/'standard_library'
    return root/'hole_wizard.json'

def _positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0

def validate_catalog(payload):
    import re
    from datetime import datetime
    if (not isinstance(payload,dict) or type(payload.get('schema_version')) is not int
            or payload['schema_version']!=1 or payload.get('native_geometry_verified') is not False
            or payload.get('units')!='mm_degrees' or payload.get('source_access')!='sqlite_mode_ro'
            or not isinstance(payload.get('source_database'),str) or not payload['source_database']
            or not isinstance(payload.get('source_sha256'),str)
            or re.fullmatch(r'[0-9a-f]{64}',payload['source_sha256']) is None
            or not isinstance(payload.get('generated_at'),str)
            or not isinstance(payload.get('families'),list) or not 1<=len(payload['families'])<=9):
        raise ValueError('Invalid generated hole catalog format, units or provenance.')
    if datetime.fromisoformat(payload['generated_at']).tzinfo is None:
        raise ValueError('Catalog generation time must have a timezone.')
    seen=set()
    for f in payload['families']:
        if not isinstance(f,dict):raise ValueError('Invalid hole family.')
        standard=f.get('standard');kind=f.get('hole_type')
        if not isinstance(standard,str) or standard not in HOLE_STANDARDS or not isinstance(kind,str) or kind not in HOLE_STANDARDS[standard]['fasteners']:
            raise ValueError('Unsupported hole catalog family.')
        mapping=HOLE_STANDARDS[standard]
        if (type(f.get('standard_index')) is not int or type(f.get('fastener_type_index')) is not int
                or f['standard_index']!=mapping['index'] or f['fastener_type_index']!=mapping['fasteners'][kind]
                or (standard,kind) in seen or not isinstance(f.get('rows'),list) or not 1<=len(f['rows'])<=10000
                or not isinstance(f.get('fastener_name'),str) or not f['fastener_name']
                or not isinstance(f.get('source_table'),str) or re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',f['source_table']) is None):
            raise ValueError('Invalid or duplicated hole family mapping.')
        seen.add((standard,kind));sizes=set()
        required={'drill':{'diameter_mm'},
                  'counterbore':{'nominal_diameter_mm','counterbore_diameter_mm','counterbore_depth_mm'},
                  'countersink':{'nominal_diameter_mm','fastener_head_diameter_mm','fastener_head_angle_deg'}}[kind]
        for row in f['rows']:
            if not isinstance(row,dict) or not isinstance(row.get('catalog_size'),str) or not row['catalog_size']:
                raise ValueError('Invalid catalog size.')
            if row['catalog_size'] in sizes or not required.issubset(row):raise ValueError('Duplicate size or missing dimensions.')
            sizes.add(row['catalog_size'])
            for key,value in row.items():
                if key=='clearance_mm':
                    if not isinstance(value,dict) or set(value)!={'close','normal','loose'} or not all(_positive(v) for v in value.values()):
                        raise ValueError('Invalid clearance dimensions.')
                elif key.endswith('_mm') or key.endswith('_deg'):
                    if not _positive(value) or key.endswith('_deg') and value>=180:
                        raise ValueError('Invalid scalar hole catalog dimension.')
    return payload

def load_catalog():
    path=catalog_path()
    if not path.is_file():raise ValueError('Hole catalog missing; run scripts/build_hole_wizard_catalog.py.')
    if path.stat().st_size>5_000_000:raise ValueError('Hole catalog exceeds 5 MB limit.')
    return validate_catalog(json.loads(path.read_text(encoding='utf-8')))
