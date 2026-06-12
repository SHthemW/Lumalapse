"""Rendering engines.

builtin     - the numpy/OpenCV pipeline in lumalapse.adjustments (always available)
rawtherapee - renders through rawtherapee-cli with a generated PP3 profile,
              using RawTherapee's mature RAW pipeline (color science, highlight
              reconstruction, exposure/tone/saturation/dehaze)
"""

from __future__ import annotations

ENGINE_NAMES = ["builtin", "rawtherapee"]

_instances: dict = {}


def get_engine(name: str):
    if name not in _instances:
        if name == "builtin":
            from .builtin import BuiltinEngine

            _instances[name] = BuiltinEngine()
        elif name == "rawtherapee":
            from .rawtherapee import RawTherapeeEngine

            _instances[name] = RawTherapeeEngine()
        else:
            raise ValueError(f"Unknown engine {name!r}; choose from {ENGINE_NAMES}")
    return _instances[name]
