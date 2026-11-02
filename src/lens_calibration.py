"""Actual camera calibration; no inference of focal length from advertised FOV."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "tree-camera-intrinsics-v1"


def board_points(columns: int = 8, rows: int = 6, square_mm: float = 20.0) -> np.ndarray:
    if columns < 3 or rows < 3 or not np.isfinite(square_mm) or square_mm <= 0:
        raise ValueError("Invalid checkerboard dimensions")
    points = np.zeros((columns * rows, 1, 3), np.float64)
    points[:, 0, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_mm
    return points


def solve_calibration(object_points, image_points, image_size, model="fisheye") -> dict:
    """Fit diverse checkerboard views; RMS is fit residual, not diameter accuracy."""
    if model not in {"fisheye", "pinhole"}:
        raise ValueError("Choose fisheye or pinhole")
    if len(image_points) < 10 or len(object_points) != len(image_points):
        raise ValueError("Need at least 10 accepted, different checkerboard views; aim for 20-25")
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image size")
    views = [np.asarray(p, np.float64).reshape(-1, 1, 2) for p in image_points]
    objects = [np.asarray(p, np.float64).reshape(-1, 1, 3) for p in object_points]
    for obj, img in zip(objects, views):
        if len(obj) != len(img) or not np.isfinite(obj).all() or not np.isfinite(img).all():
            raise ValueError("Invalid checkerboard correspondences")
    # Refuse repeated/static poses that cannot determine reliable intrinsics.
    centers = np.array([p.mean(axis=0)[0] for p in views])
    spans = np.array([np.ptp(p[:, 0, 0]) for p in views])
    if np.max(np.ptp(centers, axis=0) / [width, height]) < 0.12:
        raise ValueError("Board stays near one position. Add left/right/top/bottom views")
    if min(spans) <= 0 or max(spans) / min(spans) < 1.25:
        raise ValueError("Board scale barely changes. Add closer and farther views")
    try:
        if model == "fisheye":
            flags = (cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC |
                     cv2.fisheye.CALIB_CHECK_COND | cv2.fisheye.CALIB_FIX_SKEW)
            rms, matrix, distortion, rvecs, tvecs = cv2.fisheye.calibrate(
                objects, views, image_size, np.eye(3), np.zeros((4, 1)),
                flags=flags, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER, 150, 1e-8))
            rectified = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
                matrix, distortion, image_size, np.eye(3), balance=0, new_size=image_size)
        else:
            rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
                [p.astype(np.float32) for p in objects],
                [p.astype(np.float32) for p in views], image_size, None, None)
            rectified, _ = cv2.getOptimalNewCameraMatrix(matrix, distortion, image_size, 0, image_size)
    except cv2.error as exc:
        raise ValueError("Calibration failed. Retake sharp, varied views with the complete board visible. "
                         "Do not switch models just to hide a failure. OpenCV: " + str(exc)) from exc
    per_view = []
    for obj, img, rv, tv in zip(objects, views, rvecs, tvecs):
        if model == "fisheye":
            projected, _ = cv2.fisheye.projectPoints(obj, rv, tv, matrix, distortion)
        else:
            projected, _ = cv2.projectPoints(obj, rv, tv, matrix, distortion)
        per_view.append(float(np.sqrt(np.mean(np.sum((projected - img) ** 2, axis=2)))))
    if not np.isfinite(rms) or rms > 2.0 or max(per_view) > 3.0:
        raise ValueError(f"Fit residual too high: RMS={rms:.3f}px, worst view={max(per_view):.3f}px. Retake poor views")
    for m in (matrix, rectified):
        if not np.isfinite(m).all() or m[0, 0] <= 0 or m[1, 1] <= 0:
            raise ValueError("Invalid fitted focal length")
    return {
        "schema": SCHEMA, "model": model, "image_size": [int(width), int(height)],
        "camera_matrix": matrix.tolist(), "distortion": distortion.ravel().tolist(),
        "rectified_camera_matrix": rectified.tolist(), "rms_px": float(rms),
        "per_view_rms_px": per_view, "accepted_views": len(views),
        "warning": "Fit RMS is not physical diameter accuracy. Validate against measured cylinders."
    }


def calibrate_folder(folder: Path, output: Path, columns=8, rows=6, square_mm=20.0, model="fisheye") -> dict:
    if not folder.is_dir():
        raise ValueError(f"Calibration folder does not exist: {folder}")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not files:
        raise ValueError("No JPG/PNG calibration photographs found; take photos with the actual OV2640 first")
    objects, corners, accepted, rejected, hashes = [], [], [], [], set()
    size = None
    overlay_folder = output.parent / "calibration_corner_checks"
    overlay_folder.mkdir(parents=True, exist_ok=True)
    for path in files:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            rejected.append({"image": path.name, "reason": "duplicate file"})
            continue
        hashes.add(digest)
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            rejected.append({"image": path.name, "reason": "unreadable"})
            continue
        current_size = (image.shape[1], image.shape[0])
        if size is None:
            size = current_size
        if current_size != size:
            raise ValueError("Mixed resolutions: use original full-size photos from the same camera mode")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        found, points = cv2.findChessboardCornersSB(gray, (columns, rows), cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not found:
            rejected.append({"image": path.name, "reason": "complete checkerboard not detected"})
            continue
        objects.append(board_points(columns, rows, square_mm))
        corners.append(points.astype(np.float64))
        accepted.append(path.name)
        cv2.drawChessboardCorners(image, (columns, rows), points, True)
        cv2.imencode(".jpg", image)[1].tofile(str(overlay_folder / (path.stem + "_corners.jpg")))
    result = solve_calibration(objects, corners, size or (0, 0), model)
    result.update({"pattern_inner_corners": [columns, rows], "square_mm": square_mm,
                   "accepted_images": accepted, "rejected_images": rejected})
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only a successful fit can replace existing intrinsics.
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(output)
    return result


def rectify_image(image: np.ndarray, path: Path) -> tuple[np.ndarray, dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != SCHEMA or data.get("model") not in {"fisheye", "pinhole"}:
        raise ValueError("Unsupported camera intrinsics file")
    size = (image.shape[1], image.shape[0])
    if data.get("image_size") != list(size):
        raise ValueError("Image size differs from camera calibration. Use original full-resolution photos; do not resize/crop")
    matrix = np.asarray(data["camera_matrix"], np.float64)
    new_matrix = np.asarray(data["rectified_camera_matrix"], np.float64)
    distortion = np.asarray(data["distortion"], np.float64).reshape(-1, 1)
    if matrix.shape != (3, 3) or new_matrix.shape != (3, 3):
        raise ValueError("Invalid intrinsic matrix shape")
    if (not all(np.isfinite(v).all() for v in (matrix, new_matrix, distortion)) or
            min(matrix[0, 0], matrix[1, 1], new_matrix[0, 0], new_matrix[1, 1]) <= 0 or
            not np.allclose(new_matrix[2], [0, 0, 1]) or not np.allclose(matrix[2], [0, 0, 1])):
        raise ValueError("Invalid camera calibration numbers")
    if data["model"] == "fisheye":
        if distortion.size != 4:
            raise ValueError("Fisheye model requires four distortion coefficients")
        map1, map2 = cv2.fisheye.initUndistortRectifyMap(matrix, distortion, np.eye(3), new_matrix, size, cv2.CV_32FC1)
    else:
        if distortion.size not in {4, 5, 8, 12, 14}:
            raise ValueError("Invalid pinhole distortion coefficients")
        map1, map2 = cv2.initUndistortRectifyMap(matrix, distortion, None, new_matrix, size, cv2.CV_32FC1)
    info = {"path": str(path), "model": data["model"], "rectified": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "fx_px": float(new_matrix[0, 0]), "fy_px": float(new_matrix[1, 1]),
            "cx_px": float(new_matrix[0, 2]), "cy_px": float(new_matrix[1, 2]),
            "fit_rms_px": data.get("rms_px")}
    return cv2.remap(image, map1, map2, cv2.INTER_LINEAR), info
