"""Video export by piping rendered frames into ffmpeg (binary from imageio-ffmpeg)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .procutil import NO_WINDOW
from .project import Project
from .render import render_sequence

CODEC_ARGS = {
    "h264": ["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p"],
    "h265": ["-c:v", "libx265", "-preset", "slow", "-pix_fmt", "yuv420p"],
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
}


def export_video(
    project: Project,
    out_path: str | Path,
    fps: float = 25.0,
    width: int | None = None,
    codec: str = "h264",
    quality: int = 17,
    half_size: bool = False,
    progress=None,
    cancelled=None,
) -> str:
    """Render the sequence and encode it to `out_path`. Returns the output path."""
    import imageio_ffmpeg

    if codec not in CODEC_ARGS:
        raise ValueError(f"Unknown codec {codec!r}; choose from {sorted(CODEC_ARGS)}")
    out_path = str(Path(out_path).resolve())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    frames = render_sequence(project, width=width, half_size=half_size, progress=progress)
    try:
        first_idx, first = next(frames)
    except StopIteration:
        raise ValueError("Empty sequence, nothing to export")
    h, w = first.shape[:2]

    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
        *CODEC_ARGS[codec],
    ]
    if codec in ("h264", "h265"):
        cmd += ["-crf", str(quality)]
    cmd += [out_path]

    # stderr goes to a temp file: piping it without a reader deadlocks ffmpeg
    # once the pipe buffer fills with progress logs.
    with tempfile.TemporaryFile() as errlog:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errlog, creationflags=NO_WINDOW)
        try:
            proc.stdin.write(first.tobytes())
            for _, frame in frames:
                if cancelled and cancelled():
                    proc.kill()
                    raise InterruptedError("Export cancelled")
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            ret = proc.wait()
            if ret != 0:
                errlog.seek(0)
                err = errlog.read().decode(errors="replace")[-2000:]
                raise RuntimeError(f"ffmpeg failed ({ret}):\n{err}")
        finally:
            if proc.poll() is None:
                proc.kill()
    return out_path
