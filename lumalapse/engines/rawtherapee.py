"""RawTherapee engine: grade frames through rawtherapee-cli.

RawTherapee is a mature open-source RAW processor; its processing profiles
(PP3) are plain INI text, which makes it the most scriptable of the
established engines. We map Lumalapse parameters onto stable PP3 controls:

  exposure     -> [Exposure] Compensation (EV, linear gain + RT's tone curve)
  contrast     -> [Exposure] Contrast
  saturation   -> [Exposure] Saturation
  highlights / shadows / whites / blacks
               -> a custom diagonal tone curve ([Exposure] Curve), the same
                  parametric-curve approach Lightroom uses
  dehaze       -> [Dehaze] (RT's own haze removal)
  temperature  -> [White Balance] custom Kelvin shift
  + [HLRecovery] color propagation for real highlight reconstruction

Requires rawtherapee-cli (https://rawtherapee.com), located via PATH, the
LUMALAPSE_RAWTHERAPEE env var, or the default install directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from ..procutil import NO_WINDOW

_DEFAULT_LOCATIONS = [
    r"C:\Program Files\RawTherapee\rawtherapee-cli.exe",
    "/usr/bin/rawtherapee-cli",
    "/usr/local/bin/rawtherapee-cli",
    "/Applications/RawTherapee.app/Contents/MacOS/rawtherapee-cli",
]


def find_cli() -> str | None:
    env = os.environ.get("LUMALAPSE_RAWTHERAPEE")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("rawtherapee-cli")
    if on_path:
        return on_path
    for loc in _DEFAULT_LOCATIONS:
        if Path(loc).exists():
            return loc
    # Versioned install layouts: "RawTherapee\rawtherapee-cli.exe",
    # "RawTherapee 5.11\..." or "RawTherapee\5.12\..."
    pf = Path(r"C:\Program Files")
    if pf.exists():
        for d in sorted(pf.glob("RawTherapee*"), reverse=True):
            for cli in (d / "rawtherapee-cli.exe", *sorted(d.glob("*/rawtherapee-cli.exe"), reverse=True)):
                if cli.exists():
                    return str(cli)
    return None


def _winget_install(progress=None) -> bool:
    winget = shutil.which("winget")
    if not winget:
        return False
    if progress:
        progress("正在通过 winget 下载并安装 RawTherapee(约 100 MB)…")
    res = subprocess.run(
        [winget, "install", "RawTherapee.RawTherapee", "--silent",
         "--accept-source-agreements", "--accept-package-agreements"],
        capture_output=True, timeout=1800, creationflags=NO_WINDOW,
    )
    return res.returncode == 0


def _github_install(progress=None) -> bool:
    """Fallback: download the official installer from the latest GitHub release."""
    import json as _json
    import urllib.request

    if progress:
        progress("正在查询 RawTherapee 最新版本…")
    try:
        with urllib.request.urlopen(
                "https://api.github.com/repos/Beep6581/RawTherapee/releases/latest",
                timeout=30) as resp:
            release = _json.load(resp)
        asset = next((a for a in release.get("assets", [])
                      if "win64" in a["name"].lower() and a["name"].lower().endswith(".exe")), None)
        if not asset:
            return False
        if progress:
            progress(f"正在下载 {asset['name']}…")
        installer = Path(tempfile.gettempdir()) / asset["name"]
        urllib.request.urlretrieve(asset["browser_download_url"], installer)
        if progress:
            progress("正在安装 RawTherapee(可能出现系统授权提示)…")
        res = subprocess.run([str(installer), "/VERYSILENT", "/NORESTART", "/SP-"],
                             timeout=900, creationflags=NO_WINDOW)
        return res.returncode == 0
    except Exception:
        return False


def ensure_installed(progress=None) -> str | None:
    """Locate rawtherapee-cli, installing RawTherapee if necessary (blocking).

    progress, if given, receives human-readable status strings.
    Returns the cli path, or None if installation failed.
    """
    cli = find_cli()
    if cli:
        return cli
    if _winget_install(progress):
        cli = find_cli()
        if cli:
            return cli
    if _github_install(progress):
        return find_cli()
    return find_cli()


def _tone_curve(highlights: float, shadows: float, whites: float, blacks: float) -> str | None:
    """Build an [Exposure] Curve spline (type 1 = custom) from the four tone params."""
    if not any((highlights, shadows, whites, blacks)):
        return None
    # Black point: positive lifts the floor, negative crushes by shifting x0.
    x0, y0 = (0.0, blacks * 0.08) if blacks >= 0 else (-blacks * 0.06, 0.0)
    # White point: positive brightens by pulling x1 in, negative lowers y1.
    x1, y1 = (1.0 - whites * 0.12, 1.0) if whites >= 0 else (1.0, 1.0 + whites * 0.12)
    points = [
        (x0, y0),
        (0.25, np.clip(0.25 + shadows * 0.10, 0.02, 0.48)),
        (0.50, 0.50),
        (0.75, np.clip(0.75 + highlights * 0.10, 0.52, 0.98)),
        (x1, y1),
    ]
    return "1;" + ";".join(f"{x:.5f};{y:.5f}" for x, y in points) + ";"


# Where Adobe DNG Converter / Camera Raw install their per-camera DCP
# calibration profiles. When present, these are Adobe's own color data and
# give the closest possible match to Lightroom/ACR rendering.
ADOBE_PROFILE_DIRS = [
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Adobe/CameraRaw/CameraProfiles",
    Path.home() / "AppData/Roaming/Adobe/CameraRaw/CameraProfiles",
    Path("/Library/Application Support/Adobe/CameraRaw/CameraProfiles"),
]

_adobe_dcp_cache: dict = {}


def find_adobe_dcp(camera_model: str | None) -> str | None:
    """Locate an Adobe Standard DCP for a camera model, if Adobe software
    (DNG Converter, Camera Raw) has installed its profile set."""
    if not camera_model:
        return None
    key = camera_model.strip().lower()
    if key in _adobe_dcp_cache:
        return _adobe_dcp_cache[key]
    result = None
    for root in ADOBE_PROFILE_DIRS:
        if not root.is_dir():
            continue
        for dcp in root.rglob("*.dcp"):
            stem = dcp.stem.lower()
            if key in stem and "adobe standard" in stem:
                result = str(dcp)
                break
        if result:
            break
    _adobe_dcp_cache[key] = result
    return result


def _color_management_lines(dcp_path: str | None = None) -> list[str]:
    """DCP camera color profile selection.

    Priority: LUMALAPSE_DCP env override > Adobe Standard DCP matched to the
    camera (when Adobe DNG Converter/Camera Raw is installed) > (cameraICC),
    which makes RawTherapee auto-match its own bundled DCP. All three apply
    the same per-camera calibration mechanism Adobe Camera Raw uses: hue/sat
    look table, camera tone curve and baseline exposure offset.
    """
    env = os.environ.get("LUMALAPSE_DCP")
    if env and Path(env).exists():
        dcp_path = env
    # Forward slashes: PP3 is a GKeyFile, backslashes there are escape chars.
    profile = f"file:{Path(dcp_path).as_posix()}" if dcp_path else "(cameraICC)"
    return [
        "", "[Color Management]",
        f"InputProfile={profile}",
        "ToneCurve=true",
        "ApplyLookTable=true",
        "ApplyBaselineExposureOffset=true",
        "ApplyHueSatMap=true",
        "DCPIlluminant=0",
    ]


def build_pp3(params: dict, color_managed: bool = True, dcp_path: str | None = None) -> str:
    """Render Lumalapse params as a PP3 processing profile."""
    exposure = float(params.get("exposure", 0.0))
    contrast = float(params.get("contrast", 0.0))
    saturation = float(params.get("saturation", 1.0))
    dehaze = float(params.get("dehaze", 0.0))
    temperature = float(params.get("temperature", 0.0))
    highlights = float(params.get("highlights", 0.0))
    shadows = float(params.get("shadows", 0.0))

    lines = [
        "[Version]",
        "AppVersion=5.8",
        "Version=346",
        "",
        "[Exposure]",
        "Auto=false",
        f"Compensation={exposure:.4f}",
        f"Contrast={round(np.clip(contrast, -1, 1) * 100)}",
        f"Saturation={round(np.clip(saturation - 1.0, -1, 2) * 100)}",
        "CurveMode=Standard",
    ]
    # Recovery directions (darken highlights / lift shadows) go to RT's
    # Shadows&Highlights: a spatial, edge-aware (guided filter) local tool -
    # the same locally-adaptive, halo-suppressed approach as Lightroom's
    # PV2012 Highlights/Shadows. Boost directions stay on the tone curve.
    sh_highlights = round(-min(highlights, 0.0) * 100)
    sh_shadows = round(max(shadows, 0.0) * 100)
    curve = _tone_curve(
        max(highlights, 0.0),
        min(shadows, 0.0),
        float(params.get("whites", 0.0)),
        float(params.get("blacks", 0.0)),
    )
    lines.append(f"Curve={curve}" if curve else "Curve=0;")

    if sh_highlights or sh_shadows:
        lines += [
            "", "[Shadows & Highlights]",
            "Enabled=true",
            f"Highlights={sh_highlights}",
            "HighlightTonalWidth=70",
            f"Shadows={sh_shadows}",
            "ShadowTonalWidth=40",
            "Radius=40",
            "Lab=false",
        ]

    lines += ["", "[HLRecovery]", "Enabled=true", "Method=Coloropp"]

    # Capture sharpening, matching Adobe's always-on default sharpen.
    lines += ["", "[PostDemosaicSharpening]", "Enabled=true"]

    if color_managed:
        lines += _color_management_lines(dcp_path)

    if dehaze > 0:
        lines += ["", "[Dehaze]", "Enabled=true",
                  f"Strength={round(np.clip(dehaze, 0, 1) * 100)}"]

    if temperature != 0.0:
        kelvin = int(np.clip(5000 + 2500 * temperature, 2000, 12000))
        lines += ["", "[White Balance]", "Enabled=true", "Setting=Custom",
                  f"Temperature={kelvin}", "Green=1.0"]

    return "\n".join(lines) + "\n"


class RawTherapeeEngine:
    name = "rawtherapee"
    parallel_jobs = 3  # concurrent rawtherapee-cli processes during export

    def __init__(self):
        self.cli = find_cli()

    def is_available(self) -> bool:
        if self.cli is None:  # re-probe: RT may have been installed since startup
            self.cli = find_cli()
        return self.cli is not None

    _model_cache: dict = {}

    def _adobe_dcp_for(self, path: str) -> str | None:
        """Adobe Standard DCP for the camera that shot `path`, if installed."""
        model = self._model_cache.get(path)
        if model is None:
            from .. import loader

            model = loader.read_metadata(path).get("model") or ""
            self._model_cache[path] = model
        return find_adobe_dcp(model)

    def render(self, path: str, params: dict, half_size: bool = False,
               max_dim: int | None = None, cache: bool = False) -> np.ndarray:
        if not self.cli:
            raise RuntimeError(
                "rawtherapee-cli not found. Install RawTherapee (https://rawtherapee.com) "
                "or set LUMALAPSE_RAWTHERAPEE to the executable path."
            )
        with tempfile.TemporaryDirectory(prefix="lumalapse_rt_") as tmp:
            pp3 = Path(tmp) / "params.pp3"
            pp3.write_text(build_pp3(params, dcp_path=self._adobe_dcp_for(path)),
                           encoding="utf-8")
            out = Path(tmp) / "out.tif"
            cmd = [self.cli, "-o", str(out), "-t", "-b8", "-Y",
                   "-p", str(pp3), "-c", str(path)]
            res = subprocess.run(cmd, capture_output=True, timeout=600,
                                 creationflags=NO_WINDOW)
            if res.returncode != 0 or not out.exists():
                err = (res.stderr or res.stdout or b"").decode(errors="replace")[-1500:]
                raise RuntimeError(f"rawtherapee-cli failed on {path}:\n{err}")
            img = cv2.imread(str(out), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Cannot read RawTherapee output for {path}")
        rgb = img[:, :, ::-1]
        h, w = rgb.shape[:2]
        target = max_dim
        if half_size:
            target = min(target, max(h, w) // 2) if target else max(h, w) // 2
        if target and max(h, w) > target:
            scale = target / max(h, w)
            rgb = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))),
                             interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(rgb)
