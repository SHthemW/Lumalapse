"""GUI smoke test: launch offscreen, load a project, render a preview, quit."""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lumalapse.gui.main_window import MainWindow  # noqa: E402
from lumalapse.project import Project  # noqa: E402

demo = sys.argv[1]
app = QApplication([])
win = MainWindow()
win.show()
win._load_project(Project.load(Path(demo) / "project.llproj"))
assert win.project is not None and win.project.n_frames > 0

state = {"ok": False}


def on_preview(idx, frame):
    state["ok"] = True
    print(f"preview rendered: frame {idx}, shape {frame.shape}")
    app.quit()


win.preview_thread.rendered.connect(on_preview)
win.set_frame(5)
QTimer.singleShot(15000, app.quit)  # safety timeout
app.exec()
win.preview_thread.stop()
assert state["ok"], "preview was never rendered"
print("GUI SMOKE TEST PASSED")
