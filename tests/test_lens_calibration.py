"""Synthetic camera recovery and integration checks; no claim of real-lens accuracy."""
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.camera_model import CameraModel
from src.lens_calibration import SCHEMA, board_points, rectify_image, solve_calibration
from src.measure import diameter_from_intrinsics
from src.pipeline import MeasureSettings, measure_image


class LensCalibrationTests(unittest.TestCase):
    def synthetic_views(self, model):
        rng = np.random.default_rng(123)
        points = board_points()
        matrix = np.array([[820., 0, 800], [0, 830, 600], [0, 0, 1]])
        distortion = (np.array([-.04, .005, -.0005, .0001]) if model == "fisheye"
                      else np.array([-.12, .02, .001, -.002, -.003]))
        objects, views = [], []
        for _ in range(24):
            rvec = rng.uniform(-.5, .5, 3).reshape(3, 1)
            tvec = np.array([rng.uniform(-220, 100), rng.uniform(-160, 60), rng.uniform(350, 800)]).reshape(3, 1)
            if model == "fisheye":
                img, _ = cv2.fisheye.projectPoints(points, rvec, tvec, matrix, distortion)
            else:
                img, _ = cv2.projectPoints(points, rvec, tvec, matrix, distortion)
            objects.append(points.copy())
            views.append(img)
        return matrix, objects, views

    def test_recovers_fisheye_intrinsics(self):
        matrix, objects, views = self.synthetic_views("fisheye")
        result = solve_calibration(objects, views, (1600, 1200), "fisheye")
        self.assertLess(result["rms_px"], .01)
        np.testing.assert_allclose(result["camera_matrix"], matrix, atol=.01)

    def test_recovers_pinhole_intrinsics(self):
        matrix, objects, views = self.synthetic_views("pinhole")
        result = solve_calibration(objects, views, (1600, 1200), "pinhole")
        self.assertLess(result["rms_px"], .01)
        np.testing.assert_allclose(result["camera_matrix"], matrix, atol=.1)

    def test_static_views_are_rejected(self):
        _, objects, views = self.synthetic_views("pinhole")
        with self.assertRaisesRegex(ValueError, "one position"):
            solve_calibration(objects[:10], [views[0]] * 10, (1600, 1200), "pinhole")

    def test_insufficient_views_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 10"):
            solve_calibration([], [], (1600, 1200))

    def test_known_cylinder_projects_back_to_real_diameter(self):
        # Independent forward tangent geometry for D=300mm, front distance=1000mm.
        diameter, distance, focal = 300., 1000., 800.
        angle = np.arcsin((diameter / 2) / (distance + diameter / 2))
        projected_width = 2 * focal * np.tan(angle)
        result = diameter_from_intrinsics(projected_width, focal, distance)
        self.assertAlmostEqual(result.diameter_mm, diameter, places=10)
        self.assertAlmostEqual(diameter_from_intrinsics(80, 800, 1000, "flat").diameter_mm, 100)

    def test_high_image_width_cylinder_not_silently_flat(self):
        result = diameter_from_intrinsics(1200, 800, 1000)
        self.assertGreater(result.diameter_mm, 1500)

    def test_invalid_inputs_rejected(self):
        for value in [0., -1., np.nan, np.inf]:
            with self.assertRaises(ValueError):
                diameter_from_intrinsics(200, 800, value)

    def calibration_file(self, folder):
        matrix = [[800., 0, 800], [0, 800, 600], [0, 0, 1]]
        payload = {"schema": SCHEMA, "model": "pinhole", "image_size": [1600, 1200],
                   "camera_matrix": matrix, "rectified_camera_matrix": matrix,
                   "distortion": [0.] * 5, "rms_px": 0.}
        path = Path(folder) / "camera_intrinsics.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_rectification_checks_full_image_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.calibration_file(temp)
            with self.assertRaisesRegex(ValueError, "size differs"):
                rectify_image(np.zeros((600, 800, 3), np.uint8), path)

    def test_pipeline_uses_actual_rectified_focal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = self.calibration_file(temp)
            image = np.full((1200, 1600, 3), 230, np.uint8)
            cv2.rectangle(image, (720, 80), (880, 1120), (30, 30, 30), -1)
            # Deliberately absurd old focal: intrinsics must take precedence.
            camera = CameraModel("test", 1600, 1200, .0022, "1/4 inch", 99.)
            settings = MeasureSettings(camera, 1000., False, output_dir=root / "out", intrinsics_path=path)
            result = measure_image(image, root / "test.jpg", settings, root)
            self.assertEqual(result["scale_mode"], "calibrated_distance")
            self.assertEqual(result["camera_calibration"]["fx_px"], 800.)
            self.assertAlmostEqual(result["diameter_mm"], diameter_from_intrinsics(result["pixel_diameter"], 800, 1000).diameter_mm, places=2)

    def test_default_36mm_does_not_produce_measurement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = np.full((600, 800, 3), 230, np.uint8)
            cv2.rectangle(image, (340, 40), (460, 560), (30, 30, 30), -1)
            settings = MeasureSettings(CameraModel("test", 1600, 1200, .0022, "1/4 inch", 3.6), 1000, False)
            with self.assertRaisesRegex(ValueError, "Lens not calibrated"):
                measure_image(image, root / "test.jpg", settings, root)

    def test_cli_reads_distance_filename_and_uses_intrinsics(self):
        import main as cli
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.calibration_file(temp)
            config = root / "config.yaml"
            config.write_text("camera:\n  name: test\n  sensor_width: 1600\n  sensor_height: 1200\n  pixel_size_mm: 0.0022\n  focal_length_mm: 3.6\n  focal_length_verified: false\n", encoding="utf-8")
            image = np.full((1200, 1600, 3), 230, np.uint8)
            cv2.rectangle(image, (720, 80), (880, 1120), (30, 30, 30), -1)
            path = root / "driveprefix_object1_1000mm.jpg"
            cv2.imwrite(str(path), image)
            with patch.object(cli, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--image", str(path)]), 0)
            result = json.loads((root / "output" / "driveprefix_object1_1000mm_diameter.json").read_text(encoding="utf-8"))
            self.assertEqual(result["scale_detail"]["distance_mm"], 1000)
            self.assertTrue(result["distance_source"].startswith("filename"))
            self.assertEqual(result["scale_mode"], "calibrated_distance")

    def test_old_scale_cannot_cross_rectification_spaces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = self.calibration_file(temp)
            (root / "calibration.json").write_text(json.dumps({"mm_per_px": .1, "image_width": 1600}), encoding="utf-8")
            image = np.full((1200, 1600, 3), 230, np.uint8)
            cv2.rectangle(image, (720, 80), (880, 1120), (30, 30, 30), -1)
            settings = MeasureSettings(CameraModel("test", 1600, 1200, .0022, "1/4 inch", 3.6), None, True, intrinsics_path=path)
            with self.assertRaisesRegex(ValueError, "different image/calibration space"):
                measure_image(image, root / "test.jpg", settings, root)


if __name__ == "__main__":
    unittest.main()
