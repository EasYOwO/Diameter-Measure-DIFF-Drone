"""Find the aimed-at object and measure its width in pixels.

Segment first, then measure. The frame centre is the prior because the camera
is aimed at the target. For trunks, take the median horizontal edge-to-edge width
through the middle. This implementation does not fit a trunk axis or correct
leaning trunks. For round objects, use the area-equivalent diameter.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    kind: str
    pixel_diameter: float
    uncertainty_px: float
    center_xy: tuple[float, float]
    bbox_xywh: tuple[int, int, int, int]
    mask: np.ndarray
    contour: np.ndarray
    confidence: float
    notes: str


def detect_object(image_bgr: np.ndarray) -> Detection:
    """Return the main foreground object. Raises ValueError if nothing usable is found."""
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("empty image")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("expected a BGR colour image")

    mask = _best_mask(image_bgr)
    mask = _largest_center_component(mask)
    if int(mask.sum()) < 80:
        raise ValueError("No usable object found")

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("mask has no contour")
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < 80:
        raise ValueError("Object area is too small")

    perimeter = float(cv2.arcLength(contour, True))
    circularity = 0.0 if perimeter <= 0 else float(4.0 * np.pi * area / (perimeter * perimeter))
    x, y, w, h = cv2.boundingRect(contour)
    aspect = h / float(w) if w else 0.0

    # Trunks are tall and narrow; circles have circularity near 1. Other objects use area-equivalent diameter.
    if circularity >= 0.82:
        kind = "round"
        diameter, uncertainty = _equivalent_diameter(area, contour)
        notes = "Round object; equivalent diameter 2*sqrt(area/pi)"
    elif aspect >= 1.25:
        kind = "trunk"
        diameter, uncertainty = _trunk_width_px(mask)
        notes = "Median horizontal width between left and right edges; no lean correction"
    else:
        kind = "object"
        diameter, uncertainty = _equivalent_diameter(area, contour)
        notes = "General object; equivalent circular diameter"

    moments = cv2.moments(contour)
    if moments["m00"] > 0:
        center = (float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"]))
    else:
        center = (x + w / 2.0, y + h / 2.0)

    # Consistent edges raise confidence. A large width deviation indicates irregular edges.
    consistency = 1.0 - min(1.0, uncertainty / max(diameter, 1.0))
    confidence = float(np.clip(0.55 * consistency + 0.45 * min(circularity, 1.0 if kind == "round" else 0.7), 0.0, 0.99))

    return Detection(
        kind=kind,
        pixel_diameter=float(diameter),
        uncertainty_px=float(uncertainty),
        center_xy=center,
        bbox_xywh=(int(x), int(y), int(w), int(h)),
        mask=mask,
        contour=contour,
        confidence=confidence,
        notes=notes,
    )


def find_reference_marker(image_bgr: np.ndarray, main_mask: np.ndarray) -> float | None:
    """Find a small round marker and return its diameter in pixels.

    The marker must be much smaller than the subject and approximately round,
    such as a sticker, disk or laser spot. Return None without a reliable scale.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Try bright and dark spots: laser spots are usually bright, while black disks are dark.
    dark = cv2.bitwise_not(bright)
    candidates = []
    image_area = gray.shape[0] * gray.shape[1]
    for binary in (bright, dark):
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < image_area * 0.0004 or area > image_area * 0.03:
                continue
            peri = float(cv2.arcLength(contour, True))
            if peri <= 0:
                continue
            circularity = 4.0 * np.pi * area / (peri * peri)
            if circularity < 0.75:
                continue
            overlap = _contour_overlap(contour, main_mask)
            # Accept markers outside the subject or small round stickers on its surface.
            # Reject the subject itself; the area limit enforces this.
            if overlap > 0.85 and area > int(main_mask.sum()) * 0.5:
                continue
            eq = 2.0 * np.sqrt(area / np.pi)
            candidates.append((circularity, eq))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return float(candidates[0][1])


def _best_mask(image_bgr: np.ndarray) -> np.ndarray:
    """GrabCut with a centre box, then keep it only if it beats a simple threshold mask."""
    height, width = image_bgr.shape[:2]
    grab_mask = _grabcut_mask(image_bgr)
    thresh_mask = _threshold_mask(image_bgr)
    grab_score = _mask_score(image_bgr, grab_mask)
    thresh_score = _mask_score(image_bgr, thresh_mask)
    chosen = grab_mask if grab_score >= thresh_score else thresh_mask
    # Remove small noise without erasing narrow trunks.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    chosen = cv2.morphologyEx(chosen, cv2.MORPH_CLOSE, kernel)
    chosen = cv2.morphologyEx(chosen, cv2.MORPH_OPEN, kernel)
    if chosen.shape[:2] != (height, width):
        chosen = cv2.resize(chosen, (width, height), interpolation=cv2.INTER_NEAREST)
    return chosen


