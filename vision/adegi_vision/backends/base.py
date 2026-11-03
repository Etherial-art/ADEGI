"""Backend interface. The pipeline only talks to this, so swapping hardware is a flag."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..types import Detection, PersonPose


class InferenceBackend(ABC):
    """Runs the two models. Frames are BGR uint8 arrays (H, W, 3), as OpenCV delivers them."""

    name = "base"

    @abstractmethod
    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Furniture / aids detector (7 ADEGI classes). Run every N frames."""

    @abstractmethod
    def pose(self, frame: np.ndarray) -> list[PersonPose]:
        """17-keypoint pose of every person. Run every frame."""

    def close(self) -> None:
        """Release resources (sockets, NPU contexts)."""
