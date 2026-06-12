"""Worker threads used by the GUI."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from ..project import Project
from ..render import render_frame


class AnalyzeThread(QThread):
    progressed = Signal(int, int)
    failed = Signal(str)

    def __init__(self, project: Project):
        super().__init__()
        self.project = project

    def run(self):
        try:
            self.project.ensure_analysis(progress=lambda d, t: self.progressed.emit(d, t))
        except Exception:
            self.failed.emit(traceback.format_exc())


class PreviewThread(QThread):
    rendered = Signal(int, object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._pending = None
        self._quit = False

    def request(self, project: Project, idx: int, params, max_dim: int | None, half_size: bool):
        self._pending = (project, idx, params, max_dim, half_size)
        if not self.isRunning():
            self.start()

    def stop(self):
        self._quit = True
        self.wait(2000)

    def run(self):
        while not self._quit:
            job = self._pending
            if job is None:
                self.msleep(30)
                continue
            self._pending = None
            project, idx, params, max_dim, half_size = job
            try:
                frame = render_frame(project, idx, params, half_size=half_size, max_dim=max_dim, cache=True)
                if self._pending is None:
                    self.rendered.emit(idx, frame)
            except Exception as exc:
                traceback.print_exc()
                if self._pending is None:
                    self.failed.emit(str(exc))


class VisualDeflickerThread(QThread):
    progressed = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, project: Project, passes: int = 2):
        super().__init__()
        self.project = project
        self.passes = passes

    def run(self):
        from ..render import compute_visual_deflicker

        try:
            compute_visual_deflicker(self.project, passes=self.passes,
                                     progress=lambda d, t: self.progressed.emit(d, t))
            self.finished_ok.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())


class InstallRTThread(QThread):
    message = Signal(str)
    done = Signal(object)

    def run(self):
        from ..engines.rawtherapee import ensure_installed

        try:
            self.done.emit(ensure_installed(progress=self.message.emit))
        except Exception:
            traceback.print_exc()
            self.done.emit(None)


class ExportThread(QThread):
    progressed = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, project: Project, opts: dict):
        super().__init__()
        self.project = project
        self.opts = opts
        self.cancelled = False

    def run(self):
        from ..export import export_video

        try:
            out = export_video(
                self.project,
                progress=lambda d, t: self.progressed.emit(d, t),
                cancelled=lambda: self.cancelled,
                **self.opts,
            )
            self.finished_ok.emit(out)
        except InterruptedError:
            pass
        except Exception:
            self.failed.emit(traceback.format_exc())


class FramesExportThread(QThread):
    progressed = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, project: Project, out_dir: str, fmt: str = "jpg", quality: int = 95):
        super().__init__()
        self.project = project
        self.out_dir = out_dir
        self.fmt = fmt
        self.quality = quality
        self.cancelled = False

    def run(self):
        from ..export import export_frames

        try:
            out = export_frames(
                self.project, self.out_dir, fmt=self.fmt, quality=self.quality,
                progress=lambda d, t: self.progressed.emit(d, t),
                cancelled=lambda: self.cancelled,
            )
            self.finished_ok.emit(out)
        except InterruptedError:
            pass
        except Exception:
            self.failed.emit(traceback.format_exc())
