"""Pre/post-processing for raw YOLOv8 outputs, in pure NumPy.

Why here and not inside each backend: the NPU runs only the convolutional core (see
docs/vision-research.md §3 and ST's advice to keep post-processing on the CPU). Decoding
raw tensors -> boxes/keypoints is therefore OUR job, and being backend-independent it can
be unit-tested without a board.

ASSUMED raw layouts (Ultralytics YOLOv8 export, NOT yet verified on the ST .tflite files):
  detection: (4 + n_classes, N)  rows = cx, cy, w, h, class scores
  pose:      (4 + 1 + 51, N)     rows = cx, cy, w, h, person score, 17 * (x, y, conf)
N = 1344 anchors at 256x256 (32² + 16² + 8²). The array may also arrive transposed (N, C).
Coordinates may be in input pixels or normalised to [0, 1]; `coords_normalized=None`
auto-detects by magnitude. Check both against the real model on the board.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .classes import NUM_KPTS
from .types import Box, Detection, PersonPose


@dataclass(frozen=True)
class Letterbox:
    """Geometry of resizing a frame into a square model input keeping aspect ratio."""

    scale: float
    pad_x: float
    pad_y: float
    size: int

    @classmethod
    def compute(cls, src_w: int, src_h: int, size: int) -> "Letterbox":
        scale = min(size / src_w, size / src_h)
        new_w, new_h = round(src_w * scale), round(src_h * scale)
        # Integer padding: the preprocessing pastes the image at exactly this offset, so
        # the inverse mapping below is exact (no half-pixel drift).
        return cls(scale, float((size - new_w) // 2), float((size - new_h) // 2), size)

    def to_frame(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Model-input pixel coordinates -> original frame coordinates."""
        return (x - self.pad_x) / self.scale, (y - self.pad_y) / self.scale


def dequantize(arr: np.ndarray, scale: float, zero_point: int) -> np.ndarray:
    """int8/uint8 tensor -> float32: real = (q - zero_point) * scale."""
    return (arr.astype(np.float32) - zero_point) * scale


def quantize_input(x01: np.ndarray, dtype: np.dtype, scale: float, zero_point: int) -> np.ndarray:
    """Float image in [0,1] -> the dtype the model expects (q = x/scale + zero_point)."""
    dtype = np.dtype(dtype)
    if dtype.kind == "f":
        return x01.astype(dtype)
    info = np.iinfo(dtype)
    q = np.round(x01 / scale) + zero_point
    return np.clip(q, info.min, info.max).astype(dtype)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    """Greedy non-maximum suppression. boxes: (n,4) xyxy. Returns kept indices."""
    order = np.argsort(-scores)
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_r = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        iou = inter / np.maximum(area_i + area_r - inter, 1e-9)
        order = rest[iou <= iou_thr]
    return keep


def _channels_first(raw: np.ndarray, n_channels: int) -> np.ndarray:
    a = np.asarray(raw, dtype=np.float32)
    if a.ndim == 3:
        a = np.squeeze(a, axis=0)
    if a.shape[0] == n_channels:
        return a
    if a.shape[1] == n_channels:
        return a.T
    raise ValueError(f"expected {n_channels} channels, got shape {a.shape}")


def _to_pixels(a: np.ndarray, rows: slice, size: int, normalized: bool | None) -> np.ndarray:
    if normalized is None:
        normalized = float(np.abs(a[rows]).max()) <= 2.0  # real pixel values reach ~size
    return a[rows] * size if normalized else a[rows]


def _xywh_to_xyxy(cx, cy, w, h) -> np.ndarray:
    return np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)


def _clip_box(x1, y1, x2, y2, lb_w, lb_h) -> Box:
    return Box(float(np.clip(x1, 0, lb_w)), float(np.clip(y1, 0, lb_h)),
               float(np.clip(x2, 0, lb_w)), float(np.clip(y2, 0, lb_h)))


def decode_detections(
    raw: np.ndarray, n_classes: int, lb: Letterbox, frame_w: int, frame_h: int,
    conf_thr: float = 0.35, iou_thr: float = 0.5, coords_normalized: bool | None = None,
) -> list[Detection]:
    a = _channels_first(raw, 4 + n_classes).copy()
    a[:4] = _to_pixels(a, slice(0, 4), lb.size, coords_normalized)
    scores = a[4:]
    cls = scores.argmax(axis=0)
    conf = scores.max(axis=0)
    sel = conf >= conf_thr
    if not sel.any():
        return []
    boxes = _xywh_to_xyxy(a[0, sel], a[1, sel], a[2, sel], a[3, sel])
    cls, conf = cls[sel], conf[sel]

    out: list[Detection] = []
    for c in np.unique(cls):  # class-aware NMS: a chair box must not suppress a person box
        idx = np.where(cls == c)[0]
        for k in nms(boxes[idx], conf[idx], iou_thr):
            x1, y1 = lb.to_frame(boxes[idx[k], 0], boxes[idx[k], 1])
            x2, y2 = lb.to_frame(boxes[idx[k], 2], boxes[idx[k], 3])
            out.append(Detection(int(c), float(conf[idx[k]]), _clip_box(x1, y1, x2, y2, frame_w, frame_h)))
    return sorted(out, key=lambda d: -d.conf)


def decode_poses(
    raw: np.ndarray, lb: Letterbox, frame_w: int, frame_h: int,
    conf_thr: float = 0.35, iou_thr: float = 0.5, coords_normalized: bool | None = None,
) -> list[PersonPose]:
    n_ch = 5 + 3 * NUM_KPTS
    a = _channels_first(raw, n_ch).copy()
    # Decide once, from the box rows, whether coordinates are normalised; keypoint x/y
    # rows follow the same convention (their confidence rows must NOT be scaled).
    normalized = coords_normalized
    if normalized is None:
        normalized = float(np.abs(a[:4]).max()) <= 2.0
    factor = lb.size if normalized else 1.0
    a[:4] *= factor
    xy_rows = [5 + 3 * i + j for i in range(NUM_KPTS) for j in (0, 1)]
    a[xy_rows] *= factor
    conf = a[4]
    sel = conf >= conf_thr
    if not sel.any():
        return []
    boxes = _xywh_to_xyxy(a[0, sel], a[1, sel], a[2, sel], a[3, sel])
    conf = conf[sel]
    kps = a[5:, sel].reshape(NUM_KPTS, 3, -1)  # (17, [x,y,c], n)

    out: list[PersonPose] = []
    for k in nms(boxes, conf, iou_thr):
        x1, y1 = lb.to_frame(boxes[k, 0], boxes[k, 1])
        x2, y2 = lb.to_frame(boxes[k, 2], boxes[k, 3])
        kx, ky = lb.to_frame(kps[:, 0, k], kps[:, 1, k])
        out.append(PersonPose(
            _clip_box(x1, y1, x2, y2, frame_w, frame_h), float(conf[k]),
            np.stack([kx, ky, kps[:, 2, k]], axis=1).astype(np.float32),
        ))
    return sorted(out, key=lambda p: -p.conf)
