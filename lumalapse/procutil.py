"""Subprocess helpers."""

import os

# Pass as creationflags= on every subprocess call: stops child processes
# (ffmpeg, rawtherapee-cli, winget) from flashing console windows when the
# GUI runs under pythonw on Windows. 0 elsewhere (the documented default).
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # subprocess.CREATE_NO_WINDOW
