"""Adobe DCP status UI test (offscreen).

The engine box must show whether Adobe DNG Converter's profiles are present,
which color profile the current sequence will get, and offer an install
button only when the profiles are missing.

Usage: python test_adobe_status.py <demo_dir_with_.lumalapse>
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LUMALAPSE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="lumalapse_cfg_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

import lumalapse.engines.rawtherapee as rt  # noqa: E402
from lumalapse.gui import main_window as mw  # noqa: E402
from lumalapse.project import Project  # noqa: E402

demo = sys.argv[1]
app = QApplication([])

# --- not installed ---------------------------------------------------------
empty = Path(tempfile.mkdtemp(prefix="no_adobe_"))
rt.ADOBE_PROFILE_DIRS = [empty / "missing"]
rt._adobe_dcp_cache.clear()

win = mw.MainWindow()
assert "未安装" in win.adobe_status.text()
assert not win.btn_install_adobe.isHidden(), "install button must show when missing"

win._load_project(Project.open_folder(demo))
assert "本序列色彩档" in win.dcp_status.text()
# demo JPEGs have no camera model -> standard matrix fallback message
assert "标准色彩矩阵" in win.dcp_status.text() or "自动匹配" in win.dcp_status.text()
print("missing state OK:", win.adobe_status.text(), "|", win.dcp_status.text())

# --- installed (fake profile dir) ------------------------------------------
profiles = Path(tempfile.mkdtemp(prefix="adobe_")) / "CameraProfiles"
std = profiles / "Adobe Standard"
std.mkdir(parents=True)
(std / "Nikon D850 Adobe Standard.dcp").write_bytes(b"x")
(std / "Canon EOS R5 Adobe Standard.dcp").write_bytes(b"x")
rt.ADOBE_PROFILE_DIRS = [profiles]
rt._adobe_dcp_cache.clear()

win._update_adobe_status()
assert "已安装" in win.adobe_status.text() and "2" in win.adobe_status.text()
assert win.btn_install_adobe.isHidden(), "install button must hide when installed"
print("installed state OK:", win.adobe_status.text())

# --- install flow with stubbed installer ------------------------------------
rt.ADOBE_PROFILE_DIRS = [empty / "missing"]
rt._adobe_dcp_cache.clear()
win._update_adobe_status()
assert not win.btn_install_adobe.isHidden()

calls = []


def fake_install(progress=None):
    calls.append(1)
    rt.ADOBE_PROFILE_DIRS = [profiles]  # "installation" makes profiles appear
    rt._adobe_dcp_cache.clear()
    return True


rt.install_dng_converter = fake_install
mw.QMessageBox.information = staticmethod(lambda *a, **k: None)
win.install_adobe_dcp()
assert calls, "installer was not invoked"
assert "已安装" in win.adobe_status.text(), "status must refresh after install"
assert win.btn_install_adobe.isHidden()
print("install flow OK")

win.preview_thread.stop()
print("ADOBE STATUS TESTS PASSED")
