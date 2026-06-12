"""Generate a small flickering demo JPEG sequence: python make_demo.py <out_dir> [n]"""

import sys
from pathlib import Path

import cv2
import numpy as np

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
rng = np.random.default_rng(1)
h, w = 180, 240
yy, xx = np.mgrid[0:h, 0:w]
scene = (0.2 + 0.5 * xx / w + 0.2 * yy / h).astype(np.float32)
for i in range(n):
    img = np.clip(scene * 2 ** (i / n + rng.normal(0, 0.2)), 0, 1)
    cv2.imwrite(str(out / f"f{i:03d}.jpg"), (img * 255).astype("uint8"))
print(f"wrote {n} frames to {out}")
