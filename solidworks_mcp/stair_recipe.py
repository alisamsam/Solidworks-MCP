"""Measured construction recipes. Geometry evidence is distinct from design intent."""
import math


def analyze_repetition(components,seed_path):
    rows=[c for c in components if c.get('parent_path') is None and c.get('path')==seed_path
          and c.get('suppressed') is not True]
    rows.sort(key=lambda c:int(c['name'].rsplit('-',1)[-1]))
    if len(rows)<2 or any(not c.get('transform') or len(c['transform'])<12 for c in rows):
        raise ValueError('At least two resolved instances with transforms are required.')
    positions=[c['transform'][9:12] for c in rows]
    gaps=[[1000*(b[i]-a[i]) for i in range(3)] for a,b in zip(positions,positions[1:])]
    if any(not math.isfinite(v) for gap in gaps for v in gap):raise ValueError('Nonfinite transform.')
    mean=[sum(g[i] for g in gaps)/len(gaps) for i in range(3)]
    deviations=[math.dist(g,mean) for g in gaps]
    return {'observed_instances':len(rows),'translation_per_instance_mm':mean,
            'pitch_mm':math.sqrt(sum(v*v for v in mean)),
            'uniform':max(deviations)<1e-5,'max_gap_deviation_mm':max(deviations),
            'coordinate_frame':'assembly model coordinates; axis meaning needs confirmation',
            'first_to_last_mm':[1000*(positions[-1][i]-positions[0][i]) for i in range(3)]}


def centered_sketch_commands(geometry):
    if not geometry.get('complete') or not geometry.get('endpoint_center_mm'):
        raise ValueError('Complete line/arc sketch evidence is required.')
    center=geometry['endpoint_center_mm'];commands=[]
    if abs(center[2])>1e-6:raise ValueError('Only planar XY source profiles are supported.')
    for s in geometry['segments']:
        a=[s['start_mm'][i]-center[i] for i in range(3)]
        b=[s['end_mm'][i]-center[i] for i in range(3)]
        if abs(a[2])>1e-6 or abs(b[2])>1e-6:raise ValueError('Nonplanar profile.')
        if s['type']==0:
            commands.append({'tool':'draw_line','arguments':dict(x1=a[0],y1=a[1],x2=b[0],y2=b[1],unit='mm')})
        elif s['type']==1:
            c=[s['center_mm'][i]-center[i] for i in range(3)]
            start=math.atan2(a[1]-c[1],a[0]-c[0]);end=math.atan2(b[1]-c[1],b[0]-c[0])
            direction=s['rotation_direction']
            if direction not in (-1,1):raise ValueError('Unknown arc orientation.')
            sweep=(end-start)%(2*math.pi) if direction==1 else -((start-end)%(2*math.pi))
            if abs(sweep)<1e-9:raise ValueError('Full circles are not supported in this replay.')
            mid=start+sweep/2;r=s['radius_mm']
            commands.append({'tool':'draw_arc_3point','arguments':dict(start_x=a[0],start_y=a[1],end_x=b[0],end_y=b[1],point_x=c[0]+r*math.cos(mid),point_y=c[1]+r*math.sin(mid),unit='mm')})
        else:raise ValueError('Unsupported profile segment.')
    if not commands:raise ValueError('Empty profile.')
    return commands


def compile_changes(bindings,values):
    mapped={b['key']:b for b in bindings}
    if len(mapped)!=len(bindings):raise ValueError('Duplicate semantic binding.')
    unknown=set(values)-set(mapped)
    if unknown:raise ValueError('Unsupported or unresolved parameters: '+', '.join(sorted(unknown)))
    changes=[]
    for key,value in values.items():
        b=mapped[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Positive finite numeric value required: '+key)
        if abs(value-b['observed_value'])<1e-9:continue
        changes.append({k:b[k] for k in ('document_path','configuration','name','unit')})
        changes[-1].update(expected_value=b['observed_value'],value=value)
    return changes


def replay_centered_segments(document,commands):
    from .comutil import com
    com(document,'SetAddToDB',True)
    com(document,'SetDisplayWhenAdded',False)
    try:
        manager=com(document,'SketchManager')
        for command in commands:
            a=command['arguments']
            if command['tool']=='draw_line':
                entity=com(manager,'CreateLine',a['x1']/1000,a['y1']/1000,0,a['x2']/1000,a['y2']/1000,0)
            elif command['tool']=='draw_arc_3point':
                entity=com(manager,'Create3PointArc',a['start_x']/1000,a['start_y']/1000,0,
                           a['end_x']/1000,a['end_y']/1000,0,a['point_x']/1000,a['point_y']/1000,0)
            else:raise ValueError('Unknown replay command.')
            if entity is None:raise RuntimeError('Sketch entity creation failed.')
    finally:
        com(document,'SetAddToDB',False)
        com(document,'SetDisplayWhenAdded',True)


def turn_concept(turn_angle_deg,transition_type,element_count):
    if isinstance(turn_angle_deg,bool) or not isinstance(turn_angle_deg,(int,float)) or not math.isfinite(turn_angle_deg) or not 0<abs(turn_angle_deg)<=180:
        raise ValueError('Signed finite turn angle in (0,180] required.')
    if type(element_count) is not int or not 1<=element_count<=100:
        raise ValueError('Integer transition element count in 1..100 required.')
    if transition_type not in ('landing','winders'):raise ValueError('Transition must be landing or winders.')
    if transition_type=='landing' and element_count!=1:raise ValueError('One landing is one transition element, not an inferred rise.')
    return {'turn_angle_deg':turn_angle_deg,'transition_type':transition_type,
            'transition_element_count':element_count,
            'angular_divisions_deg':[turn_angle_deg/element_count]*element_count if transition_type=='winders' else [],
            'riser_count':None,'height_gain_mm':None,'cad_geometry_created':False,
            'angle_reference':'local plan: +X walking forward, +Y left; positive turns left',
            'assumptions':['Equal angular sectors are a concept choice, not verified tread contours.'],
            'missing_geometry':['Flight frames and handedness','Finished nosing elevations/rise assignment',
                'Walking line and actual inner/outer tread contours','Steel support plate templates and assembly interfaces']}
