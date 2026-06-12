"""Dehaze halo regression.

Night-city regime: dusk sky is BRIGHTER than unlit building mass. The dark
channel's rectangular min-filter then propagates the buildings' low values
into the sky, and without a proper edge-aware refinement the transmission
map keeps hard patch-sized rectangles hugging every silhouette — the white
boxes users see after raising highlights. The guided-filter refinement must
keep the sky free of hard steps (a soft diffuse glow is the dark-channel
prior's known residual and is acceptable).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.adjustments import apply_adjustments  # noqa: E402


def night_city() -> tuple[np.ndarray, np.ndarray]:
    """Linear-light scene + sky mask: gradient dusk sky above dark towers
    with sparse lit windows."""
    rng = np.random.default_rng(4)
    h, w = 600, 1500
    yy = np.linspace(0.055, 0.025, h, dtype=np.float32)[:, None]
    img = np.dstack([np.tile(yy, (1, w)) * 0.75,
                     np.tile(yy, (1, w)) * 0.85,
                     np.tile(yy, (1, w)) * 1.25]).astype(np.float32)
    sky = np.ones((h, w), dtype=np.uint8)
    for x in range(60, w - 200, 220):
        bh = int(rng.uniform(0.35, 0.7) * h)
        img[h - bh:, x:x + 150] = 0.004
        sky[h - bh - 3:, x - 3:x + 153] = 0
        for wy in range(h - bh + 10, h - 10, 18):
            for wx in range(x + 8, x + 142, 16):
                if rng.random() < 0.35:
                    img[wy:wy + 7, wx:wx + 8] = rng.uniform(0.2, 0.8)
    return img, sky.astype(bool)


def max_sky_step(out: np.ndarray, sky: np.ndarray) -> float:
    """Largest single-pixel brightness step (8-bit) inside the sky region —
    hard rectangle borders show up here; smooth gradients do not."""
    g = out.mean(axis=2).astype(np.float32)
    dx = np.abs(np.diff(g, axis=1))[sky[:, :-1] & sky[:, 1:]]
    dy = np.abs(np.diff(g, axis=0))[sky[:-1, :] & sky[1:, :]]
    return float(max(dx.max(), dy.max()))


def main():
    img, sky = night_city()

    out = apply_adjustments(img.copy(), {"dehaze": 0.4, "highlights": 0.6})
    step = max_sky_step(out, sky)
    print(f"max hard step in sky (dehaze+highlights): {step:.2f}/255")
    # The old bilateral refinement left ~3-6 level rectangle borders here.
    assert step < 1.5, f"hard blocky halo in sky (step {step:.2f})"

    out_h = apply_adjustments(img.copy(), {"highlights": 0.6, "shadows": 0.4})
    step_h = max_sky_step(out_h, sky)
    print(f"max hard step in sky (tone only):         {step_h:.2f}/255")
    assert step_h < 1.0, "tone controls must never create spatial steps"

    print("DEHAZE HALO TESTS PASSED")


if __name__ == "__main__":
    main()
