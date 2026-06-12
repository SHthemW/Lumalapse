"""Live-preview test: changing a parameter must auto-refresh the preview,
and the cached re-render must skip the decode (much faster than the first).

Usage: python test_live_preview.py <demo_dir_with_project.llproj>
"""

import os
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lumalapse.gui.main_window import MainWindow  # noqa: E402
from lumalapse.project import Project  # noqa: E402

demo = sys.argv[1]
app = QApplication([])
win = MainWindow()
win.show()
win._load_project(Project.load(Path(demo) / "project.llproj"))

previews = []  # (time, idx, mean brightness)


def on_preview(idx, frame):
    previews.append((time.perf_counter(), idx, float(np.mean(frame))))
    if len(previews) == 1:
        # First preview arrived; now simulate the user raising exposure.
        QTimer.singleShot(0, lambda: win.param_spins["exposure"].setValue(2.0))
    else:
        app.quit()


win.preview_thread.rendered.connect(on_preview)
t0 = time.perf_counter()
win.set_frame(5)
QTimer.singleShot(20000, app.quit)  # safety timeout
app.exec()
win.preview_thread.stop()

assert len(previews) >= 2, f"expected a second preview after param change, got {len(previews)}"
(t1, i1, b1), (t2, i2, b2) = previews[0], previews[1]
first_render = t1 - t0
second_render = t2 - t1
print(f"first render  (decode+grade): {first_render * 1000:.0f} ms, brightness {b1:.1f}")
print(f"param change -> new preview:  {second_render * 1000:.0f} ms, brightness {b2:.1f}")
assert i1 == i2 == 5
assert b2 > b1 + 20, f"exposure +2EV must brighten preview ({b1:.1f} -> {b2:.1f})"
assert win.project.get_keyframe(5) is not None, "param edit should create a keyframe"
print("LIVE PREVIEW TEST PASSED")
