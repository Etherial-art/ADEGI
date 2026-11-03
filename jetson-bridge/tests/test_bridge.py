"""Bridge tests: both sides simulated on one machine (localhost, port 0).

Run from jetson-bridge/:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as P  # noqa: E402
from client import SOURCE_JETSON, SOURCE_LOCAL, BridgeClient  # noqa: E402
from detectors import SimulatedDetector  # noqa: E402
from server import BridgeServer  # noqa: E402

FRAME = b"\xff\xd8fake-jpeg\xff\xd9"


def wait_until(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class BridgeTestCase(unittest.TestCase):
    """Fast timings so the whole suite runs in a few seconds."""

    def setUp(self) -> None:
        self.jetson_det = SimulatedDetector("sim-jetson")
        self.local_det = SimulatedDetector("sim-local")
        self.server = BridgeServer(self.jetson_det)
        self.server.start()
        self.clients: list[BridgeClient] = []
        self.addCleanup(self.server.stop)

    def make_client(self, port: int | None = None, **kw) -> BridgeClient:
        params = dict(request_timeout=0.3, heartbeat_interval=0.1, heartbeat_timeout=0.5,
                      reconnect_min=0.05, reconnect_max=0.2, connect_timeout=0.3)
        params.update(kw)
        c = BridgeClient("127.0.0.1", port or self.server.port, self.local_det, **params)
        c.start()
        self.addCleanup(c.stop)
        return c


class TestHappyPath(BridgeTestCase):
    def test_jetson_answers(self):
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        r = c.detect(FRAME, 640, 480)
        self.assertEqual(r.source, SOURCE_JETSON)
        self.assertEqual(r.model, "sim-jetson")
        self.assertEqual(r.detections, self.jetson_det.detect(FRAME, 640, 480))

    def test_many_frames_in_order(self):
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        for i in range(30):
            data = FRAME + bytes([i])
            r = c.detect(data, 320, 240)
            self.assertEqual(r.source, SOURCE_JETSON)
            self.assertEqual(r.detections, self.jetson_det.detect(data, 320, 240))
        self.assertEqual(c.stats["jetson"], 30)

    def test_concurrent_callers_get_their_own_reply(self):
        import concurrent.futures as cf
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        payloads = [FRAME + bytes([i]) for i in range(20)]
        with cf.ThreadPoolExecutor(8) as ex:
            results = list(ex.map(lambda p: c.detect(p, 640, 480), payloads))
        for p, r in zip(payloads, results):
            self.assertEqual(r.source, SOURCE_JETSON)
            self.assertEqual(r.detections, self.jetson_det.detect(p, 640, 480))


class TestFallback(BridgeTestCase):
    def test_no_server_at_all(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead_port = s.getsockname()[1]
        s.close()  # nothing listens here
        c = self.make_client(port=dead_port)
        t0 = time.monotonic()
        r = c.detect(FRAME, 640, 480)
        self.assertEqual(r.source, SOURCE_LOCAL)
        self.assertEqual(r.model, "sim-local")
        self.assertLess(time.monotonic() - t0, 0.2, "fallback must be immediate")

    def test_slow_jetson_times_out_then_falls_back(self):
        self.jetson_det.delay = 1.0  # >> request_timeout (0.3)
        c = self.make_client(max_consecutive_timeouts=99)
        self.assertTrue(c.wait_connected(2))
        t0 = time.monotonic()
        r = c.detect(FRAME, 640, 480)
        self.assertEqual(r.source, SOURCE_LOCAL)
        self.assertLess(time.monotonic() - t0, 0.6)
        self.assertEqual(c.stats["timeouts"], 1)

    def test_repeated_timeouts_reset_link_and_recover(self):
        self.jetson_det.delay = 0.5
        c = self.make_client(request_timeout=0.1, max_consecutive_timeouts=2)
        self.assertTrue(c.wait_connected(2))
        for _ in range(2):
            self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_LOCAL)
        self.assertGreaterEqual(c.stats["timeouts"], 2)
        self.jetson_det.delay = 0.0
        # Link is reset, reconnects, and the Jetson is used again.
        self.assertTrue(wait_until(lambda: c.detect(FRAME, 64, 64).source == SOURCE_JETSON))

    def test_jetson_detector_error_falls_back(self):
        self.jetson_det.fail = True
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_LOCAL)
        self.jetson_det.fail = False
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_JETSON)

    def test_late_reply_is_ignored(self):
        self.jetson_det.delay = 0.45
        c = self.make_client(max_consecutive_timeouts=99)
        self.assertTrue(c.wait_connected(2))
        self.assertEqual(c.detect(b"A" + FRAME, 64, 64).source, SOURCE_LOCAL)
        self.jetson_det.delay = 0.0
        time.sleep(0.4)  # the late reply for frame A arrives meanwhile
        data = b"B" + FRAME
        r = c.detect(data, 64, 64)
        self.assertEqual(r.source, SOURCE_JETSON)
        self.assertEqual(r.detections, self.jetson_det.detect(data, 64, 64))


class TestHeartbeat(BridgeTestCase):
    def test_server_stops_then_restarts(self):
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_JETSON)

        port = self.server.port
        self.server.stop()
        self.assertTrue(wait_until(lambda: not c.connected))
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_LOCAL)

        self.server = BridgeServer(self.jetson_det, port=port)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.assertTrue(c.wait_connected(3), "client must reconnect by itself")
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_JETSON)

    def test_silent_server_detected_by_heartbeat(self):
        """TCP stays open but the Jetson stops answering (hung process)."""
        c = self.make_client()
        self.assertTrue(c.wait_connected(2))
        self.server.mute = True
        self.assertTrue(wait_until(lambda: not c.connected, 2.0),
                        "heartbeat timeout should mark the link down")
        self.assertEqual(c.detect(FRAME, 64, 64).source, SOURCE_LOCAL)

    def test_pending_request_wakes_when_link_dies(self):
        self.jetson_det.delay = 2.0
        c = self.make_client(request_timeout=5.0)
        self.assertTrue(c.wait_connected(2))
        import threading
        threading.Timer(0.2, self.server.stop).start()
        t0 = time.monotonic()
        r = c.detect(FRAME, 64, 64)
        self.assertEqual(r.source, SOURCE_LOCAL)
        self.assertLess(time.monotonic() - t0, 2.0, "must not wait the full request_timeout")


class TestProtocol(unittest.TestCase):
    def pair(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        b.settimeout(1)
        return a, b

    def test_roundtrip(self):
        a, b = self.pair()
        P.send_message(a, {"type": "frame", "id": 7}, b"\x00\x01\x02")
        h, p = P.read_message(b)
        self.assertEqual((h["type"], h["id"], p), ("frame", 7, b"\x00\x01\x02"))

    def test_fragmented_delivery(self):
        a, b = self.pair()
        raw = P.encode({"type": "ping"}, b"x" * 1000)
        for i in range(0, len(raw), 7):  # dribble 7 bytes at a time
            a.sendall(raw[i:i + 7])
        h, p = P.read_message(b)
        self.assertEqual(h["type"], "ping")
        self.assertEqual(len(p), 1000)

    def test_rejects_oversized_lengths(self):
        a, b = self.pair()
        a.sendall(P._PREFIX.pack(10, P.MAX_PAYLOAD_BYTES + 1))
        with self.assertRaises(P.ProtocolError):
            P.read_message(b)

    def test_rejects_bad_json(self):
        a, b = self.pair()
        a.sendall(P._PREFIX.pack(3, 0) + b"{{{")
        with self.assertRaises(P.ProtocolError):
            P.read_message(b)

    def test_closed_connection(self):
        a, b = self.pair()
        a.sendall(P.encode({"type": "ping"})[:5])
        a.close()
        with self.assertRaises(P.ConnectionClosed):
            P.read_message(b)

    def test_server_survives_garbage_client(self):
        server = BridgeServer(SimulatedDetector())
        server.start()
        self.addCleanup(server.stop)
        s = socket.create_connection(("127.0.0.1", server.port))
        s.sendall(b"\xff" * 64)  # not a valid envelope
        s.settimeout(1)
        try:
            self.assertEqual(s.recv(10), b"")  # server hung up on us (FIN)...
        except ConnectionResetError:
            pass  # ...or with RST, since it had unread bytes. Both mean "hung up".
        finally:
            s.close()
        # ...and still serves well-behaved clients
        c = BridgeClient("127.0.0.1", server.port, SimulatedDetector("l"),
                         heartbeat_interval=0.1)
        c.start()
        self.addCleanup(c.stop)
        self.assertTrue(c.wait_connected(2))


if __name__ == "__main__":
    unittest.main()
