"""Project model: sequence + keyframes + deflicker settings, persisted as JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import analysis, loader
from .deflicker import deflicker_corrections
from .develop import apply_profile, estimate_camera_profile, needs_profile
from .keyframes import Keyframe, interpolate_params

PROJECT_SUFFIX = ".llproj"
DATA_DIR_NAME = ".lumalapse"


def default_project_path(folder: str | Path) -> Path:
    """Where a sequence folder's project data lives: <folder>/.lumalapse/project.llproj"""
    return Path(folder) / DATA_DIR_NAME / f"project{PROJECT_SUFFIX}"


@dataclass
class Project:
    folder: str = ""
    files: list = field(default_factory=list)
    keyframes: list = field(default_factory=list)  # list[Keyframe]
    interp_mode: str = "smooth"                    # "smooth" | "linear"
    engine: str = "builtin"                        # rendering engine, see lumalapse.engines
    acceleration: str = "auto"                     # "auto" | "off"
    deflicker_enabled: bool = False
    deflicker_strength: float = 10.0
    develop_profile_enabled: bool = False
    develop_profile: dict | None = None
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
    def open_folder(folder: str | Path) -> "Project":
        """Open a sequence folder, reusing data stored in <folder>/.lumalapse.

        If the folder was opened before and its image files are unchanged
        (compared by filename, so a moved/renamed folder still matches), the
        cached analysis, keyframes and settings are reused. If the sequence
        changed, keyframes and settings are kept but the stale analysis is
        dropped so it gets recomputed.
        """
        fresh = Project.from_folder(folder)
        cached_path = default_project_path(fresh.folder)
        if not cached_path.exists():
            return fresh
        try:
            proj = Project.load(cached_path)
        except (json.JSONDecodeError, KeyError, OSError):
            return fresh

        same_files = [Path(f).name for f in proj.files] == [Path(f).name for f in fresh.files]
        proj.folder, proj.files = fresh.folder, fresh.files
        if not same_files:
            proj.analysis = None
        proj.path = str(cached_path)
        return proj

    @staticmethod
    def load(path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        proj = Project(
            folder=data["folder"],
            files=data["files"],
            keyframes=[Keyframe.from_dict(k) for k in data.get("keyframes", [])],
            interp_mode=data.get("interp_mode", "smooth"),
            engine=data.get("engine", "builtin"),
            acceleration=data.get("acceleration", "auto"),
            deflicker_enabled=data.get("deflicker_enabled", False),
            deflicker_strength=data.get("deflicker_strength", 10.0),
            develop_profile_enabled=data.get("develop_profile_enabled", False),
            develop_profile=data.get("develop_profile"),
            analysis=data.get("analysis"),
            path=str(path),
        )
        return proj

    def save(self, path: str | Path | None = None) -> str:
        path = Path(path or self.path or default_project_path(self.folder))
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "folder": self.folder,
            "files": self.files,
            "keyframes": [k.to_dict() for k in self.keyframes],
            "interp_mode": self.interp_mode,
            "engine": self.engine,
            "acceleration": self.acceleration,
            "deflicker_enabled": self.deflicker_enabled,
            "deflicker_strength": self.deflicker_strength,
            "develop_profile_enabled": self.develop_profile_enabled,
            "develop_profile": self.develop_profile,
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

    def ensure_develop_profile(self, enabled: bool | None = None) -> dict | None:
        if enabled is None:
            enabled = self.develop_profile_enabled
        if not enabled:
            return self.develop_profile
        if needs_profile(self.files, self.develop_profile):
            self.develop_profile = estimate_camera_profile(self.files)
        return self.develop_profile

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

    def frame_params(self, include_develop: bool | None = None) -> dict[str, np.ndarray]:
        """Interpolated params for every frame, with deflicker folded into exposure."""
        params = interpolate_params(self.keyframes, self.n_frames, mode=self.interp_mode)
        if self.deflicker_enabled and self.n_frames > 1:
            lum = self.ensure_analysis()["luminance"]
            corr = deflicker_corrections(lum, params["exposure"], strength=self.deflicker_strength)
            params["exposure"] = params["exposure"] + corr
        if include_develop is None:
            include_develop = self.develop_profile_enabled
        if include_develop:
            params = apply_profile(params, self.develop_profile)
        return params
