"""Reusable grading controls for the GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QSlider, QWidget


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
    "exposure": 0.1,
    "highlights": 0.05,
    "shadows": 0.05,
    "whites": 0.05,
    "blacks": 0.05,
    "contrast": 0.05,
    "saturation": 0.05,
    "dehaze": 0.05,
    "temperature": 0.05,
}


class ParamSlider(QWidget):
    """Horizontal slider with a precise numeric editor."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float, step: float, decimals: int = 2):
        super().__init__()
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = float(step)
        self._decimals = decimals
        self._ticks = max(1, round((self._maximum - self._minimum) / self._step))

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self._ticks)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, round(0.5 / self._step)))
        self.slider.setTickPosition(QSlider.NoTicks)
        self.slider.valueChanged.connect(self._on_slider_changed)

        self.spin = QDoubleSpinBox(
            minimum=self._minimum,
            maximum=self._maximum,
            singleStep=self._step,
            decimals=decimals,
            value=value,
        )
        self.spin.setFixedWidth(78)
        self.spin.valueChanged.connect(self._on_spin_changed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.setValue(value)

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, value: float):
        value = min(max(float(value), self._minimum), self._maximum)
        pos = self._value_to_pos(value)
        rounded = self._pos_to_value(pos)
        old_value = self.value()
        self.slider.blockSignals(True)
        self.spin.blockSignals(True)
        self.slider.setValue(pos)
        self.spin.setValue(rounded)
        self.spin.blockSignals(False)
        self.slider.blockSignals(False)
        if rounded != old_value:
            self.valueChanged.emit(rounded)

    def _value_to_pos(self, value: float) -> int:
        return round((value - self._minimum) / self._step)

    def _pos_to_value(self, pos: int) -> float:
        value = self._minimum + pos * self._step
        return round(min(max(value, self._minimum), self._maximum), self._decimals)

    def _on_slider_changed(self, pos: int):
        value = self._pos_to_value(pos)
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self.valueChanged.emit(value)

    def _on_spin_changed(self, value: float):
        pos = self._value_to_pos(value)
        self.slider.blockSignals(True)
        self.slider.setValue(pos)
        self.slider.blockSignals(False)
        self.valueChanged.emit(float(value))
