"""Native exported DXF contours must identify only the requested sheet body."""
import json
import math
import os
from pathlib import Path
import shutil
import unittest
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.sheetmetal_bodies import list_sheet_metal_bodies
from solidworks_mcp.tools.sheetmetal_body_export import export_sheet_metal_body_dxf,_source_state,_same_source,_same_selection
from solidworks_mcp.tools.component_edges import _selections


def rectangle_dxf_metrics(path):
    """Independent ASCII-DXF entity/scale/topology proof for rectangle fixtures."""
    raw=Path(path).read_text(encoding='cp1252').splitlines()
    if len(raw)%2:raise ValueError('Malformed DXF pairs')
    pairs=[(int(raw[i].strip()),raw[i+1].strip()) for i in range(0,len(raw),2)]
    section=None;entities=[];entity=None;units=None
    for i,(code,value) in enumerate(pairs):
        if code==9 and value=='$INSUNITS':units=int(pairs[i+1][1])
        if code==0 and value=='SECTION':
            section=pairs[i+1][1];continue
        if section!='ENTITIES':continue
        if code==0:
            if entity is not None:entities.append(entity)
            entity=None if value=='ENDSEC' else dict(kind=value,values={})
            if value=='ENDSEC':section=None
        elif entity is not None:entity['values'][code]=value
    if not entities or any(e['kind']!='LINE' for e in entities):raise ValueError('Fixture should contain only LINE edges')
    lines=[]
    for e in entities:
        v=e['values'];lines.append(((float(v[10]),float(v[20])),(float(v[11]),float(v[21]))))
    points=[p for line in lines for p in line]
    perimeter=sum(math.dist(a,b) for a,b in lines)
    for point in points:
        if sum(math.dist(point,other)<1e-6 for other in points)!=2:raise ValueError('DXF contour is not one closed rectangle')
    return dict(units=units,line_count=len(lines),width=max(p[0] for p in points)-min(p[0] for p in points),
                height=max(p[1] for p in points)-min(p[1] for p in points),perimeter=perimeter)


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveSheetBodyDxfTests(unittest.TestCase):
    def test_three_distinct_body_contours_preserve_source_and_selection(self):
        base=Path(__file__).resolve().parents[3]/'output'
        fixture=base/'sheet-metal-multibody-20261018-R01/MULTIBODY_VERIFIED.SLDPRT'
        if not fixture.exists():self.skipTest('Create own verified multibody fixture first.')
        root=base/'sheet-metal-body-dxf-20261019-R01'/('live-'+uuid4().hex[:8])
        source=root/'source/SOURCE.SLDPRT';source.parent.mkdir(parents=True);shutil.copyfile(fixture,source)
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root]);doc=None
        try:
            self.assertTrue(sw.open_document(str(source))['success']);doc=com(sw.app,'ActiveDoc')
            seed=com(doc,'FeatureByName','Base-Flange1');self.assertTrue(com(seed,'Select2',False,9))
            before=_source_state(doc);selection=_selections(doc);self.assertEqual(1,len(selection))
            info=list_sheet_metal_bodies(sw);self.assertTrue(info['data']['complete'],info);results=[]
            self.assertEqual(3,info['data']['sheet_body_count'])
            for row in info['data']['bodies']:
                r=export_sheet_metal_body_dxf(sw,row['body_index'],info['data']['update_stamp'],str(root/('DXF-'+str(row['body_index']))))
                self.assertTrue(r['success'],r);data=r['data'];self.assertTrue(data['source_unchanged'])
                self.assertTrue(_same_source(before,_source_state(doc)));self.assertTrue(_same_selection(sw,selection,_selections(doc)))
                metrics=rectangle_dxf_metrics(data['path']);self.assertEqual(4,metrics['line_count']);self.assertEqual(4,metrics['units'])
                dims=sorted((before['geometry'][row['solid_body_index']]['box_m'][i+3]-before['geometry'][row['solid_body_index']]['box_m'][i])*1000 for i in range(3))[-2:]
                self.assertAlmostEqual(dims[0],min(metrics['width'],metrics['height']),delta=1e-4)
                self.assertAlmostEqual(dims[1],max(metrics['width'],metrics['height']),delta=1e-4)
                self.assertAlmostEqual(2*sum(dims),metrics['perimeter'],delta=1e-4)
                self.assertIsNone(com(sw.app,'GetOpenDocumentByName',str(next((root/('DXF-'+str(row['body_index']))/'native-copy').glob('*.SLDPRT')))))
                results.append(dict(result=data,dxf=metrics,expected_dimensions_mm=dims))
            self.assertEqual({(50,100),(30,60),(40,80)},set(tuple(round(v) for v in r['expected_dimensions_mm']) for r in results))
            (root/'verification.json').write_text(json.dumps(dict(results=results,source_unchanged=True,selection_mark=selection[0][1]),indent=2),encoding='utf-8')
        finally:
            if doc is not None:sw.app.CloseDoc(com(doc,'GetTitle'))


if __name__=='__main__':unittest.main()
