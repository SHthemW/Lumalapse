"""Sequence analysis: per-frame luminance and camera EV curves."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import loader
from .settings import load_settings

LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
ANALYSIS_MAX_DIM = 480  # analysis runs on small proxies; plenty for mean luminance
DEFAULT_ANALYSIS_CPU_PERCENT = 80


def analysis_worker_count(cpu_percent: int | None = None) -> int:
    """Approximate the configured CPU budget with a bounded thread count."""
    if cpu_percent is None:
        cpu_percent = int(load_settings().get("analysis_cpu_percent", DEFAULT_ANALYSIS_CPU_PERCENT))
    cpu_percent = min(max(int(cpu_percent), 10), 100)
    cores = os.cpu_count() or 1
    return max(1, min(cores, int(cores * cpu_percent / 100)))


def frame_log_luminance(linear_rgb: np.ndarray) -> float:
    """Mean log2 luminance of a linear-light RGB image.

    Working in log space means an exposure change of +1 EV shifts this value
    by exactly +1, which makes deflicker corrections exact gains.
    """
    luma = linear_rgb @ LUMA_WEIGHTS
    return float(np.mean(np.log2(np.maximum(luma, 1e-6))))


def analyze_sequence(files: list[str], progress=None, workers: int | None = None) -> dict:
    """Compute per-frame log-luminance and EXIF EV for a sequence.

    Returns {"luminance": [...], "ev": [...]} where ev entries may be None.
    """
    n = len(files)
    luminance: list[float | None] = [None] * n
    evs: list[float | None] = [None] * n
    errors: list[dict] = []
    done = 0

    def work(i: int):
        try:
            img = loader.load_linear(files[i], half_size=True, max_dim=ANALYSIS_MAX_DIM)
            lum = frame_log_luminance(img)
            ev = loader.exposure_value(loader.read_metadata(files[i]))
            return i, lum, ev, None
        except Exception as exc:
            return i, None, None, str(exc)

    with ThreadPoolExecutor(max_workers=workers or analysis_worker_count()) as pool:
        for i, lum, ev, error in pool.map(work, range(n)):
            luminance[i] = lum
            evs[i] = ev
            if error:
                errors.append({"frame": i, "file": files[i], "error": error})
            done += 1
            if progress:
                progress(done, n)

    valid = [i for i, value in enumerate(luminance) if value is not None]
    if not valid:
        sample = errors[0]["error"] if errors else "no readable images"
        raise IOError(f"Cannot analyze sequence: {sample}")
    if len(valid) < n:
        x = np.arange(n, dtype=np.float64)
        luminance = np.interp(x, valid, [luminance[i] for i in valid]).tolist()

    return {"luminance": luminance, "ev": evs, "errors": errors}
