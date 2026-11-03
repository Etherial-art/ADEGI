"""36-dim feature vector for the posture MLP.

Why normalise inside the person box: with raw pixels the network would learn WHERE the
person is in the room, not HOW they are posed. Dividing by the box makes the features
invariant to position and distance to the camera.
"""

from __future__ import annotations

import numpy as np

from .classes import FLIP_IDX, L_HIP, L_KNEE, NUM_KPTS, R_HIP, R_KNEE
from .types import Box

KPT_CONF_MIN = 0.25  # below this a keypoint is treated as "not seen" and zeroed
N_FEATURES = 2 * NUM_KPTS + 2  # 34 keypoint coords + aspect ratio + femur drop = 36


def extract_features(box: Box, keypoints: np.ndarray) -> np.ndarray:
    """Build the (36,) float32 feature vector.

    Layout: [x0,y0, x1,y1, ... x16,y16, aspect, femur_drop].
    - keypoint coords: ((x-xmin)/w, (y-ymin)/h) clipped to [0,1]; (0,0) if conf < 0.25.
    - aspect: min(w/h, 3)/3. Lying people are wide, standing people are tall.
    - femur_drop: mean over visible sides of (knee_y - hip_y)/h. Large and positive when
      standing (knee well below hip); ~0 when sitting (thigh horizontal) or lying.
    """
    kp = np.asarray(keypoints, dtype=np.float32)
    if kp.shape != (NUM_KPTS, 3):
        raise ValueError(f"keypoints must have shape (17, 3), got {kp.shape}")
    w = max(box.w, 1e-6)
    h = max(box.h, 1e-6)

    coords = np.zeros((NUM_KPTS, 2), dtype=np.float32)
    visible = kp[:, 2] >= KPT_CONF_MIN
    coords[visible, 0] = np.clip((kp[visible, 0] - box.x1) / w, 0.0, 1.0)
    coords[visible, 1] = np.clip((kp[visible, 1] - box.y1) / h, 0.0, 1.0)

    aspect = min(w / h, 3.0) / 3.0

    drops = []
    for hip, knee in ((L_HIP, L_KNEE), (R_HIP, R_KNEE)):
        if visible[hip] and visible[knee]:
            drops.append((kp[knee, 1] - kp[hip, 1]) / h)
    femur_drop = float(np.clip(np.mean(drops), -1.0, 1.0)) if drops else 0.0

    return np.concatenate([coords.reshape(-1), [aspect, femur_drop]]).astype(np.float32)


def flip_features(feats: np.ndarray) -> np.ndarray:
    """Mirror a feature vector left<->right (data augmentation).

    A pair (0,0) means "missing keypoint" and stays (0,0); otherwise x -> 1 - x and the
    left/right keypoints swap places. Femur drop and aspect are mirror-invariant.
    """
    f = np.asarray(feats, dtype=np.float32)
    kp = f[: 2 * NUM_KPTS].reshape(NUM_KPTS, 2).copy()
    missing = (kp[:, 0] == 0) & (kp[:, 1] == 0)
    kp[~missing, 0] = 1.0 - kp[~missing, 0]
    kp = kp[FLIP_IDX]
    return np.concatenate([kp.reshape(-1), f[2 * NUM_KPTS :]]).astype(np.float32)
