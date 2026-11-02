"""Threshold boundaries, nominal provenance and isolated batch results."""
import contextlib
import io
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.batch import measure_folder
from src.classification import classify_diameter
from src.pipeline import load_settings, measure_image

ROOT = Path(__file__).resolve().parents[1]


def image():
    result = np.full((600, 800, 3), 230, np.uint8)
    cv2.rectangle(result, (340, 45), (459, 555), (30, 30, 30), -1)
    return result


class ScreeningTests(unittest.TestCase):
    def settings(self, root):
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        return load_settings(root, config)

    def test_strict_boundary_uses_unrounded_value(self):
        self.assertFalse(classify_diameter(127)["passes_diameter_rule"])
        self.assertFalse(classify_diameter(126.999999)["passes_diameter_rule"])
        self.assertTrue(classify_diameter(127.000001)["passes_diameter_rule"])
        self.assertEqual(classify_diameter(127)["threshold_mm"], 127)

    def test_unusable_or_calibration_results_do_not_pass(self):
        for value in (None, math.nan, math.inf, 0, -1):
            self.assertIsNone(classify_diameter(value)["passes_diameter_rule"])
        self.assertIsNone(classify_diameter(500, calibration_only=True)["passes_diameter_rule"])
        for limit in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                classify_diameter(200, limit)

    def test_nominal_estimate_has_source_and_full_precision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(self.settings(root), distance_mm=1000)
            result = measure_image(image(), root / "tree.jpg", settings, root)
            self.assertEqual(result["scale_mode"], "uncalibrated_distance")
            self.assertFalse(result["lens_calibrated"])
            self.assertIn("kailaptech.net", result["focal_source_url"])
            self.assertEqual(result["assessment"]["category"], "above_threshold")
            saved = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["report_path"], result["report_path"])
            self.assertGreater(saved["diameter_mm_unrounded"], 127)

    def test_wrong_aspect_ratio_cannot_use_nominal_scale(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = replace(self.settings(root), distance_mm=1000)
            with self.assertRaisesRegex(ValueError, "uncropped"):
                measure_image(cv2.resize(image(), (800, 700)), root / "tree.jpg", settings, root)

    def test_batch_keeps_originals_and_duplicate_filenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root / "input"
            for directory in (inputs / "a", inputs / "b"):
                directory.mkdir(parents=True)
                cv2.imwrite(str(directory / "object1_1000mm.jpg"), image())
            cv2.imwrite(str(inputs / "object2_distance-unavailable.jpg"), image())
            (inputs / "bad.jpg").write_bytes(b"not an image")
            with contextlib.redirect_stdout(io.StringIO()):
                result = measure_folder(inputs, self.settings(root), root, recursive=True)
            self.assertEqual(len(result["items"]), 4)
            self.assertEqual(result["counts"]["above_threshold"], 2)
            self.assertEqual(result["counts"]["needs_review"], 2)
            self.assertEqual(len(list(inputs.rglob("*.jpg"))), 4)
            run = Path(result["run_dir"])
            for row in result["items"]:
                self.assertTrue((run / row["report"]).is_file())
                if row["annotation"]:
                    self.assertTrue((run / row["annotation"]).is_file())
                    saved = json.loads((run / row["report"]).read_text(encoding="utf-8"))
                    self.assertTrue(Path(saved["annotated_image"]).is_file())
            self.assertTrue((run / "summary.csv").is_file())
            self.assertIn("No usable physical diameter", (run / "needs_review" / "item-0004" / "object2_distance-unavailable_diameter.json").read_text(encoding="utf-8"))
            self.assertTrue((run / "index.html").is_file())
