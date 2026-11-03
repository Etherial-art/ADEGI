"""Optional accelerator: forward frames to the Jetson through jetson-bridge, with fallback.

Rule of the project: THE ROBOT MUST NOT DEPEND ON THE JETSON. So this class wraps a local
backend; any socket error/timeout transparently serves the request locally and the Jetson
is not retried until `retry_after_s` has passed (otherwise every frame would pay the
connection timeout while the Jetson is down).

Wire protocol (also in docs/protocol.md), one request/response at a time on a TCP socket:
  request : JSON header line + "\n" + JPEG bytes
            {"type":"infer","task":"detect"|"pose","seq":N,"jpeg_len":L}
  response: one JSON line
            {"type":"result","task":...,"seq":N,"items":[...]}
            detect item: {"cls":int,"conf":f,"box":[x1,y1,x2,y2]}
            pose item  : {"conf":f,"box":[x1,y1,x2,y2],"keypoints":[[x,y,c] x17]}
            or {"type":"error","message":"..."}
Why JPEG over raw pixels: a 640x480 BGR frame is ~920 KB; JPEG is ~30 KB, which matters on
the USB/Ethernet link.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from typing import Callable

import numpy as np

from ..classes import NUM_KPTS
from ..types import Box, Detection, PersonPose
from .base import InferenceBackend

log = logging.getLogger(__name__)


def _default_encode(frame: np.ndarray) -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


class JetsonBackend(InferenceBackend):
    name = "jetson"

    def __init__(self, fallback: InferenceBackend, host: str, port: int, *,
                 timeout_s: float = 0.5, retry_after_s: float = 5.0,
                 tasks: frozenset[str] = frozenset({"detect", "pose"}),
                 encode: Callable[[np.ndarray], bytes] = _default_encode,
                 clock: Callable[[], float] = time.monotonic):
        self._fallback = fallback
        self._addr = (host, port)
        self._timeout, self._retry_after, self._tasks = timeout_s, retry_after_s, tasks
        self._encode, self._clock = encode, clock
        self._sock: socket.socket | None = None
        self._rfile = None
        self._down_until = 0.0
        self._seq = 0
        self.remote_calls = 0
        self.fallback_calls = 0

    # -- connection management -------------------------------------------------------
    def _disconnect(self) -> None:
        for obj in (self._rfile, self._sock):
            try:
                if obj:
                    obj.close()
            except OSError:
                pass
        self._sock = self._rfile = None

    def _request(self, task: str, frame: np.ndarray) -> list[dict]:
        if self._sock is None:
            self._sock = socket.create_connection(self._addr, timeout=self._timeout)
            self._sock.settimeout(self._timeout)
            self._rfile = self._sock.makefile("rb")
        self._seq += 1
        jpeg = self._encode(frame)
        header = json.dumps({"type": "infer", "task": task, "seq": self._seq, "jpeg_len": len(jpeg)})
        self._sock.sendall(header.encode() + b"\n" + jpeg)
        line = self._rfile.readline()
        if not line:
            raise ConnectionError("jetson closed the connection")
        msg = json.loads(line)
        if msg.get("type") != "result" or msg.get("seq") != self._seq:
            raise ValueError(f"unexpected reply from jetson: {str(msg)[:100]}")
        return msg["items"]

    def _try_remote(self, task: str, frame: np.ndarray) -> list[dict] | None:
        if task not in self._tasks or self._clock() < self._down_until:
            return None
        try:
            items = self._request(task, frame)
            self.remote_calls += 1
            return items
        except (OSError, ValueError, KeyError, ConnectionError) as exc:
            # socket.timeout and ConnectionError are OSError; bad JSON is ValueError.
            log.warning("jetson unavailable (%s); using local fallback for %.0fs", exc, self._retry_after)
            self._disconnect()
            self._down_until = self._clock() + self._retry_after
            return None

    # -- InferenceBackend ------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> list[Detection]:
        items = self._try_remote("detect", frame)
        if items is None:
            self.fallback_calls += 1
            return self._fallback.detect(frame)
        return [Detection(int(i["cls"]), float(i["conf"]), Box(*map(float, i["box"]))) for i in items]

    def pose(self, frame: np.ndarray) -> list[PersonPose]:
        items = self._try_remote("pose", frame)
        if items is None:
            self.fallback_calls += 1
            return self._fallback.pose(frame)
        out = []
        for i in items:
            kp = np.asarray(i["keypoints"], dtype=np.float32)
            if kp.shape != (NUM_KPTS, 3):
                # Malformed payload: do not trust the Jetson for this frame.
                self.fallback_calls += 1
                return self._fallback.pose(frame)
            out.append(PersonPose(Box(*map(float, i["box"])), float(i["conf"]), kp))
        return out

    def close(self) -> None:
        self._disconnect()
        self._fallback.close()
