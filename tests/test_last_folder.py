"""Last-folder restore test (offscreen).

Opening a sequence must record its folder in the app settings; a fresh window
must reopen it via open_last_folder(), and skip gracefully if it vanished.

Usage: python test_last_folder.py <demo_dir_with_.lumalapse>
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LUMALAPSE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="lumalapse_cfg_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from lumalapse.gui.main_window import MainWindow  # noqa: E402
from lumalapse.project import Project  # noqa: E402
from lumalapse.settings import load_settings, update_settings  # noqa: E402

demo = str(Path(sys.argv[1]).resolve())
app = QApplication([])

# Session 1: opening a folder records it.
win1 = MainWindow()
win1._load_project(Project.open_folder(demo))
assert load_settings().get("last_folder") == demo, "last_folder not recorded"
win1.preview_thread.stop()

# Session 2: a fresh window restores it (analysis cached -> loads synchronously).
win2 = MainWindow()
assert win2.open_last_folder(), "open_last_folder() failed"
assert win2.project is not None and win2.project.folder == demo
win2.preview_thread.stop()
print("restore OK")

# Vanished folder: returns False, no crash.
update_settings(last_folder=str(Path(tempfile.gettempdir()) / "lumalapse_gone_xyz"))
win3 = MainWindow()
assert not win3.open_last_folder()
assert win3.project is None
win3.preview_thread.stop()
print("missing-folder fallback OK")

print("LAST FOLDER TEST PASSED")
