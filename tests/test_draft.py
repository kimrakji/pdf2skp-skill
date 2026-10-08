import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from test_pipeline import SKILL, make_decisions, make_pdf
from core.files import digest, read_json
from externals.pdf.adapter import inspect_pdf
from externals.pdf.outlined_paths import closed_outline, parallel_footprints
from features.walls.service import build_model
from features.walls.solid import validate_model


class DraftTest(unittest.TestCase):
    def test_parallel_lines_preserve_a_door_gap(self):
        objects = [{"stroke": True, "fill": False, "path": [("m", (lo, y)), ("l", (hi, y))]}
                   for lo, hi in [(0, 60), (90, 150)] for y in (0, 6)]
        polygons = list(parallel_footprints(objects))
        self.assertEqual([p.bounds for p in polygons], [(0, 0, 60, 6), (90, 0, 150, 6)])
        self.assertEqual(list(parallel_footprints(objects + objects)), polygons)
        self.assertFalse(closed_outline([("m", (0, 0)), ("l", (60, 0)), ("l", (60, 6))]))

    def test_rotated_stroke_pdf_produces_outline_and_pair_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=150)
            stream = DecodedStreamObject()
            stream.set_data(b"20 20 60 6 re S\n100 20 m 160 20 l S\n100 26 m 160 26 l S\n")
            page[NameObject("/Contents")] = writer._add_object(stream)
            page.rotate(270)
            with (root / "stroke.pdf").open("wb") as target:
                writer.write(target)
            evidence = inspect_pdf(root / "stroke.pdf", 1, root, outlines=True)
            kinds = {c.get("source_kind") for c in evidence["candidates"]}
            self.assertEqual(kinds, {"closed_outline", "parallel_lines"})
            decisions = make_decisions(evidence)
            model = build_model(evidence, decisions, read_json(SKILL / "references/company-rules.json"), 2800, draft=True)
            self.assertEqual(len(model["walls"]), 2)
            self.assertEqual({w["height_mm"] for w in model["walls"]}, {2800})
            self.assertEqual({w["area_mm2"] for w in model["walls"]}, {36000})
            self.assertEqual({w["group"] for w in model["walls"]}, {"Walls_Suggested"})
            self.assertEqual(model["geometry_sha256"], build_model(evidence, decisions, read_json(SKILL / "references/company-rules.json"), 2800, draft=True)["geometry_sha256"])

    def prepare_scan(self, root):
        image = Image.new("RGB", (200, 150), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 180, 130), outline="black", width=3)
        image.save(root / "scan.pdf", resolution=72)
        evidence_dir = root / "evidence"
        evidence_dir.mkdir()
        evidence = inspect_pdf(root / "scan.pdf", 1, evidence_dir, outlines=True)
        self.assertEqual(evidence["candidates"], [])
        (evidence_dir / "evidence.json").write_text(json.dumps(evidence))
        decisions = make_decisions(evidence)
        decisions["calibration"] = []
        decisions["unresolved"] = ["Raster source; trace remaining walls manually"]
        (root / "decisions.json").write_text(json.dumps(decisions))
        result = subprocess.run([sys.executable, str(SKILL / "scripts/main.py"), "compile", "--evidence", str(evidence_dir / "evidence.json"),
                                 "--decisions", str(root / "decisions.json"), "--wall-height-mm", "2800", "--out", str(root / "model")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return read_json(root / "model/model.json")

    def test_scan_and_missing_scale_deliver_a_reference_instead_of_blocking(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = self.prepare_scan(root)
            validate_model(payload)
            self.assertEqual(payload["walls"], [])
            self.assertEqual(payload["status"], "draft_ready")
            self.assertAlmostEqual(payload["mm_per_pt"], 100 * 25.4 / 72)
            self.assertIn("Raster source; trace remaining walls manually", payload["review_items"])
            self.assertTrue((root / "model/source-plan.png").is_file())
            tampered = copy.deepcopy(payload)
            tampered["reference"]["width_mm"] *= 2
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_model(tampered)

    def test_draft_uncertainty_and_conflicting_dimensions_do_not_block_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_pdf(root / "filled.pdf")
            evidence = inspect_pdf(root / "filled.pdf", 1, root)
            decisions = make_decisions(evidence)
            decisions["calibration"][1]["distance_mm"] = 1500
            decisions["walls"][0]["confidence"] = 0.6
            decisions["unresolved"] = ["Window details omitted"]
            model = build_model(evidence, decisions, read_json(SKILL / "references/company-rules.json"), 2800, draft=True)
            self.assertEqual(model["status"], "draft_ready")
            self.assertIn("Window details omitted", model["review_items"])
            self.assertTrue(any("disagree" in note for note in model["review_items"]))
            self.assertEqual(model["mm_per_pt"], 10)
            self.assertTrue(any(w["group"] == "Walls_Suggested" for w in model["walls"]))
            decisions["walls"][0]["candidate_id"] = "missing"
            with self.assertRaisesRegex(ValueError, "Unknown"):
                build_model(evidence, decisions, read_json(SKILL / "references/company-rules.json"), 2800, draft=True)

    def test_native_reference_only_roundtrip(self):
        library = Path("/Applications/SketchUp 2026/SketchUp.app/Contents/Frameworks/SketchUpAPI.framework/SketchUpAPI")
        if not library.is_file():
            self.skipTest("No local SketchUp C API")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.prepare_scan(root)
            for command in ("export-native", "verify-native"):
                out = root / ("draft.skp" if command == "export-native" else "reopen.json")
                args = [sys.executable, str(SKILL / "scripts/main.py"), command, "--model", str(root / "model/model.json"),
                        "--library", str(library), "--out", str(out)]
                if command == "verify-native":
                    args += ["--skp", str(root / "draft.skp")]
                result = subprocess.run(args, capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr)
            report = read_json(root / "reopen.json")
            self.assertTrue(report["reference_verified"])
            self.assertEqual(report["wall_count"], 0)
            self.assertTrue(report["review_items"])


if __name__ == "__main__":
    unittest.main()
