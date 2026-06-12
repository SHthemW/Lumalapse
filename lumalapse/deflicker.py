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


def holy_grail_corrections(ev_values, strength: float = 10.0) -> np.ndarray:
    """Neutralize discrete exposure-setting steps using the EXIF EV curve.

    During day/night ("holy grail") timelapses the camera steps shutter/ISO,
    making the rendered brightness jump by the EV delta in the opposite
    direction. Subtracting the smoothed EV trend isolates those steps;
    applying the residual as exposure compensation cancels the jumps while
    leaving the scene's own gradual brightness change untouched.

    ev_values may contain None (frames without EXIF); they are interpolated.
    Returns zeros if no frame has EV data.
    """
    ev = np.array([np.nan if v is None else float(v) for v in ev_values], dtype=np.float64)
    n = ev.size
    valid = ~np.isnan(ev)
    if n < 2 or not valid.any():
        return np.zeros(n)
    idx = np.arange(n)
    ev = np.interp(idx, idx[valid], ev[valid])
    return ev - gaussian_smooth(ev, sigma=strength)


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
