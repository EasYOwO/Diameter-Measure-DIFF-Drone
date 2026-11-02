"""Group annotated measurements without moving or changing original photographs."""

from __future__ import annotations

import csv
import html
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import cv2

from .filename_distance import apply_filename_distance_to_settings
from .pipeline import MeasureSettings, measure_file

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def measure_folder(folder: Path, settings: MeasureSettings, project_root: Path,
                   *, recursive: bool = False) -> dict:
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Image folder not found: {folder}")
    output = settings.output_dir.resolve()
    paths = sorted(p for p in (folder.rglob("*") if recursive else folder.iterdir())
                   if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
                   and not p.resolve().is_relative_to(output))
    if not paths:
        raise ValueError("No supported images found outside the output directory")
    if settings.known_mm is not None:
        raise ValueError("Use --known-mm with one --image; batch calibration would overwrite the scale repeatedly")
    run = output / datetime.now().strftime("batch-%Y%m%d-%H%M%S-%f")
    run.mkdir(parents=True)
    rows = []
    for index, path in enumerate(paths, 1):
        work = run / f"item-{index:04d}"
        per_image = replace(settings, output_dir=work)
        if per_image.distance_mm is None and per_image.ref_mm is None and not per_image.use_saved_calibration:
            apply_filename_distance_to_settings(per_image, path)
        try:
            report = measure_file(path, per_image, project_root)
            category = report["assessment"]["category"]
            row = {"input": str(path), "diameter_mm": report["diameter_mm_unrounded"],
                   "diameter_inches": report["diameter_inches"], "category": category,
                   "passes_diameter_rule": report["assessment"]["passes_diameter_rule"],
                   "scale_mode": report["scale_mode"], "nominal_estimate": report["approximate_nominal_lens"],
                   "distance_mm": report["distance_mm_used"], "note": report.get("warning") or ""}
            dest = run / category / work.name
            dest.parent.mkdir(exist_ok=True)
            work.rename(dest)
            report["annotated_image"] = str(dest / Path(report["annotated_image"]).name)
            report["report_path"] = str(dest / Path(report["report_path"]).name)
            Path(report["report_path"]).write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
            row["annotation"] = Path(report["annotated_image"]).relative_to(run).as_posix()
            row["report"] = Path(report["report_path"]).relative_to(run).as_posix()
        except (ValueError, OSError, cv2.error) as exc:
            dest = run / "needs_review" / f"item-{index:04d}"
            dest.mkdir(parents=True, exist_ok=True)
            error = {"input": str(path), "category": "needs_review", "error": str(exc)}
            (dest / "error.json").write_text(json.dumps(error, indent=2), encoding="utf-8")
            row = {"input": str(path), "diameter_mm": None, "diameter_inches": None,
                   "category": "needs_review", "passes_diameter_rule": None, "scale_mode": "error",
                   "nominal_estimate": None, "distance_mm": per_image.distance_mm,
                   "note": str(exc), "annotation": "", "report": (dest / "error.json").relative_to(run).as_posix()}
        rows.append(row)
        print(f"[{index}/{len(paths)}] {path.name}: {row['category']}")
    summary = {"threshold_inches": settings.threshold_inches, "threshold_mm": settings.threshold_inches * 25.4,
               "operator": ">", "items": rows,
               "counts": {group: sum(r["category"] == group for r in rows)
                          for group in ("above_threshold", "at_or_below_threshold", "needs_review")}}
    (run / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    with (run / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_gallery(run, summary)
    return {"run_dir": str(run), **summary}


def _write_gallery(run: Path, summary: dict) -> None:
    cards = []
    for row in summary["items"]:
        image = (f'<img loading="lazy" src="{quote(row["annotation"])}" alt="Measured edges">'
                 if row["annotation"] else "")
        diameter = "Unavailable" if row["diameter_mm"] is None else f'{row["diameter_mm"]:.2f} mm / {row["diameter_inches"]:.4f} in'
        cards.append(f'<article data-group="{row["category"]}"><h2>{html.escape(Path(row["input"]).name)}</h2>'
                     f'{image}<strong>{diameter}</strong><p>{row["category"].replace("_", " ")}</p>'
                     f'<p>{html.escape(row["note"])}</p><a href="{quote(row["report"])}">JSON report</a></article>')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DIFF Drone | Diameter results</title><style>
body{font:16px system-ui;background:#eee9dc;color:#173b31;margin:0;padding:24px}header,main{max-width:1200px;margin:auto}
h1{font-size:32px}select{padding:12px;border:1px solid #839789;border-radius:8px;background:white;color:inherit}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;margin-top:24px}
article{padding:20px;background:#fffdf7;border-radius:16px;border-top:4px solid #52765b}h2{font-size:17px;overflow-wrap:anywhere}
img{width:100%;height:210px;object-fit:contain;background:#e3e7df}p{line-height:1.5;overflow-wrap:anywhere}a{color:#215c48}
[hidden]{display:none}</style><header><small>DIFF / DRONE CAMERA</small><h1>Diameter screening results</h1>
<p>Rule: diameter strictly &gt; LIMIT inches. Confirm the target and both edges in each annotation. Nominal lens values are approximate.</p>
<label>Show <select id="filter"><option value="all">All results</option><option value="above_threshold">Above threshold</option>
<option value="at_or_below_threshold">At or below threshold</option><option value="needs_review">Needs review</option></select></label>
<p><a href="summary.csv">Download CSV</a> · <a href="summary.json">Summary JSON</a></p></header><main>CARDS</main>
<script>document.getElementById('filter').addEventListener('change',e=>document.querySelectorAll('article').forEach(a=>a.hidden=e.target.value!=='all'&&a.dataset.group!==e.target.value));</script></html>'''
    (run / "index.html").write_text(document.replace("LIMIT", f'{summary["threshold_inches"]:g}').replace("CARDS", "".join(cards)), encoding="utf-8")
