"""Plain data containers shared by all backends. Pixel coordinates in the ORIGINAL frame."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def center(self) -> tuple[float, float]:
        return (0.5 * (self.x1 + self.x2), 0.5 * (self.y1 + self.y2))

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def intersection_area(self, other: "Box") -> float:
        iw = min(self.x2, other.x2) - max(self.x1, other.x1)
        ih = min(self.y2, other.y2) - max(self.y1, other.y1)
        return max(0.0, iw) * max(0.0, ih)


@dataclass(frozen=True)
class Detection:
    cls_id: int
    conf: float
    box: Box


@dataclass(frozen=True)
class PersonPose:
    box: Box
    conf: float
    keypoints: np.ndarray  # shape (17, 3): x, y, confidence (pixels of the original frame)
