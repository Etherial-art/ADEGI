"""Train the posture MLP from extracted features and export it as .npz.

    python -m adegi_vision.tools.train_posture --features data/posture_features.npz \\
        --out models/posture_mlp.npz

Mirror-flip augmentation doubles the data for free: a person lying facing left is the same
posture as one facing right, and the net should not care which way they face.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ..classes import POSTURES
from ..features import flip_features
from ..posture_mlp import train


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--val-fraction", type=float, default=0.2)
    ap.add_argument("--no-flip", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    data = np.load(args.features)
    x, y = data["x"], data["y"]
    # Split FIRST, augment only the training part. If a sample and its mirror image landed on
    # different sides of the split, validation accuracy would be optimistic (near-duplicates).
    order = np.random.default_rng(args.seed).permutation(len(x))
    n_val = max(1, int(len(x) * args.val_fraction))
    va, tr = order[:n_val], order[n_val:]
    xtr, ytr = x[tr], y[tr]
    if not args.no_flip:
        xtr = np.concatenate([xtr, np.stack([flip_features(f) for f in xtr])])
        ytr = np.concatenate([ytr, ytr])
    # Still judge the final model on a separate test set of DIFFERENT people/scenes: frames of
    # the same video are near-duplicates, so a random split of them is already optimistic.
    res = train(xtr, ytr, epochs=args.epochs, lr=args.lr, dropout=args.dropout, seed=args.seed,
                val=(x[va], y[va]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.model.save(args.out)
    print(f"{res.model.n_params} params, best val acc {res.best_val_acc:.3f}, classes {POSTURES} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
