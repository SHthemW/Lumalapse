"""Render engine and acceleration actions for the main window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from ..acceleration import apply_acceleration, status_text
from .threads import InstallRTThread


def on_engine_changed(win):
    if win.project is None:
        return
    name = win.engine_combo.currentData()
    if name == win.project.engine:
        return
    from ..engines import get_engine

    if not get_engine(name).is_available():
        choice = QMessageBox.question(
            win,
            "Lumalapse",
            "未找到 RawTherapee。\n\n是否自动下载安装？(约 100 MB，安装完成后将自动启用该引擎)\n\n"
            "也可以手动安装 https://rawtherapee.com 或设置环境变量 LUMALAPSE_RAWTHERAPEE。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if choice == QMessageBox.Yes:
            install_rawtherapee(win, name)
        else:
            revert_engine_combo(win)
        return
    apply_engine(win, name)


def apply_engine(win, name: str):
    win.project.engine = name
    refresh_acceleration_status(win)
    win.project.save()
    win._preview_timer.start()


def revert_engine_combo(win):
    win.engine_combo.blockSignals(True)
    win.engine_combo.setCurrentIndex(max(0, win.engine_combo.findData(win.project.engine)))
    win.engine_combo.blockSignals(False)


def install_rawtherapee(win, engine_name: str):
    dlg = QProgressDialog("正在准备下载...", None, 0, 0, win)
    dlg.setWindowTitle("安装 RawTherapee")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    thread = InstallRTThread()
    thread.message.connect(dlg.setLabelText)

    def on_done(cli):
        dlg.close()
        if cli:
            QMessageBox.information(win, "Lumalapse", f"RawTherapee 安装完成:\n{cli}")
            apply_engine(win, engine_name)
        else:
            QMessageBox.critical(
                win,
                "Lumalapse",
                "自动安装失败。请手动安装 https://rawtherapee.com，或设置环境变量 LUMALAPSE_RAWTHERAPEE 指向 rawtherapee-cli。",
            )
            revert_engine_combo(win)

    thread.done.connect(on_done)
    win._install_thread = thread
    thread.start()
    dlg.exec()


def on_acceleration_changed(win):
    if win.project is None:
        return
    mode = win.accel_combo.currentData()
    win.project.acceleration = mode
    apply_acceleration(mode)
    refresh_acceleration_status(win)
    win.project.save()
    win._preview_timer.start()


def sync_acceleration_controls(win):
    win.accel_combo.blockSignals(True)
    win.accel_combo.setCurrentIndex(max(0, win.accel_combo.findData(win.project.acceleration)))
    win.accel_combo.blockSignals(False)
    apply_acceleration(win.project.acceleration)
    refresh_acceleration_status(win)


def refresh_acceleration_status(win):
    engine = win.project.engine if win.project else None
    mode = win.project.acceleration if win.project else win.accel_combo.currentData()
    win.accel_status.setText(status_text(mode, engine))
