"""Built-in engine: rawpy decode + numpy tone pipeline (lumalapse.adjustments)."""

from __future__ import annotations

from collections import OrderedDict

import numpy as np

from .. import loader
from ..adjustments import apply_adjustments

# Decoded-image cache for interactive previews: re-grading a frame after a
# parameter tweak then only costs the adjustment pass (~ms), not a RAW decode
# (~seconds). apply_adjustments never mutates its input, so sharing is safe.
_DECODE_CACHE: OrderedDict[tuple, np.ndarray] = OrderedDict()
_DECODE_CACHE_MAX = 8  # ~10 MB per 1100px preview frame


class BuiltinEngine:
    name = "builtin"

    def is_available(self) -> bool:
        return True

    def render(self, path: str, params: dict, half_size: bool = False,
               max_dim: int | None = None, cache: bool = False) -> np.ndarray:
        """Render one graded frame as uint8 RGB."""
        if cache:
            img = self._load_cached(path, half_size, max_dim)
        else:
            img = loader.load_linear(path, half_size=half_size, max_dim=max_dim)
        return apply_adjustments(img, params)

    @staticmethod
    def _load_cached(path: str, half_size: bool, max_dim: int | None) -> np.ndarray:
        key = (path, half_size, max_dim)
        img = _DECODE_CACHE.get(key)
        if img is None:
            img = loader.load_linear(path, half_size=half_size, max_dim=max_dim)
            _DECODE_CACHE[key] = img
            if len(_DECODE_CACHE) > _DECODE_CACHE_MAX:
                _DECODE_CACHE.popitem(last=False)
        else:
            _DECODE_CACHE.move_to_end(key)
        return img
