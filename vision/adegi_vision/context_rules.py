"""Context rules: turn "horizontal" into lying_bed vs fallen, using furniture and keypoints.

Why rules on top of the MLP: a person lying on a bed and a person lying on the floor have
the SAME body pose. Only the surroundings tell them apart, so this decision cannot be
learned from keypoints alone.

Why IoP (intersection over person) instead of IoU: a bed is far bigger than a person, so
IoU would stay tiny even when the person is entirely on the bed.

All thresholds are INITIAL values (docs/vision-research.md §7); calibrate them with real
footage from the robot camera height (~30-50 cm).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .classes import (
    BED, CANE, CHAIR, COUCH, HORIZONTAL, L_HIP, L_SHOULDER, NOSE, R_HIP, R_SHOULDER, SITTING,
    STANDING, STATE_FALLEN, STATE_LYING_BED, STATE_SITTING, STATE_STANDING, STATE_UNKNOWN, WALKER,
)
from .types import Box, Detection


@dataclass(frozen=True)
class RuleConfig:
    bed_iop_min: float = 0.55
    bed_trunk_kpts_min: int = 2
    kpt_conf_min: float = 0.3
    hip_above_base_frac: float = 0.15
    torso_angle_max_deg: float = 35.0
    sit_iop_min: float = 0.30
    aid_overlap_min: float = 0.30  # fraction of the cane/walker box inside the person box
    aid_far_factor: float = 1.0  # "far" = center distance > factor * longer side of person box


@dataclass(frozen=True)
class PersonContext:
    state: str
    with_aid: bool = False  # standing + cane/walker overlapping ("walking with aid")
    sitting_confirmed: bool = False
    aid_far: bool = False  # cane/walker lying away from the person (extra fall evidence)
    bed_iop: float = 0.0


def iop(person: Box, other: Box) -> float:
    """Intersection over Person: area(person ∩ other) / area(person)."""
    if person.area <= 0:
        return 0.0
    return person.intersection_area(other) / person.area


def _visible_xy(kp: np.ndarray, idxs: tuple[int, ...], conf_min: float) -> np.ndarray:
    pts = [kp[i, :2] for i in idxs if kp[i, 2] > conf_min]
    return np.array(pts, dtype=np.float32).reshape(-1, 2)


def torso_angle_deg(kp: np.ndarray, conf_min: float = 0.3) -> float | None:
    """Angle of the shoulders-midpoint -> hips-midpoint line vs the HORIZONTAL axis.

    0° = torso horizontal, 90° = vertical. None if shoulders or hips are not visible.
    """
    sh = _visible_xy(kp, (L_SHOULDER, R_SHOULDER), conf_min)
    hp = _visible_xy(kp, (L_HIP, R_HIP), conf_min)
    if len(sh) == 0 or len(hp) == 0:
        return None
    d = hp.mean(axis=0) - sh.mean(axis=0)
    return math.degrees(math.atan2(abs(float(d[1])), abs(float(d[0]))))


def _is_lying_on(person: Box, kp: np.ndarray, furniture: Box, cfg: RuleConfig) -> bool:
    # (2) at least 2 trunk keypoints (nose, shoulders, hips) inside the furniture box
    trunk = (NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)
    inside = sum(
        1 for i in trunk if kp[i, 2] > cfg.kpt_conf_min and furniture.contains(kp[i, 0], kp[i, 1])
    )
    if inside < cfg.bed_trunk_kpts_min:
        return False
    # (3) hip above the base of the bed (image y grows downward). Someone who slid off the
    # bed ends with the hips at/below the bed's lower edge, i.e. on the floor beside it.
    hips = _visible_xy(kp, (L_HIP, R_HIP), cfg.kpt_conf_min)
    hip_y = float(hips[:, 1].mean()) if len(hips) else person.center[1]  # fallback: box center
    return hip_y < furniture.y2 - cfg.hip_above_base_frac * furniture.h


def classify_context(
    posture: int,
    person: Box,
    keypoints: np.ndarray,
    detections: list[Detection],
    cfg: RuleConfig = RuleConfig(),
) -> PersonContext:
    kp = np.asarray(keypoints, dtype=np.float32)
    aids = [d for d in detections if d.cls_id in (CANE, WALKER)]

    if posture == HORIZONTAL:
        angle = torso_angle_deg(kp, cfg.kpt_conf_min)
        if angle is not None and angle >= cfg.torso_angle_max_deg:
            # MLP says horizontal but the torso is clearly upright: contradictory evidence.
            return PersonContext(STATE_UNKNOWN)

        beds = [d for d in detections if d.cls_id in (BED, COUCH)]
        best = max(beds, key=lambda d: iop(person, d.box), default=None)
        best_iop = iop(person, best.box) if best else 0.0
        on_bed = best is not None and best_iop >= cfg.bed_iop_min and _is_lying_on(
            person, kp, best.box, cfg
        )
        if on_bed:
            return PersonContext(STATE_LYING_BED, bed_iop=best_iop)
        return PersonContext(STATE_FALLEN, aid_far=_aid_far(person, aids, cfg), bed_iop=best_iop)

    if posture == SITTING:
        seats = [d for d in detections if d.cls_id in (CHAIR, COUCH, BED)]
        confirmed = any(iop(person, d.box) > cfg.sit_iop_min for d in seats)
        return PersonContext(STATE_SITTING, sitting_confirmed=confirmed)

    if posture == STANDING:
        with_aid = any(_aid_overlap(person, d.box) >= cfg.aid_overlap_min for d in aids)
        return PersonContext(STATE_STANDING, with_aid=with_aid)

    raise ValueError(f"unknown posture index {posture}")


def _aid_overlap(person: Box, aid: Box) -> float:
    return person.intersection_area(aid) / aid.area if aid.area > 0 else 0.0


def _aid_far(person: Box, aids: list[Detection], cfg: RuleConfig) -> bool:
    """True if there is a cane/walker and none of them is near the person."""
    if not aids:
        return False
    px, py = person.center
    # Use the LONGER box side as the body length: a lying person has a wide, short box, so
    # box height would make every cane look "far".
    limit = cfg.aid_far_factor * max(person.w, person.h, 1e-6)
    return all(math.hypot(d.box.center[0] - px, d.box.center[1] - py) > limit for d in aids)


class FallDebouncer:
    """Raise the fall alert only after `hold_s` of sustained `fallen`.

    Why: pose estimation flickers frame to frame, and a person who just crouched to pick
    something up looks horizontal for a moment. A false alarm to the family costs trust.
    A short non-fallen blip (< `clear_s`) does NOT reset the timer, so noise cannot hide a
    real fall either. `None` (inconclusive/no person) changes nothing.
    """

    def __init__(self, hold_s: float = 3.0, clear_s: float = 1.0):
        self.hold_s, self.clear_s = hold_s, clear_s
        self.active = False
        self._fall_since: float | None = None
        self._ok_since: float | None = None

    def update(self, fallen: bool | None, t: float) -> bool:
        if fallen is None:
            return self.active
        if fallen:
            self._ok_since = None
            if self._fall_since is None:
                self._fall_since = t
            if t - self._fall_since >= self.hold_s:
                self.active = True
        else:
            if self._ok_since is None:
                self._ok_since = t
            if t - self._ok_since >= self.clear_s:
                self._fall_since = None
                self.active = False
        return self.active
