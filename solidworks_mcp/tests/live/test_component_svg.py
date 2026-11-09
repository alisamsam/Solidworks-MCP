"""Native SVG-to-edge roundtrip on our own rotated repeated-instance fixture."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools.component_edges import _component, _context, _selections
from solidworks_mcp.tools.component_svg import export_component_edge_svg, select_component_svg_edges


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS')=='1','Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveComponentSvgTests(unittest.TestCase):
    def test_svg_labels_roundtrip_to_rotated_native_instance(self):
        root=Path(__file__).resolve().parents[3]/'output/component-edge-selection-20261018-R01'
        files=[root/n for n in ('MAIN.SLDASM','SUB.SLDASM','BLOCK.SLDPRT')]
        if not all(p.exists() for p in files):self.skipTest('Create the own R01 nested fixture first.')
        sw=SolidWorksAutomation();self.assertTrue(sw.connect()['success']);sw._path_policy=PathPolicy([root])
        self.assertIsNone(com(sw.app,'GetOpenDocumentByName',str(files[0])),'Own fixture already in use.')
        target=root/('svg-live-'+uuid4().hex[:8]);target.mkdir();doc=None
        try:
            self.assertTrue(sw.open_document(str(files[0]))['success']);doc=com(sw.app,'ActiveDoc')
            component=_component(doc,'SUB-1/BLOCK-2')
            def state():return dict(context=_context(doc,component),dirty=com(doc,'GetSaveFlag'),
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
            before=state();result=export_component_edge_svg(sw,'SUB-1/BLOCK-2',str(target/'ROTATED.svg'),limit=100)
            self.assertTrue(result['success'],result);data=result['data'];self.assertTrue(data['complete'],data['warnings'])
            self.assertIsNone(data['next_offset']);self.assertEqual(before,state())
            circle=next(row for row in data['labels'] if row['geometry']['curve_type']=='circle')
            selected=select_component_svg_edges(sw,data['map_id'],[circle['label']],mark=7)
            self.assertTrue(selected['success'],selected)
            actual=_selections(doc);self.assertEqual(1,len(actual));self.assertEqual(7,actual[0][1])
            self.assertEqual(1,com(sw.app,'IsSame',component,com(actual[0][0],'GetComponent')))
            self.assertEqual(before,state())
            again=export_component_edge_svg(sw,'SUB-1/BLOCK-2',str(target/'ROTATED-XZ.svg'),view='xz',limit=100)
            self.assertTrue(again['success'],again);self.assertEqual(1,len(_selections(doc)))
            self.assertEqual(1,com(sw.app,'IsSame',actual[0][0],_selections(doc)[0][0]))
            self.assertTrue(select_component_svg_edges(sw,data['map_id'],[circle['label']],append=True,mark=7)['success'])
            self.assertEqual(1,len(_selections(doc)));self.assertEqual(before,state())
            (target/'verification.json').write_text(json.dumps(dict(first=result,second=again,selection=selected,unchanged=before),indent=2),encoding='utf-8')
        finally:
            if doc is not None:sw.app.CloseDoc(com(doc,'GetTitle'))


if __name__=='__main__':unittest.main()
