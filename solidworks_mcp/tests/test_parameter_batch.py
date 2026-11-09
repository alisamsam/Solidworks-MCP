import unittest
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from solidworks_mcp.tools.parameter_batch import apply_parameter_changes


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.sw = SimpleNamespace(_result=lambda success, message, *a, **k:
            dict(success=success, message=message, data=k.get('data', a[-1] if a and isinstance(a[-1], dict) else {})))
        self.changes = [dict(document_path='one.SLDPRT', configuration='Default',
            name='D1@Sketch1', value=120, unit='mm', expected_value=100)]

    def test_entire_batch_preflight_before_first_write(self):
        with patch('solidworks_mcp.tools.parameter_batch._preflight', side_effect=ValueError('stale')), \
             patch('solidworks_mcp.tools.parameter_batch.set_model_dimension') as write:
            r = apply_parameter_changes(self.sw, self.changes)
        self.assertFalse(r['success']); write.assert_not_called()

    def test_duplicate_driver_rejected(self):
        with patch('solidworks_mcp.tools.parameter_batch._preflight') as preflight:
            r = apply_parameter_changes(self.sw, self.changes * 2)
        self.assertFalse(r['success']); preflight.assert_not_called()

    def test_partial_failure_is_not_rollback(self):
        @contextmanager
        def opened(sw, path, **kwargs): yield object()
        second = dict(self.changes[0], name='D2@Sketch1')
        with patch('solidworks_mcp.tools.parameter_batch._preflight'), \
             patch('solidworks_mcp.tools.parameter_batch.open_exact', opened), \
             patch('solidworks_mcp.tools.parameter_batch.set_model_dimension', side_effect=[
                 dict(success=True, data={'after':120}), dict(success=False, message='rebuild', data={'document_may_be_modified':True})]):
            r = apply_parameter_changes(self.sw, self.changes + [second])
        self.assertFalse(r['success'])
        self.assertTrue(r['data']['document_may_be_modified'])
        self.assertFalse(r['data']['rollback_performed'])
        self.assertEqual(len(r['data']['results']), 2)

    def test_empty_batch_rejected(self):
        self.assertFalse(apply_parameter_changes(self.sw, [])['success'])


if __name__ == '__main__': unittest.main()
