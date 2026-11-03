import unittest

import numpy as np

from adegi_vision.backends.stai_mpu_backend import StaiMpuBackend, TensorSpec
from adegi_vision.classes import BED, CLASS_NAMES, PERSON
from adegi_vision.decode import (
    Letterbox, decode_detections, decode_poses, dequantize, nms, quantize_input,
)

try:
    import cv2  # noqa: F401
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

N = 1344
NC = len(CLASS_NAMES)


def det_tensor(entries, normalized=False, size=256):
    """entries: (cx, cy, w, h, cls, score) in input pixels -> raw (4+nc, N)."""
    a = np.zeros((4 + NC, N), dtype=np.float32)
    for i, (cx, cy, w, h, c, s) in enumerate(entries):
        k = 1.0 / size if normalized else 1.0
        a[0:4, i] = np.array([cx, cy, w, h]) * k
        a[4 + c, i] = s
    return a[None]


class LetterboxTests(unittest.TestCase):
    def test_wide_frame_gets_vertical_padding(self):
        lb = Letterbox.compute(640, 480, 256)
        self.assertAlmostEqual(lb.scale, 0.4)
        self.assertEqual((lb.pad_x, lb.pad_y), (0.0, 32.0))

    def test_roundtrip(self):
        lb = Letterbox.compute(640, 480, 256)
        x, y = lb.to_frame(np.array([lb.pad_x + 0.4 * 100]), np.array([lb.pad_y + 0.4 * 200]))
        self.assertAlmostEqual(float(x[0]), 100, places=4)
        self.assertAlmostEqual(float(y[0]), 200, places=4)


class QuantTests(unittest.TestCase):
    def test_quantize_dequantize(self):
        x = np.array([0.0, 0.5, 1.0], dtype=np.float32)
        q = quantize_input(x, np.int8, 1 / 255, -128)
        self.assertEqual(q.dtype, np.int8)
        self.assertEqual((int(q[0]), int(q[2])), (-128, 127))
        self.assertLessEqual(abs(int(q[1])), 1)  # 0.5 -> 127.5: float rounding may land on either side
        np.testing.assert_allclose(dequantize(q, 1 / 255, -128), x, atol=2 / 255)

    def test_float_passthrough(self):
        self.assertEqual(quantize_input(np.zeros(2), np.float32, 1, 0).dtype, np.float32)

    def test_uint8_clips(self):
        q = quantize_input(np.array([2.0]), np.uint8, 1 / 255, 0)
        self.assertEqual(int(q[0]), 255)


