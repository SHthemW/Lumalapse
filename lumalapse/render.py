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


def measure_rendered_luminance(project: Project, max_dim: int = 360,
                               all_params: dict | None = None, progress=None) -> np.ndarray:
    """Mean log2 luminance of every frame as actually rendered by the engine.

    Unlike the analysis curve (measured on undeveloped linear data), this sees
    the full pipeline output — tone curves, dehaze, engine color science — so
    it stays valid even when the pipeline is non-linear.
    """
    from .loader import srgb_to_linear

    engine = get_engine(project.engine)
    if all_params is None:
        all_params = project.frame_params()
    luma_w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    n = project.n_frames
    measured = np.zeros(n)
    done = 0

    def job(i: int) -> tuple[int, float]:
        frame = engine.render(project.files[i], _params_at(all_params, i),
                              half_size=True, max_dim=max_dim)
        linear = srgb_to_linear(frame.astype(np.float32) / 255.0)
        mean_luma = float((linear @ luma_w).mean())
        return i, np.log2(max(mean_luma, 1e-5))

    jobs = max(1, getattr(engine, "parallel_jobs", 1))
    with ThreadPoolExecutor(max_workers=max(jobs, 4)) as pool:
        for i, value in pool.map(job, range(n)):
            measured[i] = value
            done += 1
            if progress:
                progress(done, n)
    return measured


def compute_visual_deflicker(project: Project, passes: int = 2, max_dim: int = 360,
                             progress=None, damping: float = 0.8) -> np.ndarray:
    """Iterative "visual" deflicker (LRTimelapse-style), engine-agnostic.

    Renders small previews of the fully developed frames, measures their
    luminance, and folds the smoothed-vs-measured difference back into the
    per-frame exposure corrections. Iterating absorbs any non-linearity in
    the pipeline (tone curves, dehaze, RawTherapee's curve) that the analytic
    single-pass deflicker cannot account for.

    Stores the result in project.visual_deflicker (which frame_params then
    uses instead of the analytic correction) and returns it. Re-run after
    changing keyframes — like LRTimelapse, corrections are a baked pass.
    """
    n = project.n_frames
    corrections = np.zeros(n)
    total = passes * n
    project.deflicker_enabled = True  # frame_params must apply the in-progress corrections
    for p in range(passes):
        project.visual_deflicker = corrections.tolist()
        offset = p * n
        measured = measure_rendered_luminance(
            project, max_dim=max_dim,
            progress=(lambda d, t: progress(offset + d, total)) if progress else None)
        from .deflicker import gaussian_smooth

        target = gaussian_smooth(measured, sigma=project.deflicker_strength)
        # Damped update: content-adaptive ops (dehaze's atmospheric-light pick)
        # can respond discontinuously to tiny exposure changes; full-step
        # updates would chase those jumps instead of converging.
        corrections += damping * (target - measured)
    project.visual_deflicker = corrections.tolist()
    return corrections


def even_size(w: int, h: int, target_w: int | None) -> tuple[int, int]:
    """Output size scaled to target width, forced even for yuv420p."""
    if target_w:
        h = round(h * target_w / w)
        w = target_w
    return w - w % 2, h - h % 2


def render_sequence(project: Project, width: int | None = None, half_size: bool = False, progress=None):
    """Yield (idx, uint8 RGB frame) for the whole sequence at a uniform size.

    Engines that spawn external processes (RawTherapee) render several frames
    concurrently; frames are still yielded in order.
    """
    all_params = project.frame_params()
    engine = get_engine(project.engine)
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
