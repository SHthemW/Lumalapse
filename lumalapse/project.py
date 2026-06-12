"""Project model: sequence + keyframes + deflicker settings, persisted as JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import analysis, loader
from .deflicker import deflicker_corrections
from .keyframes import Keyframe, interpolate_params

PROJECT_SUFFIX = ".llproj"


@dataclass
class Project:
    folder: str = ""
    files: list = field(default_factory=list)
    keyframes: list = field(default_factory=list)  # list[Keyframe]
    interp_mode: str = "smooth"                    # "smooth" | "linear"
    deflicker_enabled: bool = False
    deflicker_strength: float = 10.0
    analysis: dict | None = None                   # {"luminance": [...], "ev": [...]}
    path: str | None = None                        # where this project file lives

    # ---------- lifecycle ----------

    @staticmethod
    def from_folder(folder: str | Path) -> "Project":
        folder = str(Path(folder).resolve())
        files = loader.list_sequence(folder)
        if not files:
            raise ValueError(f"No supported images found in {folder}")
        return Project(folder=folder, files=files)

    @staticmethod
    def load(path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        proj = Project(
            folder=data["folder"],
            files=data["files"],
            keyframes=[Keyframe.from_dict(k) for k in data.get("keyframes", [])],
            interp_mode=data.get("interp_mode", "smooth"),
            deflicker_enabled=data.get("deflicker_enabled", False),
            deflicker_strength=data.get("deflicker_strength", 10.0),
            analysis=data.get("analysis"),
            path=str(path),
        )
        return proj

    def save(self, path: str | Path | None = None) -> str:
        path = Path(path or self.path or Path(self.folder) / f"project{PROJECT_SUFFIX}")
        data = {
            "folder": self.folder,
            "files": self.files,
            "keyframes": [k.to_dict() for k in self.keyframes],
            "interp_mode": self.interp_mode,
            "deflicker_enabled": self.deflicker_enabled,
            "deflicker_strength": self.deflicker_strength,
            "analysis": self.analysis,
        }
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        self.path = str(path)
        return self.path

    # ---------- analysis ----------

    @property
    def n_frames(self) -> int:
        return len(self.files)

    def ensure_analysis(self, progress=None) -> dict:
        if not self.analysis or len(self.analysis.get("luminance", [])) != self.n_frames:
            self.analysis = analysis.analyze_sequence(self.files, progress=progress)
        return self.analysis

    # ---------- keyframes ----------

    def set_keyframe(self, frame: int, params: dict) -> Keyframe:
        """Add a keyframe or update params of an existing one at `frame`."""
        for kf in self.keyframes:
            if kf.frame == frame:
                kf.params.update(params)
                return kf
        kf = Keyframe(frame=frame)
        kf.params.update(params)
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.frame)
        return kf

    def remove_keyframe(self, frame: int) -> bool:
        before = len(self.keyframes)
        self.keyframes = [k for k in self.keyframes if k.frame != frame]
        return len(self.keyframes) != before

    def get_keyframe(self, frame: int) -> Keyframe | None:
        return next((k for k in self.keyframes if k.frame == frame), None)

    # ---------- effective per-frame parameters ----------

    def frame_params(self) -> dict[str, np.ndarray]:
        """Interpolated params for every frame, with deflicker folded into exposure."""
        params = interpolate_params(self.keyframes, self.n_frames, mode=self.interp_mode)
        if self.deflicker_enabled and self.n_frames > 1:
            lum = self.ensure_analysis()["luminance"]
            corr = deflicker_corrections(lum, params["exposure"], strength=self.deflicker_strength)
            params["exposure"] = params["exposure"] + corr
        return params
