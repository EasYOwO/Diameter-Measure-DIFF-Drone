# Diameter Measure DIFF Drone

Measure diameter from original ESP32-S3-CAM / OV2640 photographs, then group results using the project's rule: **diameter > 5 inches (127 mm)**. Exactly 127 mm does not pass. Code comments, terminal messages and reports are in English; this guide is bilingual.

## Quick start / 快速运行

Use **64-bit Python 3.13** (tested). Download or clone this repository, then open a terminal in its folder.

Windows:

```bat
setup.cmd
demo.cmd
```

`setup.cmd` creates a local `.venv` and installs the tested dependencies. `demo.cmd` generates three synthetic pictures, processes them, and prints the location of an offline `index.html`. Open that file to filter the groups and inspect the annotated edges. The synthetic pictures demonstrate operation; they do not establish accuracy on real trees.

Other systems:

```sh
python3 -m venv .venv
# Linux / macOS
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python examples/create_demo.py
python main.py --folder output/demo-input --output output/demo-results --non-interactive
```

先安装 64 位 Python，进入本文件夹运行 `setup.cmd`，再运行 `demo.cmd`。最后打开终端显示的 `index.html`。程序在电脑上处理照片，无须改动 ESP 固件或在线相机网页。

## Use your photographs / 使用相机照片

Download the **original still image** from the camera's SD card or Drive. Keep the original filename, resolution and full field of view; do not use a live-preview screenshot or a crop. Use the distance captured with that photograph.

```bat
run.cmd --image "C:\Photos\object73_152mm.jpg"
run.cmd --folder "C:\Photos" --recursive --non-interactive
run.cmd --image "C:\Photos\tree.jpg" --distance-mm 1000
```

On Linux/macOS, use `python main.py` in place of `run.cmd`.

`object73_152mm.jpg` means **152 mm shooting distance**, not 152 mm trunk diameter. A Drive download prefix is accepted, such as `abcd_object73_152mm.jpg`. `object74_distance-unavailable.jpg` has no usable distance: supply `--distance-mm` from an actual measurement, or leave it in `needs_review`.

Distance priority is command line → `config.yaml` → filename → interactive prompt. Batch mode never asks for missing distances. A shared `--distance-mm` or config distance applies to every batch image; use it only if every picture was captured at that distance.

Filename distance is the rangefinder reading. The formula needs distance **from the lens to the front surface along the viewing axis**. Align the VL53L0X with the camera and account for its physical offset from the lens. The sensor reading must hit the same trunk at capture time. Changing drone distance between photographs is supported; reusing a stale distance is not.

中文：使用 SD／Drive 原图，并保留 `object编号_距离mm.jpg` 文件名。文件名中的数字是拍摄距离，程序会自动读取。缺少距离时，批量模式只输出像素并归入待检查；不会猜测距离。镜头与测距器需要对准同一树干，测距器与镜头前后位置不同产生的距离偏移也需要计入。

## The 66-degree lens / 66 度镜头

