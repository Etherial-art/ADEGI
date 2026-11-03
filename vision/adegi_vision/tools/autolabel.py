"""Auto-label COCO-class objects with yolov8x so cane/walker images don't cause forgetting.

    python -m adegi_vision.tools.autolabel --images path/to/images --out path/to/autolabels

Why this exists (catastrophic forgetting): if you fine-tune YOLOv8n on images where only
`cane` and `walker` are labelled, every unlabelled chair/person/bed in those images is
trained as BACKGROUND, and the model "unlearns" what it knew from COCO. yolov8x (the big,
accurate COCO model) fills in the missing labels for the 5 COCO classes we keep; the
merge tool then combines them with the human cane/walker boxes.

Output: one YOLO .txt per image, class ids already remapped to the ADEGI scheme.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ..classes import COCO_TO_ADEGI
from ..dataset import autolabel_filter_ids, format_label

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", type=Path, required=True, help="folder (searched recursively)")
    ap.add_argument("--out", type=Path, required=True, help="folder for the .txt labels (flat, by image stem)")
    ap.add_argument("--model", default="yolov8x.pt")
    ap.add_argument("--conf", type=float, default=0.45,
                    help="high on purpose: a wrong auto-label is worse than a missing one")
    ap.add_argument("--imgsz", type=int, default=640, help="teacher runs at full res, not 256")
    ap.add_argument("--device", default=None)
    args = ap.parse_args(argv)

    from ultralytics import YOLO  # lazy import

    files = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMG_EXT)
    if not files:
        raise SystemExit(f"no images found under {args.images}")
    dupes = {s for s, c in Counter(f.stem for f in files).items() if c > 1}
    if dupes:  # labels are stored flat by stem, so equal stems would overwrite each other
        raise SystemExit(f"duplicate image names (e.g. {sorted(dupes)[:3]}): rename or run per folder")
    args.out.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)

    n_boxes = 0
    # classes= restricts the output to COCO ids [0, 56, 57, 59, 60]
    for res in model.predict([str(f) for f in files], classes=autolabel_filter_ids(), conf=args.conf,
                             imgsz=args.imgsz, device=args.device, stream=True, verbose=False):
        lines = []
        for xywhn, cls in zip(res.boxes.xywhn.cpu().numpy(), res.boxes.cls.cpu().numpy()):
            lines.append(format_label((COCO_TO_ADEGI[int(cls)], *map(float, xywhn))))
        n_boxes += len(lines)
        (args.out / f"{Path(res.path).stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    print(f"labelled {len(files)} images, {n_boxes} boxes -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