class NmsTests(unittest.TestCase):
    def test_suppresses_overlap_keeps_best(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
        self.assertEqual(sorted(nms(boxes, np.array([0.9, 0.8, 0.7]), 0.5)), [0, 2])


class DecodeDetTests(unittest.TestCase):
    def test_decode_pixels_and_class_aware_nms(self):
        lb = Letterbox.compute(256, 256, 256)  # identity
        raw = det_tensor([(100, 100, 50, 80, PERSON, 0.9), (102, 100, 50, 80, PERSON, 0.6),
                          (100, 100, 50, 80, BED, 0.8)])
        dets = decode_detections(raw, NC, lb, 256, 256)
        self.assertEqual(sorted(d.cls_id for d in dets), [PERSON, BED])  # dup person removed
        person = next(d for d in dets if d.cls_id == PERSON)
        self.assertAlmostEqual(person.box.x1, 75)
        self.assertAlmostEqual(person.box.y2, 140)

    def test_normalized_equals_pixels(self):
        lb = Letterbox.compute(640, 480, 256)
        e = [(128, 128, 60, 90, PERSON, 0.9)]
        a = decode_detections(det_tensor(e, False), NC, lb, 640, 480)
        b = decode_detections(det_tensor(e, True), NC, lb, 640, 480)
        self.assertAlmostEqual(a[0].box.x1, b[0].box.x1, places=3)

    def test_transposed_input_ok(self):
        lb = Letterbox.compute(256, 256, 256)
        raw = det_tensor([(100, 100, 50, 80, PERSON, 0.9)])[0].T[None]
        self.assertEqual(len(decode_detections(raw, NC, lb, 256, 256)), 1)

    def test_below_threshold_empty(self):
        lb = Letterbox.compute(256, 256, 256)
        self.assertEqual(decode_detections(det_tensor([(1, 1, 5, 5, 0, 0.1)]), NC, lb, 256, 256), [])

    def test_bad_channels_raise(self):
        with self.assertRaises(ValueError):
            decode_detections(np.zeros((1, 10, 10)), NC, Letterbox.compute(256, 256, 256), 256, 256)


class DecodePoseTests(unittest.TestCase):
    def raw(self, normalized):
        a = np.zeros((56, N), dtype=np.float32)
        k = 1 / 256 if normalized else 1.0
        a[0:4, 3] = np.array([100, 120, 60, 160]) * k
        a[4, 3] = 0.9
        for i in range(17):
            a[5 + 3 * i, 3] = (90 + i) * k
            a[6 + 3 * i, 3] = (50 + 5 * i) * k
            a[7 + 3 * i, 3] = 0.8  # confidence must NOT be rescaled
        return a[None]

    def test_pixels_and_normalized_agree(self):
        lb = Letterbox.compute(640, 480, 256)
        a = decode_poses(self.raw(False), lb, 640, 480)[0]
        b = decode_poses(self.raw(True), lb, 640, 480)[0]
        np.testing.assert_allclose(a.keypoints, b.keypoints, atol=1e-2)
        self.assertAlmostEqual(float(a.keypoints[3, 2]), 0.8, places=5)

    def test_keypoint_geometry(self):
        lb = Letterbox.compute(256, 256, 256)
        p = decode_poses(self.raw(False), lb, 256, 256)[0]
        self.assertAlmostEqual(float(p.keypoints[0, 0]), 90)
        self.assertAlmostEqual(float(p.keypoints[16, 1]), 130)
        self.assertEqual(p.keypoints.shape, (17, 3))


@unittest.skipUnless(HAS_CV2, "opencv not installed")
class StaiBackendWithFakeNetTests(unittest.TestCase):
    class FakeNet:
        def __init__(self, raw, spec, out_spec):
            self.input_spec, self.output_spec, self._raw, self.last_input = spec, out_spec, raw, None

        def run(self, tensor):
            self.last_input = tensor
            return self._raw

    def test_detect_end_to_end_int8(self):
        # Realistic int8 model: ONE output scale for boxes and scores, so coordinates are
        # normalised to [0,1] (pixel values would saturate int8). Exercises
        # quantize input -> run -> dequantize -> auto-detect normalised -> decode.
        out_scale, out_zp = 1 / 255, -128
        floats = np.zeros((1, 4 + NC, N), dtype=np.float32)
        floats[0, 0:4, 0] = [0.5, 0.5, 0.25, 0.5]  # cx, cy, w, h in model-input units / 256
        floats[0, 4 + PERSON, 0] = 0.9
        q_out = (np.round(floats / out_scale) + out_zp).astype(np.int8)
        net = self.FakeNet(q_out, TensorSpec((1, 256, 256, 3), np.dtype(np.int8), 1 / 255, -128),
                           TensorSpec(q_out.shape, np.dtype(np.int8), out_scale, out_zp))
        backend = StaiMpuBackend(det_net=net, pose_net=net, det_conf=0.5)
        dets = backend.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(net.last_input.shape, (1, 256, 256, 3))
        self.assertEqual(net.last_input.dtype, np.int8)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0].cls_id, PERSON)
        # model-space x1 = (0.5-0.125)*256 = 96 -> frame x = 96 / 0.4 = 240 (±1 quantisation step)
        self.assertAlmostEqual(dets[0].box.x1, 240.0, delta=4.0)
        self.assertAlmostEqual(dets[0].conf, 0.9, delta=0.01)

    def test_nchw_float_input_layout(self):
        net = self.FakeNet(det_tensor([]), TensorSpec((1, 3, 256, 256), np.dtype(np.float32)),
                           TensorSpec((1, 4 + NC, N), np.dtype(np.float32)))
        StaiMpuBackend(det_net=net, pose_net=net).detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(net.last_input.shape, (1, 3, 256, 256))
        self.assertEqual(net.last_input.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
