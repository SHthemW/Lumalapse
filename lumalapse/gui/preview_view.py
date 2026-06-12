"""Zoomable and pannable preview widget."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class PreviewView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self._fit = True
        self.setScene(self._scene)
        self.setBackgroundBrush(Qt.black)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setAlignment(Qt.AlignCenter)

    def set_pixmap(self, pixmap: QPixmap):
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(self._item.boundingRect())
        if self._fit:
            self.reset_zoom()

    def reset_zoom(self):
        if self._item.pixmap().isNull():
            return
        self._fit = True
        self.resetTransform()
        self.fitInView(self._item, Qt.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent):
        if self._item.pixmap().isNull():
            return
        self._fit = False
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        self.reset_zoom()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.reset_zoom()
