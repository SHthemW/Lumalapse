"""RawTherapee profile template and merge helpers."""

from __future__ import annotations

import configparser
from pathlib import Path

import numpy as np

from ..keyframes import PARAM_DEFAULTS


DEFAULT_PROFILE_TEXT = """[Version]
AppVersion=5.12
Version=352

[Exposure]
Auto=false
Clip=0.02
Compensation=0
Brightness=0
Contrast=0
Saturation=0
Black=0
HighlightCompr=0
HighlightComprThreshold=0
ShadowCompr=50
HistogramMatching=true
CurveFromHistogramMatching=true
ClampOOG=true
CurveMode=FilmLike
CurveMode2=Standard
Curve=4;0;0;0.050000000000000003;0.084200584515560242;0.12;0.24182195568553397;0.21799999999999997;0.4945506347879095;0.35519999999999996;0.77650236482078938;0.54727999999999999;0.94358363362165321;0.81619199999999992;0.99165332487157676;1;1;
Curve2=0;

[HLRecovery]
Enabled=true
Method=Coloropp
Hlbl=0
Hlth=1

[White Balance]
Enabled=true
Setting=Camera

[LensProfile]
LcMode=lfauto
UseDistortion=true
UseVignette=true
UseCA=false

[Color Management]
ToneCurve=false
ApplyLookTable=true
ApplyBaselineExposureOffset=true
ApplyHueSatMap=true
DCPIlluminant=0
InputProfile=(cameraICC)
WorkingProfile=ProPhoto
WorkingTRC=none
OutputProfile=RTv4_sRGB
OutputBPC=true
aIntent=Relative
OutputProfileIntent=Relative

[RAW]
CA=true

[RAW Bayer]
Method=amaze

[RAW X-Trans]
Method=3-pass (best)

[PostDemosaicSharpening]
Enabled=false

[Sharpening]
Enabled=false
"""


def sidecar_path(source: str | Path) -> Path:
    path = Path(source)
    return path.with_suffix(path.suffix + ".pp3")


def base_profile_text(source: str | Path | None = None) -> str:
    if source is not None:
        candidate = sidecar_path(source)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return DEFAULT_PROFILE_TEXT


def build_pp3(params: dict, source_path: str | Path | None = None) -> str:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(base_profile_text(source_path))

    def set_section(section: str) -> configparser.SectionProxy:
        if not parser.has_section(section):
            parser.add_section(section)
        return parser[section]

    exposure = set_section("Exposure")
    exposure["CurveMode"] = "FilmLike"
    if (v := params.get("exposure")) is not None and float(v) != PARAM_DEFAULTS["exposure"]:
        exposure["Compensation"] = f"{float(v):.4f}"
    if (v := params.get("contrast")) is not None and float(v) != PARAM_DEFAULTS["contrast"]:
        exposure["Contrast"] = str(round(np.clip(float(v), -1, 1) * 100))
    if (v := params.get("saturation")) is not None and float(v) != PARAM_DEFAULTS["saturation"]:
        exposure["Saturation"] = str(round(np.clip(float(v) - 1.0, -1, 2) * 100))
    if any(float(params.get(name, PARAM_DEFAULTS[name])) != PARAM_DEFAULTS[name]
           for name in ("highlights", "shadows", "whites", "blacks")):
        exposure["Curve"] = _tone_curve(
            float(params.get("highlights", PARAM_DEFAULTS["highlights"])),
            float(params.get("shadows", PARAM_DEFAULTS["shadows"])),
            float(params.get("whites", PARAM_DEFAULTS["whites"])),
            float(params.get("blacks", PARAM_DEFAULTS["blacks"])),
        )

    if (v := params.get("dehaze")) is not None and float(v) > 0.0:
        set_section("Dehaze")["Enabled"] = "true"
        set_section("Dehaze")["Strength"] = str(round(np.clip(float(v), 0, 1) * 100))

    if (v := params.get("temperature")) is not None and float(v) != PARAM_DEFAULTS["temperature"]:
        wb = set_section("White Balance")
        wb["Enabled"] = "true"
        wb["Setting"] = "Custom"
        kelvin = int(np.clip(5000 + 2500 * float(v), 2000, 12000))
        wb["Temperature"] = str(kelvin)
        wb["Green"] = "1.0"

    if (v := params.get("_histogram_matching")) is not None:
        exposure["HistogramMatching"] = "true" if bool(v) else "false"
        exposure["CurveFromHistogramMatching"] = "true" if bool(v) else "false"

    return _write(parser)


def _tone_curve(highlights: float, shadows: float, whites: float, blacks: float) -> str:
    if not any((highlights, shadows, whites, blacks)):
        return "4;0;0;0.050000000000000003;0.084200584515560242;0.12;0.24182195568553397;0.21799999999999997;0.4945506347879095;0.35519999999999996;0.77650236482078938;0.54727999999999999;0.94358363362165321;0.81619199999999992;0.99165332487157676;1;1;"
    x0, y0 = (0.0, blacks * 0.08) if blacks >= 0 else (-blacks * 0.06, 0.0)
    x1, y1 = (1.0 - whites * 0.12, 1.0) if whites >= 0 else (1.0, 1.0 + whites * 0.12)
    points = [
        (x0, y0),
        (0.25, np.clip(0.25 + shadows * 0.10, 0.02, 0.48)),
        (0.50, 0.50),
        (0.75, np.clip(0.75 + highlights * 0.10, 0.52, 0.98)),
        (x1, y1),
    ]
    return "1;" + ";".join(f"{x:.5f};{y:.5f}" for x, y in points) + ";"


def _write(parser: configparser.ConfigParser) -> str:
    import io

    buf = io.StringIO()
    parser.write(buf, space_around_delimiters=False)
    return buf.getvalue()
