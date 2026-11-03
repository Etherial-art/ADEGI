"""Merge several YOLO datasets (+ yolov8x auto-labels) into one 7-class dataset and data.yaml.

    python -m adegi_vision.tools.merge_dataset --out /content/adegi_det \\
        --source canewalker /content/cw "CC BY 4.0" \\
        --source coco_subset /content/coco_sub "CC BY 4.0" \\
        --autolabels /content/autolabels

Steps and why:
1. Each source's own class names are remapped to the ADEGI ids BY NAME (dataset.py). Names
   with no equivalent are dropped and reported, never guessed.
2. For images that have a yolov8x auto-label file, those boxes are added (human labels win
   on duplicates) so COCO classes in cane/walker images are not trained as background.
3. Existing train/valid/test splits are kept (a random split of near-duplicate video frames
   would leak between train and val); unsplit sources get a seeded random 90/10 split.
4. Writes data.yaml and dataset_manifest.json with the LICENSE of every source: ADEGI is a
   product, so we must know what each image may be used for.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import Counter
from pathlib import Path

from ..classes import CLASS_NAMES
from ..dataset import build_id_map, format_label, merge_boxes, remap_labels

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLIT_ALIASES = {"train": "train", "valid": "val", "val": "val", "test": "test"}


def read_names(root: Path) -> dict[int, str] | list[str]:
    import yaml

    for name in ("data.yaml", "dataset.yaml"):
        f = root / name
        if f.exists():
            names = yaml.safe_load(f.read_text()).get("names")
            if names is None:
                break
            return {int(k): v for k, v in names.items()} if isinstance(names, dict) else list(names)
    raise SystemExit(f"{root}: no data.yaml with `names` found")


def find_splits(root: Path) -> dict[str, tuple[Path, Path]]:
    """Return {split: (images_dir, labels_dir)} for Roboflow or Ultralytics layouts."""
    found: dict[str, tuple[Path, Path]] = {}
    for folder, split in SPLIT_ALIASES.items():
        if (root / folder / "images").is_dir():  # Roboflow: train/images, train/labels
            found[split] = (root / folder / "images", root / folder / "labels")
        elif (root / "images" / folder).is_dir():  # Ultralytics: images/train, labels/train
            found[split] = (root / "images" / folder, root / "labels" / folder)
    if not found and (root / "images").is_dir():  # unsplit: images/, labels/
        found["all"] = (root / "images", root / "labels")
    if not found:
        raise SystemExit(f"{root}: unrecognised layout (expected train/images or images/train)")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", nargs=3, action="append", metavar=("NAME", "PATH", "LICENSE"), required=True)
    ap.add_argument("--autolabels", type=Path, default=None, help="folder from tools.autolabel")
    ap.add_argument("--dup-iou", type=float, default=0.6)
    ap.add_argument("--val-fraction", type=float, default=0.1, help="only for unsplit sources")
    ap.add_argument("--drop-empty", action="store_true", help="skip images left with no labels")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    counts: dict[str, Counter] = {s: Counter() for s in ("train", "val", "test")}
    class_counts: Counter = Counter()
    manifest = {"classes": CLASS_NAMES, "sources": []}

    for name, path_s, lic in args.source:
        root = Path(path_s)
        id_map, dropped = build_id_map(read_names(root))
        if not id_map:
            raise SystemExit(f"{name}: none of its classes map to ADEGI classes ({dropped})")
        n_img = 0
        for split, (img_dir, lbl_dir) in find_splits(root).items():
            for img in sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT):
                dst_split = split if split != "all" else ("val" if rng.random() < args.val_fraction else "train")
                lbl = lbl_dir / f"{img.stem}.txt"
                own = remap_labels(lbl.read_text().splitlines(), id_map) if lbl.exists() else []
                auto: list = []
                if args.autolabels and (args.autolabels / f"{img.stem}.txt").exists():
                    auto = remap_labels((args.autolabels / f"{img.stem}.txt").read_text().splitlines(),
                                        {i: i for i in range(len(CLASS_NAMES))})
                boxes = merge_boxes(own, auto, args.dup_iou)
                if args.drop_empty and not boxes:
                    continue
                stem = f"{name}__{img.stem}"
                (args.out / "images" / dst_split).mkdir(parents=True, exist_ok=True)
                (args.out / "labels" / dst_split).mkdir(parents=True, exist_ok=True)
                shutil.copy2(img, args.out / "images" / dst_split / f"{stem}{img.suffix.lower()}")
                (args.out / "labels" / dst_split / f"{stem}.txt").write_text(
                    "".join(format_label(b) + "\n" for b in boxes))
                counts[dst_split][name] += 1
                class_counts.update(CLASS_NAMES[b[0]] for b in boxes)
                n_img += 1
        manifest["sources"].append({"name": name, "path": str(root), "license": lic,
                                    "images": n_img, "dropped_class_names": dropped})
        print(f"{name}: {n_img} images, dropped classes: {dropped or 'none'}")

    manifest["boxes_per_class"] = dict(class_counts)
    manifest["images_per_split"] = {k: sum(v.values()) for k, v in counts.items()}
    (args.out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2))

    yaml_lines = [f"path: {args.out.resolve()}", "train: images/train", "val: images/val"]
    if (args.out / "images" / "test").is_dir():
        yaml_lines.append("test: images/test")
    yaml_lines.append("names:")
    yaml_lines += [f"  {i}: {n}" for i, n in enumerate(CLASS_NAMES)]
    (args.out / "data.yaml").write_text("\n".join(yaml_lines) + "\n")

    print("boxes per class:", dict(class_counts))
    for c in CLASS_NAMES:
        if class_counts[c] == 0:
            print(f"WARNING: class {c!r} has no boxes - training would never learn it")
    print(f"wrote {args.out / 'data.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
