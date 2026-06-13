"""RawTherapee PP3 sidecar round-trip tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.engines.rawtherapee_profile import read_pp3_params, save_pp3


def test_pp3_round_trip(tmp_path: Path):
    source = tmp_path / "frame.NEF"
    source.write_bytes(b"raw")

    params = {
        "exposure": 1.25,
        "contrast": -0.3,
        "saturation": 1.4,
        "highlights": 0.5,
        "shadows": -0.25,
        "whites": 0.2,
        "blacks": -0.1,
        "dehaze": 0.6,
        "temperature": -0.4,
    }

    path = save_pp3(source, params)
    assert path == source.with_suffix(source.suffix + ".pp3")

    loaded = read_pp3_params(source)
    assert loaded is not None
    assert loaded["exposure"] == params["exposure"]
    assert loaded["contrast"] == params["contrast"]
    assert loaded["saturation"] == params["saturation"]
    assert loaded["dehaze"] == params["dehaze"]
    assert loaded["temperature"] == params["temperature"]


def test_pp3_preferred_over_defaults():
    source = Path("testdata/dataset/0605_mini/DSC_0681.NEF")
    loaded = read_pp3_params(source)
    assert loaded is not None
    assert loaded["_histogram_matching"] is True
    assert loaded["temperature"] != 0.0
    assert loaded["contrast"] != 0.0
