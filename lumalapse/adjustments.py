"""Per-frame image adjustments: exposure, dehaze, saturation, contrast, temperature."""

from __future__ import annotations

import cv2
import numpy as np

from .loader import linear_to_srgb

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def dehaze_dark_channel(img: np.ndarray, strength: float, omega: float = 0.85, t_min: float = 0.15) -> np.ndarray:
    """Dark-channel-prior dehaze on a display-referred (gamma) float RGB image.

    `strength` in [0, 1] blends between input and fully dehazed result.
    """
    if strength <= 0.0:
        return img
    h, w = img.shape[:2]
    patch = max(3, (min(h, w) // 50) | 1)

    dark = cv2.erode(img.min(axis=2), cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch)))

    # Atmospheric light: mean color of the brightest 0.1% pixels in the dark channel.
    flat = dark.ravel()
    n_top = max(1, flat.size // 1000)
    idx = np.argpartition(flat, -n_top)[-n_top:]
    atmo = img.reshape(-1, 3)[idx].mean(axis=0)
    atmo = np.maximum(atmo, 0.05)

    norm_dark = cv2.erode((img / atmo).min(axis=2), cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch)))
    trans = 1.0 - omega * norm_dark
    # Edge-aware refinement of the transmission map (cheap guided-filter stand-in).
    gray = (img @ LUMA).astype(np.float32)
    trans = cv2.ximgproc.guidedFilter(gray, trans.astype(np.float32), patch * 2, 1e-3) \
        if hasattr(cv2, "ximgproc") else cv2.bilateralFilter(trans.astype(np.float32), 9, 0.1, patch * 2)
    trans = np.clip(trans, t_min, 1.0)[:, :, None]

    dehazed = (img - atmo) / trans + atmo
    out = img + strength * (dehazed - img)
    return np.clip(out, 0.0, 1.0)


def apply_adjustments(linear_rgb: np.ndarray, params: dict) -> np.ndarray:
    """Apply grading params to a linear-light RGB float image. Returns uint8 sRGB."""
    img = linear_rgb

    # Exposure + white-balance shift act as gains in linear light.
    gain = 2.0 ** float(params.get("exposure", 0.0))
    temp = float(params.get("temperature", 0.0))
    if temp != 0.0:
        wb = np.array([1.0 + 0.3 * temp, 1.0, 1.0 - 0.3 * temp], dtype=np.float32)
        img = img * (gain * wb)
    elif gain != 1.0:
        img = img * gain

    img = linear_to_srgb(img)

    dehaze = float(params.get("dehaze", 0.0))
    if dehaze > 0.0:
        img = dehaze_dark_channel(img, dehaze)

    contrast = float(params.get("contrast", 0.0))
    if contrast != 0.0:
        # S-curve around mid-gray; negative flattens.
        img = np.clip(img + contrast * (img - 0.5) * (1.0 - np.abs(2.0 * img - 1.0)), 0.0, 1.0)

    sat = float(params.get("saturation", 1.0))
    if sat != 1.0:
        luma = (img @ LUMA)[:, :, None]
        img = np.clip(luma + (img - luma) * sat, 0.0, 1.0)

    return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
