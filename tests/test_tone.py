"""Tone control tests: highlights/shadows/whites/blacks behavior, and that
highlight/white recovery really uses unclipped >1.0 linear data instead of
flattening it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lumalapse.adjustments import apply_adjustments  # noqa: E402

# Linear gradient scene covering deep shadow to just-below-white.
BASE = np.tile(np.linspace(0.002, 0.9, 256, dtype=np.float32)[None, :, None], (8, 1, 3))


def render(params: dict) -> np.ndarray:
    return apply_adjustments(BASE.copy(), params)


def main():
    neutral = render({})

    # --- highlight recovery uses >1 overshoot ---------------------------
    # +1.2 EV pushes the top of the gradient to linear ~2.0: without recovery
    # the brightest quarter clips to a flat 255.
    over = render({"exposure": 1.2})
    top = over[0, 192:, 0].astype(int)
    assert (top == 255).sum() > 40, "test premise: overexposure must clip"

    recovered = render({"exposure": 1.2, "highlights": -1.0})
    top_rec = recovered[0, 192:, 0].astype(int)
    assert (top_rec == 255).sum() < 5, "highlights=-1 must unclip the top"
    assert len(np.unique(top_rec)) > 20, "recovered highlights must keep gradient detail"

    # whites=-1 lowers the white point exactly one stop, so it fully recovers
    # a +0.9 EV overshoot (top of gradient at linear ~1.68 < 2.0).
    over_w = render({"exposure": 0.9})
    assert (over_w[0, 192:, 0].astype(int) == 255).sum() > 20, "premise: must clip"
    rec_w = render({"exposure": 0.9, "whites": -1.0})
    assert (rec_w[0, 192:, 0].astype(int) == 255).sum() == 0
    assert len(np.unique(rec_w[0, 192:, 0])) > 20

    # whites=+0.5 brightens the top end.
    bright_w = render({"whites": 0.5})
    assert bright_w[0, 200, 0] > neutral[0, 200, 0]

    # --- shadows -----------------------------------------------------------
    lifted = render({"shadows": 1.0})
    assert lifted[0, 10, 0] > neutral[0, 10, 0] + 15, "shadows=+1 must lift darks"
    hi_change = abs(int(lifted[0, 250, 0]) - int(neutral[0, 250, 0]))
    assert hi_change <= 2, f"shadows must not move highlights (changed {hi_change})"

    # --- blacks ------------------------------------------------------------
    crushed = render({"blacks": -1.0})
    assert crushed[0, 10, 0] < neutral[0, 10, 0], "blacks=-1 must darken the floor"
    lifted_b = render({"blacks": 1.0})
    assert lifted_b[0, 0, 0] > neutral[0, 0, 0], "blacks=+1 must lift the floor"

    # --- defaults are a no-op vs the old pipeline ---------------------------
    assert np.array_equal(neutral, render({"highlights": 0, "shadows": 0,
                                           "whites": 0, "blacks": 0}))

    print("TONE CONTROL TESTS PASSED")


if __name__ == "__main__":
    main()
