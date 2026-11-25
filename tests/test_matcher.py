"""White-text recognition regressions using deterministic screen-like images."""

import unittest

import numpy as np

from loco_box.matcher import WhiteTextMatcher


def text_frame():
    frame = np.zeros((40, 150, 3), dtype=np.uint8)
    for x in range(10, 140, 28):
        frame[8:32, x:x + 3] = 255
        frame[8:11, x:x + 17] = 255
        frame[19:22, x:x + 14] = 255
        frame[29:32, x:x + 17] = 255
    return frame


class WhiteTextMatcherTests(unittest.TestCase):
    def setUp(self):
        self.template = text_frame()
        self.matcher = WhiteTextMatcher(self.template)

    def test_matching_text_is_strongly_present(self):
        self.assertTrue(self.matcher.is_valid)
        result = self.matcher.analyze(self.template, threshold=0.45)
        self.assertFalse(result.absent)
        self.assertTrue(result.strong_present)
        self.assertTrue(result.weak_present)
        self.assertAlmostEqual(result.score, 1.0)

    def test_blank_and_white_screens_do_not_match_text(self):
        for brightness in (0, 195, 230, 255):
            with self.subTest(brightness=brightness):
                result = self.matcher.analyze(np.full_like(self.template, brightness), 0.45)
                self.assertTrue(result.absent)
                self.assertFalse(result.strong_present)
                self.assertFalse(result.weak_present)
                self.assertEqual(result.score, 0.0)

    def test_incomplete_text_cannot_trigger_appearance(self):
        frame = self.template.copy()
        frame[:, 60:] = 0
        result = self.matcher.analyze(frame, threshold=0.45)
        self.assertTrue(result.absent)
        self.assertFalse(result.strong_present)
        self.assertFalse(result.weak_present)


if __name__ == "__main__":
    unittest.main()
