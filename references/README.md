# References and implementation map

## Shao, Qu and Du (2022)

Tianyi Shao, Yonghua Qu, Jianqing Du. **A low-cost integrated sensor for measuring tree diameter at breast height (DBH)**. Computers and Electronics in Agriculture 199, 107140.

- DOI: https://doi.org/10.1016/j.compag.2022.107140
- Author/institution-hosted PDF: https://srs.bnu.edu.cn/docs/2023-11/313159b8e4e5464db55358e1eb535228.pdf
- Copyright: Elsevier, all rights reserved. Original PDF linked, not redistributed.

`src/measure.py` uses the distance geometry in Eq. 3 and cylinder correction in Eq. 6. Let `q = pixel_width / fx_pixels`, `d` be lens-to-front-surface distance, and `x = D/d`. The cylinder equation factors as `(x+1)(x²-q²x-q²)=0`; its positive solution is `D = d*q*(q + sqrt(q²+4))/2`. The flat result is `D = d*q`. Cylinder and tangent expressions represent the same geometry, not independent accuracy validation. Use a centred, upright trunk and axial distance. Our detector uses median horizontal widths rather than the paper's learned segmentation and leaning-trunk fit.

## Wang et al. (2023)

Sheng Wang, Rao Li, Huan Li, Xiaowen Ma, Qiang Ji, Fu Xu, Hongping Fu. **An automated method for stem diameter measurement based on laser module and deep learning**. Plant Methods 19, 68.

- DOI/article: https://doi.org/10.1186/s13007-023-01045-7
- Archive: https://pmc.ncbi.nlm.nih.gov/articles/PMC10324111/
- Original PDF: https://link.springer.com/content/pdf/10.1186/s13007-023-01045-7.pdf
- Included full-text XML: `Wang-2023-stem-diameter-CC-BY-4.0.xml` (unchanged archive response).
- Source XML: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10324111/fullTextXML
- © The Author(s) 2023, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Retain attribution and any third-party credit restrictions when reusing article content. No changes were made to the included XML. Publisher PDF download returned an HTML challenge in this environment, so no mislabeled PDF is included.

The optional reference mode follows Eq. 9: `diameter = object_pixels * known_reference_mm / reference_pixels`. The reference must have known physical size at the target's depth. This implementation uses a round marker; it does not recreate the paper's laser optics, trained U²-Net or measurement device. Paper accuracy results do not describe this repository.

## Nominal camera specification

Kai Lap Technologies, **JAL-KA4-OV2640 OmniVision OV2640 DVP Parallel Interface Fixed Focus 2MP Camera Module**.

- Original manufacturer PDF: https://kailaptech.net/KLT/EN/PDF/JAL-KA4-OV2640%20OmniVision%20OV2640%20DVP%20Parallel%20Interface%20Fixed%20Focus%202MP%20Camera%20Module.pdf
- EFL 3.6 mm; advertised view angle 66.4° (axis unspecified); sensor output 1600 × 1200; pixel pitch 2.2 µm.
- Used only as nominal lens/sensor provenance in `config.yaml`. Actual calibrated intrinsics take precedence. OV2640 is a sensor model, not a unique lens specification.
- Manufacturer document is linked, not redistributed. Accessed 2026-11-02.

## Project-specific classification

`src/classification.py` applies the user's requirement, not a rule from either paper: **D > 5 inches = 127 mm**. Equality does not pass. Calibration-only inputs and unavailable physical diameters need review. Shape detection is heuristic; inspect the annotated target before using the diameter-screening result.
