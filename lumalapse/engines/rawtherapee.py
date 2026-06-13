"""RawTherapee engine: grade frames through rawtherapee-cli."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from ..procutil import NO_WINDOW
from .rawtherapee_profile import build_pp3 as build_rt_pp3

_DEFAULT_LOCATIONS = [
    r"C:\Program Files\RawTherapee\rawtherapee-cli.exe",
    "/usr/bin/rawtherapee-cli",
    "/usr/local/bin/rawtherapee-cli",
    "/Applications/RawTherapee.app/Contents/MacOS/rawtherapee-cli",
]


def build_pp3(params: dict, source_path: str | Path | None = None) -> str:
    return build_rt_pp3(params, source_path=source_path)


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


class RawTherapeeEngine:
    name = "rawtherapee"
    parallel_jobs = 3  # concurrent rawtherapee-cli processes during export

    def __init__(self):
        self.cli = find_cli()

    def is_available(self) -> bool:
        if self.cli is None:  # re-probe: RT may have been installed since startup
            self.cli = find_cli()
        return self.cli is not None

    def render(self, path: str, params: dict, half_size: bool = False,
               max_dim: int | None = None, cache: bool = False) -> np.ndarray:
        if not self.cli:
            raise RuntimeError(
                "rawtherapee-cli not found. Install RawTherapee (https://rawtherapee.com) "
                "or set LUMALAPSE_RAWTHERAPEE to the executable path."
            )
        with tempfile.TemporaryDirectory(prefix="lumalapse_rt_") as tmp:
            pp3 = Path(tmp) / "params.pp3"
            pp3.write_text(build_rt_pp3(params, source_path=path), encoding="utf-8")
            out = Path(tmp) / "out.tif"
            cmd = [self.cli, "-o", str(out), "-t", "-b16", "-Y",
                   "-p", str(pp3), "-c", str(path)]
            res = subprocess.run(cmd, capture_output=True, timeout=600,
                                 creationflags=NO_WINDOW)
            if res.returncode != 0 or not out.exists():
                err = (res.stderr or res.stdout or b"").decode(errors="replace")[-1500:]
                raise RuntimeError(f"rawtherapee-cli failed on {path}:\n{err}")
            img = cv2.imread(str(out), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"Cannot read RawTherapee output for {path}")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            img = img[:, :, :3]
        rgb = img[:, :, ::-1]
        if rgb.dtype == np.uint16:
            rgb = ((rgb.astype(np.float32) / 65535.0) * 255.0 + 0.5).astype(np.uint8)
        elif rgb.dtype != np.uint8:
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        h, w = rgb.shape[:2]
        target = max_dim
        if half_size:
            target = min(target, max(h, w) // 2) if target else max(h, w) // 2
        if target and max(h, w) > target:
            scale = target / max(h, w)
            rgb = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))),
                             interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(rgb)
