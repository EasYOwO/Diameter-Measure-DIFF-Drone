# Validation record

Date: 2026-11-02.

## Environment

- Windows x64, Python 3.13.
- Clean project virtual environment, installed from the included dependency files.
- OpenCV Python 4.13.0.92; NumPy 2.5.4.
- Exact installed dependencies are recorded in `requirements-lock.txt`.
- OpenCV 5 was found incompatible with the current fisheye calibration API. Setup and CI use the tested OpenCV 4 release.

## Completed checks

- 21 discovered unit/integration tests plus 4 synthetic geometry/detection tests passed.
- Independent forward cylinder projection recovers a known diameter; pinhole and fisheye synthetic calibration recover known intrinsics.
- Exactly 127 mm fails the strict greater-than rule; values just above/below use their unrounded values.
- Nominal lens outputs retain manufacturer provenance and are marked uncalibrated. Actual intrinsics take precedence.
- Unreadable images, missing distance, calibration-only inputs and incompatible image aspect ratios are handled without a positive diameter-screening result.
- Batch inputs with identical filenames remain separate; originals are retained; output report/annotation paths resolve after grouping.
- `setup.cmd`, `demo.cmd`, CLI help and dependency consistency check succeeded.
- Demo produced one above-threshold result, one at-or-below result and one needs-review result. The annotated synthetic trunk was visually inspected.

## Practical limits

These checks establish software operation, geometry and data handling. No actual checkerboard images for this individual lens or field measurements of known tree diameters were supplied for this release. The 3.6 mm profile is a manufacturer-sourced nominal estimate. Segmentation is a lightweight heuristic, not either paper's trained model. Inspect annotations and validate real measurements before relying on threshold decisions.

Google Drive OAuth requires the operator's own credentials and consent. This release tests local image operation; it does not claim a new end-to-end Drive sign-in test on a second computer or live ESP/website integration.

The initial algorithm files were carried forward from `EasYOwO/DIFF-Drone` at commit `cfdb6cb438883f3792f9abdb067839c0e611560b`, then packaged and updated here. The hardware repository and connected board were not changed for this measurement release.
