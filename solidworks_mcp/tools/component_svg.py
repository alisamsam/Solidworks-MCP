"""Session-bound SVG labels backed by checked native assembly edge references."""
import hashlib
from html import escape
import json
import math
from pathlib import Path

from ..constants import SwErrors
from ..core.policy import OperationClass
from ..registry import tool
from .component_edges import _assembly, _cache, _component, _context, list_component_edges, select_component_edges
from .guard import require_output_write

VIEWS={
    'xy': ((1,0,0),(0,1,0)), 'xz': ((1,0,0),(0,0,1)), 'yz': ((0,1,0),(0,0,1)),
    'isometric': ((1/math.sqrt(2),-1/math.sqrt(2),0),(-1/math.sqrt(6),-1/math.sqrt(6),2/math.sqrt(6))),
}


def _samples(row):
    if row['curve_type']=='line':return [row['start_mm'],row['end_mm']]
    if row['curve_type']!='circle':raise ValueError('Unsupported curve; no SVG label assigned.')
    center=row['center_mm']; radius=row['radius_mm']; axis=row['circle_axis']
    u=[(v-c)/radius for v,c in zip(row['start_mm'],center)]
    if abs(math.sqrt(sum(v*v for v in u))-1)>1e-5 or abs(sum(a*b for a,b in zip(u,axis)))>1e-5:
        raise ValueError('Circle start/axis does not match native radius.')
    v=[axis[1]*u[2]-axis[2]*u[1],axis[2]*u[0]-axis[0]*u[2],axis[0]*u[1]-axis[1]*u[0]]
    angle=row['length_mm']/radius
    if not 0<angle<=2*math.pi+1e-5:raise ValueError('Unsupported native circle sweep.')
    def point(t):return [center[i]+radius*(u[i]*math.cos(t)+v[i]*math.sin(t)) for i in range(3)]
    tolerance=max(1e-5,radius*1e-5)
    if all(math.dist(point(s*angle),row['end_mm'])<=tolerance for s in (1,-1)) and math.dist(point(angle/2),point(-angle/2))>tolerance:
        raise ValueError('Native arc direction is ambiguous from endpoints; no SVG label assigned.')
    sign=min((1,-1),key=lambda s:math.dist(point(s*angle),row['end_mm']))
    if math.dist(point(sign*angle),row['end_mm'])>max(1e-5,radius*1e-5):
        raise ValueError('Circle sweep does not match native endpoints.')
    steps=max(2,math.ceil(angle/(math.pi/36)))
    return [point(sign*angle*i/steps) for i in range(steps+1)]


