"""Run synthetic checks without a camera or Google account.

Drawn diameters should have small pixel errors. A hand-checked numerical case
also checks the Shao 2022 cylinder equation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.camera_model import CameraModel
from src.detect import detect_object
from src.measure import cylinder_diameter_mm, similar_triangle_diameter_mm, tangent_diameter_mm
from src.pipeline import MeasureSettings, measure_image


CAMERA = CameraModel(
    name="test",
    sensor_width=1600,
    sensor_height=1200,
    pixel_size_mm=0.0022,
    optical_format="1/4 inch",
    focal_length_mm=3.6,
)


def _circle_image(diameter: int = 400) -> np.ndarray:
    image = np.full((900, 1200, 3), 235, np.uint8)
    cv2.circle(image, (600, 450), diameter // 2, (30, 30, 30), thickness=-1)
    return image


def _trunk_image(width: int = 180) -> np.ndarray:
    image = np.full((1000, 800, 3), 230, np.uint8)
    x0 = 400 - width // 2
    cv2.rectangle(image, (x0, 40), (x0 + width, 960), (45, 55, 70), thickness=-1)
    return image


class GeometryTests(unittest.TestCase):
    def test_circle_pixel_diameter(self):
        detection = detect_object(_circle_image(400))
        self.assertEqual(detection.kind, "round")
        # Allow four pixels because a raster circle does not have the exact geometric area.
        self.assertAlmostEqual(detection.pixel_diameter, 400, delta=4)

    def test_trunk_pixel_diameter(self):
        detection = detect_object(_trunk_image(180))
        self.assertEqual(detection.kind, "trunk")
        self.assertAlmostEqual(detection.pixel_diameter, 180, delta=3)

    def test_shao_cylinder_is_near_the_flat_width(self):
        # L = 200 px * 0.0022 mm = 0.44 mm, f = 3.6 mm, d = 1000 mm
        # Similar triangles: D = 0.44 * 1000 / 3.6 = 122.222 mm
        pixel_diameter = 200
        pitch = 0.0022
        focal = 3.6
        distance = 1000
        rect = similar_triangle_diameter_mm(pixel_diameter, pitch, focal, distance)
        cyl = cylinder_diameter_mm(pixel_diameter, pitch, focal, distance)
        tangent = tangent_diameter_mm(pixel_diameter, pitch, focal, distance)
        self.assertAlmostEqual(rect, 122.222, delta=0.01)
        self.assertGreater(cyl, rect)
        self.assertLess(abs(cyl - tangent) / tangent, 0.05)

    def test_reference_scale_on_a_circle(self):
        image = _circle_image(400)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = MeasureSettings(
                camera=CAMERA,
                distance_mm=None,
                use_saved_calibration=False,
                known_mm=100.0,
                output_dir=root / "output",
            )
            report = measure_image(image, root / "disk.jpg", settings, root)
            self.assertEqual(report["scale_mode"], "calibrate")
            self.assertAlmostEqual(report["diameter_mm"], 100.0, delta=0.01)
            self.assertTrue((root / "calibration.json").is_file())


def run_self_test(project_root: Path) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GeometryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    out = project_root / "output"
    out.mkdir(exist_ok=True)
    cv2.imwrite(str(out / "selftest_circle.jpg"), _circle_image())
    cv2.imwrite(str(out / "selftest_trunk.jpg"), _trunk_image())
    print("Synthetic images written to output/selftest_*.jpg")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(run_self_test(Path(__file__).resolve().parents[1]))
