"""Build our Hole Wizard snapshot from an installed Toolbox, opened read-only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from solidworks_mcp.hole_catalog import HOLE_STANDARDS,catalog_path,validate_catalog

DEFAULT_DB=Path('C:/SOLIDWORKS Data/lang/english/swbrowser.sldedb')

def _identifier(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name):raise ValueError('Invalid source table identifier.')
    return '"'+name+'"'

def _rows(db,table):
    return [{k.upper():r[k] for k in r.keys()} for r in db.execute('SELECT * FROM '+_identifier(table)+' WHERE enabled=1')]

def _number(value):
    if isinstance(value,bool):raise ValueError('Boolean dimension.')
    n=float(value)
    if not math.isfinite(n) or n<=0:raise ValueError('Expected positive finite catalog dimension.')
    return n

def _source_digest(path):
    raw=path.read_bytes()
    # A read-only SQLite connection can read WAL frames outside the hashed DB,
    # or create SHM files. Refuse WAL before opening SQLite, including WAL mode
    # recorded in the database header even when sidecars are currently absent.
    if path.with_name(path.name+'-wal').exists() or raw[18:20]!=b'\x01\x01':
        raise ValueError('WAL database not supported; supply a consistent non-WAL snapshot.')
    return hashlib.sha256(raw).hexdigest()

def build_catalog(database,standards=None):
    path=Path(database).resolve(strict=True)
    selected=list(HOLE_STANDARDS) if standards is None else standards
    if not selected or len(set(selected))!=len(selected) or any(s not in HOLE_STANDARDS for s in selected):raise ValueError('Invalid standards.')
    digest=_source_digest(path)
    families=[]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        for standard in selected:
            mapping=HOLE_STANDARDS[standard];prefix=mapping['prefix']
            clearances={}
            for row in _rows(db,prefix+'_DATA_HW_ScrewClearances'):
                size=row['SIZE']
                if size in clearances:raise ValueError('Duplicate clearance size.')
                clearances[size]={label:_number(row[key]) for label,key in [('close','CLOSE_FIT'),('normal','NORMAL_FIT'),('loose','LOOSE_FIT')]}
            for kind,fastener in mapping['fasteners'].items():
                type_table=prefix+('_Type_Holes' if kind=='drill' else '_TYPE_BS')
                metadata=[r for r in _rows(db,type_table) if r['SWCONST_ENUM_VALUE']==fastener]
                if len(metadata)!=1:raise ValueError(f'Expected one enabled {standard}/{kind} definition.')
                meta=metadata[0];ref=meta['DATATABLE']
                table=prefix+'_'+ref[1:] if isinstance(ref,str) and ref.startswith('+') else ref
                if not isinstance(table,str):raise ValueError('Missing source data table.')
                rows=[];seen=set()
                for item in _rows(db,table):
                    size=item['SIZE']
                    if not isinstance(size,str) or not size or size in seen:raise ValueError('Missing or duplicated size.')
                    seen.add(size);row={'catalog_size':size}
                    if kind=='drill':row['diameter_mm']=_number(item['DIAMETER'])
                    else:
                        row['nominal_diameter_mm']=_number(item['DIAMETER'])
                        if size in clearances:row['clearance_mm']=clearances[size]
                        for key,field in [('CBORE_DIA','counterbore_diameter_mm'),('CBORE_DEPTH','counterbore_depth_mm'),
                                          ('HEAD_DIA','fastener_head_diameter_mm'),('HEAD_ANG','fastener_head_angle_deg'),
                                          ('COUNTERSINK_DIAMETER','countersink_diameter_mm')]:
                            value=item.get(key)
                            if value is not None and str(value).strip():row[field]=_number(value)
                        if kind=='counterbore' and not all(k in row for k in ('counterbore_diameter_mm','counterbore_depth_mm')):
                            raise ValueError('Missing counterbore dimensions.')
                    rows.append(row)
                if not rows:raise ValueError('Empty enabled catalog family.')
                rows.sort(key=lambda r:r.get('diameter_mm',r.get('nominal_diameter_mm')))
                families.append(dict(standard=standard,hole_type=kind,standard_index=mapping['index'],
                                     fastener_type_index=fastener,fastener_name=meta['NAME'],source_table=table,rows=rows))
    if _source_digest(path)!=digest:raise ValueError('Source changed while building snapshot.')
    return validate_catalog(dict(schema_version=1,generated_at=datetime.now(timezone.utc).isoformat(),
                source_database=path.name,source_sha256=digest,source_access='sqlite_mode_ro',
                units='mm_degrees',native_geometry_verified=False,families=families))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=DEFAULT_DB);parser.add_argument('--out',type=Path,default=catalog_path())
    args=parser.parse_args()
    if args.db.resolve() in (args.out.resolve(),args.out.with_suffix('.json.tmp').resolve()):raise ValueError('Snapshot cannot overwrite its source database.')
    payload=build_catalog(args.db);args.out.parent.mkdir(parents=True,exist_ok=True)
    temp=args.out.with_suffix('.json.tmp');temp.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');temp.replace(args.out)
    print(json.dumps(dict(path=str(args.out),families=len(payload['families']),sizes=sum(len(f['rows']) for f in payload['families']),source_sha256=payload['source_sha256'])))
    return 0

if __name__=='__main__':raise SystemExit(main())
