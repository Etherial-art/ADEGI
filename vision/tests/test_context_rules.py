import unittest

import numpy as np

from adegi_vision.classes import (
    BED, CANE, CHAIR, COUCH, HORIZONTAL, SITTING, STANDING, STATE_FALLEN, STATE_LYING_BED,
    STATE_SITTING, STATE_STANDING, STATE_UNKNOWN, WALKER,
)
from adegi_vision.context_rules import FallDebouncer, classify_context, iop, torso_angle_deg
from adegi_vision.types import Box, Detection
from helpers import kp_array, lying_person, standing_person


def det(cls, x1, y1, x2, y2):
    return Detection(cls, 0.9, Box(x1, y1, x2, y2))


class IoPTests(unittest.TestCase):
    def test_person_fully_inside_big_bed_is_one(self):
        self.assertAlmostEqual(iop(Box(10, 10, 20, 20), Box(0, 0, 500, 500)), 1.0)

    def test_disjoint_is_zero(self):
        self.assertEqual(iop(Box(0, 0, 10, 10), Box(20, 20, 30, 30)), 0.0)

    def test_degenerate_person(self):
        self.assertEqual(iop(Box(5, 5, 5, 5), Box(0, 0, 10, 10)), 0.0)

    def test_not_symmetric(self):  # that is the whole point vs IoU
        small, big = Box(0, 0, 10, 10), Box(0, 0, 100, 100)
        self.assertAlmostEqual(iop(small, big), 1.0)
        self.assertAlmostEqual(iop(big, small), 0.01)


class TorsoAngleTests(unittest.TestCase):
    def test_standing_is_vertical(self):
        self.assertGreater(torso_angle_deg(standing_person()[1]), 80)

    def test_lying_is_horizontal(self):
        self.assertLess(torso_angle_deg(lying_person()[1]), 10)

    def test_none_when_hips_missing(self):
        kp = kp_array({5: (0, 0), 6: (1, 0)})
        self.assertIsNone(torso_angle_deg(kp))


class LyingVsFallenTests(unittest.TestCase):
    def test_lying_on_bed(self):
        person, kp = lying_person(100, 280)
        bed = det(BED, 50, 150, 500, 400)  # hips y=280 < 400 - 0.15*250 = 362.5
        ctx = classify_context(HORIZONTAL, person, kp, [bed])
        self.assertEqual(ctx.state, STATE_LYING_BED)

    def test_lying_on_couch_counts_as_lying(self):
        person, kp = lying_person(100, 280)
        ctx = classify_context(HORIZONTAL, person, kp, [det(COUCH, 50, 150, 500, 400)])
        self.assertEqual(ctx.state, STATE_LYING_BED)

    def test_horizontal_no_furniture_is_fallen(self):
        person, kp = lying_person()
        self.assertEqual(classify_context(HORIZONTAL, person, kp, []).state, STATE_FALLEN)

    def test_horizontal_next_to_bed_is_fallen(self):
        person, kp = lying_person(600, 280)  # far to the right of the bed
        bed = det(BED, 50, 150, 500, 400)
        self.assertEqual(classify_context(HORIZONTAL, person, kp, [bed]).state, STATE_FALLEN)

    def test_hip_at_base_of_bed_is_fallen(self):
        # Person overlaps the bed a lot but the hips are at its lower edge (slid off).
        person, kp = lying_person(100, 395)
        bed = det(BED, 50, 150, 500, 420)  # limit = 420 - 0.15*270 = 379.5 < 395
        self.assertEqual(classify_context(HORIZONTAL, person, kp, [bed]).state, STATE_FALLEN)

    def test_chair_does_not_make_lying(self):
        person, kp = lying_person()
        chair = det(CHAIR, 0, 0, 1000, 1000)
        self.assertEqual(classify_context(HORIZONTAL, person, kp, [chair]).state, STATE_FALLEN)

    def test_upright_torso_contradicts_horizontal(self):
        person, kp = standing_person()
        self.assertEqual(classify_context(HORIZONTAL, person, kp, []).state, STATE_UNKNOWN)

    def test_missing_hips_falls_back_to_box_center(self):
        person, kp = lying_person(100, 280)
        kp[11, 2] = kp[12, 2] = 0.0  # hips not visible; shoulders+nose still inside bed
        bed = det(BED, 50, 150, 500, 400)
        self.assertEqual(classify_context(HORIZONTAL, person, kp, [bed]).state, STATE_LYING_BED)

    def test_fallen_flags_loose_aid(self):
        person, kp = lying_person(100, 280)
        walker = det(WALKER, 1500, 280, 1600, 380)
        ctx = classify_context(HORIZONTAL, person, kp, [walker])
        self.assertEqual(ctx.state, STATE_FALLEN)
        self.assertTrue(ctx.aid_far)

    def test_fallen_aid_close_is_not_far(self):
        person, kp = lying_person(100, 280)
        cane = det(CANE, 420, 240, 440, 320)
        self.assertFalse(classify_context(HORIZONTAL, person, kp, [cane]).aid_far)


