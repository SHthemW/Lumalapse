"""Project-level RAW develop baseline derived from camera embedded JPEGs."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from . import loader

PROFILE_VERSION = 3
SAMPLE_COUNT = 5
SAMPLE_MAX_DIM = 900

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def needs_profile(files: list[str], profile: dict | None) -> bool:
    if not any(loader.is_raw(path) for path in files):
        return False
    return not profile or profile.get("version") != PROFILE_VERSION


def estimate_camera_profile(files: list[str]) -> dict | None:
    """Estimate a fixed camera-look baseline from RAW embedded JPEG previews."""
    raw_files = [path for path in files if loader.is_raw(path)]
    if not raw_files:
        return None
    indexes = np.linspace(0, len(raw_files) - 1, min(SAMPLE_COUNT, len(raw_files)), dtype=int)
    pairs = [_sample_pair(raw_files[i]) for i in dict.fromkeys(indexes)]
    pairs = [pair for pair in pairs if pair is not None]
    if not pairs:
        return None

    contrast_offsets, saturation_scales = [], []
    for raw_rgb, camera_rgb in pairs:
        raw_stats = _stats(raw_rgb)
        camera_stats = _stats(camera_rgb)
        contrast_offsets.append(_contrast_offset(raw_stats, camera_stats))
        saturation_scales.append(_saturation_scale(raw_rgb, camera_rgb))

    return {
        "version": PROFILE_VERSION,
        "source": "embedded_jpeg",
        "samples": len(pairs),
        "histogram_matching": True,
        "exposure": 0.0,
        "contrast": _median_clipped(contrast_offsets, -0.15, 0.25),
        "saturation": _median_clipped(saturation_scales, 0.9, 1.1),
        "highlights": 0.0,
        "shadows": 0.0,
    }


def apply_profile(params: dict[str, np.ndarray], profile: dict | None) -> dict[str, np.ndarray]:
    if not profile:
        return params
    out = {name: values.copy() for name, values in params.items()}
    if profile.get("histogram_matching"):
        n_frames = len(next(iter(out.values()))) if out else 0
        out["_histogram_matching"] = np.ones(n_frames, dtype=np.float64)
    _add(out, "exposure", float(profile.get("exposure", 0.0)))
    _add(out, "contrast", float(profile.get("contrast", 0.0)))
    _mul(out, "saturation", float(profile.get("saturation", 1.0)))
    _add(out, "highlights", float(profile.get("highlights", 0.0)))
    _add(out, "shadows", float(profile.get("shadows", 0.0)))
    return out


def _sample_pair(path: str) -> tuple[np.ndarray, np.ndarray] | None:
    camera = _embedded_jpeg(path)
    if camera is None:
        return None
    raw = _raw_preview(path)
    if raw is None:
        return None
    camera = _resize_like(camera, raw)
    return raw, camera


def _embedded_jpeg(path: str) -> np.ndarray | None:
    import rawpy

    try:
        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
    except Exception:
        return None
    if thumb.format != rawpy.ThumbFormat.JPEG:
        return None
    data = np.frombuffer(thumb.data, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return _resize_max(bgr[:, :, ::-1])


def _raw_preview(path: str) -> np.ndarray | None:
    import rawpy

    try:
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=8,
                half_size=True,
            )
    except Exception:
        return None
    return _resize_max(rgb)


def _resize_max(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    scale = SAMPLE_MAX_DIM / max(h, w)
    if scale >= 1.0:
        return img
    size = max(1, round(w * scale)), max(1, round(h * scale))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


def _resize_like(img: np.ndarray, target: np.ndarray) -> np.ndarray:
    h, w = target.shape[:2]
    if img.shape[:2] == (h, w):
        return img
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def _stats(rgb: np.ndarray) -> dict[str, float]:
    y = rgb.astype(np.float32) @ LUMA
    return {
        "p10": float(np.percentile(y, 10)),
        "p50": float(np.percentile(y, 50)),
        "p90": float(np.percentile(y, 90)),
    }


def _contrast_offset(raw: dict[str, float], camera: dict[str, float]) -> float:
    raw_span = max(raw["p90"] - raw["p10"], 1.0)
    camera_span = max(camera["p90"] - camera["p10"], 1.0)
    return float((camera_span / raw_span - 1.0) * 0.22)


def _saturation_scale(raw_rgb: np.ndarray, camera_rgb: np.ndarray) -> float:
    raw_chroma = _chroma(raw_rgb)
    camera_chroma = _chroma(camera_rgb)
    return float(camera_chroma / max(raw_chroma, 1e-3))


def _chroma(rgb: np.ndarray) -> float:
    x = rgb.astype(np.float32) / 255.0
    gray = (x @ LUMA)[:, :, None]
    return float(np.mean(np.abs(x - gray)))


def _median_clipped(values: list[float], lo: float, hi: float) -> float:
    return float(np.clip(np.median(values), lo, hi))


def _add(params: dict[str, np.ndarray], name: str, value: float):
    if value and name in params:
        params[name] = params[name] + value


def _mul(params: dict[str, np.ndarray], name: str, value: float):
    if value != 1.0 and name in params:
        params[name] = params[name] * value
