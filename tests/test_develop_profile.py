from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.project import Project  # noqa: E402


def test_jpeg_sequence_has_no_raw_develop_profile(tmp_path: Path):
    img = np.full((24, 32, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)

    project = Project.from_folder(tmp_path)

    assert project.ensure_develop_profile() is None


def test_develop_profile_is_optional_in_frame_params(tmp_path: Path):
    img = np.full((24, 32, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)
    project = Project.from_folder(tmp_path)
    project.develop_profile = {
        "version": 3,
        "exposure": 0.5,
        "contrast": 0.2,
        "saturation": 1.1,
        "highlights": -0.1,
        "shadows": 0.1,
    }

    display_params = project.frame_params(include_develop=False)
    render_params = project.frame_params(include_develop=True)

    assert display_params["exposure"][0] == 0.0
    assert render_params["exposure"][0] == 0.5
    assert render_params["contrast"][0] == 0.2
    assert render_params["saturation"][0] == 1.1
