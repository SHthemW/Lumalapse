"""Frames-first workflow test: develop to a JPG sequence, then assemble video.

Also exercises non-ASCII (Chinese) output paths, matching the unicode-safe
read path already in loader.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse import loader  # noqa: E402
from lumalapse.export import assemble_video, export_frames  # noqa: E402
from lumalapse.project import Project  # noqa: E402


def make_demo_frames(folder: Path, n: int = 12):
    import cv2

    rng = np.random.default_rng(3)
    h, w = 120, 160
    yy, xx = np.mgrid[0:h, 0:w]
    scene = (0.2 + 0.5 * xx / w + 0.2 * yy / h).astype(np.float32)
    for i in range(n):
        img = np.clip(scene * 2 ** rng.normal(0, 0.15), 0, 1)
        ok, buf = cv2.imencode(".jpg", (img * 255).astype("uint8"))
        assert ok
        buf.tofile(str(folder / f"f{i:03d}.jpg"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lumalapse_frames_"))
    try:
        seq = tmp / "测试序列"
        seq.mkdir()
        make_demo_frames(seq)
        proj = Project.from_folder(seq)
        proj.ensure_analysis()
        proj.set_keyframe(0, {"exposure": 0.4, "saturation": 1.2})
        proj.deflicker_enabled = True

        # Develop to JPG stills (Chinese dir name on purpose).
        frames_dir = Path(export_frames(proj, tmp / "冲洗输出", fmt="jpg", quality=95))
        jpgs = sorted(frames_dir.glob("*.jpg"))
        assert len(jpgs) == proj.n_frames, f"expected {proj.n_frames} stills, got {len(jpgs)}"
        first = loader.load_linear(jpgs[0])
        assert first.shape[2] == 3 and first.mean() > 0.05, "developed still unreadable/black"

        # The grade must actually be baked into the stills (+0.4 EV brightens).
        # Sequence-wide averages: per-frame deflicker corrections and highlight
        # clipping make single-frame comparisons noisy.
        dev_mean = np.mean([loader.load_linear(p).mean() for p in jpgs])
        src_mean = np.mean([loader.load_linear(p).mean() for p in proj.files])
        assert dev_mean > src_mean * 1.1, \
            f"exposure grade missing from developed JPGs ({src_mean:.3f} -> {dev_mean:.3f})"

        # Assemble the stills into a video.
        out = assemble_video(frames_dir, tmp / "合成" / "out.mp4", fps=12)
        size = Path(out).stat().st_size
        print(f"stills: {len(jpgs)}, video: {size} bytes")
        assert size > 2_000  # 12 deflickered gradient frames compress very well

        # TIFF format also supported.
        tif_dir = Path(export_frames(proj, tmp / "tif_out", fmt="tif"))
        assert len(list(tif_dir.glob("*.tif"))) == proj.n_frames

        print("FRAMES WORKFLOW TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
