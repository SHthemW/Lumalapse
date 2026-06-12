"""Lumalapse GUI: preview, exposure curve, keyframe editing, deflicker, export."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressDialog, QPushButton, QSlider, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from ..keyframes import PARAM_DEFAULTS, PARAM_RANGES, interpolate_params
from ..project import PROJECT_SUFFIX, Project
from ..render import render_frame
from ..settings import load_settings, update_settings

PREVIEW_MAX_DIM = 1100

PARAM_LABELS = {
    "exposure": "曝光 (EV)",
    "highlights": "高光",
    "shadows": "阴影",
    "whites": "白色色阶",
    "blacks": "黑色色阶",
    "contrast": "对比度",
    "saturation": "饱和度",
    "dehaze": "去雾",
    "temperature": "色温",
}
PARAM_STEPS = {
    "exposure": 0.1, "highlights": 0.05, "shadows": 0.05, "whites": 0.05,
    "blacks": 0.05, "contrast": 0.05, "saturation": 0.05, "dehaze": 0.05,
    "temperature": 0.05,
}


# ---------------------------------------------------------------- worker threads

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
    """Renders preview frames one at a time; only the latest request is kept."""
    rendered = Signal(int, object)  # frame index, np.ndarray RGB
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._pending = None
        self._quit = False

    def request(self, project: Project, idx: int, params):
        self._pending = (project, idx, params)
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
            project, idx, params = job
            try:
                frame = render_frame(project, idx, params, half_size=True,
                                     max_dim=PREVIEW_MAX_DIM, cache=True)
                if self._pending is None:  # stale results are dropped
                    self.rendered.emit(idx, frame)
            except Exception as e:
                traceback.print_exc()
                if self._pending is None:
                    self.failed.emit(str(e))


class InstallRTThread(QThread):
    """Downloads and installs RawTherapee (winget, then GitHub release fallback)."""
    message = Signal(str)
    done = Signal(object)  # cli path str, or None on failure

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
        self.project, self.opts = project, opts
        self.cancelled = False

    def run(self):
        from ..export import export_video
        try:
            out = export_video(
                self.project, progress=lambda d, t: self.progressed.emit(d, t),
                cancelled=lambda: self.cancelled, **self.opts,
            )
            self.finished_ok.emit(out)
        except InterruptedError:
            pass
        except Exception:
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------- export dialog

class ExportDialog(QDialog):
    def __init__(self, parent, default_dir: str):
        super().__init__(parent)
        self.setWindowTitle("导出视频")
        form = QFormLayout(self)

        self.path_edit = QLineEdit(str(Path(default_dir) / "timelapse.mp4"))
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        form.addRow("输出文件", row)

        self.fps = QDoubleSpinBox(minimum=1, maximum=120, value=25, decimals=2)
        form.addRow("帧率 (fps)", self.fps)
        self.width = QSpinBox(minimum=0, maximum=8192, value=1920)
        self.width.setSpecialValueText("原始尺寸")
        form.addRow("输出宽度", self.width)
        self.codec = QComboBox()
        self.codec.addItems(["h264", "h265", "prores"])
        form.addRow("编码", self.codec)
        self.quality = QSpinBox(minimum=0, maximum=51, value=17)
        form.addRow("质量 (CRF)", self.quality)
        self.half = QCheckBox("半尺寸解码 RAW(更快)")
        form.addRow("", self.half)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "输出视频", self.path_edit.text(),
                                              "Video (*.mp4 *.mov *.mkv)")
        if path:
            self.path_edit.setText(path)

    def options(self) -> dict:
        return {
            "out_path": self.path_edit.text(),
            "fps": self.fps.value(),
            "width": self.width.value() or None,
            "codec": self.codec.currentText(),
            "quality": self.quality.value(),
            "half_size": self.half.isChecked(),
        }


# ---------------------------------------------------------------- main window

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

        self._build_menu()
        self._build_ui()
        self._set_enabled(False)

    # ---------- UI construction ----------

    def _build_menu(self):
        m = self.menuBar().addMenu("文件(&F)")
        for text, slot, key in [
            ("打开图片文件夹…", self.open_folder, "Ctrl+O"),
            ("打开项目…", self.open_project, "Ctrl+Shift+O"),
            ("保存项目", self.save_project, "Ctrl+S"),
            ("导出视频…", self.export_video, "Ctrl+E"),
        ]:
            act = QAction(text, self)
            act.setShortcut(key)
            act.triggered.connect(slot)
            m.addAction(act)

    def _build_ui(self):
        # Preview
        self.preview_label = QLabel("文件 → 打开图片文件夹…  (支持 RAW/JPEG/TIFF 序列)")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setStyleSheet("background:#161616;color:#888;")

        # "rendering…" badge overlaid on the preview while a frame is in flight
        self.loading_label = QLabel("渲染中…", self.preview_label)
        self.loading_label.setStyleSheet(
            "background:rgba(0,0,0,160);color:#ddd;padding:4px 12px;border-radius:4px;")
        self.loading_label.move(12, 12)
        self.loading_label.hide()

        # Curve plot
        pg.setConfigOptions(antialias=True, background="#202020", foreground="#cccccc")
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "帧")
        self.plot.setLabel("left", "log2 亮度")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.curve_lum = self.plot.plot(pen=pg.mkPen("#4aa3ff", width=1.5), name="原始亮度")
        self.curve_out = self.plot.plot(pen=pg.mkPen("#ffb84a", width=1.5), name="调整后")
        self.kf_scatter = pg.ScatterPlotItem(size=11, brush=pg.mkBrush("#ff5555"),
                                             pen=pg.mkPen("w", width=0.5), symbol="d")
        self.plot.addItem(self.kf_scatter)
        self.playhead = pg.InfiniteLine(0, angle=90, movable=True, pen=pg.mkPen("#88ff88", width=1))
        self.playhead.sigPositionChanged.connect(self._on_playhead_moved)
        self.plot.addItem(self.playhead)
        legend = self.plot.addLegend(offset=(8, 8))
        legend.addItem(self.curve_lum, "原始亮度")
        legend.addItem(self.curve_out, "调整后(含去闪)")

        # Frame slider
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.valueChanged.connect(self.set_frame)
        self.frame_spin = QSpinBox()
        self.frame_spin.valueChanged.connect(self.set_frame)
        self.frame_info = QLabel("")
        nav = QHBoxLayout()
        nav.addWidget(QLabel("帧"))
        nav.addWidget(self.frame_slider, 1)
        nav.addWidget(self.frame_spin)
        nav.addWidget(self.frame_info)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.preview_label)
        split.addWidget(self.plot)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        ll.addWidget(split, 1)
        ll.addLayout(nav)

        # Right panel: keyframe params
        kf_box = QGroupBox("当前帧关键帧参数")
        kf_form = QFormLayout(kf_box)
        self.param_spins: dict[str, QDoubleSpinBox] = {}
        for name in PARAM_DEFAULTS:
            lo, hi = PARAM_RANGES[name]
            spin = QDoubleSpinBox(minimum=lo, maximum=hi, value=PARAM_DEFAULTS[name],
                                  singleStep=PARAM_STEPS[name], decimals=2)
            spin.valueChanged.connect(self._on_param_changed)
            self.param_spins[name] = spin
            kf_form.addRow(PARAM_LABELS[name], spin)
        self.kf_status = QLabel("")
        kf_form.addRow(self.kf_status)
        self.btn_add_kf = QPushButton("在当前帧添加关键帧")
        self.btn_add_kf.clicked.connect(self.add_keyframe)
        self.btn_del_kf = QPushButton("删除当前帧关键帧")
        self.btn_del_kf.clicked.connect(self.remove_keyframe)
        kf_form.addRow(self.btn_add_kf)
        kf_form.addRow(self.btn_del_kf)

        df_box = QGroupBox("去闪 (Deflicker)")
        df_form = QFormLayout(df_box)
        self.df_enable = QCheckBox("启用基于曝光的去闪")
        self.df_enable.toggled.connect(self._on_deflicker_changed)
        self.df_strength = QDoubleSpinBox(minimum=1, maximum=200, value=10, singleStep=1)
        self.df_strength.valueChanged.connect(self._on_deflicker_changed)
        df_form.addRow(self.df_enable)
        df_form.addRow("平滑强度(帧)", self.df_strength)

        eng_box = QGroupBox("渲染引擎")
        eng_form = QFormLayout(eng_box)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("内置 (快速)", "builtin")
        self.engine_combo.addItem("RawTherapee (高质量)", "rawtherapee")
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        eng_form.addRow(self.engine_combo)
        eng_note = QLabel("RawTherapee 引擎预览较慢,\n但色彩科学与高光重建更佳")
        eng_note.setStyleSheet("color:#888;")
        eng_form.addRow(eng_note)

        self.btn_export = QPushButton("导出视频…")
        self.btn_export.clicked.connect(self.export_video)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(kf_box)
        rl.addWidget(df_box)
        rl.addWidget(eng_box)
        rl.addStretch(1)
        rl.addWidget(self.btn_export)
        right.setFixedWidth(300)

        central = QWidget()
        cl = QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(left, 1)
        cl.addWidget(right)
        self.setCentralWidget(central)

    def _set_enabled(self, on: bool):
        for w in (self.frame_slider, self.frame_spin, self.btn_add_kf, self.btn_del_kf,
                  self.df_enable, self.df_strength, self.btn_export, self.engine_combo,
                  *self.param_spins.values()):
            w.setEnabled(on)

    def _on_engine_changed(self):
        if self.project is None:
            return
        name = self.engine_combo.currentData()
        if name == self.project.engine:
            return
        from ..engines import get_engine
        if not get_engine(name).is_available():
            choice = QMessageBox.question(
                self, "Lumalapse",
                "未找到 RawTherapee。\n\n是否自动下载并安装?(约 100 MB,"
                "安装完成后将自动启用该引擎)\n\n也可以手动安装 "
                "https://rawtherapee.com 或设置环境变量 LUMALAPSE_RAWTHERAPEE。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
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
        dlg = QProgressDialog("正在准备下载…", None, 0, 0, self)  # indeterminate, no cancel
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
                    self, "Lumalapse",
                    "自动安装失败。请手动安装 https://rawtherapee.com,"
                    "或设置环境变量 LUMALAPSE_RAWTHERAPEE 指向 rawtherapee-cli。")
                self._revert_engine_combo()

        thread.done.connect(on_done)
        self._install_thread = thread  # keep alive
        thread.start()
        dlg.exec()

    # ---------- project lifecycle ----------

    def open_folder(self):
        start_dir = load_settings().get("last_folder", "")
        if start_dir and not Path(start_dir).is_dir():
            start_dir = ""
        folder = QFileDialog.getExistingDirectory(self, "选择延时序列文件夹", start_dir)
        if not folder:
            return
        try:
            project = Project.open_folder(folder)
        except ValueError as e:
            QMessageBox.warning(self, "Lumalapse", str(e))
            return
        self._analyze_and_load(project)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目", "", f"Lumalapse 项目 (*{PROJECT_SUFFIX})")
        if not path:
            return
        project = Project.load(path)
        self._analyze_and_load(project)

    def _analyze_and_load(self, project: Project):
        if project.analysis and len(project.analysis.get("luminance", [])) == project.n_frames:
            self._load_project(project)
            return
        dlg = QProgressDialog("正在分析曝光曲线…", "取消", 0, project.n_frames, self)
        dlg.setWindowModality(Qt.WindowModal)
        thread = AnalyzeThread(project)
        thread.progressed.connect(lambda d, t: (dlg.setMaximum(t), dlg.setValue(d)))
        thread.failed.connect(lambda tb: QMessageBox.critical(self, "分析失败", tb))
        thread.finished.connect(lambda: (dlg.close(), self._load_project(project)))
        dlg.canceled.connect(thread.terminate)
        self._analyze_thread = thread  # keep alive
        thread.start()
        dlg.exec()

    def _load_project(self, project: Project):
        if not project.analysis:
            return
        self.project = project
        project.save()
        update_settings(last_folder=project.folder)
        n = project.n_frames
        self.frame_slider.setRange(0, n - 1)
        self.frame_spin.setRange(0, n - 1)
        self.playhead.setBounds([0, n - 1])
        self.df_enable.setChecked(project.deflicker_enabled)
        self.df_strength.setValue(project.deflicker_strength)
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(project.engine)))
        self.engine_combo.blockSignals(False)
        self._set_enabled(True)
        self.setWindowTitle(f"Lumalapse — {Path(project.folder).name} ({n} 帧)")
        self.current_frame = -1
        self.refresh_curves()
        self.set_frame(0)

    def save_project(self):
        if self.project:
            self.project.save()
            self.statusBar().showMessage(f"已保存 {self.project.path}", 3000)

    # ---------- frame navigation ----------

    def set_frame(self, idx: int):
        if self.project is None or idx == self.current_frame:
            return
        idx = max(0, min(idx, self.project.n_frames - 1))
        self.current_frame = idx
        for w in (self.frame_slider, self.frame_spin):
            w.blockSignals(True)
            w.setValue(idx)
            w.blockSignals(False)
        self.playhead.blockSignals(True)
        self.playhead.setValue(idx)
        self.playhead.blockSignals(False)
        self.frame_info.setText(Path(self.project.files[idx]).name)
        self._sync_panel_from_frame()
        self._preview_timer.start()

    def _on_playhead_moved(self):
        self.set_frame(round(self.playhead.value()))

    # ---------- keyframes ----------

    def _sync_panel_from_frame(self):
        """Show keyframe params if on a keyframe, else interpolated values."""
        proj, idx = self.project, self.current_frame
        kf = proj.get_keyframe(idx)
        if kf:
            params = kf.params
        else:
            interp = interpolate_params(proj.keyframes, proj.n_frames, proj.interp_mode)
            params = {name: float(arr[idx]) for name, arr in interp.items()}
        self._loading_panel = True
        for name, spin in self.param_spins.items():
            spin.setValue(float(params.get(name, PARAM_DEFAULTS[name])))
        self._loading_panel = False
        self.kf_status.setText("● 此帧是关键帧" if kf else "○ 非关键帧(显示插值结果)")
        self.btn_del_kf.setEnabled(kf is not None)

    def _on_param_changed(self):
        if self._loading_panel or self.project is None:
            return
        # Editing params on a keyframe updates it live; otherwise creates one.
        self.project.set_keyframe(self.current_frame, self._panel_params())
        self.kf_status.setText("● 此帧是关键帧")
        self.btn_del_kf.setEnabled(True)
        self.refresh_curves()
        self._preview_timer.start()

    def _panel_params(self) -> dict:
        return {name: spin.value() for name, spin in self.param_spins.items()}

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

    # ---------- deflicker ----------

    def _on_deflicker_changed(self):
        if self.project is None:
            return
        self.project.deflicker_enabled = self.df_enable.isChecked()
        self.project.deflicker_strength = self.df_strength.value()
        self.refresh_curves()
        self._preview_timer.start()

    # ---------- curves & preview ----------

    def refresh_curves(self):
        proj = self.project
        lum = np.asarray(proj.analysis["luminance"], dtype=float)
        x = np.arange(proj.n_frames)
        self.curve_lum.setData(x, lum)
        params = proj.frame_params()
        self.curve_out.setData(x, lum + params["exposure"])
        kx = [k.frame for k in proj.keyframes]
        self.kf_scatter.setData(kx, lum[kx] + params["exposure"][kx] if kx else [])

    def _request_preview(self):
        if self.project is None:
            return
        self.loading_label.show()
        self.loading_label.raise_()
        self.preview_thread.request(self.project, self.current_frame, self.project.frame_params())

    def _on_preview_failed(self, message: str):
        self.loading_label.hide()
        self.statusBar().showMessage(f"预览渲染失败:{message}", 8000)

    def _on_preview_rendered(self, idx: int, frame: np.ndarray):
        self.loading_label.hide()
        h, w = frame.shape[:2]
        img = QImage(frame.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._preview_pixmap = QPixmap.fromImage(img)
        self._update_preview_label()

    def _update_preview_label(self):
        if self._preview_pixmap:
            self.preview_label.setPixmap(self._preview_pixmap.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_label()

    # ---------- export ----------

    def export_video(self):
        if self.project is None:
            return
        dlg = ExportDialog(self, self.project.folder)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        self.project.save()
        prog = QProgressDialog("正在渲染并编码…", "取消", 0, self.project.n_frames, self)
        prog.setWindowModality(Qt.WindowModal)
        thread = ExportThread(self.project, opts)
        thread.progressed.connect(lambda d, t: (prog.setMaximum(t), prog.setValue(d)))
        thread.finished_ok.connect(lambda out: (prog.close(), QMessageBox.information(
            self, "导出完成", f"已导出:\n{out}")))
        thread.failed.connect(lambda tb: (prog.close(), QMessageBox.critical(self, "导出失败", tb)))
        prog.canceled.connect(lambda: setattr(thread, "cancelled", True))
        self._export_thread = thread  # keep alive
        thread.start()

    def open_last_folder(self) -> bool:
        """Reopen the folder from the previous session, if it still has images."""
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


def run_gui(project_path: str | None = None) -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if project_path:
        p = Path(project_path)
        if p.is_dir():
            win._analyze_and_load(Project.open_folder(p))
        else:
            win._analyze_and_load(Project.load(p))
    else:
        win.open_last_folder()
    return app.exec()
