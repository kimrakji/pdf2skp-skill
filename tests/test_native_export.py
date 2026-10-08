"""Real native file round trips; skipped only when no local C API is available."""

import copy
import ctypes as c
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "skills/pdf-to-sketchup"
sys.path.insert(0, str(SKILL / "scripts"))

from core.files import digest, read_json, write_json
from externals.sketchup.c_api import CAPI, NativeError, Transform
from externals.sketchup.native import verify_file
from features.walls.solid import prism
from features.walls.solid import validate_model


def fixture():
    shapes = [
        ("rectangle", [[0, 0], [600, 0], [600, 100], [0, 100]], [], 2700, 60000, "Walls_Default"),
        ("concave", [[1000, 0], [1600, 0], [1600, 100], [1100, 100], [1100, 700], [1000, 700]], [], 2700, 120000, "Walls_Default"),
        ("hole", [[2000, 0], [2800, 0], [2800, 800], [2000, 800]], [[[2200, 200], [2200, 600], [2600, 600], [2600, 200]]], 2700, 480000, "벽체_구멍"),
        ("low", [[3000, 0], [3400, 0], [3400, 100], [3000, 100]], [], 1200, 40000, "Walls_Low"),
    ]
    walls = [{"id": name, "outer_mm": outer, "holes_mm": holes, "height_mm": height,
              "area_mm2": area, "group": group, "source_ids": [f"synthetic:{name}"]}
             for name, outer, holes, height, area, group in shapes]
    return {"schema_version": "1.0", "units": "mm", "scope": "partial", "status": "ready_for_native_test",
            "review_items": [], "source_sha256": "0" * 64, "geometry_sha256": digest(walls), "walls": walls}


class NativeBoundaryTest(unittest.TestCase):
    def test_rejects_review_and_tampered_geometry(self):
        payload = fixture()
        payload["status"] = "review_required"
        with self.assertRaisesRegex(ValueError, "Review"):
            validate_model(payload)
        payload = fixture()
        payload["walls"][0]["height_mm"] = 3200
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_model(payload)

    def test_rejects_invalid_polygon_and_false_area(self):
        payload = fixture()
        payload["walls"][0]["outer_mm"] = [[0, 0], [100, 100], [0, 100], [100, 0]]
        payload["geometry_sha256"] = digest(payload["walls"])
        with self.assertRaisesRegex(ValueError, "polygon"):
            validate_model(payload)
        payload = fixture()
        payload["walls"][0]["area_mm2"] *= 2
        payload["geometry_sha256"] = digest(payload["walls"])
        with self.assertRaisesRegex(ValueError, "area does not match"):
            validate_model(payload)


class NativeRoundTripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = Path(os.environ.get("INTERIOR_OS_TEST_SKETCHUP_API", "/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI"))
        if not cls.library.is_file():
            raise unittest.SkipTest("Set INTERIOR_OS_TEST_SKETCHUP_API to a local SketchUp C API binary")

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(SKILL / "scripts/main.py"), *map(str, args), "--library", str(self.library)],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_geometry_roundtrip_repeatability_and_height_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = fixture()
            write_json(root / "model.json", original)
            reports = []
            for i in range(3):
                skp = root / f"roundtrip-{i}.skp"
                result = self.run_cli("export-native", "--model", root / "model.json", "--out", skp)
                self.assertTrue(result["reopen_verified"])
                self.assertGreater(skp.stat().st_size, 100)
                # A second independent process reads the file and validates serialized data.
                reopened = self.run_cli("verify-native", "--model", root / "model.json", "--skp", skp, "--out", root / f"reopened-{i}.json")
                self.assertEqual(reopened["wall_count"], 4)
                walls = {wall["id"]: wall for wall in reopened["walls"]}
                self.assertEqual(walls["hole"]["cap_hole_counts"], [1, 1])
                self.assertEqual(walls["low"]["actual_height_mm"], 1200)
                self.assertTrue(all(wall["solid"] for wall in walls.values()))
                reports.append(reopened)
            # File GUIDs can vary: compare semantic geometry, not .skp byte hashes.
            self.assertEqual(reports[0]["walls"], reports[1]["walls"])
            self.assertEqual(reports[1]["walls"], reports[2]["walls"])
            changed = copy.deepcopy(original)
            for wall in changed["walls"]:
                if wall["id"] != "low":
                    wall["height_mm"] = 3200
            changed["geometry_sha256"] = digest(changed["walls"])
            write_json(root / "height.json", changed)
            self.run_cli("export-native", "--model", root / "height.json", "--out", root / "height.skp")
            height_report = read_json(root / "height.skp.validation.json")
            baseline = {wall["id"]: wall for wall in reports[0]["walls"]}
            for wall in height_report["walls"]:
                expected_height = 1200 if wall["id"] == "low" else 3200
                self.assertAlmostEqual(wall["actual_height_mm"], expected_height, places=6)
                expected_ratio = 1 if wall["id"] == "low" else 3200 / 2700
                self.assertAlmostEqual(wall["actual_volume_mm3"] / baseline[wall["id"]]["actual_volume_mm3"], expected_ratio, places=8)

    def test_refuses_overwrite_and_mismatched_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = fixture()
            write_json(root / "model.json", payload)
            skp = root / "protected.skp"
            self.run_cli("export-native", "--model", root / "model.json", "--out", skp)
            before = skp.read_bytes()
            result = subprocess.run([sys.executable, str(SKILL / "scripts/main.py"), "export-native", "--model", str(root / "model.json"),
                                     "--out", str(skp), "--library", str(self.library)], capture_output=True, text=True, timeout=45)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Output already exists", result.stderr)
            self.assertEqual(skp.read_bytes(), before)
            payload["walls"][0]["height_mm"] = 3200
            payload["geometry_sha256"] = digest(payload["walls"])
            write_json(root / "changed.json", payload)
            result = subprocess.run([sys.executable, str(SKILL / "scripts/main.py"), "verify-native", "--model", str(root / "changed.json"),
                                     "--skp", str(skp), "--out", str(root / "rejected.json"), "--library", str(self.library)], capture_output=True, text=True, timeout=45)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("attribute mismatch", result.stderr)
            self.assertFalse((root / "rejected.json").exists())

    def test_moved_parent_group_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = fixture()
            write_json(root / "model.json", payload)
            self.run_cli("export-native", "--model", root / "model.json", "--out", root / "original.skp")
            with CAPI(self.library) as api:
                with api.model(root / "original.skp") as model:
                    entities = api.ref("SUModelGetEntities", model)
                    group = api.collection(entities, "Groups")[0]
                    transform = Transform()
                    for i in range(16):
                        transform.values[i] = 1 if i % 5 == 0 else 0
                    transform.values[12] = 100 / 25.4
                    api.call("SUGroupSetTransform", group, c.byref(transform))
                    api.call("SUModelSaveToFile", model, str(root / "moved.skp").encode())
            with self.assertRaisesRegex(NativeError, "group transform"):
                verify_file(self.library, root / "moved.skp", payload, [prism(wall) for wall in payload["walls"]])


if __name__ == "__main__":
    unittest.main()
