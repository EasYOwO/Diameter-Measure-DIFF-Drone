"""Apply the project's strict diameter threshold before display rounding."""

from __future__ import annotations

import math

MM_PER_INCH = 25.4


def classify_diameter(diameter_mm: float | None, threshold_inches: float = 5.0,
                      *, calibration_only: bool = False) -> dict:
    if not math.isfinite(threshold_inches) or threshold_inches <= 0:
        raise ValueError("Threshold must be finite and positive")
    limit = threshold_inches * MM_PER_INCH
    valid = diameter_mm is not None and math.isfinite(diameter_mm) and diameter_mm > 0
    if calibration_only or not valid:
        group, passes = "needs_review", None
        reason = "Calibration input is not an unknown measurement" if calibration_only else "No usable physical diameter"
    else:
        passes = diameter_mm > limit
        group = "above_threshold" if passes else "at_or_below_threshold"
        reason = "Strictly above threshold" if passes else "At or below threshold"
    return {"category": group, "passes_diameter_rule": passes,
            "threshold_inches": threshold_inches, "threshold_mm": limit,
            "operator": ">", "reason": reason,
            "scope": "Diameter screening only; inspect the annotation to confirm the target and edges"}
