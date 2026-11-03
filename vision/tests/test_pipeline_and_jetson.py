import json
import socket
import threading
import unittest

import numpy as np

from adegi_vision.backends.base import InferenceBackend
from adegi_vision.backends.jetson_backend import JetsonBackend
from adegi_vision.classes import BED, STATE_FALLEN, STATE_LYING_BED, STATE_STANDING, STATE_UNKNOWN
from adegi_vision.features import extract_features
from adegi_vision.pipeline import PipelineConfig, VisionPipeline, person_state_event
from adegi_vision.posture_mlp import train
from adegi_vision.types import Box, Detection, PersonPose
from helpers import lying_person, standing_person
from test_features_and_mlp import _synthetic_dataset

FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


class FakeBackend(InferenceBackend):
    name = "fake"

    def __init__(self):
        self.detect_calls = self.pose_calls = 0
        self.poses: list[PersonPose] = []
        self.dets: list[Detection] = []

    def detect(self, frame):
        self.detect_calls += 1
        return list(self.dets)

    def pose(self, frame):
        self.pose_calls += 1
        return list(self.poses)


def pose_of(maker, conf=0.9, **kw):
    box, kp = maker(**kw)
    return PersonPose(box, conf, kp)


def trained_mlp():
    x, y = _synthetic_dataset()
    return train(x, y, epochs=60, lr=3e-3, seed=1).model


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mlp = trained_mlp()

    def test_interleaving_counts(self):
        fb = FakeBackend()
        pipe = VisionPipeline(fb, self.mlp, PipelineConfig(detector_every=4))
        ran = [pipe.process(FRAME, i * 0.1).detector_ran for i in range(12)]
        self.assertEqual(fb.pose_calls, 12)  # pose EVERY frame
        self.assertEqual(fb.detect_calls, 3)  # frames 0, 4, 8
        self.assertEqual([i for i, r in enumerate(ran) if r], [0, 4, 8])

    def test_furniture_map_persists_between_detector_runs(self):
        fb = FakeBackend()
        fb.dets = [Detection(BED, 0.9, Box(50, 150, 500, 400))]
        fb.poses = [pose_of(lying_person)]
        pipe = VisionPipeline(fb, self.mlp, PipelineConfig(detector_every=5))
        states = [pipe.process(FRAME, i * 0.1).primary.state for i in range(4)]
        self.assertEqual(set(states), {STATE_LYING_BED})  # frames 1-3 reuse the cached bed
        self.assertEqual(fb.detect_calls, 1)

    def test_fall_alert_after_hold_and_clear(self):
        fb = FakeBackend()
        fb.poses = [pose_of(lying_person)]  # no bed anywhere -> fallen
        pipe = VisionPipeline(fb, self.mlp, PipelineConfig(fall_hold_s=2.0, fall_clear_s=1.0))
        alerts = [pipe.process(FRAME, t).fall_alert for t in (0.0, 1.0, 1.9, 2.0, 2.5)]
        self.assertEqual(alerts, [False, False, False, True, True])
        self.assertEqual(pipe.process(FRAME, 2.6).primary.state, STATE_FALLEN)
        fb.poses = [pose_of(standing_person)]
        pipe.process(FRAME, 3.0)
        self.assertTrue(pipe.process(FRAME, 3.5).fall_alert)  # not cleared yet
        self.assertFalse(pipe.process(FRAME, 4.1).fall_alert)

    def test_no_person_keeps_alert(self):
        fb = FakeBackend()
        fb.poses = [pose_of(lying_person)]
        pipe = VisionPipeline(fb, self.mlp, PipelineConfig(fall_hold_s=1.0))
        pipe.process(FRAME, 0.0)
        self.assertTrue(pipe.process(FRAME, 1.0).fall_alert)
        fb.poses = []
        self.assertTrue(pipe.process(FRAME, 30.0).fall_alert)

    def test_low_confidence_person_ignored(self):
        fb = FakeBackend()
        fb.poses = [pose_of(standing_person, conf=0.1)]
        res = VisionPipeline(fb, self.mlp).process(FRAME, 0.0)
        self.assertEqual(res.persons, [])

    def test_event_schema(self):
        fb = FakeBackend()
        fb.poses = [pose_of(standing_person)]
        pipe = VisionPipeline(fb, self.mlp)
        ev = person_state_event(pipe.process(FRAME, 5.0), 5.0)
        json.dumps(ev)  # must be serialisable
        self.assertEqual(ev["state"], STATE_STANDING)
        self.assertEqual(ev["type"], "person_state")
        self.assertTrue(ev["present"])
        fb.poses = []
        self.assertEqual(person_state_event(pipe.process(FRAME, 6.0), 6.0)["present"], False)

    def test_unknown_frame_holds_last_state(self):
        class StubMLP:  # says "horizontal" whenever told to, regardless of features
            def __init__(self):
                self.answer = 0  # standing

            def predict(self, feats):
                return self.answer, 0.99

        fb, mlp = FakeBackend(), StubMLP()
        fb.poses = [pose_of(standing_person)]
        pipe = VisionPipeline(fb, mlp)
        self.assertEqual(pipe.process(FRAME, 0.0).held_state, STATE_STANDING)
        mlp.answer = 2  # horizontal, but the skeleton is upright -> contradictory -> unknown
        res = pipe.process(FRAME, 1.0)
        self.assertEqual(res.primary.state, STATE_UNKNOWN)
        self.assertEqual(res.held_state, STATE_STANDING)  # consumers keep the last state
        self.assertFalse(res.fall_alert)
        self.assertEqual(person_state_event(res, 1.0)["state"], STATE_STANDING)


