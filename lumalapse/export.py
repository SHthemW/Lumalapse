"""Video export by piping rendered frames into ffmpeg (binary from imageio-ffmpeg)."""

from __future__ import annotations

import cv2
import shutil
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


def _encode_from_sequence(pattern: str, out_path: str, fps: float, codec: str, quality: int):
    import imageio_ffmpeg

    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-framerate", str(fps), "-i", pattern, *CODEC_ARGS[codec]]
    if codec in ("h264", "h265"):
        cmd += ["-crf", str(quality)]
    cmd += [out_path]
    with tempfile.TemporaryFile() as errlog:
        ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=errlog, creationflags=NO_WINDOW).returncode
        if ret != 0:
            errlog.seek(0)
            err = errlog.read().decode(errors="replace")[-2000:]
            raise RuntimeError(f"ffmpeg failed ({ret}):\n{err}")


def _export_jpg_sequence(project: Project, out_path: str, fps: float, width: int | None, codec: str,
                         quality: int, keep_jpg: bool, progress, cancelled) -> str:
    frame_dir = Path(out_path).with_suffix("")
    frame_dir = frame_dir.with_name(f"{frame_dir.name}_jpg_frames") if keep_jpg else None
    tmp_ctx = tempfile.TemporaryDirectory(prefix="lumalapse_jpg_") if frame_dir is None else None
    try:
        folder = Path(tmp_ctx.name) if tmp_ctx else frame_dir
        if keep_jpg and folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
        pattern = str(folder / "frame_%06d.jpg")
        frames = render_sequence(project, width=width, engine_name="rawtherapee")
        for idx, frame in frames:
            if cancelled and cancelled():
                raise InterruptedError("Export cancelled")
            jpg = folder / f"frame_{idx:06d}.jpg"
            ok = cv2.imwrite(str(jpg), frame[:, :, ::-1], [
                cv2.IMWRITE_JPEG_QUALITY, 100,
                cv2.IMWRITE_JPEG_LUMA_QUALITY, 100,
                cv2.IMWRITE_JPEG_CHROMA_QUALITY, 100,
                cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
            ])
            if not ok:
                raise RuntimeError(f"Cannot write intermediate JPEG: {jpg}")
            if progress:
                progress(idx + 1, project.n_frames * 2)
        _encode_from_sequence(pattern, out_path, fps, codec, quality)
        if progress:
            progress(project.n_frames * 2, project.n_frames * 2)
    finally:
        if tmp_ctx:
            tmp_ctx.cleanup()
    return out_path


def export_video(
    project: Project,
    out_path: str | Path,
    fps: float = 25.0,
    width: int | None = None,
    codec: str = "h264",
    quality: int = 17,
    half_size: bool = False,
    engine_name: str | None = None,
    acceleration: str | None = None,
    keep_jpg: bool = False,
    progress=None,
    cancelled=None,
) -> str:
    """Render the sequence and encode it to `out_path`. Returns the output path."""
    import imageio_ffmpeg

    if codec not in CODEC_ARGS:
        raise ValueError(f"Unknown codec {codec!r}; choose from {sorted(CODEC_ARGS)}")
    out_path = str(Path(out_path).resolve())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if acceleration is not None:
        project.acceleration = acceleration
    if engine_name == "rawtherapee":
        return _export_jpg_sequence(project, out_path, fps, width, codec, quality, keep_jpg, progress, cancelled)

    frames = render_sequence(project, width=width, half_size=half_size, progress=progress, engine_name=engine_name)
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
