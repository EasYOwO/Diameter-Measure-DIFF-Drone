"""Run camera calibration on original photos of the supplied checkerboard."""
import argparse
from pathlib import Path

from src.lens_calibration import calibrate_folder

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Calibrate the actual lens; 8x6 INNER corners on supplied pattern")
    parser.add_argument("--images", type=Path, default=ROOT / "calibration_images")
    parser.add_argument("--output", type=Path, default=ROOT / "camera_intrinsics.json")
    parser.add_argument("--model", choices=["fisheye", "pinhole"], default="pinhole")
    parser.add_argument("--columns", type=int, default=8)
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--square-mm", type=float, default=20.0)
    args = parser.parse_args()
    try:
        result = calibrate_folder(args.images, args.output, args.columns, args.rows, args.square_mm, args.model)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"Saved {args.output}")
    print(f"Accepted {result['accepted_views']} views; fit RMS {result['rms_px']:.3f} px")
    print("Inspect calibration_corner_checks, then validate with measured cylinders at several distances.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
