"""RawTherapee engine test.

Unit-checks the PP3 generation, then (if rawtherapee-cli and a test image are
available) renders through RawTherapee and verifies parameters take effect.

Usage: python test_rt_engine.py [image_file]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.engines.rawtherapee import RawTherapeeEngine, build_pp3, find_cli  # noqa: E402


def test_pp3():
    pp3 = build_pp3({"exposure": 1.5, "contrast": 0.2, "saturation": 1.3,
                     "dehaze": 0.4, "temperature": 0.5, "highlights": -0.5,
                     "shadows": 0.3, "whites": 0.0, "blacks": 0.0})
    assert "Compensation=1.5000" in pp3
    assert "Contrast=20" in pp3
    assert "Saturation=30" in pp3
    assert "[Dehaze]" in pp3 and "Strength=40" in pp3
    assert "Temperature=6250" in pp3
    assert "Curve=1;" in pp3, "tone params must produce a custom curve"
    assert "HistogramMatching=false" in pp3
    assert "Method=Coloropp" in pp3
    assert "[Directional Pyramid Denoising]" in pp3
    assert "[LensProfile]" in pp3 and "LcMode=lfauto" in pp3
    assert "[Color Management]" in pp3 and "ApplyLookTable=true" in pp3
    assert "[PostDemosaicSharpening]" in pp3
    assert "[Sharpening]" in pp3
    assert "[RAW]" in pp3 and "CA=true" in pp3

    neutral = build_pp3({})
    assert "Curve=0;" in neutral and "[Dehaze]" not in neutral
    matched = build_pp3({"_histogram_matching": 1.0})
    assert "HistogramMatching=true" in matched
    print("PP3 generation OK")


def test_render(image: str):
    eng = RawTherapeeEngine()
    base = eng.render(image, {}, max_dim=480)
    plus1 = eng.render(image, {"exposure": 1.0}, max_dim=480)
    sat0 = eng.render(image, {"saturation": 0.0}, max_dim=480)

    assert base.dtype == np.uint8 and base.ndim == 3
    b0, b1 = float(base.mean()), float(plus1.mean())
    print(f"render OK: {base.shape}, mean {b0:.1f} -> +1EV {b1:.1f}")
    assert b1 > b0 * 1.3, "exposure +1EV must brighten the RT render"

    chroma = np.abs(np.diff(sat0.astype(int), axis=2)).mean()
    print(f"saturation=0 residual chroma: {chroma:.2f}")
    assert chroma < 3.0, "saturation=0 must desaturate the RT render"


if __name__ == "__main__":
    test_pp3()
    cli = find_cli()
    if not cli:
        print("rawtherapee-cli not found - render checks SKIPPED")
        sys.exit(0)
    print(f"using {cli}")
    if len(sys.argv) > 1:
        test_render(sys.argv[1])
        print("RT ENGINE TESTS PASSED")
    else:
        print("no test image given - render checks SKIPPED")
