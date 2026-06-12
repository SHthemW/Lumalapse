"""Holy-grail compensation test.

Simulates a day-to-night shoot: the scene darkens continuously while the camera
steps its shutter every 10 frames (EV drops 1 stop -> rendered brightness jumps
+1 EV). Holy-grail compensation must cancel the jumps without flattening the
scene's own gradual ramp, and must survive missing EXIF entries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.deflicker import holy_grail_corrections  # noqa: E402
from lumalapse.project import Project  # noqa: E402

N = 40


def build_curves():
    """Per-frame camera EV (sawtooth steps) and resulting image log-luminance."""
    scene = np.linspace(0.0, -4.0, N)            # scene darkens 4 stops
    ev = np.full(N, 10.0)
    for step, start in enumerate(range(10, N, 10), 1):
        ev[start:] -= 1.0                        # camera opens up 1 stop
    # Rendered brightness: scene plus what the camera exposure gives back.
    lum = scene + (ev[0] - ev)
    return ev, lum


def hf_noise(curve: np.ndarray) -> float:
    return float(np.std(np.diff(curve, 2)))


def main():
    ev, lum = build_curves()

    comp = holy_grail_corrections(ev, strength=6.0)
    fixed = lum + comp
    assert hf_noise(fixed) < hf_noise(lum) * 0.2, \
        f"steps not neutralized: {hf_noise(lum):.3f} -> {hf_noise(fixed):.3f}"
    # The slow trend must survive: the camera compensated 3 of the scene's
    # 4 stops, so the rendered output legitimately declines ~1 EV overall.
    net = fixed[0] - fixed[-1]
    assert 0.5 < net < 1.5, f"trend distorted: net decline {net:.2f} EV (expected ~1)"
    # And the decline must now be smooth: largest frame-to-frame step stays
    # far below the 1 EV camera jumps in the raw curve.
    assert np.abs(np.diff(fixed)).max() < 0.3, "visible step survived"
    # (jump = +1 EV camera step minus the scene's own ~0.1 EV per-frame decline)
    assert np.abs(np.diff(lum)).max() > 0.8, "test premise: raw curve has ~1 EV jumps"

    # Missing EXIF entries are interpolated.
    ev_gaps = [None if i % 7 == 3 else float(v) for i, v in enumerate(ev)]
    comp_gaps = holy_grail_corrections(ev_gaps, strength=6.0)
    assert np.all(np.isfinite(comp_gaps))
    assert np.abs(comp_gaps - comp).max() < 0.6, "gap interpolation diverged"

    # No EXIF at all -> zeros (no-op).
    assert not holy_grail_corrections([None] * N).any()

    # Through the Project pipeline, combined with deflicker.
    proj = Project(folder=".", files=[f"f{i}.jpg" for i in range(N)])
    proj.analysis = {"luminance": list(lum), "ev": list(ev)}
    assert proj.has_exif_ev()
    proj.holy_grail_enabled = True
    proj.deflicker_enabled = True
    proj.deflicker_strength = 6.0
    rendered = lum + proj.frame_params()["exposure"]
    assert hf_noise(rendered) < hf_noise(lum) * 0.1
    print(f"steps HF noise: raw={hf_noise(lum):.4f} holygrail={hf_noise(fixed):.4f} "
          f"+deflicker={hf_noise(rendered):.4f}")

    # Round-trip persistence.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "p.llproj"
        proj.save(p)
        assert Project.load(p).holy_grail_enabled
    print("HOLY GRAIL TESTS PASSED")


if __name__ == "__main__":
    main()