class OtherStatesTests(unittest.TestCase):
    def test_standing_with_walker(self):
        person, kp = standing_person()
        walker = det(WALKER, 90, 250, 210, 400)
        ctx = classify_context(STANDING, person, kp, [walker])
        self.assertEqual(ctx.state, STATE_STANDING)
        self.assertTrue(ctx.with_aid)

    def test_standing_without_aid(self):
        person, kp = standing_person()
        self.assertFalse(classify_context(STANDING, person, kp, []).with_aid)

    def test_sitting_confirmed_by_chair(self):
        person, kp = standing_person()
        ctx = classify_context(SITTING, person, kp, [det(CHAIR, 90, 200, 210, 420)])
        self.assertEqual(ctx.state, STATE_SITTING)
        self.assertTrue(ctx.sitting_confirmed)

    def test_sitting_unconfirmed_without_furniture(self):
        person, kp = standing_person()
        ctx = classify_context(SITTING, person, kp, [])
        self.assertEqual(ctx.state, STATE_SITTING)
        self.assertFalse(ctx.sitting_confirmed)

    def test_unknown_posture_raises(self):
        person, kp = standing_person()
        with self.assertRaises(ValueError):
            classify_context(9, person, kp, [])


class DebouncerTests(unittest.TestCase):
    def test_alert_after_hold(self):
        d = FallDebouncer(hold_s=3, clear_s=1)
        self.assertFalse(d.update(True, 0.0))
        self.assertFalse(d.update(True, 2.9))
        self.assertTrue(d.update(True, 3.0))

    def test_short_blip_does_not_reset(self):
        d = FallDebouncer(hold_s=3, clear_s=1)
        d.update(True, 0.0)
        d.update(False, 1.0)  # blip shorter than clear_s
        d.update(True, 1.5)
        self.assertTrue(d.update(True, 3.0))

    def test_clears_after_clear_s(self):
        d = FallDebouncer(hold_s=1, clear_s=1)
        d.update(True, 0.0)
        self.assertTrue(d.update(True, 1.0))
        d.update(False, 2.0)
        self.assertTrue(d.update(False, 2.5))  # not yet
        self.assertFalse(d.update(False, 3.0))

    def test_none_keeps_state(self):
        d = FallDebouncer(hold_s=1, clear_s=1)
        d.update(True, 0.0)
        d.update(True, 1.0)
        self.assertTrue(d.update(None, 50.0))

    def test_brief_crouch_never_alerts(self):
        d = FallDebouncer(hold_s=3, clear_s=1)
        d.update(True, 0.0)
        d.update(True, 1.0)
        d.update(False, 1.2)
        d.update(False, 2.5)  # cleared the candidate
        self.assertFalse(d.update(True, 3.0))
        self.assertFalse(d.update(True, 5.0))


if __name__ == "__main__":
    unittest.main()
