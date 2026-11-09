"""CAD workflow contracts tested without starting SolidWorks."""
import base64
import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import patch

from solidworks_mcp.tools import cad_workflows as cad


class Feature:
    def __init__(self, kind='Boss'):
        self.Name = 'Target'; self.kind = kind; self.suppressed = False
        self.writes = []; self.write_ok = True; self.error = 0
    def GetTypeName2(self): return self.kind
    def IsSuppressed2(self, option, configs): return (self.suppressed,)
    def SetSuppression2(self, action, option, configs):
        self.writes.append((action, option, configs))
        if self.write_ok: self.suppressed = action == 0
        return True
    def GetErrorCode(self): return self.error
    def GetNextFeature(self): return None
    def GetFirstSubFeature(self): return None


class Document:
    def __init__(self):
        self.feature = Feature(); self.rebuild_ok = True; self.kind = 1
        self.ConfigurationManager = SimpleNamespace(ActiveConfiguration=SimpleNamespace(Name='Default'))
        self.configs = ['Default', 'Other']; self.activations = []
        self.Extension = Extension(self)
    def GetType(self): return self.kind
    def GetPathName(self): return 'C:/copy/Part.sldprt'
    def FeatureByName(self, name): return self.feature if name == 'Target' else None
    def FirstFeature(self): return self.feature
    def GetConfigurationNames(self): return self.configs
    def ShowConfiguration2(self, name):
        self.activations.append(name); self.ConfigurationManager.ActiveConfiguration.Name = name; return True
    def EditRebuild3(self): return self.rebuild_ok


class Extension:
    def __init__(self, doc): self.doc = doc; self.status = 0
    def GetPersistReference3(self, obj): return bytes([1, 2, 255])
    def GetObjectByPersistReference3(self, ref, status):
        status.value = self.status
        return self.doc.feature if self.status == 0 else None
    def GetDependencies(self, *args): return ('Missing', 'C:/absent.sldprt')
    def ListExternalFileReferencesCount(self): return 2


class Automation:
    def __init__(self): self.doc = Document()
    def get_active_doc(self): return self.doc, None
    def _result(self, success, message, error_code=0, data=None):
        return {'success': success, 'message': message, 'data': data or {}}


