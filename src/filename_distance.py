"""Read shooting distance in millimetres from ESP or Drive image names.

Examples:
  object43_100mm.jpg -> capture distance 100 mm, not object diameter.
  object44_distance-unavailable.jpg -> no distance should be filled automatically.
Downloaded names may have a prefix, such as driveprefix_object1_1000mm.jpg.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# object<id>_<distance>mm or object<id>_distance-unavailable
_OBJECT_DISTANCE = re.compile(
    r"(?:^|_)(object(?P<object_id>\d+))_(?P<tail>.+)$",
    re.IGNORECASE,
)
_UNAVAILABLE = re.compile(r"^distance[-_]?unavailable$", re.IGNORECASE)
_DISTANCE_MM = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)mm$", re.IGNORECASE)


@dataclass(frozen=True)
class FilenameDistance:
    """Parsed distance metadata from the file stem (no extension)."""

    object_id: str | None
    distance_mm: float | None
    unavailable: bool
    matched_pattern: str
    source_name: str

    @property
    def has_distance(self) -> bool:
        return self.distance_mm is not None and self.distance_mm > 0


def parse_filename_distance(path: Path | str) -> FilenameDistance | None:
    """Return parsed info, or None if the name does not follow the object_* convention."""
    name = Path(path).name
    stem = Path(path).stem
    match = _OBJECT_DISTANCE.search(stem)
    if not match:
        return None

    object_id = match.group("object_id")
    tail = match.group("tail").strip()
    if _UNAVAILABLE.fullmatch(tail):
        return FilenameDistance(
            object_id=object_id,
            distance_mm=None,
            unavailable=True,
            matched_pattern="object<id>_distance-unavailable",
            source_name=name,
        )

    dist = _DISTANCE_MM.fullmatch(tail)
    if dist:
        value = float(dist.group("value"))
        if value <= 0:
            return None
        return FilenameDistance(
            object_id=object_id,
            distance_mm=value,
            unavailable=False,
            matched_pattern="object<id>_<N>mm",
            source_name=name,
        )
    return None


def apply_filename_distance_to_settings(settings, path: Path) -> FilenameDistance | None:
    """Fill settings.distance_mm from the filename when CLI/config did not set it."""
    parsed = parse_filename_distance(path)
    if parsed is None:
        return None
    if parsed.unavailable:
        return parsed
    if parsed.has_distance and settings.distance_mm is None:
        settings.distance_mm = parsed.distance_mm
        settings.distance_source = (
            f"filename:{parsed.source_name} ({parsed.matched_pattern}, shooting distance mm)"
        )
    return parsed
