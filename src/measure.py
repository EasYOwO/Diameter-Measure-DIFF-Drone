"""Convert a pixel width into a physical diameter.

The references use different scales and must not be mixed:

1. Wang et al., Plant Methods 2023, Eq. 9:
   The object and known reference are at the same camera distance.
   S / S' = R / R'; S = S' * (R / R').
   S' is trunk width in pixels, R is reference diameter, and R' is its pixel width.

2. Shao et al., Computers and Electronics in Agriculture 2022:
   Without a reference, use front-surface distance d, focal length f and pixel pitch.
   Eq. 3 models a front-facing rectangle: D_rect = Lpixel * d / f,
   where Lpixel is pixel diameter multiplied by physical pixel pitch.
   Eq. 6 models a cylinder and solves for x = D / d:
   x^3 + (1 - k) x^2 - 2 k x - k = 0,
   where k = (Lpixel / f)^2 and D_cyl = x * d.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .camera_model import CameraModel


@dataclass(frozen=True)
class ScaleResult:
    mode: str
    diameter_mm: float | None
    mm_per_px: float | None
    detail: dict
    warning: str | None = None


def reference_diameter_mm(object_px: float, reference_px: float, reference_mm: float) -> float:
    """Wang 2023 Eq. 9. Both objects must lie in the same plane (same distance)."""
    _check_positive(object_px, reference_px, reference_mm)
    return object_px * (reference_mm / reference_px)


def similar_triangle_diameter_mm(pixel_diameter: float, pitch_mm: float, focal_mm: float, distance_mm: float) -> float:
    """Shao 2022 Eq. 3. Distance is from the lens to the front surface of the trunk."""
    _check_positive(pixel_diameter, pitch_mm, focal_mm, distance_mm)
    l_pixel = pixel_diameter * pitch_mm
    return l_pixel * distance_mm / focal_mm


def cylinder_diameter_mm(pixel_diameter: float, pitch_mm: float, focal_mm: float, distance_mm: float) -> float:
    """Shao 2022 Eq. 6, evaluated with its unique positive closed-form root."""
    _check_positive(pixel_diameter, pitch_mm, focal_mm, distance_mm)
    return diameter_from_intrinsics(pixel_diameter, focal_mm / pitch_mm, distance_mm).diameter_mm


def tangent_diameter_mm(pixel_diameter: float, pitch_mm: float, focal_mm: float, distance_mm: float) -> float:
    """Equivalent expression using rays tangent to a cylinder.

    sin(alpha) = R / (d + R); tan(alpha) = (Lpixel / 2) / f.
    This equivalence checks algebra only; it cannot validate the lens or distance.
    """
    _check_positive(pixel_diameter, pitch_mm, focal_mm, distance_mm)
    half = (pixel_diameter * pitch_mm) / 2.0
    tan_alpha = half / focal_mm
    sin_alpha = tan_alpha / np.sqrt(1.0 + tan_alpha * tan_alpha)
    if sin_alpha >= 1.0:
        raise ValueError("tangent geometry is impossible at this focal length")
    radius = sin_alpha * distance_mm / (1.0 - sin_alpha)
    return float(2.0 * radius)


def diameter_from_distance(
    pixel_diameter: float,
    image_width: int,
    camera: CameraModel,
    distance_mm: float,
) -> ScaleResult:
    pitch = camera.pixel_pitch_mm(image_width)
    rect = similar_triangle_diameter_mm(pixel_diameter, pitch, camera.focal_length_mm, distance_mm)
    try:
        cyl = cylinder_diameter_mm(pixel_diameter, pitch, camera.focal_length_mm, distance_mm)
    except ValueError as exc:
        return ScaleResult(
            mode="distance",
            diameter_mm=rect,
            mm_per_px=rect / pixel_diameter,
            detail={"similar_triangle_mm": rect, "error": str(exc)},
            warning="Cylinder correction failed; using similar triangles",
        )
    try:
        tangent = tangent_diameter_mm(pixel_diameter, pitch, camera.focal_length_mm, distance_mm)
    except ValueError:
        tangent = None

    warning = None
    if tangent is not None and cyl > 0 and abs(cyl - tangent) / cyl > 0.15:
        warning = (
            "Equivalent cylinder expressions disagree; inspect the calculation inputs."
        )
    return ScaleResult(
        mode="distance",
        diameter_mm=cyl,
        mm_per_px=cyl / pixel_diameter,
        detail={
            "similar_triangle_mm": rect,
            "cylinder_mm": cyl,
            "tangent_mm": tangent,
            "pixel_pitch_mm": pitch,
            "focal_length_mm": camera.focal_length_mm,
            "distance_mm": distance_mm,
            "primary": "cylinder_mm",
        },
        warning=warning,
    )


def diameter_from_reference(object_px: float, reference_px: float, reference_mm: float) -> ScaleResult:
    mm = reference_diameter_mm(object_px, reference_px, reference_mm)
    return ScaleResult(
        mode="reference",
        diameter_mm=mm,
        mm_per_px=reference_mm / reference_px,
        detail={
            "reference_mm": reference_mm,
            "reference_px": reference_px,
            "object_px": object_px,
            "formula": "S = S' * R / R'",
        },
    )


def diameter_from_mm_per_px(object_px: float, mm_per_px: float) -> ScaleResult:
    _check_positive(mm_per_px, object_px)
    return ScaleResult(
        mode="calibration",
        diameter_mm=object_px * mm_per_px,
        mm_per_px=mm_per_px,
        detail={"source": "saved calibration at the same camera distance"},
    )


def diameter_from_intrinsics(object_px: float, fx_px: float, distance_mm: float, geometry: str = "cylinder") -> ScaleResult:
    """Width in the rectified image; axial surface distance and a centered target.

    x^3+(1-k)x^2-2kx-k = (x+1)(x^2-kx-k). Use the unique positive root.
    This is the same geometry as the tangent formulation, not an independent check.
    """
    _check_positive(object_px, fx_px, distance_mm)
    if geometry not in {"cylinder", "flat"}:
        raise ValueError("Geometry must be cylinder or flat")
    q = object_px / fx_px
    flat = q * distance_mm
    cylinder = distance_mm * q * (q + np.hypot(q, 2.0)) / 2.0
    result = cylinder if geometry == "cylinder" else flat
    if not np.isfinite(result):
        raise ValueError("Diameter calculation overflowed; check focal length and distance")
    return ScaleResult(
        mode="calibrated_distance", diameter_mm=float(result), mm_per_px=float(result / object_px),
        detail={"fx_px": fx_px, "distance_mm": distance_mm, "geometry": geometry,
                "flat_mm": float(flat), "cylinder_mm": float(cylinder),
                "assumptions": "rectified image; centered target; distance to front surface along camera axis"})


def _check_positive(*values: float) -> None:
    if any(not np.isfinite(v) or v <= 0 for v in values):
        raise ValueError("pixel diameter, pixel pitch, focal length, and distance must be positive")
