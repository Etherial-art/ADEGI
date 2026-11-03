import json
import tempfile
import unittest
from pathlib import Path

from adegi_vision import dataset as ds
from adegi_vision.classes import BED, CANE, CHAIR, CLASS_NAMES, COUCH, PERSON, WALKER
from adegi_vision.tools import merge_dataset


class RemapTests(unittest.TestCase):
    def test_name_based_map_and_dropped(self):
        m, dropped = ds.build_id_map({0: "Walker", 1: "walking_stick", 2: "dog", 3: "Sofa"})
        self.assertEqual(m, {0: WALKER, 1: CANE, 3: COUCH})
        self.assertEqual(dropped, ["dog"])

    def test_list_names(self):
        m, _ = ds.build_id_map(["person", "chair"])
        self.assertEqual(m, {0: PERSON, 1: CHAIR})

    def test_remap_drops_unmapped_and_handles_polygons(self):
        lines = ["0 0.5 0.5 0.2 0.4", "1 0.1 0.1 0.9 0.1 0.9 0.5 0.1 0.5", "7 0.5 0.5 0.1 0.1", ""]
        out = ds.remap_labels(lines, {0: CANE, 1: WALKER})
        self.assertEqual(out[0], (CANE, 0.5, 0.5, 0.2, 0.4))
        self.assertEqual(out[1][0], WALKER)
        self.assertAlmostEqual(out[1][3], 0.8)  # polygon -> bbox width
        self.assertEqual(len(out), 2)

    def test_merge_boxes_dedupes_same_class_only(self):
        own = [(PERSON, 0.5, 0.5, 0.2, 0.4)]
        auto = [(PERSON, 0.5, 0.5, 0.2, 0.41), (BED, 0.5, 0.5, 0.2, 0.4), (PERSON, 0.1, 0.1, 0.1, 0.1)]
        merged = ds.merge_boxes(own, auto)
        self.assertEqual(len(merged), 3)  # near-identical person dropped; bed + far person kept
        self.assertEqual(merged[0], own[0])

    def test_autolabel_filter_ids_match_spec(self):
        self.assertEqual(ds.autolabel_filter_ids(), [0, 56, 57, 59, 60])


def make_source(root: Path, names: list[str], items: dict[str, str], split="train", layout="roboflow"):
    img_dir = root / split / "images" if layout == "roboflow" else root / "images" / split
    lbl_dir = root / split / "labels" if layout == "roboflow" else root / "labels" / split
    img_dir.mkdir(parents=True)
    lbl_dir.mkdir(parents=True)
    for stem, label in items.items():
        (img_dir / f"{stem}.jpg").write_bytes(b"x")
        (lbl_dir / f"{stem}.txt").write_text(label)
    (root / "data.yaml").write_text("names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(names)))


class MergeToolTests(unittest.TestCase):
    def test_end_to_end_merge(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            make_source(d / "cw", ["walker", "cane", "dog"],
                        {"a": "0 0.5 0.5 0.3 0.6\n2 0.1 0.1 0.1 0.1\n", "b": "1 0.4 0.4 0.1 0.5\n"})
            make_source(d / "coco", ["bed", "person"], {"c": "0 0.5 0.5 0.8 0.5\n"},
                        split="valid", layout="ultralytics")
            (d / "auto").mkdir()
            (d / "auto" / "a.txt").write_text(f"{PERSON} 0.2 0.2 0.1 0.3\n")  # person missing in cw/a
            rc = merge_dataset.main([
                "--out", str(d / "out"), "--autolabels", str(d / "auto"),
                "--source", "cw", str(d / "cw"), "CC BY 4.0",
                "--source", "coco", str(d / "coco"), "CC BY 4.0",
            ])
            self.assertEqual(rc, 0)
            out = d / "out"
            lbl = (out / "labels" / "train" / "cw__a.txt").read_text().splitlines()
            self.assertEqual(sorted(int(l.split()[0]) for l in lbl), [PERSON, WALKER])  # dog dropped
            self.assertTrue((out / "images" / "val" / "coco__c.jpg").exists())  # 'valid' -> 'val'
            self.assertEqual((out / "labels" / "val" / "coco__c.txt").read_text().split()[0], str(BED))
            yaml_text = (out / "data.yaml").read_text()
            self.assertIn("train: images/train", yaml_text)
            self.assertIn("val: images/val", yaml_text)
            for i, n in enumerate(CLASS_NAMES):
                self.assertIn(f"  {i}: {n}", yaml_text)
            manifest = json.loads((out / "dataset_manifest.json").read_text())
            self.assertEqual({s["license"] for s in manifest["sources"]}, {"CC BY 4.0"})
            self.assertEqual(manifest["sources"][0]["dropped_class_names"], ["dog"])

    def test_unrecognised_layout_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                merge_dataset.find_splits(Path(d))


if __name__ == "__main__":
    unittest.main()
