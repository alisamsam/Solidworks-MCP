import unittest
from solidworks_mcp.component_families import compile_plate_variant,same_family
class FamilyTests(unittest.TestCase):
 def test_same_size_different_hole_semantics_not_same_family(self):
  self.assertFalse(same_family({'topology':'plate4holes','hole_semantics':'round'},{'topology':'plate4holes','hole_semantics':'dowel'}))
  self.assertTrue(same_family({'topology':'plate4holes','hole_semantics':'round'},{'topology':'plate4holes','hole_semantics':'round'}))
 def test_wrong_feature_or_driven_dimension_rejected(self):
  snapshot={'configuration':'Default','dimensions':[{'name':'D2@Sketch1@Part','value':280,'unit':'mm','read_only':False,'driven_state':2,'equation_controlled':False}]}
  changes=compile_plate_variant(snapshot,'size300',{'D2@Sketch1':300})
  self.assertEqual(280,changes[0]['expected_value'])
  self.assertEqual('size300',changes[0]['configuration'])
  snapshot['dimensions'][0]['read_only']=True
  with self.assertRaises(ValueError):compile_plate_variant(snapshot,'size300',{'D2@Sketch1':300})
  with self.assertRaises(ValueError):compile_plate_variant(snapshot,'size300',{'missing':300})
 def test_nonfinite_dimension_not_allowed(self):
  snapshot={'dimensions':[{'name':'D2@Sketch1@Part','value':280,'unit':'mm','read_only':False,'driven_state':2,'equation_controlled':False}]}
  with self.assertRaises(ValueError):compile_plate_variant(snapshot,'cfg',{'D2@Sketch1':float('inf')})
