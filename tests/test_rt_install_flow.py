"""GUI auto-install flow test (offscreen, RT absence simulated).

Switching the engine combo to RawTherapee when rawtherapee-cli is missing must
pop a question dialog; answering Yes runs the installer thread and applies the
engine on success, answering No reverts the combo.

Usage: python test_rt_install_flow.py <demo_dir_with_.lumalapse>
"""

import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import lumalapse.engines as engines  # noqa: E402
import lumalapse.engines.rawtherapee as rt  # noqa: E402
from lumalapse.project import Project  # noqa: E402

# Simulate "RT not installed" and a successful install.
rt.find_cli = lambda: None
engines._instances.clear()
install_calls = []


def fake_install(progress=None):
    install_calls.append(1)
    if progress:
        progress("stub download")
    return r"C:\fake\rawtherapee-cli.exe"


rt.ensure_installed = fake_install

from lumalapse.gui import main_window as mw  # noqa: E402

asked = []
mw.QMessageBox.question = staticmethod(
    lambda *a, **k: (asked.append(1), QMessageBox.Yes)[1])
mw.QMessageBox.information = staticmethod(lambda *a, **k: None)
mw.QMessageBox.critical = staticmethod(lambda *a, **k: None)

app = QApplication([])
win = mw.MainWindow()
win._load_project(Project.open_folder(sys.argv[1]))
assert win.project.engine == "builtin"

# Yes path: dialog -> stub install -> engine applied
win.engine_combo.setCurrentIndex(win.engine_combo.findData("rawtherapee"))
assert asked, "question dialog was not shown"
assert install_calls, "installer was not invoked"
assert win.project.engine == "rawtherapee", "engine not applied after install"
print("auto-install YES path OK")

# No path: revert combo, keep engine
win.project.engine = "builtin"
win._revert_engine_combo()
mw.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
install_calls.clear()
win.engine_combo.setCurrentIndex(win.engine_combo.findData("rawtherapee"))
assert not install_calls, "installer must not run after No"
assert win.project.engine == "builtin"
assert win.engine_combo.currentData() == "builtin", "combo must revert after No"
print("auto-install NO path OK")

win.preview_thread.stop()
print("RT INSTALL FLOW TEST PASSED")
