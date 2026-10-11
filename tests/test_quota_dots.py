import unittest
from quota_dots import quota_dot, quota_level


class QuotaDotTests(unittest.TestCase):
    def test_colors_and_missing_data(self):
        self.assertEqual(quota_level(.8)[1], '#36bb87')
        self.assertEqual(quota_level(.3)[1], '#edaa43')
        self.assertEqual(quota_level(0)[1], '#f06472')
        for value in (None, float('nan'), float('inf'), True):
            self.assertIsNone(quota_level(value)[0])

    def test_circle_fill_matches_remaining_fraction(self):
        for value in (0, .25, .5, 1):
            image = quota_dot(value)
            color = quota_level(value)[1]
            rgb = tuple(bytes.fromhex(color[1:]))
            pixels = sum(pixel[:3] == rgb and pixel[3] > 0 for pixel in image.getdata())
            if value == 0:
                previous = pixels
            else:
                self.assertGreater(pixels, previous)
                previous = pixels
        self.assertNotEqual(quota_dot(None).tobytes(), quota_dot(0).tobytes())
