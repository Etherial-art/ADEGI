"""Jetson-side server: receives frames, answers detections as JSON.

Run on the Jetson:  python3 server.py --host 0.0.0.0 --port 5555
(The default detector here is the simulated one; plug in the real YOLO there.)
"""
from __future__ import annotations

import argparse
import logging
import socket
import threading
import time

import protocol as P
from detectors import Detector, SimulatedDetector

log = logging.getLogger("bridge.server")


class BridgeServer:
    def __init__(self, detector: Detector, host: str = "127.0.0.1", port: int = 0,
                 idle_timeout: float = 10.0) -> None:
        self.detector = detector
        self.host = host
        self.port = port  # 0 = let the OS pick; real value is set in start()
        # If a client sends nothing (not even pings) for this long, we drop it.
        # This frees resources when the robot loses power or WiFi without a FIN.
        self.idle_timeout = idle_timeout
        # Fault injection for tests: when True, read but never answer
        # (simulates a hung Jetson whose TCP stack is still alive).
        self.mute = False
        self._listener: socket.socket | None = None
        self._clients: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR lets us restart immediately without "address in use".
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen()
        self.port = sock.getsockname()[1]
        self._listener = sock
        self._stopped.clear()
        threading.Thread(target=self._accept_loop, name="bridge-accept", daemon=True).start()
        log.info("listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._stopped.set()
        if self._listener:
            # close() alone does not wake an accept() blocked in another thread
            # on Linux (the old socket stays alive and keeps accepting).
            # shutdown() does.
            try:
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._listener.close()
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stopped.is_set():
            try:
                conn, addr = self._listener.accept()
            except OSError:
                return  # listener closed
            if self._stopped.is_set():
                conn.close()
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(self.idle_timeout)
            with self._lock:
                self._clients.add(conn)
            threading.Thread(target=self._serve, args=(conn, addr), name="bridge-conn",
                             daemon=True).start()

    def _serve(self, conn: socket.socket, addr) -> None:
        log.info("client connected: %s", addr)
        try:
            while True:
                header, payload = P.read_message(conn)
                if self.mute:
                    continue
                self._handle(conn, header, payload)
        except (P.ConnectionClosed, P.ProtocolError, OSError) as exc:
            log.info("client %s gone: %r", addr, exc)
        finally:
            with self._lock:
                self._clients.discard(conn)
            conn.close()

    def _handle(self, conn: socket.socket, header: dict, payload: bytes) -> None:
        kind = header["type"]
        if kind == P.HELLO:
            P.send_message(conn, {"type": P.HELLO_ACK, "version": P.PROTOCOL_VERSION,
                                  "model": self.detector.name})
        elif kind == P.PING:
            P.send_message(conn, {"type": P.PONG, "seq": header.get("seq")})
        elif kind == P.FRAME:
            self._handle_frame(conn, header, payload)
        else:
            log.warning("ignoring unknown message type %r", kind)

    def _handle_frame(self, conn: socket.socket, header: dict, payload: bytes) -> None:
        frame_id = header.get("id")
        t0 = time.monotonic()
        try:
            dets = self.detector.detect(payload, int(header["width"]), int(header["height"]))
            reply = {"type": P.DETECTIONS, "id": frame_id, "model": self.detector.name,
                     "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                     "detections": dets}
        except Exception as exc:  # a bad frame must not kill the connection
            log.exception("detector failed on frame %s", frame_id)
            reply = {"type": P.DETECTIONS, "id": frame_id, "model": self.detector.name,
                     "error": str(exc), "detections": []}
        P.send_message(conn, reply)


def main() -> None:
    ap = argparse.ArgumentParser(description="ADEGI Jetson bridge server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--sim-delay", type=float, default=0.03,
                    help="simulated inference time in seconds")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    server = BridgeServer(SimulatedDetector("sim-jetson", args.sim_delay), args.host, args.port)
    server.start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
