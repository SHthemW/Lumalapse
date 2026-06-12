"""Folder cache test: opening a sequence twice must reuse the analysis stored
in <folder>/.lumalapse, and changing the sequence must invalidate the analysis
while keeping keyframes and settings.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse import analysis  # noqa: E402
from lumalapse.project import DATA_DIR_NAME, Project, default_project_path  # noqa: E402


def write_frames(folder: Path, n: int, start: int = 0):
    img = np.tile(np.linspace(40, 200, 160, dtype=np.uint8), (120, 1))
    for i in range(start, start + n):
        cv2.imwrite(str(folder / f"f{i:03d}.jpg"), img)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lumalapse_cache_"))
    calls = {"n": 0}
    real_analyze = analysis.analyze_sequence

    def counting_analyze(files, progress=None, workers=4):
        calls["n"] += 1
        return real_analyze(files, progress=progress, workers=workers)

    analysis.analyze_sequence = counting_analyze
    try:
        seq = tmp / "seq"
        seq.mkdir()
        write_frames(seq, 10)

        # First open: analyzes and persists into .lumalapse
        p1 = Project.open_folder(seq)
        assert p1.analysis is None
        p1.ensure_analysis()
        p1.set_keyframe(0, {"exposure": 0.5})
        p1.deflicker_enabled = True
        p1.save()
        assert calls["n"] == 1
        assert default_project_path(seq).exists(), "project not stored in .lumalapse"

        # Second open: everything reused, no re-analysis
        p2 = Project.open_folder(seq)
        assert p2.analysis is not None, "cached analysis not reused"
        p2.ensure_analysis()
        assert calls["n"] == 1, "second open should not re-analyze"
        assert len(p2.keyframes) == 1 and p2.deflicker_enabled

        # The .lumalapse dir itself must not be picked up as sequence content
        assert all(DATA_DIR_NAME not in f for f in p2.files)

        # Sequence changed: analysis invalidated, keyframes survive
        write_frames(seq, 2, start=10)
        p3 = Project.open_folder(seq)
        assert p3.n_frames == 12
        assert p3.analysis is None, "stale analysis must be dropped"
        assert len(p3.keyframes) == 1, "keyframes should survive a sequence change"
        p3.ensure_analysis()
        assert calls["n"] == 2
        p3.save()

        # Moved/renamed folder: filenames identical -> cache still valid
        moved = tmp / "seq_moved"
        seq.rename(moved)
        p4 = Project.open_folder(moved)
        assert p4.analysis is not None, "cache should survive a folder move"
        assert all(str(moved) in f for f in p4.files), "file paths must be refreshed"

        print("FOLDER CACHE TEST PASSED")
    finally:
        analysis.analyze_sequence = real_analyze
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
