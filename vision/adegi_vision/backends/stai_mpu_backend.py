"""On-board backend: STM32MP257 NPU through ST's STAI MPU Python API.

!!! UNVERIFIED API !!!  The `stai_mpu` calls inside `_StaiNet` were written from memory of
ST's examples and could NOT be checked in this session (wiki.st.com was unreachable).
Compare `_StaiNet` against the example shipped with the `stai-mpu-pose-estimation-python`
package from X-LINUX-AI and fix names there. Everything else (letterbox, quantisation,
decode) is plain NumPy, unit-tested, and independent of that API.

Why a thin `_StaiNet` adapter: it isolates the only part we could not verify, and tests can
inject a fake net (`det_net=` / `pose_net=`) to exercise the real pre/post-processing.

Per ST, the NPU needs a per-tensor int8 model compiled to NBG (.nb). A per-channel
model "mainly runs on GPU" (ST wiki). See vision/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..classes import CLASS_NAMES
from ..decode import Letterbox, decode_detections, decode_poses, dequantize, quantize_input
from ..types import Detection, PersonPose
from .base import InferenceBackend


@dataclass(frozen=True)
class TensorSpec:
    shape: tuple[int, ...]
    dtype: np.dtype
    scale: float = 1.0
    zero_point: int = 0


class Net(Protocol):
    input_spec: TensorSpec
    output_spec: TensorSpec

    def run(self, tensor: np.ndarray) -> np.ndarray: ...


class _StaiNet:
    """Adapter over stai_mpu (UNVERIFIED, see module docstring)."""

    def __init__(self, model_path: str, use_npu: bool = True):
        from stai_mpu import stai_mpu_network  # only exists on OpenSTLinux + X-LINUX-AI

        self._net = stai_mpu_network(model_path=model_path, use_hw_acceleration=use_npu)
        in_info = self._net.get_input_infos()[0]
        out_info = self._net.get_output_infos()[0]
        self.input_spec = TensorSpec(tuple(in_info.get_shape()), np.dtype(in_info.get_dtype()),
                                     *self._qparams(in_info))
        self.output_spec = TensorSpec(tuple(out_info.get_shape()), np.dtype(out_info.get_dtype()),
                                      *self._qparams(out_info))

    @staticmethod
    def _qparams(info) -> tuple[float, int]:
        q = info.get_qparams()  # UNVERIFIED
        return float(q.scale), int(q.zero_point)

    def run(self, tensor: np.ndarray) -> np.ndarray:
        self._net.set_input(0, tensor)
        self._net.run()
        return np.asarray(self._net.get_output(0))


class StaiMpuBackend(InferenceBackend):
    name = "stai_mpu"

    def __init__(self, det_model: str | None = None, pose_model: str | None = None, *,
                 det_net: Net | None = None, pose_net: Net | None = None,
                 det_conf: float = 0.35, pose_conf: float = 0.35, iou: float = 0.5):
        self._det_net = det_net or _StaiNet(det_model)
        self._pose_net = pose_net or _StaiNet(pose_model)
        self._det_conf, self._pose_conf, self._iou = det_conf, pose_conf, iou

    @staticmethod
    def _preprocess(frame: np.ndarray, spec: TensorSpec) -> tuple[np.ndarray, Letterbox]:
        import cv2  # python3-opencv ships with X-LINUX-AI images; lazy for tests

        nchw = spec.shape[1] == 3  # TFLite models are NHWC (…,H,W,3); some NBGs report NCHW
        size = spec.shape[2] if nchw else spec.shape[1]
        h, w = frame.shape[:2]
        lb = Letterbox.compute(w, h, size)
        resized = cv2.resize(frame, (round(w * lb.scale), round(h * lb.scale)))
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)  # grey padding as in Ultralytics
        oy, ox = int(lb.pad_y), int(lb.pad_x)
        canvas[oy:oy + resized.shape[0], ox:ox + resized.shape[1]] = resized
        rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0  # BGR -> RGB, [0,1]
        tensor = quantize_input(rgb, spec.dtype, spec.scale, spec.zero_point)
        tensor = tensor.transpose(2, 0, 1) if nchw else tensor
        return np.ascontiguousarray(tensor[None]), lb

    def _infer(self, net: Net, frame: np.ndarray) -> tuple[np.ndarray, Letterbox]:
        tensor, lb = self._preprocess(frame, net.input_spec)
        raw = net.run(tensor)
        spec = net.output_spec
        if np.dtype(spec.dtype).kind in "iu":
            raw = dequantize(raw, spec.scale, spec.zero_point)
        return raw, lb

    def detect(self, frame: np.ndarray) -> list[Detection]:
        raw, lb = self._infer(self._det_net, frame)
        return decode_detections(raw, len(CLASS_NAMES), lb, frame.shape[1], frame.shape[0],
                                 self._det_conf, self._iou)

    def pose(self, frame: np.ndarray) -> list[PersonPose]:
        raw, lb = self._infer(self._pose_net, frame)
        return decode_poses(raw, lb, frame.shape[1], frame.shape[0], self._pose_conf, self._iou)
