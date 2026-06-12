"""Settings dialogs for the GUI."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

from ..analysis import DEFAULT_ANALYSIS_CPU_PERCENT
from ..settings import load_settings, update_settings


class ResourceSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("资源使用")
        form = QFormLayout(self)
        value = int(load_settings().get("analysis_cpu_percent", DEFAULT_ANALYSIS_CPU_PERCENT))
        value = min(max(value, 10), 100)
        self.analysis_cpu = QSpinBox(minimum=10, maximum=100, value=value, suffix="%")
        self.analysis_cpu.setSingleStep(5)
        form.addRow("分析 CPU 上限", self.analysis_cpu)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        update_settings(analysis_cpu_percent=self.analysis_cpu.value())
        super().accept()
