"""Turn a folder of posture-labelled images into a feature dataset for the MLP.

    python -m adegi_vision.tools.extract_keypoints --root data/posture \\
        --pose-model yolov8n-pose.pt --out data/posture_features.npz

Expected layout: <root>/standing/*.jpg, <root>/sitting/*.jpg, <root>/horizontal/*.jpg
(folder name = label; frames from fall/ADL datasets sorted by posture).

Why run the SAME pose model that will be deployed: the MLP must see the keypoint noise
patterns of the real model. Training it on ground-truth skeletons and deploying it on
noisy estimates is a classic cause of "works in the notebook, fails on the robot".
Only the most confident person per image is used (these images show a single person).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ..classes import POSTURES
from ..features import extract_features

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--pose-model", default="yolov8n-pose.pt")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--imgsz", type=int, default=256)
    ap.add_argument("--min-conf", type=float, default=0.5)
    args = ap.parse_args(argv)

    from ..backends.ultralytics_backend import UltralyticsBackend

    # Only the pose model is needed; the detector slot is filled with the same weights file
    # to satisfy the constructor and is never called here.
    backend = UltralyticsBackend(args.pose_model, args.pose_model, imgsz=args.imgsz, pose_conf=args.min_conf)
    import cv2

    xs, ys, skipped = [], [], 0
    for label, name in enumerate(POSTURES):
        files = sorted(p for p in (args.root / name).glob("*") if p.suffix.lower() in IMG_EXT)
        if not files:
            print(f"WARNING: no images in {args.root / name}")
        for f in files:
            img = cv2.imread(str(f))
            poses = backend.pose(img) if img is not None else []
            if not poses:
                skipped += 1
                continue
            best = max(poses, key=lambda p: p.conf)
            xs.append(extract_features(best.box, best.keypoints))
            ys.append(label)
    if not xs:
        raise SystemExit("no features extracted")
    np.savez(args.out, x=np.stack(xs), y=np.array(ys, dtype=np.int64), classes=np.array(POSTURES))
    print(f"{len(xs)} samples ({skipped} images skipped, no person) -> {args.out}")
    print({n: int((np.array(ys) == i).sum()) for i, n in enumerate(POSTURES)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
