"""Lumalapse GUI: preview, exposure curve, keyframe editing, deflicker, export."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox, QProgressDialog

from ..engines.rawtherapee_profile import read_pp3_params, save_pp3
from ..keyframes import PARAM_DEFAULTS, interpolate_params
from ..project import PROJECT_SUFFIX, Project
from ..settings import load_settings, update_settings
from . import engine_flow
from .export_dialog import ExportDialog
from .export_flow import start_export
from .layout import build_menu, build_ui, set_controls_enabled
from .settings_dialog import ResourceSettingsDialog
from .threads import AnalyzeThread, PreviewThread


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumalapse")
        self.resize(1450, 950)
        self.project: Project | None = None
        self.current_frame = 0
        self._loading_panel = False
        self._preview_pixmap: QPixmap | None = None

        self.preview_thread = PreviewThread()
        self.preview_thread.rendered.connect(self._on_preview_rendered)
        self.preview_thread.failed.connect(self._on_preview_failed)
        self._preview_timer = QTimer(self, singleShot=True, interval=60)
        self._preview_timer.timeout.connect(self._request_preview)

        build_menu(self)
        build_ui(self)
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        set_controls_enabled(self, enabled)

    def _preview_request_settings(self) -> tuple[int | None, bool]:
        action = next(action for action in self.preview_quality_actions if action.isChecked())
        max_dim, half_size = action.data()
        return max_dim, half_size

    def _on_engine_changed(self):
        engine_flow.on_engine_changed(self)

    def _apply_engine(self, name: str):
        engine_flow.apply_engine(self, name)

    def _on_acceleration_changed(self):
        engine_flow.on_acceleration_changed(self)

    def _revert_engine_combo(self):
        engine_flow.revert_engine_combo(self)

    def _install_rawtherapee(self, engine_name: str):
        engine_flow.install_rawtherapee(self, engine_name)

    def open_folder(self):
        start_dir = load_settings().get("last_folder", "")
        if start_dir and not Path(start_dir).is_dir():
            start_dir = ""
        folder = QFileDialog.getExistingDirectory(self, "选择延时序列文件夹", start_dir)
        if not folder:
            return
        try:
            project = Project.open_folder(folder)
        except ValueError as exc:
            QMessageBox.warning(self, "Lumalapse", str(exc))
            return
        self._analyze_and_load(project)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "鎵撳紑椤圭洰", "", f"Lumalapse 椤圭洰 (*{PROJECT_SUFFIX})")
        if path:
            self._analyze_and_load(Project.load(path))

    def _analyze_and_load(self, project: Project):
        if project.analysis and len(project.analysis.get("luminance", [])) == project.n_frames:
            self._load_project(project)
            return
        dlg = QProgressDialog("姝ｅ湪鍒嗘瀽鏇濆厜鏇茬嚎...", "鍙栨秷", 0, project.n_frames, self)
        dlg.setWindowModality(Qt.WindowModal)
        thread = AnalyzeThread(project)
        thread.progressed.connect(lambda d, t: (dlg.setMaximum(t), dlg.setValue(d)))
        thread.failed.connect(lambda tb: QMessageBox.critical(self, "鍒嗘瀽澶辫触", tb))
        thread.finished.connect(lambda: (dlg.close(), self._load_project(project)))
        dlg.canceled.connect(thread.terminate)
        self._analyze_thread = thread
        thread.start()
        dlg.exec()

    def _load_project(self, project: Project):
        if not project.analysis:
            return
        project.ensure_develop_profile(project.develop_profile_enabled)
        errors = project.analysis.get("errors") or []
        self.project = project
        project.save()
        update_settings(last_folder=project.folder)
        n_frames = project.n_frames
        self.frame_slider.setRange(0, n_frames - 1)
        self.frame_spin.setRange(0, n_frames - 1)
        self.playhead.setBounds([0, n_frames - 1])
        self.develop_enable.blockSignals(True)
        self.develop_enable.setChecked(project.develop_profile_enabled)
        self.develop_enable.blockSignals(False)
        self.df_enable.setChecked(project.deflicker_enabled)
        self.df_strength.setValue(project.deflicker_strength)
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(project.engine)))
        self.engine_combo.blockSignals(False)
        engine_flow.sync_acceleration_controls(self)
        self._set_enabled(True)
        self.setWindowTitle(f"Lumalapse - {Path(project.folder).name} ({n_frames} 甯?")
        self.current_frame = -1
        self.refresh_curves()
        self.set_frame(0)
        if errors:
            self.statusBar().showMessage(f"鍒嗘瀽璺宠繃 {len(errors)} 寮犳棤娉曡鍙栫殑鍥剧墖锛屼寒搴︽洸绾垮凡鐢ㄧ浉閭诲抚琛ラ綈", 8000)

    def save_project(self):
        if self.project:
            self.project.save()
            self.statusBar().showMessage(f"宸蹭繚瀛?{self.project.path}", 3000)

    def set_frame(self, idx: int):
        if self.project is None or idx == self.current_frame:
            return
        idx = max(0, min(idx, self.project.n_frames - 1))
        self.current_frame = idx
        for widget in (self.frame_slider, self.frame_spin):
            widget.blockSignals(True)
            widget.setValue(idx)
            widget.blockSignals(False)
        self.playhead.blockSignals(True)
        self.playhead.setValue(idx)
        self.playhead.blockSignals(False)
        self.frame_info.setText(Path(self.project.files[idx]).name)
        self._sync_panel_from_frame()
        self._preview_timer.start()

    def _on_playhead_moved(self):
        self.set_frame(round(self.playhead.value()))

    def _sync_panel_from_frame(self):
        project, idx = self.project, self.current_frame
        keyframe = project.get_keyframe(idx)
        if project.engine == "rawtherapee":
            params = read_pp3_params(project.files[idx])
            if params is None:
                params = keyframe.params if keyframe else None
            if params is None:
                interp = interpolate_params(project.keyframes, project.n_frames, project.interp_mode)
                params = {name: float(arr[idx]) for name, arr in interp.items()}
        else:
            if keyframe:
                params = keyframe.params
            else:
                interp = interpolate_params(project.keyframes, project.n_frames, project.interp_mode)
                params = {name: float(arr[idx]) for name, arr in interp.items()}
        self._loading_panel = True
        for name, editor in self.param_spins.items():
            editor.setValue(float(params.get(name, PARAM_DEFAULTS[name])))
        self._loading_panel = False
        self.kf_status.setText("鈼?姝ゅ抚鏄叧閿抚" if keyframe else "鈼?闈炲叧閿抚(鏄剧ず鎻掑€肩粨鏋?")
        self.btn_del_kf.setEnabled(keyframe is not None)

    def _on_param_changed(self):
        if self._loading_panel or self.project is None:
            return
        params = self._panel_params()
        if self.project.engine == "rawtherapee":
            save_pp3(self.project.files[self.current_frame], params)
            self._sync_panel_from_frame()
            self.refresh_curves()
            self._preview_timer.start()
            return
        self.project.set_keyframe(self.current_frame, params)
        self.kf_status.setText("鈼?姝ゅ抚鏄叧閿抚")
        self.btn_del_kf.setEnabled(True)
        self.refresh_curves()
        self._preview_timer.start()

    def _panel_params(self) -> dict:
        return {name: editor.value() for name, editor in self.param_spins.items()}

    def add_keyframe(self):
        if self.project is None:
            return
        params = self._panel_params()
        if self.project.engine == "rawtherapee":
            save_pp3(self.project.files[self.current_frame], params)
            self._sync_panel_from_frame()
            self.refresh_curves()
            self._preview_timer.start()
            return
        self.project.set_keyframe(self.current_frame, params)
        self._sync_panel_from_frame()
        self.refresh_curves()
        self._preview_timer.start()

    def remove_keyframe(self):
        if self.project and self.project.remove_keyframe(self.current_frame):
            self._sync_panel_from_frame()
            self.refresh_curves()
            self._preview_timer.start()

    def _on_deflicker_changed(self):
        if self.project is None:
            return
        self.project.deflicker_enabled = self.df_enable.isChecked()
        self.project.deflicker_strength = self.df_strength.value()
        self.project.save()
        self.refresh_curves()
        self._preview_timer.start()

    def _on_develop_changed(self):
        if self.project is None:
            return
        self.project.develop_profile_enabled = self.develop_enable.isChecked()
        if self.project.develop_profile_enabled:
            self.project.ensure_develop_profile(True)
        self.project.save()
        self.refresh_curves()
        self._preview_timer.start()

    def _on_preview_quality_changed(self):
        if self.project is not None:
            self._preview_timer.start()

    def edit_resource_settings(self):
        ResourceSettingsDialog(self).exec()

    def refresh_curves(self):
        project = self.project
        lum = np.asarray(project.analysis["luminance"], dtype=float)
        x = np.arange(project.n_frames)
        self.curve_lum.setData(x, lum)
        params = project.frame_params(include_develop=False)
        self.curve_out.setData(x, lum + params["exposure"])
        kx = [keyframe.frame for keyframe in project.keyframes]
        self.kf_scatter.setData(kx, lum[kx] + params["exposure"][kx] if kx else [])

    def _request_preview(self):
        if self.project is None:
            return
        self.loading_label.show()
        self.loading_label.raise_()
        max_dim, half_size = self._preview_request_settings()
        self.preview_thread.request(
            self.project,
            self.current_frame,
            self.project.frame_params(),
            max_dim,
            half_size,
        )

    def _on_preview_failed(self, message: str):
        self.loading_label.hide()
        self.statusBar().showMessage(f"棰勮娓叉煋澶辫触: {message}", 8000)

    def _on_preview_rendered(self, idx: int, frame: np.ndarray):
        self.loading_label.hide()
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888).copy()
        self._preview_pixmap = QPixmap.fromImage(image)
        self.preview_view.set_pixmap(self._preview_pixmap)

    def export_video(self):
        if self.project is None:
            return
        default_dir = load_settings().get("last_export_folder") or self.project.folder
        dlg = ExportDialog(self, default_dir)
        if dlg.exec() == QDialog.Accepted:
            start_export(self, dlg.options())

    def open_last_folder(self) -> bool:
        last = load_settings().get("last_folder")
        if not last or not Path(last).is_dir():
            return False
        try:
            self._analyze_and_load(Project.open_folder(last))
        except ValueError:
            return False
        return True

    def closeEvent(self, event):
        self.preview_thread.stop()
        if self.project:
            self.project.save()
        super().closeEvent(event)

