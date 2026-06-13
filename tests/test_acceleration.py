from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.acceleration import apply_acceleration, detect_gpu, normalize_mode, status_text  # noqa: E402
from lumalapse.export import export_video  # noqa: E402
from lumalapse.project import Project  # noqa: E402


def test_acceleration_helpers_are_stable():
    info = detect_gpu()

    assert normalize_mode("bad") == "auto"
    assert isinstance(info["available"], bool)
    assert status_text("auto")

    off = apply_acceleration("off")
    assert off["mode"] == "off"
    assert not cv2.ocl.useOpenCL()


def test_project_persists_acceleration(tmp_path: Path):
    img = np.full((16, 16, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)

    project = Project.from_folder(tmp_path)
    project.acceleration = "off"
    saved = project.save()

    loaded = Project.load(saved)

    assert loaded.acceleration == "off"


def test_export_accepts_acceleration_override(tmp_path: Path):
    img = np.full((16, 16, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)
    project = Project.from_folder(tmp_path)

    out = export_video(project, tmp_path / "out.mp4", fps=1, width=16, acceleration="off")

    assert Path(out).exists()
    assert project.acceleration == "off"
