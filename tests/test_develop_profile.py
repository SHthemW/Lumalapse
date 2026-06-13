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


def test_develop_profile_disabled_by_default(tmp_path: Path):
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

    params = project.frame_params()

    assert project.develop_profile_enabled is False
    assert params["exposure"][0] == 0.0
    assert params["contrast"][0] == 0.0


def test_develop_profile_can_be_enabled_and_persisted(tmp_path: Path):
    img = np.full((24, 32, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)
    project = Project.from_folder(tmp_path)
    project.develop_profile_enabled = True
    project.develop_profile = {
        "version": 3,
        "exposure": 0.5,
        "contrast": 0.2,
        "saturation": 1.1,
        "highlights": -0.1,
        "shadows": 0.1,
    }

    params = project.frame_params()
    saved = project.save()
    loaded = Project.load(saved)

    assert params["exposure"][0] == 0.5
    assert params["contrast"][0] == 0.2
    assert loaded.develop_profile_enabled is True


def test_load_legacy_project_without_develop_flag(tmp_path: Path):
    img = np.full((24, 32, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "frame_0001.jpg"), img)
    project = Project.from_folder(tmp_path)
    path = project.save()

    data = Path(path).read_text(encoding="utf-8")
    data = data.replace('"develop_profile_enabled": false,\n', '')
    Path(path).write_text(data, encoding="utf-8")

    loaded = Project.load(path)

    assert loaded.develop_profile_enabled is False
