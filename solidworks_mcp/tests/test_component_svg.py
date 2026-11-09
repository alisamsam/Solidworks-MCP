"""SVG label identity is a server-side binding, never a component-name guess."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET

from solidworks_mcp.core.policy import PathPolicy
from solidworks_mcp.tests.test_component_edges import Automation
from solidworks_mcp.tools.component_svg import export_component_edge_svg, select_component_svg_edges
from solidworks_mcp.tools.component_svg import _render, _samples


class ComponentSvgTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'detail.svg'; self.sw=Automation()

    def export(self, **kw):
        return export_component_edge_svg(self.sw, 'SUB-1/BLOCK-1', str(self.path), **kw)

    def test_export_embeds_native_binding_without_selection(self):
        result=self.export(); self.assertTrue(result['success'], result)
        d=result['data']; self.assertEqual(2, len(d['labels'])); self.assertEqual(0,self.sw.doc.clears)
        tree=ET.fromstring(self.path.read_text()); self.assertTrue(tree.tag.endswith('svg'))
        manifest=json.loads(self.path.with_suffix('.json').read_text())
        self.assertEqual(d['map_id'],manifest['map_id'])
        self.assertEqual('SUB-1/BLOCK-1',manifest['context']['component_path'])
        self.assertIn('session',manifest['validity'])
        self.assertIn('circle_axis',d['labels'][1]['geometry'])

    def test_svg_label_selects_exact_native_instance_and_mark(self):
        d=self.export()['data']; r=select_component_svg_edges(self.sw,d['map_id'],['R1'],mark=7)
        self.assertTrue(r['success'],r)
        self.assertEqual('SUB-1/BLOCK-1',self.sw.doc.selected[0][0].component.Name2)
        self.assertEqual(7,self.sw.doc.selected[0][1])

    def test_same_names_in_other_document_are_not_accepted(self):
        d=self.export()['data']; self.sw.doc.path='C:/own/OTHER.SLDASM'
        self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],['R1'])['success'])
        self.assertEqual(0,self.sw.doc.clears)

    def test_modified_part_rejects_old_svg_without_clearing(self):
        d=self.export()['data']; self.sw.doc.child.part.stamp+=1
        self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],['R1'])['success'])
        self.assertEqual(0,self.sw.doc.clears)

    def test_untrusted_manifest_edits_cannot_retarget_label(self):
        d=self.export()['data']; self.path.with_suffix('.json').write_text('{"component_path":"BLOCK-1"}')
        self.assertTrue(select_component_svg_edges(self.sw,d['map_id'],['R1'])['success'])
        self.assertEqual('SUB-1/BLOCK-1',self.sw.doc.selected[0][0].component.Name2)

    def test_unknown_duplicate_or_non_svg_labels_rejected(self):
        d=self.export()['data']
        for labels in [['R999'],['R1','R1'],[],[1],'R1']:
            self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],labels)['success'])
        self.assertEqual(0,self.sw.doc.clears)

    def test_normal_edge_snapshot_is_not_a_svg_map(self):
        from solidworks_mcp.tools.component_edges import list_component_edges
        d=list_component_edges(self.sw,'SUB-1/BLOCK-1')['data']
        self.assertFalse(select_component_svg_edges(self.sw,d['snapshot_id'],['R1'])['success'])

    def test_no_overwrite_of_svg_or_manifest(self):
        for suffix in ['.svg','.json']:
            with self.subTest(suffix=suffix):
                p=self.path.with_suffix(suffix); p.write_text('KEEP')
                self.assertFalse(self.export()['success']); self.assertEqual('KEEP',p.read_text()); p.unlink()

    def test_output_policy_denied_before_reading_cad(self):
        self.sw._path_policy=PathPolicy([Path(self.tmp.name)/'allowed'])
        self.sw.get_active_doc=lambda: self.fail('policy must precede COM')
        self.assertFalse(self.export()['success'])

    def test_invalid_view_and_path_rejected_before_cad(self):
        self.assertFalse(self.export(view='perspective')['success'])
        self.assertFalse(export_component_edge_svg(self.sw,'SUB-1/BLOCK-1',str(self.path.with_suffix('.txt')))['success'])

    def test_page_scope_is_explicit_and_labels_map_only_returned_edges(self):
        d=self.export(limit=1)['data']; self.assertEqual(1,d['next_offset'])
        self.assertEqual('scanned_page',d['coverage_scope']); self.assertEqual(1,len(d['labels']))
        self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],['R2'])['success'])

    def test_unsupported_curve_never_becomes_selectable_svg_label(self):
        self.sw.doc.child.bodies[0].edges[1].kind='other'
        d=self.export()['data']; self.assertFalse(d['complete']); self.assertEqual(1,len(d['labels']))
        self.assertTrue(d['warnings']); self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],['R2'])['success'])

    def test_projection_collapse_is_reported_not_guessed(self):
        d=self.export(view='yz')['data']; self.assertTrue(d['labels'][0]['projected_to_point'])

    def test_semicircle_direction_is_not_invented_from_endpoints(self):
        row=dict(curve_type='circle',center_mm=[0,0,0],radius_mm=5,circle_axis=[0,0,1],
                 start_mm=[5,0,0],end_mm=[-5,0,0],length_mm=5*math.pi)
        with self.assertRaisesRegex(ValueError,'ambiguous'):_samples(row)

    def test_full_circle_and_quarter_arc_render_with_matching_endpoints(self):
        row=dict(curve_type='circle',center_mm=[0,0,0],radius_mm=5,circle_axis=[0,0,1],
                 start_mm=[5,0,0],end_mm=[0,-5,0],length_mm=2.5*math.pi)
        self.assertLess(math.dist(_samples(row)[-1],[0,-5,0]),1e-8)
        row.update(end_mm=[5,0,0],length_mm=10*math.pi)
        self.assertEqual(73,len(_samples(row)))

    def test_depth_separated_overlapping_lines_have_explicit_group_and_callouts(self):
        a=dict(curve_type='line',start_mm=[0,0,0],end_mm=[10,0,0],length_mm=10,edge_id=0)
        b={**a,'start_mm':[0,0,5],'end_mm':[10,0,5],'edge_id':1}
        svg,meta=_render(dict(edges=[a,b],warnings=[],snapshot_id='a',offset=0,next_offset=None),dict(component_path='A-1'),'xy')
        self.assertEqual(['R1','R2'],meta['labels'][0]['projected_overlap'])
        self.assertEqual([0,0],meta['labels'][0]['projection_depth_mm'])
        self.assertEqual([5,5],meta['labels'][1]['projection_depth_mm'])
        tree=ET.fromstring(svg)
        tags=[node for node in tree.iter() if node.attrib.get('class')=='tag']
        self.assertEqual(2,len(set((n.attrib['x'],n.attrib['y']) for n in tags)))

    def test_degenerate_projection_cannot_be_selected_without_another_view(self):
        d=self.export(view='yz')['data']
        self.assertFalse(select_component_svg_edges(self.sw,d['map_id'],['R1'])['success'])
        self.assertEqual(0,self.sw.doc.clears)

    def test_same_projected_circle_with_different_native_seam_is_ambiguous(self):
        a=dict(curve_type='circle',center_mm=[0,0,0],radius_mm=5,circle_axis=[0,0,1],
               start_mm=[5,0,0],end_mm=[5,0,0],length_mm=10*math.pi,edge_id=0)
        for angle in [math.pi/2,.023]:
            start=[5*math.cos(angle),5*math.sin(angle),5]
            b={**a,'center_mm':[0,0,5],'start_mm':start,'end_mm':start,'edge_id':1}
            _,meta=_render(dict(edges=[a,b],warnings=[],snapshot_id='a',offset=0,next_offset=None),dict(component_path='A-1'),'xy')
            self.assertEqual(['R1','R2'],meta['labels'][0]['projected_overlap'])


if __name__=='__main__': unittest.main()
