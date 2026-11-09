"""Query our generated Hole Wizard library without COM or a CAD document."""
from ..constants import SwErrors
from ..core.policy import OperationClass
from ..hole_catalog import HOLE_STANDARDS,load_catalog
from ..registry import tool

@tool(name='list_hole_wizard_sizes',
      description='Read our generated Hole Wizard catalog: exact sizes, native standard/type IDs and separate clearance, recess and fastener dimensions. Does not access Toolbox or CAD.',
      schema={'type':'object','properties':{
          'standard':{'enum':['ansi_metric','din','iso'],'default':'din'},
          'hole_type':{'enum':['drill','counterbore','countersink'],'default':'drill'},
          'catalog_size':{'type':'string','minLength':1},
          'offset':{'type':'integer','minimum':0,'default':0},
          'limit':{'type':'integer','minimum':1,'maximum':100,'default':20},
      },'required':[]},operation_class=OperationClass.READ,com=False)
def list_hole_wizard_sizes(sw,standard='din',hole_type='drill',catalog_size=None,offset=0,limit=20):
    try:
        if (not isinstance(standard,str) or standard not in HOLE_STANDARDS
                or not isinstance(hole_type,str) or hole_type not in ('drill','counterbore','countersink')
                or type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100
                or catalog_size is not None and (not isinstance(catalog_size,str) or not catalog_size.strip())):
            raise ValueError('Invalid standard, hole type, size or page.')
        payload=load_catalog()
        family=next((f for f in payload['families'] if f['standard']==standard and f['hole_type']==hole_type),None)
        if family is None:raise ValueError('Requested family is not in the generated snapshot; rebuild the catalog.')
        rows=[r for r in family['rows'] if catalog_size is None or r['catalog_size']==catalog_size]
        data={k:v for k,v in family.items() if k!='rows'}
        data.update(rows=rows[offset:offset+limit],total_matches=len(rows),offset=offset,
                    next_offset=offset+limit if offset+limit<len(rows) else None,
                    source_sha256=payload.get('source_sha256'),generated_at=payload.get('generated_at'),
                    source_database=payload.get('source_database'),native_geometry_verified=False)
        return sw._result(True,'Read generated Hole Wizard catalog.',data=data)
    except (ValueError,OSError,TypeError,KeyError) as exc:
        return sw._result(False,str(exc),SwErrors.swInvalidInput)
