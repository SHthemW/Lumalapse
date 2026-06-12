"""GUI application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ..project import Project
from .main_window import MainWindow


def run_gui(project_path: str | None = None) -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    if project_path:
        path = Path(project_path)
        project = Project.open_folder(path) if path.is_dir() else Project.load(path)
        win._analyze_and_load(project)
    else:
        win.open_last_folder()
    return app.exec()
