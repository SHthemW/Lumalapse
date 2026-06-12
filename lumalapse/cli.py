"""Lumalapse command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .keyframes import PARAM_DEFAULTS, PARAM_RANGES
from .project import PROJECT_SUFFIX, Project, default_project_path

def _spark_chars() -> str:
    """Unicode blocks only on UTF terminals; legacy code pages (GBK etc.) often
    claim to encode them but the console then misrenders, so fall back to ASCII."""
    enc = (sys.stdout.encoding or "").lower().replace("-", "")
    return "▁▂▃▄▅▆▇█" if enc.startswith("utf") else "_.-~=*#@"


def _load_project(path: str) -> Project:
    p = Path(path)
    if p.is_dir():
        for candidate in (default_project_path(p), p / f"project{PROJECT_SUFFIX}"):
            if candidate.exists():
                return Project.load(candidate)
        raise click.ClickException(f"No project data in {p}; run `lumalapse analyze {p}` first")
    return Project.load(p)


def _progress_bar(label: str):
    bar = click.progressbar(length=1, label=label)
    bar.__enter__()

    def cb(done, total):
        bar.length = total
        bar.update(done - bar.pos)

    return bar, cb


def _sparkline(values, width: int = 80) -> str:
    import numpy as np

    chars = _spark_chars()
    vals = np.asarray([v for v in values if v is not None], dtype=float)
    if vals.size == 0:
        return "(no data)"
    if vals.size > width:
        edges = np.linspace(0, vals.size, width + 1).astype(int)
        vals = np.array([vals[a:b].mean() for a, b in zip(edges[:-1], edges[1:])])
    lo, hi = vals.min(), vals.max()
    span = (hi - lo) or 1.0
    idx = ((vals - lo) / span * (len(chars) - 1)).round().astype(int)
    return "".join(chars[i] for i in idx) + f"   [{lo:+.2f} .. {hi:+.2f}]"


@click.group()
@click.version_option(package_name="lumalapse")
def main():
    """Lumalapse - timelapse RAW grading, deflicker and video export."""


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("-p", "--project", "project_path", type=click.Path(), default=None,
              help="Project file to write (default: <folder>/.lumalapse/project"
                   f"{PROJECT_SUFFIX})")
@click.option("--force", is_flag=True, help="Re-analyze even if cached data exists")
def analyze(folder, project_path, force):
    """Scan FOLDER, compute the exposure curve and create a project file.

    Results are cached in <folder>/.lumalapse; a second run (or opening the
    folder in the GUI) reuses them unless the sequence changed or --force is given.
    """
    proj = Project.open_folder(folder)
    click.echo(f"Found {proj.n_frames} frames")
    if force:
        proj.analysis = None
    if proj.analysis:
        click.echo("Using cached analysis from .lumalapse (use --force to re-analyze)")
    else:
        bar, cb = _progress_bar("Analyzing")
        try:
            proj.ensure_analysis(progress=cb)
        finally:
            bar.__exit__(None, None, None)
    saved = proj.save(project_path)
    click.echo(f"Project saved: {saved}")
    click.echo("\nLuminance curve (log2):")
    click.echo("  " + _sparkline(proj.analysis["luminance"]))
    if any(v is not None for v in proj.analysis["ev"]):
        click.echo("Camera EV curve:")
        click.echo("  " + _sparkline(proj.analysis["ev"]))


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--csv", "csv_path", type=click.Path(), default=None, help="Write curve data as CSV")
def curve(project_path, csv_path):
    """Show the exposure curve of a project (sparkline + optional CSV)."""
    proj = _load_project(project_path)
    ana = proj.ensure_analysis()
    click.echo(f"{proj.n_frames} frames in {proj.folder}")
    click.echo("Luminance (log2): " + _sparkline(ana["luminance"]))
    if any(v is not None for v in ana["ev"]):
        click.echo("Camera EV:        " + _sparkline(ana["ev"]))
    if proj.deflicker_enabled:
        import numpy as np
        params = proj.frame_params()
        click.echo("After deflicker:  " + _sparkline(
            np.asarray(ana["luminance"]) + params["exposure"]))
    if csv_path:
        import csv as _csv
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["frame", "file", "log2_luminance", "camera_ev"])
            for i, fpath in enumerate(proj.files):
                w.writerow([i, Path(fpath).name, ana["luminance"][i], ana["ev"][i]])
        click.echo(f"CSV written: {csv_path}")


@main.group()
def keyframe():
    """Manage keyframes."""


def _param_options(fn):
    for name in reversed(list(PARAM_DEFAULTS)):
        lo, hi = PARAM_RANGES[name]
        fn = click.option(f"--{name}", type=click.FloatRange(lo, hi), default=None,
                          help=f"{name} [{lo}, {hi}]")(fn)
    return fn


@keyframe.command("set")
@click.argument("project_path", type=click.Path(exists=True))
@click.argument("frame", type=int)
@_param_options
def keyframe_set(project_path, frame, **params):
    """Add or update a keyframe at FRAME with the given parameters."""
    proj = _load_project(project_path)
    if not 0 <= frame < proj.n_frames:
        raise click.ClickException(f"Frame out of range 0..{proj.n_frames - 1}")
    given = {k: v for k, v in params.items() if v is not None}
    kf = proj.set_keyframe(frame, given)
    proj.save()
    click.echo(f"Keyframe @ {frame}: " + ", ".join(f"{k}={v:g}" for k, v in kf.params.items()))


@keyframe.command("remove")
@click.argument("project_path", type=click.Path(exists=True))
@click.argument("frame", type=int)
def keyframe_remove(project_path, frame):
    """Remove the keyframe at FRAME."""
    proj = _load_project(project_path)
    if not proj.remove_keyframe(frame):
        raise click.ClickException(f"No keyframe at frame {frame}")
    proj.save()
    click.echo(f"Removed keyframe @ {frame}")


@keyframe.command("list")
@click.argument("project_path", type=click.Path(exists=True))
def keyframe_list(project_path):
    """List all keyframes."""
    proj = _load_project(project_path)
    if not proj.keyframes:
        click.echo("No keyframes")
        return
    for kf in proj.keyframes:
        click.echo(f"  frame {kf.frame:5d}  " + ", ".join(f"{k}={v:g}" for k, v in kf.params.items()))


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.argument("name", type=click.Choice(["builtin", "rawtherapee"]), required=False)
def engine(project_path, name):
    """Show or set the rendering engine.

    builtin: fast numpy pipeline. rawtherapee: renders through rawtherapee-cli
    (mature RAW engine: color science, highlight reconstruction, RT dehaze).
    """
    from .engines import get_engine

    proj = _load_project(project_path)
    if name is None:
        click.echo(f"Engine: {proj.engine}")
        return
    eng = get_engine(name)
    if not eng.is_available():
        raise click.ClickException(
            "rawtherapee-cli not found. Install RawTherapee (https://rawtherapee.com) "
            "or set LUMALAPSE_RAWTHERAPEE to the executable path.")
    proj.engine = name
    proj.save()
    click.echo(f"Engine set to {name}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("--enable/--disable", default=True, help="Turn deflicker on/off")
@click.option("--strength", type=click.FloatRange(1, 200), default=None,
              help="Smoothing sigma in frames (default 10)")
def deflicker(project_path, enable, strength):
    """Configure luminance-based deflicker for a project."""
    proj = _load_project(project_path)
    proj.deflicker_enabled = enable
    if strength is not None:
        proj.deflicker_strength = strength
    proj.save()
    state = f"enabled (strength={proj.deflicker_strength:g})" if enable else "disabled"
    click.echo(f"Deflicker {state}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True))
@click.option("-o", "--output", type=click.Path(), required=True, help="Output video file (.mp4/.mov)")
@click.option("--fps", type=float, default=25.0, show_default=True)
@click.option("--width", type=int, default=None, help="Output width in px (default: source size)")
@click.option("--codec", type=click.Choice(["h264", "h265", "prores"]), default="h264", show_default=True)
@click.option("--quality", type=click.IntRange(0, 51), default=17, show_default=True,
              help="CRF for h264/h265 (lower = better)")
@click.option("--half-size", is_flag=True, help="Demosaic RAWs at half resolution (much faster)")
@click.option("--engine", "engine_name", type=click.Choice(["builtin", "rawtherapee"]),
              default=None, help="Override the project's rendering engine for this export")
def export(project_path, output, fps, width, codec, quality, half_size, engine_name):
    """Render all frames and export the sequence as a video."""
    from .export import export_video

    proj = _load_project(project_path)
    proj.ensure_analysis()
    proj.save()
    if engine_name:  # one-shot override, applied after save so it doesn't persist
        proj.engine = engine_name
    bar, cb = _progress_bar("Rendering")
    try:
        out = export_video(proj, output, fps=fps, width=width, codec=codec,
                           quality=quality, half_size=half_size, progress=cb)
    finally:
        bar.__exit__(None, None, None)
    click.echo(f"Exported: {out}")


@main.command()
@click.argument("project_path", type=click.Path(exists=True), required=False)
def gui(project_path):
    """Launch the graphical interface (optionally opening a project)."""
    from .gui.main_window import run_gui

    sys.exit(run_gui(project_path))


if __name__ == "__main__":
    main()