The [Kai Lap JAL-KA4-OV2640 manufacturer specification](https://kailaptech.net/KLT/EN/PDF/JAL-KA4-OV2640%20OmniVision%20OV2640%20DVP%20Parallel%20Interface%20Fixed%20Focus%202MP%20Camera%20Module.pdf) lists **EFL 3.6 mm**, view angle **66.4°**, 1600 × 1200 output and 2.2 µm sensor pixels. This is the sourced nominal profile in `config.yaml`. The angle's axis is unspecified, so the code does not infer focal length from the angle.

The OV2640 sensor can use different lenses. A matching advertised angle does not establish the calibrated focal length of an individual camera. Until actual calibration is supplied, results explicitly say **nominal lens estimate** and `lens_calibrated: false`. The nominal model assumes an uncropped full-sensor 4:3 image; native focal length in pixels is approximately `3.6 / 0.0022 = 1636.36 px`. Full-frame resized 4:3 images scale that value; a crop or digital zoom invalidates the assumption even if its aspect ratio remains 4:3.

中文：默认已加入相近 66° 模组的 **3.6 mm 规格焦距**，可以直接得到估算直径。它不是你这颗镜头的实测标定值。实际标定文件存在时会自动优先使用。换镜头、改变对焦或裁剪画面后，要重新确认参数。

## Results and the 5-inch rule / 输出和分类

A single image produces `output/<name>_diameter.jpg` and `.json`. Batch processing creates a new run folder containing:

```text
output/batch-.../
  above_threshold/          # Strictly > 127 mm with the default rule
  at_or_below_threshold/    # <= 127 mm
  needs_review/             # No scale, unreadable image, calibration-only input, etc.
  summary.csv
  summary.json
  index.html                # Offline result viewer; no server needed
```

Original photos are never moved or overwritten. Duplicate input names get separate result folders. JSON retains the unrounded measurement used for comparison; CSV includes that value, inches, nominal-estimate flag, distance and category. The HTML groups are screening results: inspect each annotation to confirm both edges belong to the intended trunk. The shape heuristic does not identify a tree species or prove that an object is a tree. `passes_diameter_rule` expresses only this project's diameter requirement for a chopping candidate.

A rounded display of `127.00 mm` can lie on either side of the threshold; classification uses the unrounded number. No measurement-accuracy guarantee or statistically validated uncertainty interval is implied. Verify borderline estimates using a known cylinder or tape measurement.

中文：超过 **127 mm** 才归入直径条件通过组；等于 127 mm 不通过。标注图会画出识别轮廓与测量宽度，请先检查有没有选错树干或背景。3.6 mm 估算结果会保留估算标签；接近边界时应复核实物尺寸。

## Calibrate the actual lens / 实际镜头标定

Generate the printable target with `python create_calibration_pattern.py`. Print its A4 PDF at **100% / Actual size**, check the 100 mm ruler line, and mount it flat. The target has **8 × 6 inner corners**, 20 mm squares.

Take 20–25 sharp original photographs with the actual camera, varying target tilt, distance and position across the frame. Keep all corners visible. Put them in `calibration_images/` and run:

```bat
.venv\Scripts\python.exe calibrate_camera.py --images calibration_images --model pinhole
run.cmd --image "C:\Photos\object1_1000mm.jpg" --require-calibration
```

Use `--model fisheye` only when that model suits the actual lens. At least 10 usable varied views are required. The calibration tool rejects insufficient or repeated views and excessive reprojection error. It writes `camera_intrinsics.json` and corner-check images. Inspect the corners, then validate against cylinders of known diameter at multiple distances. Fit RMS is not diameter accuracy.

Actual intrinsics are used before nominal values; calibration image dimensions must match measurement dimensions. `--require-calibration` disables nominal focal estimates. A same-plane reference or explicit fixed scale can still be used because it does not require lens focal length.

中文：实际标定能纠正畸变并得到像素焦距；正常 66° 镜头先试 `pinhole`。同一镜头、对焦、分辨率及相机模式不变时，可以复用标定；拍摄距离变化本身不要求重做镜头标定。暂未提供你的实际棋盘格照片，因此此仓库没有伪造标定文件。

## Other scale modes / 其他尺度方式

```bat
REM Known round marker beside the trunk at the same depth
run.cmd --image "C:\Photos\tree-with-marker.jpg" --ref-mm 40
REM Calibrate a fixed mm/pixel scale using a known-size main subject
run.cmd --image "C:\Photos\known-cylinder.jpg" --known-mm 100
REM Reuse only at the identical distance, resolution and camera mode
run.cmd --image "C:\Photos\next-cylinder.jpg" --fixed-scale
```

`--known-mm` records a supplied calibration size; it is not an independent unknown measurement and is not classified as a chopping candidate. Keep the reference at the same depth and inspect which marker was detected. A fixed mm/pixel scale is unsuitable for varying drone distances. `--geometry flat` is available for a front-facing flat object; cylinder is the default for upright trunks.

## Optional Google Drive picker / 可选 Drive 选图

Local files require no Google account. To use the picker, enable the Google Drive API in your Google Cloud project and create a **Desktop app OAuth client**. Configure the consent screen and add your account as a test user if needed. Download its JSON to `credentials/client_secret.json`, then run `run.cmd` without an image argument. Sign in through the browser; the app requests read-only Drive access. Enter an image number or paste a folder link in the terminal. Token and client JSON stay excluded from Git.

中文：不想设置 Google 登录就直接下载照片并使用 `--image` 或 `--folder`。其他电脑只需安装 Python、下载本仓库并运行 `setup.cmd`；个人 OAuth 文件和标定文件需要自己复制。

## Implementation and references / 算法与参考资料

- `src/detect.py`: centre-prior GrabCut/Otsu segmentation; median horizontal trunk width or area-equivalent circular diameter. Lean correction and the papers' trained neural networks are not implemented. Clutter, branches, tilt, blur and incomplete silhouettes can mislead this detector.
- `src/measure.py`: perspective width and cylinder correction; see equation mapping and assumptions in [references/README.md](references/README.md).
- `src/pipeline.py`: actual lens rectification → detection → physical scale → annotation and report.
- `src/classification.py`: strict, unrounded threshold comparison.
- `src/batch.py`: isolated batch outputs, CSV and offline HTML.
- `calibrate_camera.py`: OpenCV pinhole/fisheye calibration from actual photographs.

The [references folder](references/) contains citations, DOI/source links, formula mapping and the openly licensed Wang paper full-text XML. The Shao paper and camera specification are linked to their original sources; their copyrighted full documents are not redistributed. This package implements geometric relations with its own lightweight detector; published field-accuracy numbers are not results for this hardware.

The hardware capture project remains [DIFF-Drone](https://github.com/EasYOwO/DIFF-Drone). This repository runs measurement on a computer after capture and does not replace its firmware, website or remote-video service.

## Checks / 检查

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest tests.synthetic_check -v
run.cmd --self-test
```

Software checks cover geometry, strict 127 mm boundaries, invalid/missing distances, actual intrinsics precedence, duplicate batch filenames and corrupt image handling. These are synthetic/integration checks; real lens and tree-measurement accuracy still need physical validation. See `VALIDATION.md` for this release's tested environment and result.
