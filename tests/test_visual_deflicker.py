"""Visual deflicker test.

The analytic deflicker corrects with linear-light gains, which exactly cancels
flicker that *is* a linear gain — but real-world flicker often isn't (camera
JPEG tone curves, gamma-domain brightness wobble, WB drift). Here flicker is
injected in the sRGB domain, so the analytic correction leaves a residual,
while the iterative visual deflicker (which measures the developed output)
must converge well below it.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse import loader  # noqa: E402
from lumalapse.project import Project  # noqa: E402
from lumalapse.render import compute_visual_deflicker, measure_rendered_luminance  # noqa: E402

N = 30
RNG = np.random.default_rng(7)


def make_sequence(folder: Path):
    h, w = 120, 160
    yy, xx = np.mgrid[0:h, 0:w]
    scene = (0.10 + 0.55 * xx / w + 0.15 * yy / h).astype(np.float32)
    scene = np.dstack([scene * 0.95, scene, scene * 1.05])
    base_srgb = loader.linear_to_srgb(np.clip(scene, 0, 1))
    flicker = RNG.normal(0.0, 1.0, N)
    for i in range(N):
        # Additive brightness wobble (e.g. in-camera tone-curve hunting):
        # no single linear-light gain reproduces it, so the analytic
        # gain-based correction is structurally wrong for it.
        srgb = np.clip(base_srgb + 0.06 * flicker[i], 0, 1)
        cv2.imwrite(str(folder / f"f{i:03d}.jpg"), (srgb * 255).astype(np.uint8)[:, :, ::-1],
                    [cv2.IMWRITE_JPEG_QUALITY, 95])


def hf_noise(curve: np.ndarray) -> float:
    return float(np.std(np.diff(curve, 2)))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="lumalapse_vdf_"))
    try:
        seq = tmp / "seq"
        seq.mkdir()
        make_sequence(seq)
        proj = Project.from_folder(seq)
        proj.ensure_analysis()
        # Mild grade on top; the sRGB-domain flicker is what defeats the
        # linear-gain analytic correction.
        proj.set_keyframe(0, {"exposure": 0.3, "contrast": 0.4})
        proj.deflicker_enabled = True
        proj.deflicker_strength = 6.0

        analytic = measure_rendered_luminance(proj, max_dim=160)
        hf_analytic = hf_noise(analytic)

        compute_visual_deflicker(proj, passes=3, max_dim=160)
        assert proj.visual_deflicker and len(proj.visual_deflicker) == N
        visual = measure_rendered_luminance(proj, max_dim=160)
        hf_visual = hf_noise(visual)

        print(f"residual HF flicker: analytic={hf_analytic:.4f} visual={hf_visual:.4f} "
              f"({hf_analytic / max(hf_visual, 1e-9):.1f}x better)")
        assert hf_visual < hf_analytic * 0.5, "visual deflicker must beat analytic on non-linear pipeline"

        # Persistence round-trip: frame_params exposure must be exactly the
        # keyframe value (0.3 everywhere) plus the baked visual corrections —
        # the analytic path must NOT run on top of them.
        saved = proj.save()
        proj2 = Project.load(saved)
        assert proj2.visual_deflicker is not None
        exp = proj2.frame_params()["exposure"]
        assert np.allclose(exp, 0.3 + np.asarray(proj2.visual_deflicker)), \
            "frame_params must use baked visual corrections verbatim"
        print("VISUAL DEFLICKER TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
