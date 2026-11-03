"""MP257-side client: sends frames to the Jetson, falls back to local inference.

Design rule (from the project): the robot must NEVER depend on the Jetson.
``detect()`` therefore always returns a result: from the Jetson when the link
is healthy and answers in time, otherwise from the local detector (NPU).

Threads:
  * manager  - connects, handshakes, sends heartbeats, detects a dead link,
               reconnects with exponential backoff.
  * reader   - one per connection; blocks on recv and delivers replies.
  * caller   - whoever calls detect() (the vision loop) waits on an Event.
"""
from __future__ import annotations

import itertools
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import protocol as P
from detectors import Detector

log = logging.getLogger("bridge.client")

SOURCE_JETSON = "jetson"
SOURCE_LOCAL = "local"


@dataclass
class DetectionResult:
    frame_id: int
    source: str                      # "jetson" or "local"
    model: str
    detections: list[dict[str, Any]]
    latency_ms: float                # wall time seen by the caller


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    reply: dict[str, Any] | None = None  # None after wake-up = link died / no reply


class BridgeClient:
    def __init__(
        self,
        host: str,
        port: int,
        local_detector: Detector,
        *,
        request_timeout: float = 0.5,       # max wait for one detection reply
        heartbeat_interval: float = 1.0,    # ping period
        heartbeat_timeout: float = 3.0,     # no traffic at all for this long => link dead
        connect_timeout: float = 1.0,
        reconnect_min: float = 0.5,
        reconnect_max: float = 5.0,
        max_consecutive_timeouts: int = 3,  # N slow replies in a row => reset the link
    ) -> None:
        self.host, self.port = host, port
        self.local = local_detector
        self.request_timeout = request_timeout
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.connect_timeout = connect_timeout
        self.reconnect_min, self.reconnect_max = reconnect_min, reconnect_max
        self.max_consecutive_timeouts = max_consecutive_timeouts

        self._lock = threading.Lock()        # guards _sock, _pending, counters
        self._send_lock = threading.Lock()   # one writer at a time on the socket
        self._sock: socket.socket | None = None
        self._link_down = threading.Event()
        self._pending: dict[int, _Pending] = {}
        self._ids = itertools.count(1)
        self._consecutive_timeouts = 0
        self._last_rx = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {"jetson": 0, "local": 0, "timeouts": 0, "reconnects": 0}

    # ---- public API ------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._manage, name="bridge-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._link_down.set()
        self._detach(self._sock)
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._link_down.is_set()

    def wait_connected(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected:
                return True
            time.sleep(0.01)
        return self.connected

    def detect(self, jpeg: bytes, width: int, height: int) -> DetectionResult:
        t0 = time.monotonic()
        frame_id = next(self._ids)
        reply = self._remote_detect(frame_id, jpeg, width, height)
        if reply is not None:
            source, model, dets = SOURCE_JETSON, reply.get("model", "jetson"), reply["detections"]
        else:
            source, model = SOURCE_LOCAL, self.local.name
            dets = self.local.detect(jpeg, width, height)
        with self._lock:
            self.stats[source] += 1
        return DetectionResult(frame_id, source, model, dets, (time.monotonic() - t0) * 1000)

    # ---- remote attempt --------------------------------------------------
    def _remote_detect(self, frame_id: int, jpeg: bytes, w: int, h: int) -> dict | None:
        """Return the Jetson reply, or None if we must fall back."""
        with self._lock:
            sock = self._sock if self.connected else None
            if sock is None:
                return None  # fast path: don't even try while the link is down
            pending = self._pending[frame_id] = _Pending()
        header = {"type": P.FRAME, "id": frame_id, "ts": time.time(),
                  "width": w, "height": h, "encoding": "jpeg"}
        try:
            self._send(sock, header, jpeg)
        except OSError:
            self._drop(sock)
            self._forget(frame_id)
            return None

        if not pending.event.wait(self.request_timeout):
            self._forget(frame_id)  # a late reply will be ignored
            with self._lock:
                self.stats["timeouts"] += 1
                self._consecutive_timeouts += 1
                too_many = self._consecutive_timeouts >= self.max_consecutive_timeouts
            log.warning("frame %d timed out", frame_id)
            if too_many:  # Jetson is alive enough to ping but useless: reset link
                self._drop(sock)
            return None

        self._forget(frame_id)
        reply = pending.reply
        if reply is None or reply.get("error"):
            return None  # link died while waiting, or Jetson detector failed
        with self._lock:
            self._consecutive_timeouts = 0
        return reply

    def _forget(self, frame_id: int) -> None:
        with self._lock:
            self._pending.pop(frame_id, None)

    def _send(self, sock: socket.socket, header: dict, payload: bytes = b"") -> None:
        with self._send_lock:
            P.send_message(sock, header, payload)

    # ---- connection management ------------------------------------------
    def _manage(self) -> None:
        backoff = self.reconnect_min
        while not self._stop.is_set():
            sock = self._connect()
            if sock is None:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self.reconnect_max)  # don't hammer a dead host
                continue
            backoff = self.reconnect_min
            self._run_link(sock)
            self._detach(sock)
            self._stop.wait(self.reconnect_min)

    def _connect(self) -> socket.socket | None:
        try:
            sock = socket.create_connection((self.host, self.port), self.connect_timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self.connect_timeout)  # applies to the handshake only
            P.send_message(sock, {"type": P.HELLO, "version": P.PROTOCOL_VERSION})
            header, _ = P.read_message(sock)
            if header["type"] != P.HELLO_ACK or header.get("version") != P.PROTOCOL_VERSION:
                raise P.ProtocolError(f"unexpected handshake reply: {header}")
            sock.settimeout(None)  # reader blocks; liveness is handled by heartbeats
            return sock
        except (OSError, P.ProtocolError, P.ConnectionClosed) as exc:
            log.info("connect failed: %r", exc)
            try:
                sock.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            return None

    def _run_link(self, sock: socket.socket) -> None:
        with self._lock:
            self._link_down = threading.Event()
            self._sock = sock
            self._consecutive_timeouts = 0
            self._last_rx = time.monotonic()
            self.stats["reconnects"] += 1
            down = self._link_down
        threading.Thread(target=self._reader, args=(sock, down), name="bridge-reader",
                         daemon=True).start()
        log.info("link up")
        seq = 0
        while not self._stop.is_set() and not down.wait(self.heartbeat_interval):
            seq += 1
            try:
                self._send(sock, {"type": P.PING, "seq": seq})
            except OSError:
                break
            if time.monotonic() - self._last_rx > self.heartbeat_timeout:
                log.warning("heartbeat timeout: Jetson silent")
                break
        log.info("link down")

    def _reader(self, sock: socket.socket, down: threading.Event) -> None:
        try:
            while True:
                header, _ = P.read_message(sock)
                self._last_rx = time.monotonic()  # any traffic proves liveness
                if header["type"] == P.DETECTIONS:
                    with self._lock:
                        pending = self._pending.get(header.get("id"))
                    if pending:
                        pending.reply = header
                        pending.event.set()
                # pong (and unknown types) only matter for _last_rx
        except (OSError, P.ProtocolError, P.ConnectionClosed):
            pass
        finally:
            down.set()

    def _drop(self, sock: socket.socket) -> None:
        """Mark the link dead; the manager thread will clean up and reconnect."""
        with self._lock:
            if sock is self._sock:
                self._link_down.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)  # unblocks the reader thread
        except OSError:
            pass

    def _detach(self, sock: socket.socket | None) -> None:
        with self._lock:
            if sock is not None and sock is self._sock:
                self._sock = None
            self._link_down.set()
            waiting = list(self._pending.values())
            self._pending.clear()
        for p in waiting:  # wake callers now: they fall back immediately
            p.event.set()
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
