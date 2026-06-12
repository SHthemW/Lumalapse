"""Export: video encoding (ffmpeg from imageio-ffmpeg), developed frame
sequences (JPG/TIFF/PNG), and assembling a video from an image folder."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from .procutil import NO_WINDOW
from .project import Project
from .render import even_size, render_sequence

CODEC_ARGS = {
    "h264": ["-c:v", "libx264", "-preset", "slow", "-pix_fmt", "yuv420p"],
    "h265": ["-c:v", "libx265", "-preset", "slow", "-pix_fmt", "yuv420p"],
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
}
FRAME_FORMATS = {"jpg": [cv2.IMWRITE_JPEG_QUALITY], "png": [], "tif": []}


def _encode_stream(frames, out_path: str | Path, fps: float, codec: str,
                   quality: int, cancelled=None) -> str:
    """Pipe an iterator of (idx, uint8 RGB frames of uniform size) into ffmpeg."""
    import imageio_ffmpeg

    if codec not in CODEC_ARGS:
        raise ValueError(f"Unknown codec {codec!r}; choose from {sorted(CODEC_ARGS)}")
    out_path = str(Path(out_path).resolve())
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    frames = iter(frames)
    try:
        _, first = next(frames)
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
    frames = render_sequence(project, width=width, half_size=half_size, progress=progress)
    return _encode_stream(frames, out_path, fps, codec, quality, cancelled=cancelled)


def _imwrite_unicode(path: str | Path, bgr: np.ndarray, params: list) -> None:
    """Write an image through OpenCV without losing non-ASCII Windows paths
    (mirror of loader._imread_unicode)."""
    ok, buf = cv2.imencode(Path(path).suffix, bgr, params)
    if not ok:
        raise IOError(f"Cannot encode image: {path}")
    buf.tofile(str(path))


def export_frames(
    project: Project,
    out_dir: str | Path,
    fmt: str = "jpg",
    quality: int = 95,
    width: int | None = None,
    half_size: bool = False,
    progress=None,
    cancelled=None,
) -> str:
    """Develop every frame to an image file in `out_dir` (the LRTimelapse-style
    intermediate workflow: inspect/retouch the stills, then assemble).

    Files are named <index>_<original stem>.<fmt> so they sort in sequence
    order. Returns the output directory.
    """
    fmt = fmt.lower().lstrip(".")
    if fmt == "tiff":
        fmt = "tif"
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt not in FRAME_FORMATS:
        raise ValueError(f"Unknown format {fmt!r}; choose from {sorted(FRAME_FORMATS)}")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if fmt == "jpg" else []
    for idx, frame in render_sequence(project, width=width, half_size=half_size,
                                      progress=progress):
        if cancelled and cancelled():
            raise InterruptedError("Export cancelled")
        stem = Path(project.files[idx]).stem
        _imwrite_unicode(out_dir / f"{idx:05d}_{stem}.{fmt}", frame[:, :, ::-1], params)
    return str(out_dir)


def assemble_video(
    image_dir: str | Path,
    out_path: str | Path,
    fps: float = 25.0,
    width: int | None = None,
    codec: str = "h264",
    quality: int = 17,
    progress=None,
    cancelled=None,
) -> str:
    """Encode an already-developed image sequence (e.g. from export_frames,
    or JPEGs developed elsewhere) into a video, in filename order."""
    from . import loader

    files = loader.list_sequence(image_dir)
    if not files:
        raise ValueError(f"No images found in {image_dir}")

    def frames():
        size = None
        for i, path in enumerate(files):
            img = loader._imread_unicode(path, cv2.IMREAD_COLOR)
            if img is None:
                raise IOError(f"Cannot read image: {path}")
            rgb = np.ascontiguousarray(img[:, :, ::-1])
            if size is None:
                size = even_size(rgb.shape[1], rgb.shape[0], width)
            if (rgb.shape[1], rgb.shape[0]) != size:
                rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
            if progress:
                progress(i + 1, len(files))
            yield i, rgb

    return _encode_stream(frames(), out_path, fps, codec, quality, cancelled=cancelled)
