"""Synthetic skeleton builders for tests (no models, no images needed)."""

from __future__ import annotations

import numpy as np

from adegi_vision.types import Box


def kp_array(points: dict[int, tuple[float, float]], conf: float = 0.9) -> np.ndarray:
    kp = np.zeros((17, 3), dtype=np.float32)
    for i, (x, y) in points.items():
        kp[i] = (x, y, conf)
    return kp


def standing_person() -> tuple[Box, np.ndarray]:
    """Tall box 100x300 at (100,100); shoulders y=150, hips y=250, knees y=330."""
    box = Box(100, 100, 200, 400)
    kp = kp_array({
        0: (150, 110), 5: (125, 150), 6: (175, 150), 11: (130, 250), 12: (170, 250),
        13: (130, 330), 14: (170, 330), 15: (130, 390), 16: (170, 390),
    })
    return box, kp


def lying_person(x0: float = 100, y_hip: float = 280) -> tuple[Box, np.ndarray]:
    """Wide box 300x80: head at left, feet at right, torso horizontal at y~y_hip."""
    box = Box(x0, y_hip - 40, x0 + 300, y_hip + 40)
    kp = kp_array({
        0: (x0 + 20, y_hip), 5: (x0 + 70, y_hip - 10), 6: (x0 + 70, y_hip + 10),
        11: (x0 + 160, y_hip - 10), 12: (x0 + 160, y_hip + 10),
        13: (x0 + 230, y_hip - 10), 14: (x0 + 230, y_hip + 10),
        15: (x0 + 290, y_hip - 10), 16: (x0 + 290, y_hip + 10),
    })
    return box, kp
