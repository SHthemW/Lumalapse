"""Lumalapse GUI: preview, exposure curve, keyframe editing, deflicker, export."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox, QProgressDialog

from ..keyframes import PARAM_DEFAULTS, interpolate_params
from ..project import PROJECT_SUFFIX, Project
from ..settings import load_settings, update_settings
from .export_dialog import ExportDialog
from .layout import build_menu, build_ui, set_controls_enabled
from .threads import (AnalyzeThread, ExportThread, FramesExportThread,
                      InstallAdobeDCPThread, InstallRTThread, PreviewThread,
                      VisualDeflickerThread)


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
        self._update_adobe_status()

    def _set_enabled(self, enabled: bool):
        set_controls_enabled(self, enabled)

    def _preview_request_settings(self) -> tuple[int | None, bool]:
        action = next(action for action in self.preview_quality_actions if action.isChecked())
        max_dim, half_size = action.data()
        return max_dim, half_size

    def _on_engine_changed(self):
        if self.project is None:
            return
        name = self.engine_combo.currentData()
        if name == self.project.engine:
            return
        from ..engines import get_engine

        if not get_engine(name).is_available():
            choice = QMessageBox.question(
                self,
                "Lumalapse",
                "未找到 RawTherapee。\n\n是否自动下载并安装？(约 100 MB，安装完成后将自动启用该引擎)\n\n"
                "也可以手动安装 https://rawtherapee.com 或设置环境变量 LUMALAPSE_RAWTHERAPEE。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if choice == QMessageBox.Yes:
                self._install_rawtherapee(name)
            else:
                self._revert_engine_combo()
            return
        self._apply_engine(name)

    def _apply_engine(self, name: str):
        self.project.engine = name
        self.project.save()
        self._preview_timer.start()

    def _revert_engine_combo(self):
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(self.project.engine)))
        self.engine_combo.blockSignals(False)

    def _install_rawtherapee(self, engine_name: str):
        dlg = QProgressDialog("正在准备下载...", None, 0, 0, self)
        dlg.setWindowTitle("安装 RawTherapee")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        thread = InstallRTThread()
        thread.message.connect(dlg.setLabelText)

        def on_done(cli):
            dlg.close()
            if cli:
                QMessageBox.information(self, "Lumalapse", f"RawTherapee 安装完成:\n{cli}")
                self._apply_engine(engine_name)
            else:
                QMessageBox.critical(
                    self,
                    "Lumalapse",
                    "自动安装失败。请手动安装 https://rawtherapee.com，或设置环境变量 LUMALAPSE_RAWTHERAPEE 指向 rawtherapee-cli。",
                )
                self._revert_engine_combo()

        thread.done.connect(on_done)
        self._install_thread = thread
        thread.start()
        dlg.exec()

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
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", f"Lumalapse 项目 (*{PROJECT_SUFFIX})")
        if path:
            self._analyze_and_load(Project.load(path))

    def _analyze_and_load(self, project: Project):
        if project.analysis and len(project.analysis.get("luminance", [])) == project.n_frames:
            self._load_project(project)
            return
        dlg = QProgressDialog("正在分析曝光曲线...", "取消", 0, project.n_frames, self)
        dlg.setWindowModality(Qt.WindowModal)
        thread = AnalyzeThread(project)
        thread.progressed.connect(lambda d, t: (dlg.setMaximum(t), dlg.setValue(d)))
        thread.failed.connect(lambda tb: QMessageBox.critical(self, "分析失败", tb))
        thread.finished.connect(lambda: (dlg.close(), self._load_project(project)))
        dlg.canceled.connect(thread.terminate)
        self._analyze_thread = thread
        thread.start()
        dlg.exec()

    def _load_project(self, project: Project):
        if not project.analysis:
            return
        self.project = project
        project.save()
        update_settings(last_folder=project.folder)
        n_frames = project.n_frames
        self.frame_slider.setRange(0, n_frames - 1)
        self.frame_spin.setRange(0, n_frames - 1)
        self.playhead.setBounds([0, n_frames - 1])
        self.df_enable.setChecked(project.deflicker_enabled)
        self.df_strength.setValue(project.deflicker_strength)
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(project.engine)))
        self.engine_combo.blockSignals(False)
        self._set_enabled(True)
        has_ev = project.has_exif_ev()
        self.hg_enable.blockSignals(True)
        self.hg_enable.setChecked(project.holy_grail_enabled and has_ev)
        self.hg_enable.blockSignals(False)
        self.hg_enable.setEnabled(has_ev)  # after _set_enabled: stays off without EXIF
        if not has_ev:
            self.hg_enable.setToolTip("此序列没有 EXIF 曝光数据,圣杯补偿不可用")
        self._update_visual_df_status()
        self._update_adobe_status()
        self.setWindowTitle(f"Lumalapse - {Path(project.folder).name} ({n_frames} 帧)")
        self.current_frame = -1
        self.refresh_curves()
        self.set_frame(0)

    def save_project(self):
        if self.project:
            self.project.save()
            self.statusBar().showMessage(f"已保存 {self.project.path}", 3000)

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
        if keyframe:
            params = keyframe.params
        else:
            interp = interpolate_params(project.keyframes, project.n_frames, project.interp_mode)
            params = {name: float(arr[idx]) for name, arr in interp.items()}
        self._loading_panel = True
        for name, editor in self.param_spins.items():
            editor.setValue(float(params.get(name, PARAM_DEFAULTS[name])))
        self._loading_panel = False
        self.kf_status.setText("● 此帧是关键帧" if keyframe else "● 非关键帧(显示插值结果)")
        self.btn_del_kf.setEnabled(keyframe is not None)

    def _on_param_changed(self):
        if self._loading_panel or self.project is None:
            return
        self.project.set_keyframe(self.current_frame, self._panel_params())
        self.kf_status.setText("● 此帧是关键帧")
        self.btn_del_kf.setEnabled(True)
        self.refresh_curves()
        self._preview_timer.start()

    def _panel_params(self) -> dict:
        return {name: editor.value() for name, editor in self.param_spins.items()}
    def add_keyframe(self):
        if self.project is None:
            return
        self.project.set_keyframe(self.current_frame, self._panel_params())
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
        self.project.holy_grail_enabled = self.hg_enable.isChecked()
        if self.project.deflicker_strength != self.df_strength.value():
            # strength changes invalidate baked visual corrections
            self.project.deflicker_strength = self.df_strength.value()
            self.project.visual_deflicker = None
        self._update_visual_df_status()
        self.refresh_curves()
        self._preview_timer.start()

    def _update_visual_df_status(self):
        if self.project and self.project.visual_deflicker:
            self.visual_df_status.setText("视觉去闪:已计算 ✓ (改参数后请重新计算)")
        else:
            self.visual_df_status.setText("视觉去闪:未计算 (当前为解析式去闪)")

    def run_visual_deflicker(self):
        if self.project is None:
            return
        dlg = QProgressDialog("正在渲染并测量全序列亮度…", "取消", 0,
                              self.project.n_frames * 2, self)
        dlg.setWindowModality(Qt.WindowModal)
        thread = VisualDeflickerThread(self.project, passes=2)
        thread.progressed.connect(lambda d, t: (dlg.setMaximum(t), dlg.setValue(d)))
        thread.failed.connect(lambda tb: (dlg.close(), QMessageBox.critical(self, "视觉去闪失败", tb)))

        def on_ok():
            dlg.close()
            self.project.save()
            self.df_enable.setChecked(True)
            self._update_visual_df_status()
            self.refresh_curves()
            self._preview_timer.start()

        thread.finished_ok.connect(on_ok)
        dlg.canceled.connect(thread.terminate)
        self._visual_df_thread = thread
        thread.start()
        dlg.exec()

    def _on_preview_quality_changed(self):
        if self.project is not None:
            self._preview_timer.start()

    def refresh_curves(self):
        project = self.project
        lum = np.asarray(project.analysis["luminance"], dtype=float)
        x = np.arange(project.n_frames)
        self.curve_lum.setData(x, lum)
        params = project.frame_params()
        self.curve_out.setData(x, lum + params["exposure"])
        kx = [keyframe.frame for keyframe in project.keyframes]
        self.kf_scatter.setData(kx, lum[kx] + params["exposure"][kx] if kx else [])

    def _request_preview(self):
        if self.project is None:
            return
        self.loading_label.show()
        self.loading_label.raise_()
        max_dim, half_size = self._preview_request_settings()
        self.preview_thread.request(self.project, self.current_frame, self.project.frame_params(), max_dim, half_size)

    def _on_preview_failed(self, message: str):
        self.loading_label.hide()
        self.statusBar().showMessage(f"预览渲染失败: {message}", 8000)

    def _on_preview_rendered(self, idx: int, frame: np.ndarray):
        self.loading_label.hide()
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888).copy()
        self._preview_pixmap = QPixmap.fromImage(image)
        self.preview_view.set_pixmap(self._preview_pixmap)

    def export_video(self):
        if self.project is None:
            return
        dlg = ExportDialog(self, self.project.folder)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        self.project.save()
        prog = QProgressDialog("正在渲染并编码...", "取消", 0, self.project.n_frames, self)
        prog.setWindowModality(Qt.WindowModal)
        thread = ExportThread(self.project, opts)
        thread.progressed.connect(lambda d, t: (prog.setMaximum(t), prog.setValue(d)))
        thread.finished_ok.connect(lambda out: (prog.close(), QMessageBox.information(self, "导出完成", f"已导出:\n{out}")))
        thread.failed.connect(lambda tb: (prog.close(), QMessageBox.critical(self, "导出失败", tb)))
        prog.canceled.connect(lambda: setattr(thread, "cancelled", True))
        self._export_thread = thread
        thread.start()

    def _update_adobe_status(self):
        """Adobe DNG Converter install state + which DCP this sequence gets."""
        import os

        from ..engines.rawtherapee import adobe_profiles_status, find_adobe_dcp

        status = adobe_profiles_status()
        if status["installed"]:
            self.adobe_status.setText(f"Adobe DCP:已安装({status['count']} 个相机校准档)")
            self.btn_install_adobe.hide()
        else:
            self.adobe_status.setText("Adobe DCP:未安装(RawTherapee 引擎使用内置校准)")
            self.btn_install_adobe.show()

        if self.project is None:
            self.dcp_status.setText("")
            return
        from .. import loader

        model = loader.read_metadata(self.project.files[0]).get("model")
        env = os.environ.get("LUMALAPSE_DCP")
        if env and Path(env).exists():
            source = f"强制指定 {Path(env).name}"
        elif (adobe := find_adobe_dcp(model)):
            source = f"Adobe Standard({model})✓"
        elif model:
            source = f"RawTherapee 自动匹配({model})"
        else:
            source = "无相机型号信息,标准色彩矩阵"
        self.dcp_status.setText(f"本序列色彩档:{source}")

    def install_adobe_dcp(self):
        dlg = QProgressDialog("正在准备下载…", None, 0, 0, self)
        dlg.setWindowTitle("安装 Adobe DNG Converter")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        thread = InstallAdobeDCPThread()
        thread.message.connect(dlg.setLabelText)

        def on_done(ok: bool):
            dlg.close()
            if ok:
                QMessageBox.information(
                    self, "Lumalapse",
                    "Adobe DNG Converter 安装完成,相机色彩校准档已就绪。\n"
                    "RawTherapee 引擎此后自动使用 Adobe 校准。")
            else:
                import webbrowser

                from ..engines.rawtherapee import DNG_CONVERTER_URL

                webbrowser.open(DNG_CONVERTER_URL)
                QMessageBox.information(
                    self, "Lumalapse",
                    "自动安装未成功,已打开 Adobe 官方下载页面。\n"
                    "手动安装完成后重新打开图片文件夹即可生效。")
            self._update_adobe_status()
            self._preview_timer.start()

        thread.done.connect(on_done)
        self._adobe_thread = thread
        thread.start()
        dlg.exec()

    def export_frames_seq(self):
        """Develop all frames to a JPG sequence (inspect/retouch, then assemble)."""
        if self.project is None:
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "选择 JPG 序列输出文件夹", self.project.folder)
        if not out_dir:
            return
        self.project.save()
        prog = QProgressDialog("正在冲洗 JPG 序列...", "取消", 0, self.project.n_frames, self)
        prog.setWindowModality(Qt.WindowModal)
        thread = FramesExportThread(self.project, out_dir)
        thread.progressed.connect(lambda d, t: (prog.setMaximum(t), prog.setValue(d)))
        thread.finished_ok.connect(lambda out: (prog.close(), QMessageBox.information(
            self, "导出完成", f"JPG 序列已写入:\n{out}\n\n可用「lumalapse assemble」或导出视频菜单合成。")))
        thread.failed.connect(lambda tb: (prog.close(), QMessageBox.critical(self, "导出失败", tb)))
        prog.canceled.connect(lambda: setattr(thread, "cancelled", True))
        self._frames_thread = thread
        thread.start()

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
