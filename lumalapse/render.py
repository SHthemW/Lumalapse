"""Frame rendering: dispatch to the project's engine, uniform sizing for export."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from .engines import get_engine
from .project import Project


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
    """Render one graded frame as uint8 RGB with the project's engine.

    cache=True lets the engine keep decoded data in memory (live previews).
    """
    if all_params is None:
        all_params = project.frame_params()
    engine = get_engine(project.engine)
    return engine.render(project.files[idx], _params_at(all_params, idx),
                         half_size=half_size, max_dim=max_dim, cache=cache)


def even_size(w: int, h: int, target_w: int | None) -> tuple[int, int]:
    """Output size scaled to target width, forced even for yuv420p."""
    if target_w:
        h = round(h * target_w / w)
        w = target_w
    return w - w % 2, h - h % 2


def render_sequence(
    project: Project,
    width: int | None = None,
    half_size: bool = False,
    progress=None,
    engine_name: str | None = None,
):
    """Yield (idx, uint8 RGB frame) for the whole sequence at a uniform size.

    Engines that spawn external processes (RawTherapee) render several frames
    concurrently; frames are still yielded in order.
    """
    all_params = project.frame_params()
    engine = get_engine(engine_name or project.engine)
    jobs = max(1, getattr(engine, "parallel_jobs", 1))
    size = None

    def finalize(idx: int, frame: np.ndarray):
        nonlocal size
        if size is None:
            size = even_size(frame.shape[1], frame.shape[0], width)
        if (frame.shape[1], frame.shape[0]) != size:
            frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        if progress:
            progress(idx + 1, project.n_frames)
        return idx, frame

    def job(i: int) -> np.ndarray:
        return engine.render(project.files[i], _params_at(all_params, i), half_size=half_size)

    if jobs == 1:
        for i in range(project.n_frames):
            yield finalize(i, job(i))
        return

    # Bounded look-ahead keeps at most ~2*jobs rendered frames in memory.
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = deque()
        next_submit = 0
        while next_submit < project.n_frames or pending:
            while next_submit < project.n_frames and len(pending) < jobs * 2:
                pending.append((next_submit, pool.submit(job, next_submit)))
                next_submit += 1
            i, fut = pending.popleft()
            yield finalize(i, fut.result())
