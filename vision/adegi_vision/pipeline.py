"""Main vision loop logic: frame interleaving + posture + context rules + fall debounce.

Frame interleaving, and why: people move fast but furniture does not. Pose runs EVERY
frame (cheap, needed for reactive tracking); the detector runs every N frames and updates
a furniture map reused in between. That multiplies effective FPS without losing context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .backends.base import InferenceBackend
from .classes import PERSON, POSTURES, STATE_FALLEN, STATE_UNKNOWN
from .context_rules import FallDebouncer, PersonContext, RuleConfig, classify_context
from .features import extract_features
from .posture_mlp import PostureMLP
from .types import Box, Detection, PersonPose


@dataclass
class PipelineConfig:
    detector_every: int = 4  # docs/vision-research.md §2: 3-5
    min_person_conf: float = 0.4
    fall_hold_s: float = 3.0
    fall_clear_s: float = 1.0
    rules: RuleConfig = field(default_factory=RuleConfig)


@dataclass
class PersonResult:
    pose: PersonPose
    posture: str
    posture_prob: float
    context: PersonContext

    @property
    def state(self) -> str:
        return self.context.state

    @property
    def confidence(self) -> float:
        return self.pose.conf * self.posture_prob


@dataclass
class FrameResult:
    persons: list[PersonResult]
    fall_alert: bool
    detector_ran: bool
    held_state: str = STATE_UNKNOWN  # primary person's state; last conclusive one if this frame is inconclusive

    @property
    def primary(self) -> PersonResult | None:
        return max(self.persons, key=lambda p: p.pose.conf, default=None)


class VisionPipeline:
    def __init__(self, backend: InferenceBackend, mlp: PostureMLP, cfg: PipelineConfig | None = None):
        self.backend, self.mlp, self.cfg = backend, mlp, cfg or PipelineConfig()
        self.furniture: list[Detection] = []  # the "furniture map", refreshed by the detector
        self._frame_idx = 0
        self._last_state = STATE_UNKNOWN
        # One debouncer for the whole scene: ADEGI looks after one person at home; any
        # sustained `fallen` person raises the alert.
        self._debouncer = FallDebouncer(self.cfg.fall_hold_s, self.cfg.fall_clear_s)

    def process(self, frame, t: float) -> FrameResult:
        run_det = self._frame_idx % self.cfg.detector_every == 0
        self._frame_idx += 1
        if run_det:
            # Person boxes come from the pose model; the detector contributes furniture/aids.
            self.furniture = [d for d in self.backend.detect(frame) if d.cls_id != PERSON]

        persons: list[PersonResult] = []
        for pose in self.backend.pose(frame):
            if pose.conf < self.cfg.min_person_conf:
                continue
            idx, prob = self.mlp.predict(extract_features(pose.box, pose.keypoints))
            ctx = classify_context(idx, pose.box, pose.keypoints, self.furniture, self.cfg.rules)
            persons.append(PersonResult(pose, POSTURES[idx], prob, ctx))

        # Observation for the debouncer: True if someone is fallen, False if someone is
        # seen and nobody is fallen, None if inconclusive or nobody visible (keep last).
        if any(p.state == STATE_FALLEN for p in persons):
            obs: bool | None = True
        elif persons and all(p.state != STATE_UNKNOWN for p in persons):
            obs = False
        else:
            obs = None
        alert = self._debouncer.update(obs, t)
        result = FrameResult(persons, alert, run_det)
        prim = result.primary
        if prim is not None and prim.state != STATE_UNKNOWN:
            self._last_state = prim.state
        result.held_state = self._last_state
        return result


def person_state_event(result: FrameResult, t: float) -> dict:
    """JSON-serialisable `person_state` event (documented in docs/protocol.md)."""
    p = result.primary
    if p is None:
        return {"type": "person_state", "ts": t, "present": False, "fall_alert": result.fall_alert}
    b: Box = p.pose.box
    return {
        "type": "person_state", "ts": t, "present": True,
        "state": result.held_state, "confidence": round(p.confidence, 3),
        "bbox": [round(b.x1, 1), round(b.y1, 1), round(b.x2, 1), round(b.y2, 1)],
        "with_aid": p.context.with_aid, "aid_far": p.context.aid_far,
        "fall_alert": result.fall_alert,
    }
