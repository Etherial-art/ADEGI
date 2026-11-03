import tempfile
import unittest
from pathlib import Path

import numpy as np

from adegi_vision.classes import HORIZONTAL, SITTING, STANDING
from adegi_vision.features import N_FEATURES, extract_features, flip_features
from adegi_vision.posture_mlp import PostureMLP, train
from helpers import lying_person, standing_person


class FeatureTests(unittest.TestCase):
    def test_shape_and_range(self):
        f = extract_features(*standing_person())
        self.assertEqual(f.shape, (N_FEATURES,))
        self.assertTrue(np.all(f[:34] >= 0) and np.all(f[:34] <= 1))

    def test_translation_invariance(self):
        box, kp = standing_person()
        f1 = extract_features(box, kp)
        from adegi_vision.types import Box
        shifted = kp.copy()
        shifted[:, 0] += 300
        shifted[:, 1] += 50
        box2 = Box(box.x1 + 300, box.y1 + 50, box.x2 + 300, box.y2 + 50)
        np.testing.assert_allclose(f1, extract_features(box2, shifted), atol=1e-5)

    def test_low_conf_keypoint_zeroed(self):
        box, kp = standing_person()
        kp[0, 2] = 0.1
        f = extract_features(box, kp)
        self.assertEqual((f[0], f[1]), (0.0, 0.0))

    def test_aspect_and_femur(self):
        stand = extract_features(*standing_person())
        lie = extract_features(*lying_person())
        self.assertLess(stand[34], lie[34])  # lying is wider
        self.assertGreater(stand[35], 0.2)  # knee well below hip
        self.assertAlmostEqual(float(lie[35]), 0.0, places=5)

    def test_flip_is_involution(self):
        f = extract_features(*standing_person())
        np.testing.assert_allclose(flip_features(flip_features(f)), f, atol=1e-6)

    def test_wrong_shape_raises(self):
        box, _ = standing_person()
        with self.assertRaises(ValueError):
            extract_features(box, np.zeros((17, 2)))


def _synthetic_dataset(n_per_class=150, seed=0):
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for label, make in ((STANDING, standing_person), (HORIZONTAL, lying_person)):
        base = extract_features(*make())
        xs.append(base + rng.normal(0, 0.02, (n_per_class, N_FEATURES)).astype(np.float32))
        ys += [label] * n_per_class
    # "sitting": like standing but thigh horizontal (femur drop ~0) and shorter box
    sit = extract_features(*standing_person())
    sit[35] = 0.0
    sit[34] = 0.5
    xs.append(sit + rng.normal(0, 0.02, (n_per_class, N_FEATURES)).astype(np.float32))
    ys += [SITTING] * n_per_class
    return np.concatenate(xs), np.array(ys)


class MLPTests(unittest.TestCase):
    def test_param_count_matches_doc(self):
        # 36*64+64 + 64*32+32 + 32*3+3 = 4547  (docs/vision-research.md §6: "~4.5k")
        self.assertEqual(PostureMLP.random().n_params, 4547)

    def test_save_load_roundtrip(self):
        m = PostureMLP.random(3)
        x = np.random.default_rng(0).random((5, N_FEATURES)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mlp.npz"
            m.save(path)
            np.testing.assert_allclose(PostureMLP.load(path).predict_proba(x), m.predict_proba(x))

    def test_proba_sums_to_one(self):
        p = PostureMLP.random().predict_proba(np.zeros((4, N_FEATURES), dtype=np.float32))
        np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-5)

    def test_bad_params_rejected(self):
        with self.assertRaises(ValueError):
            PostureMLP({"w1": np.zeros((2, 2))})

    def test_training_learns_synthetic_postures(self):
        x, y = _synthetic_dataset()
        res = train(x, y, epochs=60, lr=3e-3, seed=1)
        self.assertGreater(res.best_val_acc, 0.95)
        idx, prob = res.model.predict(extract_features(*lying_person()))
        self.assertEqual(idx, HORIZONTAL)
        self.assertGreater(prob, 0.5)


if __name__ == "__main__":
    unittest.main()
