"""Single source of truth for class ids, COCO mapping, posture labels and keypoint indices.

Why one file: the detector labels, the dataset merge script, the backends and the
context rules must all agree on the same ids. A mismatch here silently ruins training.
"""

from __future__ import annotations

# Detector classes (fine-tuned YOLOv8n). Order = class id.
CLASS_NAMES: list[str] = ["person", "chair", "couch", "bed", "dining table", "cane", "walker"]
CLASS_ID: dict[str, int] = {name: i for i, name in enumerate(CLASS_NAMES)}

PERSON = CLASS_ID["person"]
CHAIR = CLASS_ID["chair"]
COUCH = CLASS_ID["couch"]
BED = CLASS_ID["bed"]
TABLE = CLASS_ID["dining table"]
CANE = CLASS_ID["cane"]
WALKER = CLASS_ID["walker"]

# COCO class id -> ADEGI class id. yolov8x is asked ONLY for these classes when auto-labelling.
COCO_TO_ADEGI: dict[int, int] = {0: PERSON, 56: CHAIR, 57: COUCH, 59: BED, 60: TABLE}

# Posture classes predicted by the MLP.
POSTURES: list[str] = ["standing", "sitting", "horizontal"]
STANDING, SITTING, HORIZONTAL = 0, 1, 2

# High-level states published to the rest of the robot (see docs/protocol.md).
STATE_STANDING = "standing"
STATE_SITTING = "sitting"
STATE_LYING_BED = "lying_bed"
STATE_FALLEN = "fallen"
STATE_UNKNOWN = "unknown"  # internal: inconclusive frame, the temporal logic keeps the last state

# COCO keypoint order (left, right) as used by YOLO-pose.
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
NUM_KPTS = 17

# Left/right swap used for horizontal-flip augmentation (same as flip_idx in pose_data.yaml).
FLIP_IDX: list[int] = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
