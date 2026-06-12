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

from lumalapse.engines import rawtherapee as rt  # noqa: E402
from lumalapse.engines.rawtherapee import (RawTherapeeEngine, build_pp3, find_adobe_dcp,  # noqa: E402
                                           find_cli)


def test_pp3():
    pp3 = build_pp3({"exposure": 1.5, "contrast": 0.2, "saturation": 1.3,
                     "dehaze": 0.4, "temperature": 0.5, "highlights": -0.5,
                     "shadows": 0.3, "whites": 0.2, "blacks": 0.0})
    assert "Compensation=1.5000" in pp3
    assert "Contrast=20" in pp3
    assert "Saturation=30" in pp3
    assert "[Dehaze]" in pp3 and "Strength=40" in pp3
    assert "Temperature=6250" in pp3
    assert "Curve=1;" in pp3, "whites must still produce a custom curve"
    assert "Method=Coloropp" in pp3
    # Recovery directions ride the local Shadows&Highlights tool (PV2012-like).
    assert "[Shadows & Highlights]" in pp3
    assert "Highlights=50" in pp3 and "Shadows=30" in pp3
    assert "[PostDemosaicSharpening]" in pp3, "capture sharpening default missing"

    # Boost directions stay on the curve, no S&H section.
    boost = build_pp3({"highlights": 0.5, "shadows": -0.3})
    assert "[Shadows & Highlights]" not in boost and "Curve=1;" in boost

    neutral = build_pp3({})
    assert "Curve=0;" in neutral and "[Dehaze]" not in neutral
    assert "[Shadows & Highlights]" not in neutral
    print("PP3 generation OK")


def test_adobe_dcp():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        profiles = Path(tmp) / "CameraProfiles" / "Adobe Standard"
        profiles.mkdir(parents=True)
        (profiles / "Nikon D850 Adobe Standard.dcp").write_bytes(b"x")
        old_dirs = rt.ADOBE_PROFILE_DIRS
        rt.ADOBE_PROFILE_DIRS = [Path(tmp) / "CameraProfiles"]
        rt._adobe_dcp_cache.clear()
        try:
            hit = find_adobe_dcp("NIKON D850")
            assert hit and hit.endswith("Nikon D850 Adobe Standard.dcp")
            assert find_adobe_dcp("NIKON D4") is None
            assert find_adobe_dcp(None) is None
            # An Adobe DCP must land in the PP3 InputProfile.
            pp3 = build_pp3({}, dcp_path=hit)
            assert "InputProfile=file:" in pp3 and "Nikon%20D850" not in pp3
            assert Path(hit).as_posix() in pp3
        finally:
            rt.ADOBE_PROFILE_DIRS = old_dirs
            rt._adobe_dcp_cache.clear()
    print("Adobe DCP discovery OK")


def test_dcp():
    import os

    pp3 = build_pp3({})
    assert "[Color Management]" in pp3
    assert "InputProfile=(cameraICC)" in pp3, "auto camera DCP must be default"
    assert "ApplyLookTable=true" in pp3 and "ToneCurve=true" in pp3

    assert "[Color Management]" not in build_pp3({}, color_managed=False)

    # Env override forces an explicit .dcp file.
    fake = Path(__file__).resolve()  # any existing file
    os.environ["LUMALAPSE_DCP"] = str(fake)
    try:
        # forward slashes: backslashes are escape characters in PP3/GKeyFile
        assert f"InputProfile=file:{fake.as_posix()}" in build_pp3({})
    finally:
        del os.environ["LUMALAPSE_DCP"]
    os.environ["LUMALAPSE_DCP"] = r"C:\does\not\exist.dcp"
    try:
        assert "InputProfile=(cameraICC)" in build_pp3({}), "missing file must fall back"
    finally:
        del os.environ["LUMALAPSE_DCP"]
    print("DCP profile selection OK")


def test_render(image: str):
    import os

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

    # Local highlight recovery / shadow lift via RT's Shadows&Highlights.
    # Push exposure +2 EV first so the (dark) test image actually has
    # highlights to recover; compare against the same push without S&H.
    # Any effect at all also validates the PP3 section keys against this RT
    # build - unknown sections are silently ignored (diff would be ~0).
    pushed = eng.render(image, {"exposure": 2.0}, max_dim=480).mean(axis=2)
    bright = pushed >= np.percentile(pushed, 75)
    dark = pushed <= np.percentile(pushed, 25)

    rec = eng.render(image, {"exposure": 2.0, "highlights": -1.0}, max_dim=480).mean(axis=2)
    d_bright = float(rec[bright].mean() - pushed[bright].mean())
    d_dark = float(rec[dark].mean() - pushed[dark].mean())
    print(f"highlights=-1: bright quartile {d_bright:+.2f}, dark quartile {d_dark:+.2f}")
    assert d_bright < -2.0, "S&H highlight recovery had no effect (wrong PP3 keys?)"
    assert d_bright < d_dark - 1.0, "recovery must hit highlights harder than shadows"

    lift = eng.render(image, {"exposure": 2.0, "shadows": 1.0}, max_dim=480).mean(axis=2)
    d_dark2 = float(lift[dark].mean() - pushed[dark].mean())
    d_bright2 = float(lift[bright].mean() - pushed[bright].mean())
    print(f"shadows=+1: dark quartile {d_dark2:+.2f}, bright quartile {d_bright2:+.2f}")
    assert d_dark2 > 1.0, "S&H shadow lift had no effect"
    assert d_dark2 > d_bright2 + 0.5, "lift must hit shadows harder than highlights"

    # Forcing a bundled DCP must change the rendered colors vs auto-match.
    dcp_dir = Path(eng.cli).parent / "dcpprofiles"
    candidates = sorted(dcp_dir.glob("*.dcp")) if dcp_dir.is_dir() else []
    if candidates:
        os.environ["LUMALAPSE_DCP"] = str(candidates[0])
        try:
            forced = eng.render(image, {}, max_dim=480)
        finally:
            del os.environ["LUMALAPSE_DCP"]
        diff = np.abs(forced.astype(int) - base.astype(int)).mean()
        print(f"forced DCP ({candidates[0].name}) vs auto: mean diff {diff:.2f}")
        assert diff > 0.5, "explicit DCP must actually affect colors"
    else:
        print("no bundled DCPs found - forced-DCP check skipped")


if __name__ == "__main__":
    test_pp3()
    test_dcp()
    test_adobe_dcp()
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
