"""Posture MLP 36 -> 64 -> 32 -> 3 (ReLU). Inference AND training use only NumPy.

Why NumPy only: the board runs Linux with a minimal Python; installing PyTorch there is
heavy and pointless for a ~4.5k-parameter network (a few microseconds per forward pass on
the Cortex-A35). Training also uses NumPy so the whole pipeline is testable anywhere and
you can read exactly what backprop does. Weights travel as a .npz file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .classes import POSTURES
from .features import N_FEATURES

LAYER_SIZES = (N_FEATURES, 64, 32, len(POSTURES))
PARAM_NAMES = ("w1", "b1", "w2", "b2", "w3", "b3")


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)  # subtract max: numerical stability
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class PostureMLP:
    def __init__(self, params: dict[str, np.ndarray]):
        for name, shape in zip(PARAM_NAMES, _shapes()):
            if name not in params:
                raise ValueError(f"missing parameter {name!r}")
            if tuple(params[name].shape) != shape:
                raise ValueError(f"{name}: expected shape {shape}, got {params[name].shape}")
        self.params = {k: np.asarray(params[k], dtype=np.float32) for k in PARAM_NAMES}

    @classmethod
    def random(cls, seed: int = 0) -> "PostureMLP":
        """He initialisation: keeps ReLU activations at a sane scale across layers."""
        rng = np.random.default_rng(seed)
        params: dict[str, np.ndarray] = {}
        for i, (n_in, n_out) in enumerate(zip(LAYER_SIZES[:-1], LAYER_SIZES[1:]), start=1):
            params[f"w{i}"] = rng.normal(0.0, np.sqrt(2.0 / n_in), (n_in, n_out)).astype(np.float32)
            params[f"b{i}"] = np.zeros(n_out, dtype=np.float32)
        return cls(params)

    @classmethod
    def load(cls, path: str | Path) -> "PostureMLP":
        with np.load(path) as data:
            return cls({k: data[k] for k in PARAM_NAMES})

    def save(self, path: str | Path) -> None:
        np.savez(path, classes=np.array(POSTURES), **self.params)

    @property
    def n_params(self) -> int:
        return int(sum(p.size for p in self.params.values()))

    def logits(self, x: np.ndarray) -> np.ndarray:
        p = self.params
        x = np.asarray(x, dtype=np.float32)
        h1 = np.maximum(x @ p["w1"] + p["b1"], 0.0)
        h2 = np.maximum(h1 @ p["w2"] + p["b2"], 0.0)
        return h2 @ p["w3"] + p["b3"]  # dropout is a training-only mechanism: absent here

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return _softmax(self.logits(x))

    def predict(self, feats: np.ndarray) -> tuple[int, float]:
        """Single feature vector -> (posture index, probability)."""
        proba = self.predict_proba(feats)
        idx = int(np.argmax(proba))
        return idx, float(proba[idx])


def _shapes() -> list[tuple[int, ...]]:
    shapes: list[tuple[int, ...]] = []
    for n_in, n_out in zip(LAYER_SIZES[:-1], LAYER_SIZES[1:]):
        shapes += [(n_in, n_out), (n_out,)]
    return shapes


@dataclass
class TrainResult:
    model: PostureMLP
    best_val_acc: float
    history: list[dict] = field(default_factory=list)


def train(
    x: np.ndarray,
    y: np.ndarray,
    *,
    epochs: int = 200,
    lr: float = 1e-3,
    dropout: float = 0.2,
    batch_size: int = 64,
    val_fraction: float = 0.2,
    class_balance: bool = True,
    seed: int = 0,
    val: tuple[np.ndarray, np.ndarray] | None = None,
) -> TrainResult:
    """Mini-batch Adam + inverted dropout + class-weighted cross entropy.

    Class weights matter here: horizontal samples are rare compared with standing/sitting,
    and missing a fall is worse than a false alarm that the temporal filter can absorb.
    The best-validation weights are kept (cheap early stopping). Pass `val=(x, y)` to use
    your own validation set (e.g. different people than training); otherwise a random
    `val_fraction` is held out.
    """
    x = np.asarray(x, dtype=np.float32)
    y = np.asarray(y, dtype=np.int64)
    n_classes = len(POSTURES)
    rng = np.random.default_rng(seed)

    if val is not None:
        xtr, ytr = x, y
        xva, yva = np.asarray(val[0], dtype=np.float32), np.asarray(val[1], dtype=np.int64)
        n_val = len(xva)
    else:
        order = rng.permutation(len(x))
        n_val = max(1, int(len(x) * val_fraction)) if val_fraction > 0 else 0
        val_idx, tr_idx = order[:n_val], order[n_val:]
        xtr, ytr = x[tr_idx], y[tr_idx]
        xva, yva = x[val_idx], y[val_idx]

    counts = np.bincount(ytr, minlength=n_classes).astype(np.float32)
    cw = np.where(counts > 0, counts.sum() / (n_classes * np.maximum(counts, 1)), 0.0)
    if not class_balance:
        cw = np.ones(n_classes, dtype=np.float32)

    model = PostureMLP.random(seed)
    p = {k: v.copy() for k, v in model.params.items()}
    m = {k: np.zeros_like(v) for k, v in p.items()}  # Adam first moment
    v2 = {k: np.zeros_like(v) for k, v in p.items()}  # Adam second moment
    b1c, b2c, eps, step = 0.9, 0.999, 1e-8, 0
    best = (-1.0, {k: v.copy() for k, v in p.items()})
    history: list[dict] = []

    def drop_mask(shape: tuple[int, ...]) -> np.ndarray:
        # Inverted dropout: scale at train time so inference needs no rescaling.
        return (rng.random(shape) >= dropout).astype(np.float32) / (1.0 - dropout)

    for epoch in range(epochs):
        perm = rng.permutation(len(xtr))
        for start in range(0, len(perm), batch_size):
            idx = perm[start : start + batch_size]
            xb, yb = xtr[idx], ytr[idx]
            n = len(idx)

            # forward
            z1 = xb @ p["w1"] + p["b1"]
            a1 = np.maximum(z1, 0.0)
            m1 = drop_mask(a1.shape)
            a1d = a1 * m1
            z2 = a1d @ p["w2"] + p["b2"]
            a2 = np.maximum(z2, 0.0)
            m2 = drop_mask(a2.shape)
            a2d = a2 * m2
            probs = _softmax(a2d @ p["w3"] + p["b3"])

            # backward (softmax + cross entropy gives the simple "probs - onehot")
            onehot = np.zeros_like(probs)
            onehot[np.arange(n), yb] = 1.0
            dlogits = (probs - onehot) * cw[yb][:, None] / n
            g = {"w3": a2d.T @ dlogits, "b3": dlogits.sum(0)}
            da2 = (dlogits @ p["w3"].T) * m2 * (z2 > 0)
            g["w2"], g["b2"] = a1d.T @ da2, da2.sum(0)
            da1 = (da2 @ p["w2"].T) * m1 * (z1 > 0)
            g["w1"], g["b1"] = xb.T @ da1, da1.sum(0)

            # Adam update
            step += 1
            for k in PARAM_NAMES:
                m[k] = b1c * m[k] + (1 - b1c) * g[k]
                v2[k] = b2c * v2[k] + (1 - b2c) * g[k] ** 2
                mh = m[k] / (1 - b1c**step)
                vh = v2[k] / (1 - b2c**step)
                p[k] = p[k] - lr * mh / (np.sqrt(vh) + eps)

        cur = PostureMLP(p)
        val_acc = float((cur.predict_proba(xva).argmax(1) == yva).mean()) if n_val else 0.0
        history.append({"epoch": epoch, "val_acc": val_acc})
        if val_acc > best[0]:
            best = (val_acc, {k: v.copy() for k, v in p.items()})

    return TrainResult(PostureMLP(best[1]), best[0], history)
