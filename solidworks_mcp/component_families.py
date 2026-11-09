"""Configuration families preserve functional topology, not just nominal dimensions."""
import math

def same_family(a,b):
    required=('topology','hole_semantics')
    return all(a.get(k) is not None and a[k]==b.get(k) for k in required)


def compile_plate_variant(snapshot,configuration,targets):
    if not isinstance(configuration,str) or not configuration.strip():raise ValueError('Configuration name required.')
    if not isinstance(targets,dict) or not targets:raise ValueError('Explicit dimension targets required.')
    rows=snapshot['dimensions'];changes=[]
    for identity,value in targets.items():
        matches=[d for d in rows if '@'.join(d['name'].split('@')[:2])==identity]
        if len(matches)!=1:raise ValueError('Dimension missing or ambiguous: '+identity)
        d=matches[0]
        if d['read_only'] or d['driven_state']!=2 or d['equation_controlled'] or d['unit']!='mm':
            raise ValueError('Independent writable length dimension required: '+identity)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Positive finite dimension required.')
        if abs(d['value']-value)>1e-9:
            changes.append({'name':d['name'],'unit':'mm','expected_value':d['value'],
                            'value':value,'configuration':configuration})
    return changes
