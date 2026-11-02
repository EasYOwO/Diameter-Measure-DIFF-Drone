"""Measure a local photograph, a folder, or a photograph selected from Drive."""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

import yaml

from src.batch import measure_folder
from src.classification import classify_diameter
from src.drive_client import DriveSetupError, choose_image, connect
from src.filename_distance import apply_filename_distance_to_settings
from src.pipeline import load_settings, measure_file, print_report

ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="DIFF Drone: diameter measurement and strict >5-inch screening")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", type=Path, help="Local original image; otherwise choose from Google Drive")
    source.add_argument("--folder", type=Path, help="Batch process local photographs")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders in batch mode")
    parser.add_argument("--output", type=Path, help="Output directory (default: project/output)")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt for missing distance")
    parser.add_argument("--distance-mm", type=float, help="Lens-to-target front-surface distance in millimetres")
    parser.add_argument("--focal-mm", type=float, help="Override nominal focal length; still an uncalibrated estimate")
    scale = parser.add_mutually_exclusive_group()
    scale.add_argument("--known-mm", type=float, help="Known main-subject diameter; calibrates a fixed scale")
    scale.add_argument("--ref-mm", type=float, help="Known round reference diameter beside target at the same depth")
    scale.add_argument("--fixed-scale", action="store_true", help="Reuse calibration.json only at identical distance and camera mode")
    parser.add_argument("--require-calibration", action="store_true", help="Disable nominal-focal distance estimates")
    parser.add_argument("--threshold-inches", type=float, help="Strict diameter threshold (default: 5 inches)")
    parser.add_argument("--self-test", action="store_true", help="Synthetic geometry and detection check")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--intrinsics", type=Path, help="Actual calibration from calibrate_camera.py")
    parser.add_argument("--geometry", choices=["cylinder", "flat"], default="cylinder")
    args = parser.parse_args(argv)
    if args.self_test:
        from tests.synthetic_check import run_self_test
        return run_self_test(ROOT)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    settings = load_settings(ROOT, config)
    settings.geometry = args.geometry
    settings.use_saved_calibration = args.fixed_scale
    if args.output is not None:
        settings.output_dir = args.output
    if args.intrinsics is not None:
        if not args.intrinsics.is_file():
            raise ValueError(f"Camera intrinsics file not found: {args.intrinsics}")
        settings.intrinsics_path = args.intrinsics
    if args.distance_mm is not None:
        settings.distance_mm, settings.distance_source = args.distance_mm, "command_line"
    elif settings.distance_mm is not None:
        settings.distance_source = "config"
    if args.focal_mm is not None:
        settings.camera = replace(settings.camera, focal_length_mm=args.focal_mm)
        settings.allow_unverified_focal = True
        settings.focal_source, settings.focal_source_url = "User-supplied nominal focal length", None
    if args.require_calibration:
        settings.allow_unverified_focal = False
    if args.threshold_inches is not None:
        settings.threshold_inches = args.threshold_inches
    classify_diameter(None, settings.threshold_inches)
    settings.known_mm, settings.ref_mm = args.known_mm, args.ref_mm
    for name, value in (("distance", settings.distance_mm), ("focal length", settings.camera.focal_length_mm),
                        ("known diameter", args.known_mm), ("reference diameter", args.ref_mm)):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name.capitalize()} must be finite and positive")
    if args.fixed_scale and not (ROOT / "calibration.json").is_file():
        raise ValueError("Fixed-scale calibration is missing; create it with --image and --known-mm first")
    if args.folder is not None:
        result = measure_folder(args.folder, settings, ROOT, recursive=args.recursive)
        print("Groups:", result["counts"])
        print("Open results:", Path(result["run_dir"]) / "index.html")
        return 0
    image_path = args.image
    if image_path is None:
        if args.non_interactive:
            raise ValueError("Use --image or --folder with --non-interactive")
        try:
            service = connect(ROOT)
        except DriveSetupError as exc:
            print(exc)
            return 1
        print("Google Drive connected. Choose a photograph.")
        image_path = choose_image(service, page_size=int(config.get("drive", {}).get("page_size", 20)),
                                  download_dir=ROOT / "output" / "downloads")
    if not image_path.is_file():
        raise ValueError(f"Image not found: {image_path}")
    if settings.distance_mm is None and args.known_mm is None and args.ref_mm is None and not args.fixed_scale:
        apply_filename_distance_to_settings(settings, image_path)
    if (settings.distance_mm is None and args.known_mm is None and args.ref_mm is None
            and not args.fixed_scale and not args.non_interactive):
        typed = input("Surface distance in mm (Enter for pixels only): ").strip()
        if typed:
            settings.distance_mm, settings.distance_source = float(typed), "manual_input"
    print_report(measure_file(image_path, settings, ROOT))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled")
        raise SystemExit(130)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