class CadTests(unittest.TestCase):
    def setUp(self):
        self.sw = Automation()
        guard = patch.object(cad, 'require_editable_copy', return_value=None)
        self.guard = guard.start(); self.addCleanup(guard.stop)
    def edit(self, **kw):
        args = dict(feature_name='Target', expected_type='Boss', suppressed=True,
                    expected_suppressed=False, configuration='Default')
        args.update(kw); return cad.edit_feature_definition(self.sw, **args)
    def test_suppression_current_configuration_readback(self):
        result = self.edit(); self.assertTrue(result['success'], result)
        self.assertEqual([(0, 1, None)], self.sw.doc.feature.writes)
        self.assertFalse(result['data']['saved'])
    def test_copy_denial_prevents_write(self):
        self.guard.return_value = {'success': False, 'message': 'denied'}
        self.assertFalse(self.edit()['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_wrong_configuration_prevents_write(self):
        self.assertFalse(self.edit(configuration='Other')['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_unsupported_feature_prevents_write(self):
        self.sw.doc.feature.kind = 'Imported'
        self.assertFalse(self.edit(expected_type='Imported')['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_stale_type_prevents_write(self):
        self.assertFalse(self.edit(expected_type='Cut')['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_stale_state_prevents_write(self):
        self.assertFalse(self.edit(expected_suppressed=True)['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_missing_feature_prevents_write(self):
        self.assertFalse(self.edit(feature_name='Missing')['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_bool_validation_prevents_write(self):
        self.assertFalse(self.edit(suppressed=1)['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_failed_readback_reports_possible_write(self):
        self.sw.doc.feature.write_ok = False
        result = self.edit(); self.assertFalse(result['success']); self.assertTrue(result['data']['document_may_be_modified'])
    def test_failed_rebuild_reports_possible_write(self):
        self.sw.doc.rebuild_ok = False
        result = self.edit(); self.assertFalse(result['success']); self.assertTrue(result['data']['document_may_be_modified'])
    def test_mate_rejects_nonmate(self):
        result = cad.edit_mate(self.sw, 'Target', 'Boss', True, False, 'Default')
        self.assertFalse(result['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def test_mate_supports_distance_suppression(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'MateDistanceDim'
        result = cad.edit_mate(self.sw, 'Target', 'MateDistanceDim', True, False, 'Default')
        self.assertTrue(result['success'], result)
    def test_mate_distance_driver_delegates_guarded_dimension(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'MateDistanceDim'
        with patch.object(cad, 'set_model_dimension', return_value={'success': True}) as setter:
            result = cad.edit_mate(self.sw, 'Target', 'MateDistanceDim', configuration='Default',
                action='dimension', dimension_name='D1@Target', value=150, expected_value=100, unit='mm')
        self.assertTrue(result['success']); setter.assert_called_once_with(self.sw, 'D1@Target', 150, 'mm', 100, 'Default', False)
    def test_mate_angle_driver_requires_angular_unit(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'MatePlanarAngleDim'
        with patch.object(cad, 'set_model_dimension') as setter:
            result = cad.edit_mate(self.sw, 'Target', 'MatePlanarAngleDim', configuration='Default',
                action='dimension', dimension_name='D1@Target', value=15, expected_value=10, unit='mm')
        self.assertFalse(result['success']); setter.assert_not_called()
    def test_mate_dimension_cross_feature_rejected(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'MateDistanceDim'
        with patch.object(cad, 'set_model_dimension') as setter:
            result = cad.edit_mate(self.sw, 'Target', 'MateDistanceDim', configuration='Default',
                action='dimension', dimension_name='D1@Other', value=15, expected_value=10, unit='mm')
        self.assertFalse(result['success']); setter.assert_not_called()
    def test_pattern_spacing_driver_delegates_guarded_dimension(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'LocalLPattern'
        with patch.object(cad, 'set_model_dimension', return_value={'success': True}) as setter:
            result = cad.edit_component_pattern(self.sw, 'Target', 'LocalLPattern', configuration='Default',
                action='spacing_dimension', dimension_name='D1@Target', spacing_mm=150, expected_spacing_mm=100)
        self.assertTrue(result['success']); setter.assert_called_once_with(self.sw, 'D1@Target', 150, 'mm', 100, 'Default', False)
    def test_pattern_rejects_part_pattern(self):
        self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'LPattern'
        result = cad.edit_component_pattern(self.sw, 'Target', 'LPattern', True, False, 'Default')
        self.assertFalse(result['success']); self.assertEqual([], self.sw.doc.feature.writes)
    def definition(self):
        class Data:
            def __init__(self): self.depth = .1; self.end = 0; self.writes = []; self.released = False; self.D1TotalInstances = 3
            def AccessSelections(self, doc, component): return True
            def ReleaseSelectionAccess(self): self.released = True
            def GetDepth(self, forward): return self.depth
            def SetDepth(self, forward, depth): self.writes.append(('depth', forward, depth)); self.depth = depth
            def GetEndCondition(self, forward): return self.end
            def SetEndCondition(self, forward, condition): self.writes.append(('mode', forward, condition)); self.end = condition
            def IsThinFeature(self): return False
            BothDirections = False
        data = Data(); feature = self.sw.doc.feature
        feature.GetDefinition = MethodType(lambda self: data, feature)
        feature.ModifyDefinition = MethodType(lambda self, data, doc, comp: True, feature)
        self.sw.doc.configs = ['Default']
        return data
    def test_extrusion_depth_mode_definition_readback(self):
        data = self.definition()
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=100, end_condition='mid_plane', expected_end_condition='blind')
        self.assertTrue(result['success'], result); self.assertEqual(.15, data.depth); self.assertEqual(6, data.end)
    def test_extrusion_multi_config_rejected_before_write(self):
        data = self.definition(); self.sw.doc.configs.append('Other')
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=100, end_condition='blind', expected_end_condition='blind')
        self.assertFalse(result['success']); self.assertEqual([], data.writes)
    def test_extrusion_stale_depth_prevents_write(self):
        data = self.definition()
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=90, end_condition='blind', expected_end_condition='blind')
        self.assertFalse(result['success']); self.assertEqual([], data.writes)
    def test_extrusion_unsupported_end_condition_prevents_write(self):
        data = self.definition(); data.end = 1
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=100, end_condition='blind', expected_end_condition='blind')
        self.assertFalse(result['success']); self.assertEqual([], data.writes)
    def test_extrusion_partial_setter_failure_reports_modified_and_releases(self):
        data = self.definition()
        def fail(self, forward, depth): raise RuntimeError('COM setter failed')
        data.SetDepth = MethodType(fail, data)
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=100, end_condition='mid_plane', expected_end_condition='blind')
        self.assertFalse(result['success']); self.assertTrue(result['data']['document_may_be_modified'])
        self.assertEqual(6, data.end); self.assertTrue(data.released)
    def test_extrusion_modify_false_reports_possible_write(self):
        data = self.definition()
        self.sw.doc.feature.ModifyDefinition = MethodType(lambda self, *args: False, self.sw.doc.feature)
        result = cad.edit_feature_definition(self.sw, 'Target', 'Boss', configuration='Default', action='extrusion',
            depth_mm=150, expected_depth_mm=100, end_condition='mid_plane', expected_end_condition='blind')
        self.assertFalse(result['success']); self.assertTrue(result['data']['document_may_be_modified']); self.assertTrue(data.released)
    def test_pattern_count_definition_readback(self):
        data = self.definition(); self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'LocalLPattern'
        result = cad.edit_component_pattern(self.sw, 'Target', 'LocalLPattern', configuration='Default',
            action='linear_count', instances=5, expected_instances=3)
        self.assertTrue(result['success'], result); self.assertEqual(5, data.D1TotalInstances)
    def test_pattern_stale_count_prevents_write(self):
        data = self.definition(); self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'LocalLPattern'
        result = cad.edit_component_pattern(self.sw, 'Target', 'LocalLPattern', configuration='Default',
            action='linear_count', instances=5, expected_instances=4)
        self.assertFalse(result['success']); self.assertEqual(3, data.D1TotalInstances)
    def test_pattern_multiple_config_prevents_write(self):
        data = self.definition(); self.sw.doc.kind = 2; self.sw.doc.feature.kind = 'LocalLPattern'
        self.sw.doc.configs.append('Other')
        result = cad.edit_component_pattern(self.sw, 'Target', 'LocalLPattern', configuration='Default',
            action='linear_count', instances=5, expected_instances=3)
        self.assertFalse(result['success']); self.assertEqual(3, data.D1TotalInstances)
    def test_config_inspect_does_not_activate(self):
        result = cad.manage_configurations(self.sw)
        self.assertTrue(result['success']); self.assertEqual([], self.sw.doc.activations)
    def test_explicit_activate_requires_exact_prior(self):
        result = cad.manage_configurations(self.sw, 'activate', 'Other', 'Wrong')
        self.assertFalse(result['success']); self.assertEqual([], self.sw.doc.activations)
    def test_explicit_activate_readback(self):
        result = cad.manage_configurations(self.sw, 'activate', 'Other', 'Default')
        self.assertTrue(result['success'], result); self.assertEqual(['Other'], self.sw.doc.activations)
    def test_config_activation_false_return_valid_readback_and_rebind(self):
        def activate(doc, name): doc.ConfigurationManager.ActiveConfiguration.Name = name; return False
        self.sw.doc.ShowConfiguration2 = MethodType(activate, self.sw.doc)
        self.sw.bind_active_document = unittest.mock.Mock()
        result = cad.manage_configurations(self.sw, 'activate', 'Other', 'Default')
        self.assertTrue(result['success'], result); self.sw.bind_active_document.assert_called_once()
    def test_config_delete_rejected(self):
        self.assertFalse(cad.manage_configurations(self.sw, 'delete', 'Other', 'Default')['success'])
    def test_health_reports_existing_errors(self):
        self.sw.doc.feature.error = 7
        result = cad.inspect_model_health(self.sw)
        self.assertTrue(result['success']); self.assertFalse(result['data']['healthy'])
    def test_health_unavailable_not_healthy(self):
        self.sw.doc.feature.GetErrorCode = None
        self.sw.doc.Extension.GetDependencies = MethodType(lambda self, *args: (), self.sw.doc.Extension)
        result = cad.inspect_model_health(self.sw)
        self.assertTrue(result['success']); self.assertIsNone(result['data']['healthy'])
    def test_reference_roundtrip_document_bound(self):
        result = cad.create_persistent_reference(self.sw, 'Target', 'Default')
        self.assertTrue(result['success'], result)
        reference = result['data']['reference']
        self.assertEqual('AQL/', reference['base64'])
        self.assertTrue(cad.resolve_persistent_reference(self.sw, reference)['success'])
    def test_reference_other_document_rejected(self):
        ref = {'path': 'C:/source/Part.sldprt', 'configuration': 'Default', 'base64': 'AQL/'}
        self.assertFalse(cad.resolve_persistent_reference(self.sw, ref)['success'])
    def test_reference_deleted_status_rejected(self):
        self.sw.doc.Extension.status = 2
        ref = {'path': self.sw.doc.GetPathName(), 'configuration': 'Default', 'base64': 'AQL/'}
        self.assertFalse(cad.resolve_persistent_reference(self.sw, ref)['success'])
    def test_holes_do_not_infer_fasteners(self):
        self.sw.doc.feature.kind = 'HoleWzd'
        result = cad.inspect_holes_and_fasteners(self.sw)
        self.assertTrue(result['success']); self.assertEqual([], result['data']['identified_fasteners'])
        self.assertEqual('HoleWzd', result['data']['hole_features'][0]['type'])
    def test_external_references_inspect_and_break_reject(self):
        result = cad.manage_external_references(self.sw)
        self.assertTrue(result['success']); self.assertEqual(2, result['data']['in_context_reference_count'])
        self.assertFalse(cad.manage_external_references(self.sw, 'break')['success'])
    def test_interference_part_rejected(self):
        self.assertFalse(cad.check_interferences(self.sw, 'Default')['success'])
    def test_profile_multiple_configurations_rejected_before_definition(self):
        self.sw.doc.feature.kind = 'WeldMemberFeat'
        result = cad.replace_structural_profile(self.sw, 'Target', 'old.sldflp', 'new.sldflp', 'Default')
        self.assertFalse(result['success']); self.assertFalse(result['data']['document_may_be_modified'])
    def test_profile_single_config_modify_and_readback(self):
        import tempfile
        from pathlib import Path
        class Definition:
            WeldmentProfilePath = 'old.sldflp'
            ConfigurationName = ''
            def AccessSelections(self, doc, component): return True
            def ReleaseSelectionAccess(self): pass
        definition = Definition(); feature = self.sw.doc.feature
        feature.kind = 'WeldMemberFeat'; feature.GetDefinition = MethodType(lambda self: definition, feature)
        feature.ModifyDefinition = MethodType(lambda self, data, doc, comp: True, feature)
        self.sw.doc.configs = ['Default']
        self.sw._path_policy = SimpleNamespace(require_read=lambda path: None)
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'new.sldflp'; profile.write_bytes(b'profile')
            result = cad.replace_structural_profile(self.sw, 'Target', 'old.sldflp', str(profile), 'Default')
            self.assertTrue(result['success'], result)
            self.assertEqual(str(profile.resolve()), definition.WeldmentProfilePath)
    def test_interference_cleanup_and_actual_volume(self):
        class Manager:
            def __init__(self): self.done = False
            def GetInterferences(self): return (SimpleNamespace(Volume=.000001, Components=(), IsFastener=False),)
            def Done(self): self.done = True
        manager = Manager(); self.sw.doc.kind = 2; self.sw.doc.InterferenceDetectionManager = manager
        result = cad.check_interferences(self.sw, 'Default')
        self.assertTrue(result['success'], result); self.assertTrue(manager.done)
        self.assertAlmostEqual(1000, result['data']['interferences'][0]['volume_mm3'])


if __name__ == '__main__': unittest.main()
