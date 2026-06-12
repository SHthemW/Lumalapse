"""Sequence analysis: per-frame luminance and camera EV curves."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import loader

LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
ANALYSIS_MAX_DIM = 480  # analysis runs on small proxies; plenty for mean luminance


def frame_log_luminance(linear_rgb: np.ndarray) -> float:
    """Mean log2 luminance of a linear-light RGB image.

    Working in log space means an exposure change of +1 EV shifts this value
    by exactly +1, which makes deflicker corrections exact gains.
    """
    luma = linear_rgb @ LUMA_WEIGHTS
    return float(np.mean(np.log2(np.maximum(luma, 1e-6))))


def analyze_sequence(files: list[str], progress=None, workers: int = 4) -> dict:
    """Compute per-frame log-luminance and EXIF EV for a sequence.

    Returns {"luminance": [...], "ev": [...]} where ev entries may be None.
    """
    n = len(files)
    luminance: list[float | None] = [None] * n
    evs: list[float | None] = [None] * n
    done = 0

    def work(i: int):
        img = loader.load_linear(files[i], half_size=True, max_dim=ANALYSIS_MAX_DIM)
        lum = frame_log_luminance(img)
        ev = loader.exposure_value(loader.read_metadata(files[i]))
        return i, lum, ev

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, lum, ev in pool.map(work, range(n)):
            luminance[i] = lum
            evs[i] = ev
            done += 1
            if progress:
                progress(done, n)

    return {"luminance": luminance, "ev": evs}
