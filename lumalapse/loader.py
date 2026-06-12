"""Image loading (RAW via rawpy/LibRaw, plus JPEG/TIFF fallback) and EXIF metadata."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

RAW_EXTS = {
    ".arw", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".dng", ".raf",
    ".orf", ".rw2", ".pef", ".srw", ".x3f", ".raw", ".sr2", ".kdc",
    ".mrw", ".3fr", ".iiq", ".erf",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
SUPPORTED_EXTS = RAW_EXTS | IMAGE_EXTS


def is_raw(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTS


def list_sequence(folder: str | Path) -> list[str]:
    """Sorted list of supported image files in a folder."""
    folder = Path(folder)
    files = [
        str(p) for p in sorted(folder.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]
    return files


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1.0 / 2.4) - 0.055).astype(np.float32)


def _imread_unicode(path: str | Path, flags: int) -> np.ndarray | None:
    """Read an image through OpenCV without losing non-ASCII Windows paths."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def load_linear(path: str | Path, half_size: bool = False, max_dim: int | None = None) -> np.ndarray:
    """Load an image as linear-light float32 RGB in [0, 1].

    RAW files are demosaiced with camera white balance, no auto-brightening and
    linear gamma so that exposure changes are exact gains. Non-RAW files are
    decoded from sRGB.
    """
    path = str(path)
    if is_raw(path):
        import rawpy

        with rawpy.imread(path) as raw:
            rgb16 = raw.postprocess(
                gamma=(1, 1),
                no_auto_bright=True,
                output_bps=16,
                use_camera_wb=True,
                half_size=half_size,
            )
        img = rgb16.astype(np.float32) / 65535.0
    else:
        data = _imread_unicode(path, cv2.IMREAD_UNCHANGED)
        if data is None:
            raise IOError(f"Cannot read image: {path}")
        if data.ndim == 2:
            data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
        if data.shape[2] == 4:
            data = data[:, :, :3]
        maxval = 65535.0 if data.dtype == np.uint16 else 255.0
        srgb = data[:, :, ::-1].astype(np.float32) / maxval  # BGR -> RGB
        img = srgb_to_linear(srgb)
        if half_size:
            img = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA)

    if max_dim is not None:
        h, w = img.shape[:2]
        scale = max_dim / max(h, w)
        if scale < 1.0:
            img = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))),
                             interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def _ratio(tag) -> float | None:
    try:
        v = tag.values[0]
        return float(v.num) / float(v.den) if hasattr(v, "num") else float(v)
    except Exception:
        return None


def read_metadata(path: str | Path) -> dict:
    """Read shutter/aperture/ISO/timestamp from EXIF. Missing fields are None."""
    import exifread

    meta = {"shutter": None, "aperture": None, "iso": None, "datetime": None}
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:
        return meta

    if "EXIF ExposureTime" in tags:
        meta["shutter"] = _ratio(tags["EXIF ExposureTime"])
    if "EXIF FNumber" in tags:
        meta["aperture"] = _ratio(tags["EXIF FNumber"])
    if "EXIF ISOSpeedRatings" in tags:
        try:
            meta["iso"] = float(tags["EXIF ISOSpeedRatings"].values[0])
        except Exception:
            pass
    for key in ("EXIF DateTimeOriginal", "Image DateTime"):
        if key in tags:
            meta["datetime"] = str(tags[key])
            break
    return meta


def exposure_value(meta: dict) -> float | None:
    """Standard EV at ISO 100: EV = log2(N^2 / t) - log2(ISO / 100)."""
    shutter, aperture, iso = meta.get("shutter"), meta.get("aperture"), meta.get("iso")
    if not shutter or not aperture:
        return None
    ev = math.log2(aperture * aperture / shutter)
    if iso:
        ev -= math.log2(iso / 100.0)
    return ev
