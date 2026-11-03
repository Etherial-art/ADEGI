"""Development backend: Ultralytics on a PC (CPU/GPU). Not used on the board.

Why it exists: lets you debug the whole pipeline (rules, interleaving, events) with a
webcam or a video file before touching the NPU. Weights can be .pt or exported files.
"""

from __future__ import annotations

import numpy as np

from ..classes import CLASS_ID, NUM_KPTS
from ..types import Box, Detection, PersonPose
from .base import InferenceBackend


class UltralyticsBackend(InferenceBackend):
    name = "ultralytics"

    def __init__(self, det_weights: str, pose_weights: str, imgsz: int = 256,
                 det_conf: float = 0.35, pose_conf: float = 0.35, device: str | None = None):
        from ultralytics import YOLO  # lazy: the board does not have Ultralytics installed

        self._det = YOLO(det_weights)
        self._pose = YOLO(pose_weights)
        self._imgsz, self._det_conf, self._pose_conf, self._device = imgsz, det_conf, pose_conf, device

    def detect(self, frame: np.ndarray) -> list[Detection]:
        res = self._det.predict(frame, imgsz=self._imgsz, conf=self._det_conf,
                                device=self._device, verbose=False)[0]
        out: list[Detection] = []
        for xyxy, conf, cls in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                                   res.boxes.cls.cpu().numpy()):
            # Map by NAME, not id: lets you plug a plain COCO model during early tests.
            cls_id = CLASS_ID.get(res.names[int(cls)])
            if cls_id is not None:
                out.append(Detection(cls_id, float(conf), Box(*map(float, xyxy))))
        return out

    def pose(self, frame: np.ndarray) -> list[PersonPose]:
        res = self._pose.predict(frame, imgsz=self._imgsz, conf=self._pose_conf,
                                 device=self._device, verbose=False)[0]
        if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
            return []
        kps = res.keypoints.data.cpu().numpy()  # (n, 17, 3)
        if kps.shape[1:] != (NUM_KPTS, 3):
            raise ValueError(f"pose model returned keypoints {kps.shape}, expected (n, 17, 3)")
        return [
            PersonPose(Box(*map(float, xyxy)), float(conf), kp.astype(np.float32))
            for xyxy, conf, kp in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), kps)
        ]
