"""Detector interface plus simulated detectors used for tests and demos.

Real implementations (YOLO on the Jetson GPU, YOLO int8 on the MP257 NPU) only
need to provide ``name`` and ``detect()``. Nothing else in the bridge changes.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Protocol


class Detector(Protocol):
    name: str

    def detect(self, jpeg: bytes, width: int, height: int) -> list[dict[str, Any]]:
        """Return detections: [{"cls": str, "conf": float, "bbox": [x1,y1,x2,y2]}].

        bbox is in pixels of the frame that was sent (xyxy, origin top-left).
        """
        ...


class SimulatedDetector:
    """Deterministic fake: one 'person' whose box depends on the frame bytes.

    ``delay`` simulates inference time. ``fail`` makes detect() raise, to test
    error handling. Different ``name`` values let tests tell which side
    answered.
    """

    def __init__(self, name: str = "sim", delay: float = 0.0) -> None:
        self.name = name
        self.delay = delay
        self.fail = False

    def detect(self, jpeg: bytes, width: int, height: int) -> list[dict[str, Any]]:
        if self.fail:
            raise RuntimeError("simulated detector failure")
        if self.delay:
            time.sleep(self.delay)
        digest = hashlib.sha256(jpeg).digest()
        x1 = digest[0] / 255 * width * 0.5
        y1 = digest[1] / 255 * height * 0.5
        return [{
            "cls": "person",
            "conf": round(0.5 + digest[2] / 255 * 0.5, 3),
            "bbox": [round(x1, 1), round(y1, 1),
                     round(x1 + width * 0.25, 1), round(y1 + height * 0.4, 1)],
        }]
