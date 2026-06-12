"""Frame rendering: load -> grade -> resize."""

from __future__ import annotations

from collections import OrderedDict

import cv2
import numpy as np

from . import loader
from .adjustments import apply_adjustments
from .project import Project

# Decoded-image cache for interactive previews: re-grading a frame after a
# parameter tweak then only costs the adjustment pass (~ms), not a RAW decode
# (~seconds). apply_adjustments never mutates its input, so sharing is safe.
_DECODE_CACHE: OrderedDict[tuple, np.ndarray] = OrderedDict()
_DECODE_CACHE_MAX = 8  # ~10 MB per 1100px preview frame


def _load_cached(path: str, half_size: bool, max_dim: int | None) -> np.ndarray:
    key = (path, half_size, max_dim)
    img = _DECODE_CACHE.get(key)
    if img is None:
        img = loader.load_linear(path, half_size=half_size, max_dim=max_dim)
        _DECODE_CACHE[key] = img
        if len(_DECODE_CACHE) > _DECODE_CACHE_MAX:
            _DECODE_CACHE.popitem(last=False)
    else:
        _DECODE_CACHE.move_to_end(key)
    return img


def _params_at(all_params: dict[str, np.ndarray], idx: int) -> dict:
    return {name: float(arr[idx]) for name, arr in all_params.items()}


def render_frame(
    project: Project,
    idx: int,
    all_params: dict[str, np.ndarray] | None = None,
    half_size: bool = False,
    max_dim: int | None = None,
    cache: bool = False,
) -> np.ndarray:
    """Render one graded frame as uint8 RGB.

    cache=True keeps the decoded linear image in memory (for live previews).
    """
    if all_params is None:
        all_params = project.frame_params()
    if cache:
        img = _load_cached(project.files[idx], half_size, max_dim)
    else:
        img = loader.load_linear(project.files[idx], half_size=half_size, max_dim=max_dim)
    return apply_adjustments(img, _params_at(all_params, idx))


def even_size(w: int, h: int, target_w: int | None) -> tuple[int, int]:
    """Output size scaled to target width, forced even for yuv420p."""
    if target_w:
        h = round(h * target_w / w)
        w = target_w
    return w - w % 2, h - h % 2


def render_sequence(project: Project, width: int | None = None, half_size: bool = False, progress=None):
    """Yield (idx, uint8 RGB frame) for the whole sequence at a uniform size."""
    all_params = project.frame_params()
    size = None
    for i in range(project.n_frames):
        frame = render_frame(project, i, all_params, half_size=half_size)
        if size is None:
            size = even_size(frame.shape[1], frame.shape[0], width)
        if (frame.shape[1], frame.shape[0]) != size:
            frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        if progress:
            progress(i + 1, project.n_frames)
        yield i, frame
