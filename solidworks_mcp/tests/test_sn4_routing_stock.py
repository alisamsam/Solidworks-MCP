"""Regression gates for native SN4 stock verification, independent of COM."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

class SN4StockVerificationTests(unittest.TestCase):
    def module(self):
        path=Path(__file__).resolve().parents[2]/'scripts'/'build_sn4_routing_stock.py'
        self.assertTrue(path.exists(), 'SN4 stock builder/verification is missing')
        spec=importlib.util.spec_from_file_location('sn4_stock',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def verifier(self):
        return self.module().verify_snapshot

    def sample(self):
        return {'body_count':1,'length_mm':500.,'od_mm':110.,'id_mm':103.6,
                'nominal_mm':110.,'volume_mm3':536835.3526454199,
                'body_box_mm':[-55.,-55.,0.,55.,55.,500.],
                'component_type':1,'configurations':['SN4_OD110_ID103p6'],
                'pipe_identifier':'SN4 OD110 ID103.6',
                'qto_include_value':'NO','native_route_verified_value':'NO',
                'design_table_headers':['$prp@Pipe Identifier','OuterDiameter@PipeSketch',
                    'InnerDiameter@PipeSketch','NominalDiameter@FilterSketch']}

    def test_valid_500_native_snapshot(self):
        self.verifier()(self.sample(),500.)

    def test_disabled_routing_creates_no_directory(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'must-not-exist'
            with patch('sys.argv',['builder','--output',str(target)]), patch(
                    'solidworks_mcp.catalog.routing_enabled',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'Routing is disabled'):
                    module.main()
            self.assertFalse(target.exists())

    def test_boolean_native_type_or_count_is_rejected(self):
        verify=self.verifier()
        for key in ['component_type','body_count']:
            snapshot=self.sample();snapshot[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):verify(snapshot,500.)

    def test_same_diameter_wrong_length_is_rejected(self):
        with self.assertRaises(ValueError):self.verifier()(self.sample(),1000.)

    def test_fitting_type_is_not_pipe(self):
        s=self.sample();s['component_type']=10
        with self.assertRaises(ValueError):self.verifier()(s,500.)

    def test_wrong_bore_and_nonfinite_geometry_rejected(self):
        verify=self.verifier()
        for key,value in [('id_mm',100.),('volume_mm3',float('nan')),('od_mm',float('inf')),('length_mm',True)]:
            s=self.sample();s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify(s,500.)

    def test_wrong_axis_or_multiple_bodies_rejected(self):
        verify=self.verifier()
        for key,value in [('body_count',2),('body_box_mm',[0,-55,-55,500,55,55])]:
            s=self.sample();s[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify(s,500.)

    def test_design_table_cannot_control_length(self):
        s=self.sample();s['design_table_headers'].append('Length@Extrusion')
        with self.assertRaises(ValueError):self.verifier()(s,500.)

    def test_missing_pipe_identifier_rejected(self):
        s=self.sample();s['pipe_identifier']=''
        with self.assertRaises(ValueError):self.verifier()(s,500.)

    def test_persisted_exclusion_properties_required(self):
        verify=self.verifier()
        for key in ['qto_include_value','native_route_verified_value']:
            s=self.sample();s[key]=''
            with self.subTest(key=key),self.assertRaises(ValueError):verify(s,500.)
