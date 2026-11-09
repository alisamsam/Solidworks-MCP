import unittest,math
from solidworks_mcp.stair_recipe import analyze_repetition, centered_sketch_commands, compile_changes, replay_centered_segments, turn_concept
class RecipeTests(unittest.TestCase):
 def test_uniform_repetition_measures_each_gap(self):
  cs=[{'parent_path':None,'path':'step.SLDASM','name':f'step-{i+1}','transform':[0]*9+[.24*i,.175*i,0]+[1,0,0,0]} for i in range(3)]
  r=analyze_repetition(cs,'step.SLDASM')
  self.assertAlmostEqual(240,r['translation_per_instance_mm'][0])
  self.assertAlmostEqual(175,r['translation_per_instance_mm'][1])
  self.assertTrue(r['uniform'])
  cs[2]['transform'][9]+=.01
  self.assertFalse(analyze_repetition(cs,'step.SLDASM')['uniform'])
 def test_profile_translation_preserves_clockwise_minor_arc(self):
  geometry={'complete':True,'endpoint_center_mm':[50,75,0],'segments':[{'type':1,'start_mm':[52,75,0],'end_mm':[50,73,0],'center_mm':[50,75,0],'radius_mm':2,'rotation_direction':-1}]}
  c=centered_sketch_commands(geometry)[0]
  self.assertEqual('draw_arc_3point',c['tool'])
  self.assertAlmostEqual(math.sqrt(2),c['arguments']['point_x'])
  self.assertAlmostEqual(-math.sqrt(2),c['arguments']['point_y'])
 def test_incomplete_profile_not_reconstructed(self):
  with self.assertRaises(ValueError):centered_sketch_commands({'complete':False})
 def test_replay_disables_inference_and_restores_it_on_failure(self):
  class Manager:
   def CreateLine(self,*args):
    self.assertion();raise RuntimeError('fixture failure')
  class Doc:
   def __init__(self):self.flags=[];self.SketchManager=Manager();self.SketchManager.assertion=lambda:self.flags[-1]==True or (_ for _ in ()).throw(AssertionError())
   def SetAddToDB(self,value):self.flags.append(value)
   def SetDisplayWhenAdded(self,value):pass
  d=Doc()
  with self.assertRaises(RuntimeError):replay_centered_segments(d,[{'tool':'draw_line','arguments':{'x1':0,'y1':0,'x2':1,'y2':0}}])
  self.assertEqual([True,False],d.flags)

 def test_turn_division_preserves_landing_vs_rise_semantics(self):
  self.assertEqual([45,45],turn_concept(90,'winders',2)['angular_divisions_deg'])
  self.assertEqual([30,30,30],turn_concept(90,'winders',3)['angular_divisions_deg'])
  self.assertEqual([-45,-45],turn_concept(-90,'winders',2)['angular_divisions_deg'])
  landing=turn_concept(90,'landing',1)
  self.assertEqual(1,landing['transition_element_count'])
  self.assertEqual([],landing['angular_divisions_deg'])
  self.assertIsNone(landing['riser_count'])
 def test_turn_count_and_angle_validation(self):
  for args in [(90,'winders',0),(90,'landing',2),(float('nan'),'winders',2),(90,'winders',True)]:
   with self.assertRaises(ValueError):turn_concept(*args)

 def test_unknown_or_nonfinite_parameter_is_rejected(self):
  with self.assertRaises(ValueError):compile_changes([],{'floor_height_mm':3000})
  bindings=[{'key':'width_mm','document_path':'copy.SLDPRT','configuration':'Default','name':'D1@Sketch1','unit':'mm','observed_value':880}]
  with self.assertRaises(ValueError):compile_changes(bindings,{'width_mm':float('nan')})
  r=compile_changes(bindings,{'width_mm':900})
  self.assertEqual(880,r[0]['expected_value']);self.assertEqual(900,r[0]['value'])
