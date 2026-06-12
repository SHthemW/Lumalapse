"""End-to-end smoke test on a synthetic flickering sequence (JPEG stand-ins for RAW).

Generates a gradient scene with a slow exposure ramp plus strong random flicker,
then runs analyze -> keyframes -> deflicker -> export and verifies:
  1. the video file is produced and non-trivial in size
  2. deflicker reduces high-frequency luminance noise by a large factor
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smoothlapse import analysis, loader  # noqa: E402
from smoothlapse.deflicker import deflicker_corrections  # noqa: E402
from smoothlapse.export import export_video  # noqa: E402
from smoothlapse.project import Project  # noqa: E402

N_FRAMES = 40
RNG = np.random.default_rng(42)


def make_sequence(folder: Path) -> np.ndarray:
    """Write N_FRAMES JPEGs; returns the per-frame flicker EV that was injected."""
    h, w = 240, 320
    yy, xx = np.mgrid[0:h, 0:w]
    scene = (0.15 + 0.6 * xx / w + 0.15 * yy / h).astype(np.float32)
    scene = np.dstack([scene * 0.9, scene, scene * 1.1])

    flicker = RNG.normal(0.0, 0.25, N_FRAMES)  # ±0.25 EV random flicker
    ramp = np.linspace(0.0, 1.0, N_FRAMES)     # slow 1 EV brightening (intentional)
    for i in range(N_FRAMES):
        linear = np.clip(scene * 2.0 ** (ramp[i] + flicker[i]), 0, 1)
        srgb = (loader.linear_to_srgb(linear) * 255).astype(np.uint8)
        cv2.imwrite(str(folder / f"frame_{i:04d}.jpg"), srgb[:, :, ::-1],
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
    return flicker


def hf_noise(curve: np.ndarray) -> float:
    """High-frequency energy: std of second difference."""
    return float(np.std(np.diff(curve, 2)))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoothlapse_test_"))
    try:
        seq_dir = tmp / "seq"
        seq_dir.mkdir()
        make_sequence(seq_dir)

        # analyze
        proj = Project.from_folder(seq_dir)
        assert proj.n_frames == N_FRAMES, proj.n_frames
        proj.ensure_analysis()
        lum = np.asarray(proj.analysis["luminance"])
        assert hf_noise(lum) > 0.1, "synthetic flicker missing from analysis"

        # keyframes: grade a ramp on top
        proj.set_keyframe(0, {"exposure": 0.3, "saturation": 1.2, "dehaze": 0.2})
        proj.set_keyframe(N_FRAMES - 1, {"exposure": -0.3, "saturation": 0.9})
        assert len(proj.keyframes) == 2

        # deflicker
        proj.deflicker_enabled = True
        proj.deflicker_strength = 6.0
        params = proj.frame_params()
        residual = lum + params["exposure"]
        reduction = hf_noise(lum) / max(hf_noise(residual), 1e-9)
        print(f"flicker HF noise: raw={hf_noise(lum):.4f} deflickered={hf_noise(residual):.4f} "
              f"({reduction:.1f}x reduction)")
        assert reduction > 3, f"deflicker too weak: {reduction:.2f}x"

        # save/load round-trip
        saved = proj.save()
        proj2 = Project.load(saved)
        assert len(proj2.keyframes) == 2 and proj2.deflicker_enabled

        # export
        out = export_video(proj2, tmp / "out.mp4", fps=12, width=320)
        size = Path(out).stat().st_size
        print(f"video: {out} ({size} bytes)")
        assert size > 10_000, "suspiciously small video"

        print("ALL TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
