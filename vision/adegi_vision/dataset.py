"""Pure helpers for building the 7-class detector dataset (no ML libraries needed).

Why remapping by NAME: every public dataset numbers its classes differently (Roboflow's
"walker" may be id 0 in one export and id 3 in another). Names are the only stable key.
"""

from __future__ import annotations

from .classes import CANE, CLASS_ID, COCO_TO_ADEGI, WALKER

# Aliases found in public datasets -> ADEGI class id. Lower-case, matched after normalising.
# Extend when a new source uses another name (the merge tool reports every dropped name).
NAME_ALIASES: dict[str, int] = {
    "cane": CANE, "walking cane": CANE, "walking stick": CANE, "stick": CANE, "crutch": CANE,
    "walker": WALKER, "walking frame": WALKER, "rollator": WALKER, "zimmer frame": WALKER,
    "person": CLASS_ID["person"], "chair": CLASS_ID["chair"], "couch": CLASS_ID["couch"],
    "sofa": CLASS_ID["couch"], "bed": CLASS_ID["bed"], "dining table": CLASS_ID["dining table"],
}


def normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", " ").replace("-", " ")


def build_id_map(source_names: dict[int, str] | list[str]) -> tuple[dict[int, int], list[str]]:
    """Source class id -> ADEGI id. Returns (map, dropped_names)."""
    items = source_names.items() if isinstance(source_names, dict) else enumerate(source_names)
    mapping: dict[int, int] = {}
    dropped: list[str] = []
    for sid, name in items:
        target = NAME_ALIASES.get(normalize_name(str(name)))
        if target is None:
            dropped.append(str(name))
        else:
            mapping[int(sid)] = target
    return mapping, dropped


def parse_label_line(line: str) -> tuple[int, float, float, float, float] | None:
    """YOLO *detection* line: `cls xc yc w h`. Segmentation/pose lines are reduced to a box."""
    parts = line.split()
    if len(parts) < 5:
        return None
    cls = int(float(parts[0]))
    vals = [float(v) for v in parts[1:]]
    if len(vals) == 4 or len(vals) == 4 + 51:  # det, or YOLO-pose (box first)
        xc, yc, w, h = vals[:4]
    else:  # polygon: x1 y1 x2 y2 ... -> bounding box
        xs, ys = vals[0::2], vals[1::2]
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        xc, yc, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
    return cls, xc, yc, w, h


def iou_xywh(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw, ih = min(ax2, bx2) - max(ax1, bx1), min(ay2, by2) - max(ay1, by1)
    inter = max(0.0, iw) * max(0.0, ih)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def remap_labels(lines: list[str], id_map: dict[int, int]) -> list[tuple[int, float, float, float, float]]:
    out = []
    for line in lines:
        parsed = parse_label_line(line)
        if parsed is None or parsed[0] not in id_map:
            continue
        out.append((id_map[parsed[0]], *parsed[1:]))
    return out


def merge_boxes(
    own: list[tuple[int, float, float, float, float]],
    auto: list[tuple[int, float, float, float, float]],
    dup_iou: float = 0.6,
) -> list[tuple[int, float, float, float, float]]:
    """Human labels win; an auto box is dropped if it duplicates a same-class human box.

    Why: the cane/walker datasets sometimes also label `person`. Keeping both the human box
    and the yolov8x box would teach the detector that every person is two objects.
    """
    merged = list(own)
    for a in auto:
        if not any(a[0] == o[0] and iou_xywh(a[1:], o[1:]) >= dup_iou for o in own):
            merged.append(a)
    return merged


def format_label(box: tuple[int, float, float, float, float]) -> str:
    cls, xc, yc, w, h = box
    return f"{cls} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}"


def autolabel_filter_ids() -> list[int]:
    """COCO ids passed to yolov8x via `classes=` (person, chair, couch, bed, dining table)."""
    return sorted(COCO_TO_ADEGI)
