"""GPU acceleration detection and process-wide render toggles."""

from __future__ import annotations

from functools import lru_cache

import cv2

ACCEL_AUTO = "auto"
ACCEL_OFF = "off"
ACCEL_MODES = {ACCEL_AUTO, ACCEL_OFF}


def normalize_mode(mode: str | None) -> str:
    return mode if mode in ACCEL_MODES else ACCEL_AUTO


@lru_cache(maxsize=1)
def detect_gpu() -> dict:
    """Detect OpenCV OpenCL support used by the built-in render path."""
    info = {
        "available": False,
        "name": "",
        "vendor": "",
        "version": "",
        "compute_units": 0,
        "memory_bytes": 0,
        "level": "none",
        "summary": "未检测到可用的 OpenCL GPU 加速",
    }
    try:
        if not cv2.ocl.haveOpenCL():
            return info
        old = cv2.ocl.useOpenCL()
        cv2.ocl.setUseOpenCL(True)
        available = cv2.ocl.useOpenCL()
        device = cv2.ocl.Device_getDefault() if available else None
        cv2.ocl.setUseOpenCL(old)
        if not available or device is None:
            return info
        name = _safe_device_value(device, "name")
        vendor = _safe_device_value(device, "vendorName")
        version = _safe_device_value(device, "version")
        compute_units = int(_safe_device_value(device, "maxComputeUnits", 0) or 0)
        memory_bytes = int(_safe_device_value(device, "globalMemSize", 0) or 0)
    except Exception:
        return info

    level = _acceleration_level(compute_units, memory_bytes)
    info.update(
        available=True,
        name=name or "OpenCL GPU",
        vendor=vendor,
        version=version,
        compute_units=compute_units,
        memory_bytes=memory_bytes,
        level=level,
        summary=_summary(name, vendor, level),
    )
    return info


def apply_acceleration(mode: str | None) -> dict:
    """Apply the selected acceleration mode for OpenCV work in this process."""
    mode = normalize_mode(mode)
    info = detect_gpu()
    enabled = mode == ACCEL_AUTO and info["available"]
    try:
        cv2.setUseOptimized(True)
        cv2.ocl.setUseOpenCL(enabled)
    except Exception:
        enabled = False
    out = dict(info)
    out["enabled"] = enabled
    out["mode"] = mode
    return out


def accelerated_resize(img, size: tuple[int, int], interpolation: int):
    """Resize with OpenCV's OpenCL path when it is currently enabled."""
    if cv2.ocl.useOpenCL():
        try:
            return cv2.resize(cv2.UMat(img), size, interpolation=interpolation).get()
        except Exception:
            pass
    return cv2.resize(img, size, interpolation=interpolation)


def status_text(mode: str | None) -> str:
    mode = normalize_mode(mode)
    info = detect_gpu()
    if mode == ACCEL_OFF:
        return "GPU 加速已关闭"
    if not info["available"]:
        return info["summary"]
    level = {"limited": "有限", "moderate": "中等", "high": "较高"}.get(info["level"], "有限")
    return f"{info['name']} - {level}加速：预览缩放/导出缩放可加速，RAW 解码与 RawTherapee 仍使用 CPU"


def _safe_device_value(device, attr: str, default=""):
    try:
        return getattr(device, attr)()
    except Exception:
        return default


def _acceleration_level(compute_units: int, memory_bytes: int) -> str:
    memory_gb = memory_bytes / 1024**3
    if compute_units >= 32 and memory_gb >= 8:
        return "high"
    if compute_units >= 12 and memory_gb >= 4:
        return "moderate"
    return "limited"


def _summary(name: str, vendor: str, level: str) -> str:
    prefix = f"{vendor} {name}".strip() or "OpenCL GPU"
    label = {"limited": "有限", "moderate": "中等", "high": "较高"}.get(level, "有限")
    return f"{prefix}，可用程度：{label}"
