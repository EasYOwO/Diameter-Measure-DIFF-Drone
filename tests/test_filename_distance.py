import unittest
from pathlib import Path

from src.filename_distance import apply_filename_distance_to_settings, parse_filename_distance
from src.pipeline import MeasureSettings
from src.camera_model import CameraModel


class FilenameDistanceTests(unittest.TestCase):
    def test_object_distance_mm(self):
        parsed = parse_filename_distance("object43_100mm.jpg")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.object_id, "43")
        self.assertAlmostEqual(parsed.distance_mm, 100.0)
        self.assertFalse(parsed.unavailable)

    def test_drive_prefix(self):
        parsed = parse_filename_distance(Path("downloads/abc_object42_101mm.JPG"))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.object_id, "42")
        self.assertAlmostEqual(parsed.distance_mm, 101.0)

    def test_distance_unavailable(self):
        parsed = parse_filename_distance("object44_distance-unavailable.jpg")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.unavailable)
        self.assertIsNone(parsed.distance_mm)

    def test_apply_to_settings(self):
        settings = MeasureSettings(
            CameraModel("t", 1600, 1200, 0.0022, "1/4 inch", 3.6),
            distance_mm=None,
            use_saved_calibration=False,
        )
        apply_filename_distance_to_settings(settings, "object41_103mm.jpg")
        self.assertAlmostEqual(settings.distance_mm, 103.0)
        self.assertIn("filename:", settings.distance_source or "")


if __name__ == "__main__":
    unittest.main()