def _grabcut_mask(image_bgr: np.ndarray) -> np.ndarray:
    height, width = image_bgr.shape[:2]
    # Segment a 900-pixel-long-edge image, then scale back; full 2 MP GrabCut is slow.
    scale = 900.0 / max(height, width)
    if scale < 1.0:
        small = cv2.resize(image_bgr, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    else:
        small = image_bgr
        scale = 1.0
    sh, sw = small.shape[:2]
    rect = (
        int(sw * 0.18),
        int(sh * 0.08),
        int(sw * 0.64),
        int(sh * 0.84),
    )
    mask = np.zeros((sh, sw), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(small, mask, rect, bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return np.zeros((height, width), np.uint8)
    binary = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    if scale < 1.0:
        binary = cv2.resize(binary, (width, height), interpolation=cv2.INTER_NEAREST)
    return binary


def _threshold_mask(image_bgr: np.ndarray) -> np.ndarray:
    """Fallback when the background is plain: Otsu on the centre-weighted gray image."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # The subject may be darker or brighter than its background; prefer the central candidate.
    if _center_fraction(binary) < _center_fraction(cv2.bitwise_not(binary)):
        binary = cv2.bitwise_not(binary)
    return binary


def _center_fraction(mask: np.ndarray) -> float:
    height, width = mask.shape[:2]
    y0, y1 = int(height * 0.3), int(height * 0.7)
    x0, x1 = int(width * 0.3), int(width * 0.7)
    patch = mask[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    return float((patch > 0).mean())


def _mask_score(image_bgr: np.ndarray, mask: np.ndarray) -> float:
    """Prefer a mask that overlaps the centre and sits on a strong edge."""
    area_frac = float((mask > 0).mean())
    if area_frac < 0.002 or area_frac > 0.85:
        return -1.0
    center = _center_fraction(mask)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    boundary = cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    edge_hit = float(((edges > 0) & (boundary > 0)).sum()) / max(1, int((boundary > 0).sum()))
    return center * 0.6 + edge_hit * 0.4


def _largest_center_component(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, centroids = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros_like(mask)
    height, width = mask.shape[:2]
    cx, cy = width / 2.0, height / 2.0
    best_label = None
    best_score = -1.0
    for label in range(1, count):
        area = float(stats[label, cv2.CC_STAT_AREA])
        if area < 80:
            continue
        dx = centroids[label][0] - cx
        dy = centroids[label][1] - cy
        dist = np.hypot(dx, dy) / max(cx, cy)
        score = area / (1.0 + dist * 3.0)
        if score > best_score:
            best_score = score
            best_label = label
    if best_label is None:
        return np.zeros_like(mask)
    return np.where(labels == best_label, 255, 0).astype(np.uint8)


def _trunk_width_px(mask: np.ndarray) -> tuple[float, float]:
    """Median horizontal width, ignoring the top and bottom 15% where the mask is unstable."""
    ys, xs = np.where(mask > 0)
    if len(ys) < 10:
        raise ValueError("trunk mask is empty")
    y0 = int(np.percentile(ys, 15))
    y1 = int(np.percentile(ys, 85))
    widths = []
    # Sample alternate rows to keep 2 MP images practical.
    for y in range(y0, y1 + 1, 2):
        cols = np.where(mask[y] > 0)[0]
        if cols.size < 2:
            continue
        widths.append(float(cols[-1] - cols[0] + 1))
    if len(widths) < 5:
        raise ValueError("not enough trunk rows to measure width")
    arr = np.array(widths, dtype=np.float64)
    median = float(np.median(arr))
    # Drop rows far from the median, such as branches or occlusions.
    keep = np.abs(arr - median) <= max(3.0, 0.2 * median)
    if int(keep.sum()) >= 5:
        arr = arr[keep]
        median = float(np.median(arr))
    return median, float(np.std(arr))


def _equivalent_diameter(area: float, contour: np.ndarray) -> tuple[float, float]:
    equivalent = float(2.0 * np.sqrt(area / np.pi))
    uncertainty = 1.0
    if len(contour) >= 5:
        ellipse = cv2.fitEllipse(contour)
        (_, _), (major, minor), _ = ellipse
        # A circle has similar axes; larger differences make its equivalent diameter less representative.
        uncertainty = float(abs(major - minor) / 2.0)
    return equivalent, uncertainty


def _contour_overlap(contour: np.ndarray, mask: np.ndarray) -> float:
    probe = np.zeros_like(mask)
    cv2.drawContours(probe, [contour], -1, 255, thickness=-1)
    inside = int(((probe > 0) & (mask > 0)).sum())
    total = int((probe > 0).sum())
    if total == 0:
        return 0.0
    return inside / total
