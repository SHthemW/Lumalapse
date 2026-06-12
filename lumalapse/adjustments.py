"""Per-frame image adjustments.

Tone pipeline (exposure, whites/blacks, highlights/shadows) runs on UNCLIPPED
linear-light data: an exposure push may send values past 1.0, and the
whites/highlights controls can pull that overshoot back into range before
anything is clipped — this is what lets the RAW's headroom be recovered
instead of discarded. Display-referred ops (dehaze, contrast, saturation)
follow after gamma encoding.
"""

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


def _smooth01(x: np.ndarray) -> np.ndarray:
    """Smoothstep clamped to [0, 1]."""
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _display_luma(img: np.ndarray) -> np.ndarray:
    """Approximate display-referred luma of unclipped linear RGB, for tone masks."""
    return linear_to_srgb(np.clip(img @ LUMA, 0.0, 1.0))


def apply_tone(linear_rgb: np.ndarray, params: dict) -> np.ndarray:
    """Exposure / whites / blacks / highlights / shadows on unclipped linear data."""
    img = linear_rgb

    # Exposure + white-balance shift are plain gains. No clipping here:
    # overshoot stays available for the controls below.
    gain = 2.0 ** float(params.get("exposure", 0.0))
    temp = float(params.get("temperature", 0.0))
    if temp != 0.0:
        wb = np.array([1.0 + 0.3 * temp, 1.0, 1.0 - 0.3 * temp], dtype=np.float32)
        img = img * (gain * wb)
    elif gain != 1.0:
        img = img * gain

    # Whites / blacks: move the linear endpoints (levels). whites=-1 maps
    # linear 2.0 down to white, recovering up to 1 EV of overshoot; whites=+1
    # brightens by clipping the top stop. blacks lifts or crushes the floor.
    whites = float(params.get("whites", 0.0))
    blacks = float(params.get("blacks", 0.0))
    if whites != 0.0 or blacks != 0.0:
        white_p = 2.0 ** (-whites)
        black_p = -0.025 * blacks
        img = (img - black_p) / (white_p - black_p)

    # Highlights / shadows: luminance-masked EV gains. The highlight mask is 1
    # for anything at/above display white, so negative values compress >1 data
    # back into range (up to ~1.4 EV) with a smooth falloff into the midtones.
    highlights = float(params.get("highlights", 0.0))
    if highlights != 0.0:
        mask = _smooth01((_display_luma(img) - 0.45) / 0.55)
        img = img * (2.0 ** (1.4 * highlights * mask))[:, :, None]

    shadows = float(params.get("shadows", 0.0))
    if shadows != 0.0:
        mask = _smooth01((0.5 - _display_luma(img)) / 0.5)
        img = img * (2.0 ** (1.4 * shadows * mask))[:, :, None]

    return img


def apply_adjustments(linear_rgb: np.ndarray, params: dict) -> np.ndarray:
    """Apply grading params to a linear-light RGB float image. Returns uint8 sRGB."""
    img = apply_tone(linear_rgb, params)

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
