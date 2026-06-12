"""Export options dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
)


class ExportDialog(QDialog):
    def __init__(self, parent, default_dir: str):
        super().__init__(parent)
        self.setWindowTitle("导出视频")
        form = QFormLayout(self)

        self.path_edit = QLineEdit(str(Path(default_dir) / "timelapse.mp4"))
        browse = QPushButton("...")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        form.addRow("输出文件", row)

        self.fps = QDoubleSpinBox(minimum=1, maximum=120, value=25, decimals=2)
        form.addRow("帧率 (fps)", self.fps)
        self.width = QSpinBox(minimum=0, maximum=8192, value=1920)
        self.width.setSpecialValueText("原始宽度")
        form.addRow("输出宽度", self.width)
        self.render_engine = QComboBox()
        self.render_engine.addItem("当前项目引擎", None)
        self.render_engine.addItem("高质量 RAW 冲洗 (RawTherapee)", "rawtherapee")
        form.addRow("渲染质量", self.render_engine)
        self.codec = QComboBox()
        self.codec.addItems(["h264", "h265", "prores"])
        form.addRow("编码", self.codec)
        self.quality = QSpinBox(minimum=0, maximum=51, value=17)
        form.addRow("质量 (CRF)", self.quality)
        self.half = QCheckBox("半尺寸解码 RAW(更快)")
        form.addRow("", self.half)
        self.keep_jpg = QCheckBox("保留中间 JPG 帧")
        form.addRow("", self.keep_jpg)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出视频", self.path_edit.text(), "Video (*.mp4 *.mov *.mkv)")
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
            "engine_name": self.render_engine.currentData(),
            "keep_jpg": self.keep_jpg.isChecked(),
        }
