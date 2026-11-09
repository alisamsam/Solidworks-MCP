import math
import unittest
from solidworks_mcp.tools.engineering_planners import plan_stair, plan_railing, plan_segments, review_galvanizing


class SW:
    def _result(self, success, message, error_code=0, data=None):
        return dict(success=success, message=message, data=data or {})


class PlannerTests(unittest.TestCase):
    def test_missing_stair_inputs_are_questions(self):
        r = plan_stair(SW(), total_height_mm=3000)
        self.assertEqual('needs_inputs', r['data']['status'])
        self.assertTrue(r['data']['missing_questions'])

    def test_stair_calculates_risers_and_treads_separately(self):
        r = plan_stair(SW(), 3000, 18, 270, 1000, [1500])
        self.assertTrue(r['success'])
        self.assertEqual(17, r['data']['tread_count'])
        self.assertAlmostEqual(3000 / 18, r['data']['riser_height_mm'])
        self.assertEqual(6090, r['data']['developed_run_mm'])
        self.assertFalse(r['data']['geometry_verified'])

    def test_invalid_numbers_are_rejected(self):
        for value in (-1, 0, math.nan, math.inf, True):
            self.assertFalse(plan_stair(SW(), value, 18, 270, 1000, [])['success'])

    def test_railing_requires_height_reference(self):
        r = plan_railing(SW(), 1100, None, 3000, 1000)
        self.assertIn('height_reference', r['data']['missing_inputs'])

    def test_railing_spacing_is_upper_bound(self):
        r = plan_railing(SW(), 1100, 'finished_floor', 3100, 1000)
        self.assertEqual(4, r['data']['bay_count'])
        self.assertEqual(775, r['data']['post_spacing_mm'])

    def test_segment_limits_and_no_invented_joints(self):
        r = plan_segments(SW(), 10000, 6000, 4000)
        self.assertEqual(3, r['data']['segment_count'])
        self.assertEqual([], r['data']['joint_designs'])
        self.assertFalse(r['data']['geometry_verified'])

    def test_galvanizing_requires_orientation_and_never_approves(self):
        r = review_galvanizing(SW(), [{'id': 'tube', 'hollow': True}])
        self.assertIn('immersion_orientation', r['data']['missing_inputs'])
        self.assertFalse(r['data']['compliance_verified'])
        self.assertEqual([], r['data']['automatic_hole_placements'])

    def test_closed_hollow_member_is_flagged(self):
        r = review_galvanizing(SW(), [{'id': 'tube', 'hollow': True, 'vent_open': False,
            'drain_open': False}], 'end A high, end B low')
        self.assertTrue(r['data']['findings'])

    def test_explicit_galvanizing_facts_can_finish_review_without_approval(self):
        r = review_galvanizing(SW(), [{'id': 'tube', 'hollow': True, 'vent_open': True,
            'drain_open': True, 'connected_to_exterior': True, 'extreme_end_openings_confirmed': True,
            'provider_detail': 'provider issue/page/detail to be reviewed', 'opening_dimensions_mm': [14, 14],
            'opening_locations': 'end A and end B at orientation extrema'}],
            'end A high, end B low', 'provider issue 01')
        self.assertEqual([], r['data']['missing_inputs'])
        self.assertFalse(r['data']['compliance_verified'])

if __name__ == '__main__':
    unittest.main()
