"""GUI export helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from ..settings import update_settings
from .threads import ExportThread


def _rawtherapee_available() -> bool:
    from ..engines import get_engine

    return get_engine("rawtherapee").is_available()


def start_export(win, opts: dict):
    if opts.get("engine_name") == "rawtherapee" and not _rawtherapee_available():
        QMessageBox.warning(win, "Lumalapse", "未找到 RawTherapee，请先在渲染引擎中安装或配置后再使用高质量导出。")
        return
    update_settings(last_export_folder=str(Path(opts["out_path"]).resolve().parent))
    win.project.save()
    prog = QProgressDialog("正在渲染并编码...", "取消", 0, win.project.n_frames, win)
    prog.setWindowModality(Qt.WindowModal)
    thread = ExportThread(win.project, opts)
    thread.progressed.connect(lambda d, t: (prog.setMaximum(t), prog.setValue(d)))
    thread.finished_ok.connect(lambda out: (prog.close(), QMessageBox.information(win, "导出完成", f"已导出:\n{out}")))
    thread.failed.connect(lambda tb: (prog.close(), QMessageBox.critical(win, "导出失败", tb)))
    prog.canceled.connect(lambda: setattr(thread, "cancelled", True))
    win._export_thread = thread
    thread.start()