class FakeJetsonServer:
    """Minimal in-process server speaking the documented wire protocol."""

    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.requests = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.srv.accept()
        except OSError:
            return
        f = conn.makefile("rb")
        try:
            while True:
                line = f.readline()
                if not line:
                    return
                hdr = json.loads(line)
                f.read(hdr["jpeg_len"])
                self.requests.append(hdr)
                if self.behaviour == "hang":
                    continue  # never answer -> client must time out
                if hdr["task"] == "detect":
                    items = [{"cls": 3, "conf": 0.8, "box": [1, 2, 3, 4]}]
                else:
                    items = [{"conf": 0.9, "box": [1, 2, 3, 4], "keypoints": [[1, 2, 0.9]] * 17}]
                conn.sendall(json.dumps({"type": "result", "task": hdr["task"], "seq": hdr["seq"],
                                         "items": items}).encode() + b"\n")
        finally:
            f.close()
            conn.close()

    def close(self):
        self.srv.close()


class JetsonBackendTests(unittest.TestCase):
    def make(self, port, fallback, clock=None, **kw):
        return JetsonBackend(fallback, "127.0.0.1", port, timeout_s=0.3, retry_after_s=5.0,
                             encode=lambda f: b"jpeg-bytes", clock=clock or (lambda: 0.0), **kw)

    def test_remote_path(self):
        srv, fb = FakeJetsonServer(), FakeBackend()
        be = self.make(srv.port, fb)
        dets = be.detect(FRAME)
        poses = be.pose(FRAME)
        self.assertEqual(dets[0].cls_id, 3)
        self.assertEqual(poses[0].keypoints.shape, (17, 3))
        self.assertEqual((fb.detect_calls, fb.pose_calls), (0, 0))
        self.assertEqual([r["task"] for r in srv.requests], ["detect", "pose"])
        be.close()
        srv.close()

    def test_falls_back_when_nobody_listens(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens here
        fb = FakeBackend()
        be = self.make(port, fb)
        self.assertEqual(be.detect(FRAME), [])
        self.assertEqual(fb.detect_calls, 1)

    def test_backoff_avoids_reconnect_every_frame(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        now = [0.0]
        fb = FakeBackend()
        be = self.make(port, fb, clock=lambda: now[0])
        be.pose(FRAME)
        attempts = []
        orig = socket.create_connection
        socket.create_connection = lambda *a, **k: (attempts.append(1), orig(*a, **k))[1]
        try:
            for _ in range(5):
                be.pose(FRAME)  # within the 5 s back-off window: must not try to connect
            self.assertEqual(attempts, [])
            now[0] = 6.0
            be.pose(FRAME)
            self.assertEqual(len(attempts), 1)
        finally:
            socket.create_connection = orig
        self.assertEqual(fb.pose_calls, 7)

    def test_timeout_falls_back(self):
        srv, fb = FakeJetsonServer("hang"), FakeBackend()
        be = self.make(srv.port, fb)
        be.detect(FRAME)
        self.assertEqual(fb.detect_calls, 1)
        srv.close()

    def test_task_not_offloaded_goes_local(self):
        srv, fb = FakeJetsonServer(), FakeBackend()
        be = self.make(srv.port, fb, tasks=frozenset({"detect"}))
        be.pose(FRAME)
        self.assertEqual(fb.pose_calls, 1)
        self.assertEqual(srv.requests, [])
        srv.close()


if __name__ == "__main__":
    unittest.main()
