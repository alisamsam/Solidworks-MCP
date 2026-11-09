"""Native exact-instance selection and recovery on the own nested R01 fixture."""
import hashlib
import json
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.comutil import com
from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tools import component_edges as edges


@unittest.skipUnless(os.environ.get('SW_MCP_LIVE_TESTS') == '1', 'Set SW_MCP_LIVE_TESTS=1 for native CAD tests.')
class LiveComponentEdgeTests(unittest.TestCase):
    def test_nested_instances_circles_and_native_selection_rollback(self):
        root = Path(__file__).resolve().parents[3] / 'output/component-edge-selection-20261018-R01'
        paths = [root / n for n in ('MAIN.SLDASM', 'SUB.SLDASM', 'BLOCK.SLDPRT')]
        if not all(p.is_file() for p in paths):
            self.skipTest('Create the own R01 nested fixture using fixture.json first.')
        sw = SolidWorksAutomation()
        self.assertTrue(sw.connect()['success'])
        sw._path_policy = PathPolicy([root])
        self.assertIsNone(com(sw.app, 'GetOpenDocumentByName', str(paths[0])), 'Fixture already in use.')
        doc = None
        records = {}
        try:
            self.assertTrue(sw.open_document(str(paths[0]))['success'])
            doc = com(sw.app, 'ActiveDoc')
            target = edges._component(doc, 'SUB-1/BLOCK-1')
            def state():
                return dict(files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    assembly_stamp=com(doc, 'GetUpdateStamp'), dirty=com(doc, 'GetSaveFlag'),
                    contexts=[edges._context(doc, edges._component(doc, n)) for n in ('BLOCK-1', 'SUB-1/BLOCK-1', 'SUB-1/BLOCK-2')])
            before = state()
            page = edges.list_component_edges(sw, 'SUB-1/BLOCK-1', curve_type='line', limit=5)
            self.assertTrue(page['success'], page)
            data = page['data']; self.assertTrue(data['complete']); self.assertTrue(data['edges'])
            token = data['snapshot_id']; edge_id = data['edges'][0]['edge_id']
            selected = edges.select_component_edges(sw, token, [edge_id], mark=7)
            self.assertTrue(selected['success'], selected)
            old = edges._selections(doc)
            self.assertEqual(7, old[0][1])
            self.assertEqual(1, com(sw.app, 'IsSame', com(old[0][0], 'GetComponent'), target))
            self.assertTrue(edges.select_component_edges(sw, token, [edge_id], append=True, mark=7)['success'])
            self.assertEqual(1, len(edges._selections(doc)))
            line = data['edges'][0]
            midpoint = [(a+b)/2 for a,b in zip(line['start_mm'], line['end_mm'])]
            near = edges.list_component_edges(sw, 'SUB-1/BLOCK-1', near_point_mm=midpoint, within_mm=.01, limit=100)
            self.assertTrue(near['success'], near)
            self.assertIn(edge_id, [r['edge_id'] for r in near['data']['edges']])
            circles = edges.list_component_edges(sw, 'SUB-1/BLOCK-2', curve_type='circle', limit=100)
            self.assertTrue(circles['success'], circles)
            self.assertTrue(circles['data']['complete'])
            self.assertTrue(any(math.dist(e['start_mm'], e['end_mm']) < 1e-5 for e in circles['data']['edges']))
            ct = circles['data']['snapshot_id']; ci = circles['data']['edges'][0]['edge_id']
            native_com = edges.com
            def fail_select(obj, name, *args, **kwargs):
                if name == 'Select4': return False
                return native_com(obj, name, *args, **kwargs)
            with patch.object(edges, 'com', side_effect=fail_select):
                failed = edges.select_component_edges(sw, ct, [ci])
            self.assertFalse(failed['success'], failed)
            self.assertTrue(failed['data']['selection_restored'], failed)
            restored = edges._selections(doc)
            self.assertEqual(7, restored[0][1]); self.assertEqual(1, len(restored))
            self.assertEqual(1, com(sw.app, 'IsSame', old[0][0], restored[0][0]))
            top = edges.list_component_edges(sw, 'BLOCK-1', limit=1)['data']
            record = sw._component_edge_pages[token]
            original_ref = record['references'][edge_id]
            record['references'][edge_id] = sw._component_edge_pages[top['snapshot_id']]['references'][top['edges'][0]['edge_id']]
            wrong = edges.select_component_edges(sw, token, [edge_id])
            self.assertFalse(wrong['success'], wrong)
            self.assertIsNone(wrong['data']['selection_restored'])
            self.assertEqual(1, com(sw.app, 'IsSame', old[0][0], edges._selections(doc)[0][0]))
            record['references'][edge_id] = original_ref
            self.assertTrue(edges.select_component_edges(sw, ct, [ci], mark=1)['success'])
            self.assertEqual('SUB-1/BLOCK-2', com(com(edges._selections(doc)[0][0], 'GetComponent'), 'Name2'))
            self.assertEqual(before, state())
            records.update(line_page=data, near_page=near['data'], circle_page=circles['data'],
                           rollback=failed, wrong_owner=wrong, unchanged_state=before)
            (root / 'native-verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        finally:
            if doc is not None:
                com(doc, 'ClearSelection2', True)
                sw.app.CloseDoc(com(doc, 'GetTitle'))


if __name__ == '__main__': unittest.main()
