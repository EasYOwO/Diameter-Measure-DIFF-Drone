"""Process one image into one diameter report.

Read image -> detect subject -> measure pixels -> convert scale -> save annotation.
Pixel width is always reported. Millimetres need a reference, a saved calibration,
or a distance plus the OV2640 lens model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .camera_model import CameraModel
from .classification import classify_diameter
from .filename_distance import parse_filename_distance
from .detect import Detection, detect_object, find_reference_marker
from .measure import ScaleResult, diameter_from_mm_per_px, diameter_from_reference, diameter_from_intrinsics
from .lens_calibration import rectify_image

CALIBRATION_NAME = "calibration.json"


@dataclass
class MeasureSettings:
    camera: CameraModel
    distance_mm: float | None
    use_saved_calibration: bool
    known_mm: float | None = None
    ref_mm: float | None = None
    output_dir: Path = Path("output")
    intrinsics_path: Path | None = None
    allow_unverified_focal: bool = False
    geometry: str = "cylinder"
    distance_source: str | None = None
    focal_source: str = "Unspecified nominal lens"
    focal_source_url: str | None = None
    threshold_inches: float = 5.0


def load_settings(project_root: Path, config: dict) -> MeasureSettings:
    camera_cfg = config["camera"]
    camera = CameraModel(
        name=str(camera_cfg["name"]),
        sensor_width=int(camera_cfg["sensor_width"]),
        sensor_height=int(camera_cfg["sensor_height"]),
        pixel_size_mm=float(camera_cfg["pixel_size_mm"]),
        optical_format=str(camera_cfg.get("optical_format", "1/4 inch")),
        focal_length_mm=float(camera_cfg["focal_length_mm"]),
    )
    distance = config.get("distance_mm")
    return MeasureSettings(
        camera=camera,
        distance_mm=None if distance in (None, "", "null") else float(distance),
        use_saved_calibration=bool(config.get("use_saved_calibration", True)),
        output_dir=project_root / "output",
        intrinsics_path=project_root / "camera_intrinsics.json",
        allow_unverified_focal=bool(camera_cfg.get("allow_nominal_focal_estimate", False)),
        focal_source=str(camera_cfg.get("focal_source", "Unspecified nominal lens")),
        focal_source_url=camera_cfg.get("focal_source_url"),
        threshold_inches=float(config.get("threshold_inches", 5.0)),
    )


def measure_file(image_path: Path, settings: MeasureSettings, project_root: Path) -> dict:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")
    return measure_image(image, image_path, settings, project_root)


def measure_image(image: np.ndarray, image_path: Path, settings: MeasureSettings, project_root: Path) -> dict:
    intrinsics = None
    if settings.intrinsics_path is not None and settings.intrinsics_path.is_file():
        image, intrinsics = rectify_image(image, settings.intrinsics_path)
    detection = detect_object(image)
    scale = _resolve_scale(image, detection, settings, project_root, intrinsics)
    if scale.mode == "calibrate" and scale.mm_per_px is not None:
        _save_calibration(project_root, scale.mm_per_px, image.shape[1], detection.pixel_diameter, settings.known_mm,
                          image.shape[0], None if intrinsics is None else intrinsics["sha256"])

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    annotated_path = settings.output_dir / f"{stem}_diameter.jpg"
    report_path = settings.output_dir / f"{stem}_diameter.json"
    assessment = classify_diameter(scale.diameter_mm, settings.threshold_inches,
                                   calibration_only=scale.mode == "calibrate")
    _draw(image, detection, scale, annotated_path, assessment)

    filename_meta = parse_filename_distance(image_path)
    report = {
        "image": str(image_path),
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
        "camera": settings.camera.name,
        "sensor_optical_format": settings.camera.optical_format,
        "camera_calibration": intrinsics,
        "lens_calibrated": intrinsics is not None,
        "focal_source": "Actual checkerboard calibration" if intrinsics else settings.focal_source,
        "focal_source_url": None if intrinsics else settings.focal_source_url,
        "nominal_focal_length_mm": settings.camera.focal_length_mm,
        "distance_mm_used": settings.distance_mm,
        "distance_source": settings.distance_source,
        "filename_distance": None
        if filename_meta is None
        else {
            "object_id": filename_meta.object_id,
            "distance_mm_in_name": filename_meta.distance_mm,
            "distance_unavailable": filename_meta.unavailable,
            "pattern": filename_meta.matched_pattern,
            "note": "Nmm in the filename is shooting distance, not measured diameter",
        },
        "object_kind": detection.kind,
        "pixel_diameter": round(detection.pixel_diameter, 2),
        "pixel_uncertainty": round(detection.uncertainty_px, 2),
        "confidence": round(detection.confidence, 3),
        "notes": detection.notes,
        "diameter_mm": None if scale.diameter_mm is None else round(scale.diameter_mm, 2),
        "diameter_cm": None if scale.diameter_mm is None else round(scale.diameter_mm / 10.0, 3),
        "diameter_inches": None if scale.diameter_mm is None else round(scale.diameter_mm / 25.4, 4),
        "diameter_mm_unrounded": scale.diameter_mm,
        "assessment": assessment,
        "approximate_nominal_lens": scale.mode == "uncalibrated_distance",
        "scale_mode": scale.mode,
        "mm_per_px": None if scale.mm_per_px is None else scale.mm_per_px,
        "scale_detail": scale.detail,
        "warning": scale.warning,
        "annotated_image": str(annotated_path),
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return report


def _resolve_scale(image: np.ndarray, detection: Detection, settings: MeasureSettings, project_root: Path, intrinsics: dict | None = None) -> ScaleResult:
    # 1) A known reference in this image: Wang 2023, same distance, independent of lens focal length.
    if settings.ref_mm is not None:
        marker_px = find_reference_marker(image, detection.mask)
        if marker_px is None:
            raise ValueError(
                "No round reference marker found. Place a known-size circle beside the target at the same depth."
            )
        return diameter_from_reference(detection.pixel_diameter, marker_px, settings.ref_mm)

    # 2) A user-supplied subject diameter calibrates scale; it does not measure an unknown diameter.
    if settings.known_mm is not None:
        if not np.isfinite(settings.known_mm) or settings.known_mm <= 0:
            raise ValueError("Known diameter must be finite and positive")
        mm_per_px = settings.known_mm / detection.pixel_diameter
        return ScaleResult(
            mode="calibrate",
            diameter_mm=settings.known_mm,
            mm_per_px=mm_per_px,
            detail={
                "known_mm": settings.known_mm,
                "pixel_diameter": detection.pixel_diameter,
                "saved": True,
            },
        )

    # 3) Previously calibrated mm/pixel at the same capture distance.
    if settings.use_saved_calibration and settings.distance_mm is None and settings.ref_mm is None:
        saved = _load_calibration(project_root)
        if saved is not None:
            signature = None if intrinsics is None else intrinsics["sha256"]
            if saved.get("image_height") != int(image.shape[0]) or saved.get("intrinsics_sha256") != signature:
                raise ValueError("Fixed scale is old or uses a different image/calibration space. Recreate it with --known-mm")
            if int(saved.get("image_width", image.shape[1])) != int(image.shape[1]):
                return ScaleResult(
                    mode="pixels",
                    diameter_mm=None,
                    mm_per_px=None,
                    detail={},
                    warning="Fixed-scale calibration image width differs; physical diameter unavailable",
                )
            return diameter_from_mm_per_px(detection.pixel_diameter, float(saved["mm_per_px"]))

    # 4) Distance plus the OV2640 model: Shao 2022, with cylinder correction as the main result.
    if settings.distance_mm is not None:
        if intrinsics is not None:
            scale = diameter_from_intrinsics(detection.pixel_diameter, intrinsics["fx_px"], settings.distance_mm, settings.geometry)
            warning = None
            if settings.geometry == "cylinder" and abs(detection.center_xy[0] - intrinsics["cx_px"]) > 0.1 * intrinsics["fx_px"]:
                warning = "Center the trunk and rangefinder on the optical axis; off-axis cylinder result is approximate."
            return ScaleResult(scale.mode, scale.diameter_mm, scale.mm_per_px, scale.detail, warning)
        if not settings.allow_unverified_focal:
            raise ValueError("Lens not calibrated. Run calibrate_camera.py with actual camera photos first. "
                             "Nominal estimates are disabled; no physical diameter was produced. "
                             "Enable allow_nominal_focal_estimate or pass --focal-mm for an explicit estimate.")
        if image.shape[1] * settings.camera.sensor_height != image.shape[0] * settings.camera.sensor_width:
            raise ValueError("Nominal lens scale requires an uncropped full-frame image with the sensor aspect ratio (4:3)")
        estimate = diameter_from_intrinsics(detection.pixel_diameter,
            settings.camera.focal_length_mm / settings.camera.pixel_pitch_mm(image.shape[1]),
            settings.distance_mm, settings.geometry)
        detail = dict(estimate.detail, focal_length_mm=settings.camera.focal_length_mm,
                      focal_source=settings.focal_source, focal_source_url=settings.focal_source_url,
                      assumptions="Full sensor field scaled to file size; centered target; lens-to-front-surface distance")
        return ScaleResult("uncalibrated_distance", estimate.diameter_mm, estimate.mm_per_px, detail,
            "Nominal focal length only; image distortion is uncalibrated. This is an approximate estimate.")

    return ScaleResult(
        mode="pixels",
        diameter_mm=None,
        mm_per_px=None,
        detail={},
        warning=(
            "Pixel diameter only. Supply surface distance, a known reference, or an explicit fixed-scale calibration."
        ),
    )


def _calibration_path(project_root: Path) -> Path:
    return project_root / CALIBRATION_NAME


def _load_calibration(project_root: Path) -> dict | None:
    path = _calibration_path(project_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_calibration(project_root: Path, mm_per_px: float, image_width: int, pixel_diameter: float, known_mm: float,
                      image_height: int, intrinsics_sha256: str | None) -> None:
    payload = {
        "mm_per_px": mm_per_px,
        "image_width": image_width,
        "image_height": image_height,
        "intrinsics_sha256": intrinsics_sha256,
        "pixel_diameter": pixel_diameter,
        "known_mm": known_mm,
        "note": "Valid only at the same distance, resolution, camera mode and rectification space",
    }
    _calibration_path(project_root).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _draw(image: np.ndarray, detection: Detection, scale: ScaleResult, dest: Path, assessment: dict) -> None:
    canvas = image.copy()
    tint = canvas.copy()
    tint[detection.mask > 0] = (40, 180, 60)
    canvas = cv2.addWeighted(tint, 0.35, canvas, 0.65, 0)
    cv2.drawContours(canvas, [detection.contour], -1, (0, 220, 0), 2)

    cx, cy = detection.center_xy
    half = detection.pixel_diameter / 2.0
    p1 = (int(round(cx - half)), int(round(cy)))
    p2 = (int(round(cx + half)), int(round(cy)))
    cv2.line(canvas, p1, p2, (0, 0, 255), 2)
    cv2.circle(canvas, (int(round(cx)), int(round(cy))), 4, (0, 0, 255), -1)

    if scale.diameter_mm is None:
        label = f"{detection.kind}  {detection.pixel_diameter:.1f} px"
    else:
        label = f"{detection.kind}  {scale.diameter_mm:.1f} mm  ({detection.pixel_diameter:.1f} px)"
    cv2.putText(canvas, label, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(canvas, label, (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    status = assessment["category"].replace("_", " ")
    if scale.mode == "uncalibrated_distance":
        status += " | nominal lens estimate"
    cv2.putText(canvas, status, (16, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(canvas, status, (16, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    if not cv2.imwrite(str(dest), canvas):
        raise OSError(f"Could not write annotation: {dest}")


def print_report(report: dict) -> None:
    print("\nDIFF Drone - Diameter measurement")
    if report.get("distance_mm_used") is not None:
        print(f"Surface distance: {report['distance_mm_used']} mm ({report.get('distance_source')})")
    print(f"Detected shape: {report['object_kind']}")
    print(f"Pixel width: {report['pixel_diameter']} px; shape/edge spread: {report['pixel_uncertainty']} px")
    if report["diameter_mm"] is None:
        print("Physical diameter: unavailable (no scale)")
    else:
        print(f"Diameter: {report['diameter_mm']} mm / {report['diameter_inches']} inches")
        print(f"Scale: {report['scale_mode']}")
    assessment = report["assessment"]
    print(f"Diameter rule: > {assessment['threshold_inches']:g} inches ({assessment['threshold_mm']:g} mm)")
    print(f"Group: {assessment['category']} | {assessment['reason']}")
    print(f"Edge heuristic score: {report['confidence']} (not an accuracy probability)")
    if report.get("warning"):
        print("Note:", report["warning"])
    print("Annotation:", report["annotated_image"])
    print("Report:", report["report_path"])
