"""Generate synthetic inputs; these demonstrate operation, not real accuracy."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "output" / "demo-input"
    folder.mkdir(parents=True, exist_ok=True)
    for number, width in enumerate((80, 120, 200), 1):
        image = np.full((600, 800, 3), 230, np.uint8)
        left = (800 - width) // 2
        cv2.rectangle(image, (left, 45), (left + width - 1, 555), (35, 50, 40), -1)
        name = f"object{number}_1000mm.jpg" if number < 3 else "object3_distance-unavailable.jpg"
        if not cv2.imwrite(str(folder / name), image):
            raise OSError("Could not write synthetic input")
    print("Synthetic demo inputs:", folder)


if __name__ == "__main__":
    main()
