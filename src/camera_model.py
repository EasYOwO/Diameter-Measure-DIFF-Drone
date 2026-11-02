"""Sensor geometry from the OV2640 datasheet; lens focal length is separate.

OmniVision specifies UXGA 1600 x 1200, 2.2 um pixels and a 1/4-inch optical format.
OV2640 is the sensor, not the lens. Focal length and field of view depend on the
lens module; the same sensor can be paired with 66-degree or 120-degree lenses.
The configured focal_length_mm is a sourced nominal estimate. Actual calibration
supplies the camera-specific intrinsics used in preference to nominal geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CameraModel:
    name: str
    sensor_width: int
    sensor_height: int
    pixel_size_mm: float
    optical_format: str
    focal_length_mm: float

    def __post_init__(self) -> None:
        values = (self.sensor_width, self.sensor_height, self.pixel_size_mm, self.focal_length_mm)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Sensor dimensions, pixel pitch and focal length must be finite and positive")

    def pixel_pitch_mm(self, image_width: int) -> float:
        """Pitch of one file pixel when the full sensor is scaled to this width.

        At the native 1600-pixel UXGA width, one sensor pixel is 0.0022 mm.
        A smaller full-frame JPEG covers more sensor area per file pixel.
        """
        if image_width <= 0:
            raise ValueError("image width must be positive")
        return self.pixel_size_mm * (self.sensor_width / float(image_width))


def ov2640_sensor_defaults() -> dict:
    """Values that come from the OV2640 sensor datasheet only (not the lens)."""
    return {
        "sensor_width": 1600,
        "sensor_height": 1200,
        "pixel_size_mm": 0.0022,
        "optical_format": "1/4 inch",
    }
