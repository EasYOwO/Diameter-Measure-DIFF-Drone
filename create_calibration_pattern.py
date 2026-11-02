"""Create a physically dimensioned A4 checkerboard; no synthetic camera calibration."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parent


def main():
    folder = ROOT / "output" / "pdf"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "OV2640-calibration-checkerboard-A4.pdf"
    doc = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    doc.setTitle("OV2640 camera calibration - 8 x 6 inner corners, 20 mm squares")
    doc.setFont("Helvetica-Bold", 17)
    doc.drawString(15 * mm, height - 20 * mm, "OV2640 lens calibration")
    doc.setFont("Helvetica", 10)
    doc.drawString(15 * mm, height - 29 * mm, "Print on A4 at ACTUAL SIZE / 100%. Disable Fit to page.")
    doc.drawString(15 * mm, height - 37 * mm, "9 x 7 squares; 8 x 6 INNER corners; each square 20 x 20 mm.")
    doc.drawString(15 * mm, height - 45 * mm, "Mount flat on a rigid board. Keep the entire pattern and white border visible.")
    left, top = 15 * mm, height - 60 * mm
    for row in range(7):
        for col in range(9):
            if (row + col) % 2 == 0:
                doc.rect(left + col * 20 * mm, top - (row + 1) * 20 * mm, 20 * mm, 20 * mm, stroke=0, fill=1)
    doc.setFont("Helvetica", 10)
    for i, line in enumerate([
        "Take 20-25 sharp ORIGINAL photos with the actual ESP camera, 1600 x 1200.",
        "Vary position, tilt and distance; show the board near all sides of the image.",
        "Keep all corners visible. Avoid glare, motion blur and nearly edge-on views.",
        "Keep lens focus, camera settings and resolution unchanged after calibration.",
    ]):
        doc.drawString(15 * mm, 82 * mm - i * 6 * mm, line)
    doc.setLineWidth(.7)
    doc.line(15 * mm, 43 * mm, 115 * mm, 43 * mm)
    for x in (15, 115):
        doc.line(x * mm, 41 * mm, x * mm, 45 * mm)
    doc.setFont("Helvetica-Bold", 10)
    doc.drawString(15 * mm, 35 * mm, "CHECK WITH A RULER: this line must be 100 mm.")
    doc.setFont("Helvetica", 9)
    doc.drawString(15 * mm, 24 * mm, "This sheet is a calibration target, not proof of diameter accuracy.")
    doc.showPage()
    doc.save()
    print(path)


if __name__ == "__main__":
    main()
