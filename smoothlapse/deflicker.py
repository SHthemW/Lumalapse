"""Luminance-based deflicker.

Flicker = high-frequency luminance noise (shutter/aperture tolerance, sun through
clouds, auto-exposure steps). We smooth the measured log-luminance curve and apply
the difference between smoothed and measured as a per-frame EV correction. Because
analysis luminance is mean-of-log2 in linear light, an EV correction of `d` shifts
the measured value by exactly `d` — no iterative re-rendering needed.
"""

from __future__ import annotations

import numpy as np


def gaussian_smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    """1-D Gaussian smoothing with edge replication (no scipy dependency)."""
    if sigma <= 0:
        return values.copy()
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values.astype(np.float64), radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def deflicker_corrections(
    luminance: list[float] | np.ndarray,
    exposure_ev: np.ndarray | None = None,
    strength: float = 10.0,
) -> np.ndarray:
    """Per-frame EV corrections that remove flicker while preserving ramps.

    luminance:   measured per-frame log2 luminance (from analysis, before grading)
    exposure_ev: keyframe-interpolated exposure already being applied per frame;
                 corrections are computed on top of it so intentional ramps survive
    strength:    smoothing sigma in frames — higher removes lower-frequency wobble
    """
    lum = np.asarray(luminance, dtype=np.float64)
    if exposure_ev is not None:
        lum = lum + np.asarray(exposure_ev, dtype=np.float64)
    target = gaussian_smooth(lum, sigma=strength)
    return target - lum