def _render(data,context,view):
    right,up=VIEWS[view]; labels=[]; warnings=list(data['warnings'])
    depth=[right[1]*up[2]-right[2]*up[1],right[2]*up[0]-right[0]*up[2],right[0]*up[1]-right[1]*up[0]]
    for row in data['edges']:
        try:
            samples=_samples(row)
            points=[(sum(p[i]*right[i] for i in range(3)),-sum(p[i]*up[i] for i in range(3))) for p in samples]
            if any(not math.isfinite(v) for p in points for v in p):raise ValueError('Invalid projection.')
            collapsed=max(math.dist(points[0],p) for p in points)<1e-7
            label='R'+str(len(labels)+1)
            depths=[sum(p[i]*depth[i] for i in range(3)) for p in samples]
            labels.append(dict(label=label,edge_id=row['edge_id'],geometry=row,points=points,projected_to_point=collapsed,
                               projection_depth_mm=[min(depths),max(depths)],projected_overlap=[]))
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            warnings.append(dict(edge_id=row['edge_id'],message=str(exc)))
    if not labels:raise ValueError('No supported edges to render on this page.')
    groups={}
    for row in labels:
        geometry=row['geometry']
        if geometry['curve_type']=='circle' and abs(geometry['length_mm']/geometry['radius_mm']-2*math.pi)<1e-5:
            # Projected ellipse is independent of native seam/start phase.
            center=geometry['center_mm'];axis=geometry['circle_axis'];r2=geometry['radius_mm']**2
            ar=sum(a*b for a,b in zip(axis,right));au=sum(a*b for a,b in zip(axis,up))
            values=[sum(a*b for a,b in zip(center,right)),-sum(a*b for a,b in zip(center,up)),r2*(1-ar*ar),-r2*ar*au,r2*(1-au*au)]
            signature=('full_circle',*(round(v,5) for v in values))
        else:
            points=tuple((round(x,5),round(y,5)) for x,y in row['points'])
            signature=('samples',min(points,points[::-1]))
        groups.setdefault(signature,[]).append(row)
    for group in groups.values():
        if len(group)>1:
            for row in group:row['projected_overlap']=[member['label'] for member in group]
    points=[p for label in labels for p in label['points']]
    xmin=min(p[0] for p in points);xmax=max(p[0] for p in points)
    ymin=min(p[1] for p in points);ymax=max(p[1] for p in points)
    height=max(900,200+18*len(labels)); scale=min(800/max(xmax-xmin,1),650/max(ymax-ymin,1))
    def xy(p):return (50+(p[0]-xmin)*scale,160+(p[1]-ymin)*scale)
    title=escape(context['component_path'])
    metadata=dict(schema_version=1,map_id=data['snapshot_id'],context=context,view=view,
        projection_basis=dict(right=right,up=up),units='mm',drawing_scale='fit; not 1:1',
        coverage_scope='scanned_page',next_offset=data['next_offset'],complete=not warnings,warnings=warnings,
        visibility='wire projection, hidden and overlapping edges included; no hidden-line removal',
        validity='MCP session only; expires with edge snapshot (15 minutes / 32 pages); never reload bindings from SVG/JSON',
        labels=[{k:v for k,v in row.items() if k!='points'} for row in labels])
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="{height}" viewBox="0 0 1440 {height}">',
         '<rect width="100%" height="100%" fill="white"/>',
         '<style>text{font:13px sans-serif;fill:#182235}.edge{fill:none;stroke:#244a71;stroke-width:1.6}.tag{font-weight:bold;paint-order:stroke;stroke:white;stroke-width:4px}.edge:target{stroke:#d44220;stroke-width:4}</style>',
         '<text x="30" y="28" style="font-size:20px;font-weight:bold">Model-linked component detail</text>',
         f'<text x="30" y="52">{title}</text>',
         f'<text x="30" y="74">View: {view} | assembly mm | map: {data["snapshot_id"]}</text>',
         '<text x="30" y="96">Wire projection; hidden/overlapping edges included. Curves sampled at max 5 degrees. Not a manufacturing drawing.</text>',
         f'<text x="30" y="118">Page offset {data["offset"]}; next: {data["next_offset"]}; partial read: {bool(warnings)}</text>',
         f'<metadata>{escape(json.dumps(metadata,ensure_ascii=False))}</metadata>']
    for i,row in enumerate(labels):
        label=row['label']; mapped=[xy(p) for p in row['points']]
        coords=' '.join(f'{x:.5f},{y:.5f}' for x,y in mapped)
        if row['projected_to_point']:
            x,y=mapped[0]; shape=f'<circle cx="{x:.5f}" cy="{y:.5f}" r="3"/>'
        else:shape=f'<polyline points="{coords}"/>'
        svg.append(f'<g id="edge-{label}" class="edge"><title>{label}; native edge {row["edge_id"]}; {title}</title>{shape}</g>')
        x,y=mapped[len(mapped)//2] if len(mapped)>2 else ((mapped[0][0]+mapped[-1][0])/2,(mapped[0][1]+mapped[-1][1])/2)
        tag_y=160+18*i
        svg.append(f'<path d="M {x:.5f},{y:.5f} L 868,{tag_y-4}" fill="none" stroke="#8a9aaa" stroke-width="0.6" stroke-dasharray="3 3"/>')
        svg.append(f'<text class="tag" x="870" y="{tag_y}">{label}</text>')
        note=' [point in this view]' if row['projected_to_point'] else ''
        if row['projected_overlap']:note+=' OVERLAP '+','.join(row['projected_overlap'])
        low,high=row['projection_depth_mm']
        svg.append(f'<a href="#edge-{label}"><text x="910" y="{tag_y}">{row["geometry"]["curve_type"]}, {row["geometry"]["length_mm"]:.3f} mm; depth {low:.2f}..{high:.2f}{note}</text></a>')
    svg.append('</svg>')
    return '\n'.join(svg),metadata


@tool(name='export_component_edge_svg',description='Export a labelled SVG detail of one exact assembly component edge page plus provenance JSON. Labels bind native edges in this MCP session; select via select_component_svg_edges. Wire projection includes hidden/overlapping edges; no manufacturing or whole-assembly drawing implied.',
      schema={'type':'object','properties':{'component_path':{'type':'string'},'output_path':{'type':'string'},
        'view':{'type':'string','enum':list(VIEWS),'default':'isometric'},'offset':{'type':'integer','minimum':0,'default':0},
        'limit':{'type':'integer','minimum':1,'maximum':100,'default':40}},'required':['component_path','output_path']},operation_class=OperationClass.EXPORT)
def export_component_edge_svg(sw,component_path,output_path,view='isometric',offset=0,limit=40):
    created=[];record=None
    try:
        if not isinstance(view,str) or view not in VIEWS:raise ValueError('Unsupported orthographic view.')
        if not isinstance(output_path,str) or not output_path.strip():raise ValueError('An output SVG path is required.')
        path=Path(output_path).expanduser().resolve(); manifest=path.with_suffix('.json')
        if path.suffix.lower()!='.svg':raise ValueError('Output extension must be .svg.')
        for target in (path,manifest):
            denied=require_output_write(sw,str(target))
            if denied:return denied
            if target.exists():raise ValueError('SVG and JSON outputs must both be new files.')
        result=list_component_edges(sw,component_path,offset=offset,limit=limit)
        if not result['success']:return result
        data=result['data']; data['offset']=offset
        record=_cache(sw)[data['snapshot_id']]; svg,metadata=_render(data,record['context'],view)
        metadata['svg_sha256']=hashlib.sha256(svg.encode('utf-8')).hexdigest()
        doc=_assembly(sw)
        if _context(doc,_component(doc,component_path))!=record['context']:raise ValueError('Model changed during SVG creation; retry.')
        path.parent.mkdir(parents=True,exist_ok=True)
        for target,content in ((path,svg),(manifest,json.dumps(metadata,ensure_ascii=False,indent=2))):
            with target.open('x',encoding='utf-8',newline='') as stream:
                created.append(target);stream.write(content)
        record['svg_labels']={row['label']:row['edge_id'] for row in metadata['labels']}
        record['svg_ambiguous']={row['label'] for row in metadata['labels'] if row['projected_to_point'] or row['projected_overlap']}
        return sw._result(True,'SVG labels bound to exact native edges for this MCP session; no model changes.',data={
            **metadata,'svg_path':str(path),'manifest_path':str(manifest)})
    except Exception as exc:
        for target in created:
            try:target.unlink()
            except OSError:pass
        return sw._result(False,str(exc),SwErrors.swExportError,{'code':'COMPONENT_SVG_EXPORT_FAILED'})


@tool(name='select_component_svg_edges',description='Resolve labels from export_component_edge_svg to the exact native assembly edges in the same MCP session. Checks stale context and exact owner; preserves/rolls back selection through select_component_edges. Never trusts edited SVG/JSON names or coordinates.',
      schema={'type':'object','properties':{'map_id':{'type':'string'},'labels':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':64,'uniqueItems':True},
          'append':{'type':'boolean','default':False},'mark':{'type':'integer','minimum':0,'default':0}},'required':['map_id','labels']},operation_class=OperationClass.STATEFUL_READ)
def select_component_svg_edges(sw,map_id,labels,append=False,mark=0):
    try:
        if not isinstance(map_id,str) or not isinstance(labels,list) or not 1<=len(labels)<=64 or any(not isinstance(v,str) for v in labels) or len(set(labels))!=len(labels):
            raise ValueError('Supply a current map_id and 1..64 unique SVG labels.')
        record=_cache(sw).get(map_id)
        if record is None or 'svg_labels' not in record:raise ValueError('SVG map expired or belongs to another session; export a new detail.')
        if any(label not in record['svg_labels'] for label in labels):raise ValueError('Label not present in this SVG map.')
        if any(label in record['svg_ambiguous'] for label in labels):raise ValueError('Projected edges overlap or collapse to a point; export another view before selection.')
        result=select_component_edges(sw,map_id,[record['svg_labels'][label] for label in labels],append,mark)
        if result['success']:result['data'].update(map_id=map_id,selected_labels=labels)
        return result
    except Exception as exc:return sw._result(False,str(exc),SwErrors.swSelectionError,{'code':'COMPONENT_SVG_SELECTION_FAILED'})
