"""Keyframes and per-frame parameter interpolation."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Editable parameters and their defaults / ranges (used by GUI and CLI validation).
PARAM_DEFAULTS = {
    "exposure": 0.0,    # EV offset
    "saturation": 1.0,  # 0 = grayscale, 1 = unchanged
    "dehaze": 0.0,      # 0..1 strength of dark-channel dehaze
    "contrast": 0.0,    # -1..1 s-curve strength
    "temperature": 0.0, # -1..1 cool..warm shift
}
PARAM_RANGES = {
    "exposure": (-5.0, 5.0),
    "saturation": (0.0, 3.0),
    "dehaze": (0.0, 1.0),
    "contrast": (-1.0, 1.0),
    "temperature": (-1.0, 1.0),
}


@dataclass
class Keyframe:
    frame: int
    params: dict = field(default_factory=lambda: dict(PARAM_DEFAULTS))

    def to_dict(self) -> dict:
        return {"frame": self.frame, "params": dict(self.params)}

    @staticmethod
    def from_dict(d: dict) -> "Keyframe":
        params = dict(PARAM_DEFAULTS)
        params.update(d.get("params", {}))
        return Keyframe(frame=int(d["frame"]), params=params)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    """Cosine ease-in/out: keeps keyframe values exact, removes velocity jumps."""
    return (1.0 - np.cos(np.pi * t)) / 2.0


def interpolate_params(keyframes: list[Keyframe], n_frames: int, mode: str = "smooth") -> dict[str, np.ndarray]:
    """Interpolate keyframe parameters over the whole sequence.

    Frames before the first / after the last keyframe hold its values.
    Returns {param_name: array of length n_frames}.
    """
    out = {p: np.full(n_frames, PARAM_DEFAULTS[p], dtype=np.float64) for p in PARAM_DEFAULTS}
    if not keyframes or n_frames == 0:
        return out

    kfs = sorted(keyframes, key=lambda k: k.frame)
    xs = np.array([min(max(k.frame, 0), n_frames - 1) for k in kfs], dtype=np.float64)
    frames = np.arange(n_frames, dtype=np.float64)

    for p in PARAM_DEFAULTS:
        ys = np.array([k.params.get(p, PARAM_DEFAULTS[p]) for k in kfs], dtype=np.float64)
        if len(kfs) == 1 or mode == "linear":
            out[p] = np.interp(frames, xs, ys)
            continue
        # Smooth: cosine-eased segment-wise interpolation.
        vals = np.empty(n_frames, dtype=np.float64)
        vals[: int(xs[0]) + 1] = ys[0]
        vals[int(xs[-1]):] = ys[-1]
        for a in range(len(kfs) - 1):
            x0, x1 = int(xs[a]), int(xs[a + 1])
            if x1 <= x0:
                continue
            t = (np.arange(x0, x1 + 1) - x0) / (x1 - x0)
            vals[x0: x1 + 1] = ys[a] + (ys[a + 1] - ys[a]) * _smoothstep(t)
        out[p] = vals
    return out
