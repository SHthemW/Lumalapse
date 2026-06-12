"""Main window layout construction."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg

from ..keyframes import PARAM_DEFAULTS, PARAM_RANGES
from .param_controls import PARAM_LABELS, PARAM_STEPS, ParamSlider
from .preview_view import PreviewView


PREVIEW_QUALITY_OPTIONS = [
    ("低 (720P)", (720, False)),
    ("标准 (1200P)", (1200, False)),
    ("高 (2160P)", (2160, False)),
    ("原画", (None, False)),
]


def build_menu(win):
    file_menu = win.menuBar().addMenu("文件(&F)")
    for text, slot, key in [
        ("打开图片文件夹...", win.open_folder, "Ctrl+O"),
        ("打开项目...", win.open_project, "Ctrl+Shift+O"),
        ("保存项目", win.save_project, "Ctrl+S"),
        ("导出视频...", win.export_video, "Ctrl+E"),
    ]:
        action = QAction(text, win)
        action.setShortcut(key)
        action.triggered.connect(slot)
        file_menu.addAction(action)

    settings_menu = win.menuBar().addMenu("设置")
    resource_action = QAction("资源使用...", win)
    resource_action.triggered.connect(win.edit_resource_settings)
    settings_menu.addAction(resource_action)
    quality_menu = settings_menu.addMenu("预览画质")
    group = QActionGroup(win)
    group.setExclusive(True)
    win.preview_quality_actions = []
    for text, data in PREVIEW_QUALITY_OPTIONS:
        action = QAction(text, win)
        action.setCheckable(True)
        action.setData(data)
        action.triggered.connect(win._on_preview_quality_changed)
        group.addAction(action)
        quality_menu.addAction(action)
        win.preview_quality_actions.append(action)
    win.preview_quality_actions[1].setChecked(True)


def build_ui(win):
    win.preview_view = PreviewView()
    win.loading_label = QLabel("渲染中...", win.preview_view)
    win.loading_label.setStyleSheet(
        "background:rgba(0,0,0,160);color:#ddd;padding:4px 12px;border-radius:4px;"
    )
    win.loading_label.move(12, 12)
    win.loading_label.hide()

    pg.setConfigOptions(antialias=True, background="#202020", foreground="#cccccc")
    win.plot = pg.PlotWidget()
    win.plot.setLabel("bottom", "帧")
    win.plot.setLabel("left", "log2 亮度")
    win.plot.showGrid(x=True, y=True, alpha=0.2)
    win.curve_lum = win.plot.plot(pen=pg.mkPen("#4aa3ff", width=1.5), name="原始亮度")
    win.curve_out = win.plot.plot(pen=pg.mkPen("#ffb84a", width=1.5), name="调整后")
    win.kf_scatter = pg.ScatterPlotItem(size=11, brush=pg.mkBrush("#ff5555"), pen=pg.mkPen("w", width=0.5), symbol="d")
    win.plot.addItem(win.kf_scatter)
    win.playhead = pg.InfiniteLine(0, angle=90, movable=True, pen=pg.mkPen("#88ff88", width=1))
    win.playhead.sigPositionChanged.connect(win._on_playhead_moved)
    win.plot.addItem(win.playhead)
    legend = win.plot.addLegend(offset=(8, 8))
    legend.addItem(win.curve_lum, "原始亮度")
    legend.addItem(win.curve_out, "调整后(含去闪)")

    win.frame_slider = QSlider(Qt.Horizontal)
    win.frame_slider.valueChanged.connect(win.set_frame)
    win.frame_spin = QSpinBox()
    win.frame_spin.valueChanged.connect(win.set_frame)
    win.frame_info = QLabel("")
    nav = QHBoxLayout()
    nav.addWidget(QLabel("帧"))
    nav.addWidget(win.frame_slider, 1)
    nav.addWidget(win.frame_spin)
    nav.addWidget(win.frame_info)

    left = QWidget()
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(4, 4, 4, 4)
    split = QSplitter(Qt.Vertical)
    split.addWidget(win.preview_view)
    split.addWidget(win.plot)
    split.setStretchFactor(0, 3)
    split.setStretchFactor(1, 1)
    left_layout.addWidget(split, 1)
    left_layout.addLayout(nav)

    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.addWidget(_build_keyframe_box(win))
    right_layout.addWidget(_build_deflicker_box(win))
    right_layout.addWidget(_build_engine_box(win))
    right_layout.addStretch(1)
    win.btn_export = QPushButton("导出视频...")
    win.btn_export.clicked.connect(win.export_video)
    right_layout.addWidget(win.btn_export)
    right.setFixedWidth(360)

    central = QWidget()
    central_layout = QHBoxLayout(central)
    central_layout.setContentsMargins(0, 0, 0, 0)
    central_layout.addWidget(left, 1)
    central_layout.addWidget(right)
    win.setCentralWidget(central)


def _build_keyframe_box(win) -> QGroupBox:
    box = QGroupBox("当前帧关键帧参数")
    form = QFormLayout(box)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    win.param_spins = {}
    for name in PARAM_DEFAULTS:
        lo, hi = PARAM_RANGES[name]
        editor = ParamSlider(lo, hi, PARAM_DEFAULTS[name], PARAM_STEPS[name], decimals=2)
        editor.valueChanged.connect(win._on_param_changed)
        win.param_spins[name] = editor
        form.addRow(PARAM_LABELS[name], editor)
    win.kf_status = QLabel("")
    form.addRow(win.kf_status)
    win.btn_add_kf = QPushButton("在当前帧添加关键帧")
    win.btn_add_kf.clicked.connect(win.add_keyframe)
    win.btn_del_kf = QPushButton("删除当前帧关键帧")
    win.btn_del_kf.clicked.connect(win.remove_keyframe)
    form.addRow(win.btn_add_kf)
    form.addRow(win.btn_del_kf)
    return box


def _build_deflicker_box(win) -> QGroupBox:
    box = QGroupBox("去闪 (Deflicker)")
    form = QFormLayout(box)
    win.df_enable = QCheckBox("启用基于曝光的去闪")
    win.df_enable.toggled.connect(win._on_deflicker_changed)
    win.df_strength = ParamSlider(1, 200, 10, 1, decimals=0)
    win.df_strength.valueChanged.connect(win._on_deflicker_changed)
    form.addRow(win.df_enable)
    form.addRow("平滑强度(帧)", win.df_strength)
    return box


def _build_engine_box(win) -> QGroupBox:
    box = QGroupBox("渲染引擎")
    form = QFormLayout(box)
    win.engine_combo = QComboBox()
    win.engine_combo.addItem("内置 (快速)", "builtin")
    win.engine_combo.addItem("RawTherapee (高质量)", "rawtherapee")
    win.engine_combo.currentIndexChanged.connect(win._on_engine_changed)
    form.addRow(win.engine_combo)
    note = QLabel("RawTherapee 引擎预览较慢,\n但色彩科学与高光重建更佳")
    note.setStyleSheet("color:#888;")
    form.addRow(note)
    return box


def set_controls_enabled(win, enabled: bool):
    controls = (
        win.frame_slider,
        win.frame_spin,
        win.btn_add_kf,
        win.btn_del_kf,
        win.df_enable,
        win.df_strength,
        win.btn_export,
        win.engine_combo,
        *win.param_spins.values(),
    )
    for control in controls:
        control.setEnabled(enabled)
    for action in win.preview_quality_actions:
        action.setEnabled(enabled)
