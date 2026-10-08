import copy
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


SKILL = Path(__file__).resolve().parents[1] / "skills/pdf-to-sketchup"
sys.path.insert(0, str(SKILL / "scripts"))

from core.files import digest, read_json
from externals.pdf.adapter import inspect_pdf
from externals.pdf.filled_paths import filled_polygons
from features.walls.service import build_model


def make_pdf(path, rotation=0):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=150)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"0 g\n20 20 m 80 20 l 80 26 l h f\n20 20 m 80 26 l 20 26 l h f\n100 20 20 4 re f\nBT /F1 8 Tf 10 140 Td (SYNTHETIC DEMO - 10 mm per pt) Tj ET\n")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotation:
        page.rotate(rotation)
    with open(path, "wb") as target:
        writer.write(target)


def make_decisions(evidence):
    return {
        "schema_version": "1.0", "source_sha256": evidence["source_sha256"], "evidence_sha256": digest(evidence), "page": 1,
        "scope": "full_page", "crop_bbox_pt": [0, 0, evidence["width_pt"], evidence["height_pt"]],
        "calibration": [
            {"p1_pt": [0, 0], "p2_pt": [100, 0], "distance_mm": 1000, "evidence": "Synthetic horizontal reference, 10 mm/pt", "confidence": 1},
            {"p1_pt": [0, 0], "p2_pt": [0, 100], "distance_mm": 1000, "evidence": "Synthetic vertical reference, 10 mm/pt", "confidence": 1},
        ],
        "walls": [
            {"candidate_id": candidate["id"], "height_class": "low" if "-f00003-" in candidate["id"] else "default", "evidence": "Known synthetic wall footprint", "confidence": 1}
            for candidate in evidence["candidates"]
        ],
        "unresolved": [],
    }


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        source = root / "demo.pdf"
        make_pdf(source)
        cls.evidence = inspect_pdf(source, 1, root)
        cls.decisions = make_decisions(cls.evidence)
        cls.rules = read_json(SKILL / "references/company-rules.json")
        cls.validator = Draft202012Validator(read_json(SKILL / "references/decisions.schema.json"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def model(self, decisions=None, evidence=None, height=2700):
        decisions = self.decisions if decisions is None else decisions
        self.validator.validate(decisions)
        return build_model(self.evidence if evidence is None else evidence, decisions, self.rules, height)

    def test_triangle_pair_merges_into_one_rectangle(self):
        model = self.model()
        self.assertEqual(len(model["walls"]), 2)
        wall = model["walls"][0]
        self.assertEqual(wall["area_mm2"], 36000)
        self.assertEqual(len(wall["outer_mm"]), 4)
        self.assertEqual(len(wall["source_ids"]), 2)
        self.assertEqual(model["walls"][1]["area_mm2"], 8000)
        self.assertEqual(model["status"], "ready_for_native_test")

    def test_height_changes_preserve_xy_and_low_wall_height(self):
        a, b = self.model(height=2700), self.model(height=3200)
        for left, right in zip(a["walls"], b["walls"]):
            for key in ("outer_mm", "holes_mm", "group", "source_ids", "area_mm2"):
                self.assertEqual(left[key], right[key])
        self.assertEqual(b["walls"][0]["height_mm"], 3200)
        self.assertEqual(b["walls"][1]["height_mm"], 1200)

    def test_repeated_and_reordered_selections_have_same_geometry(self):
        a, b, c = self.model(), self.model(), self.model()
        self.assertEqual(a, b)
        self.assertEqual(b, c)
        reversed_decisions = copy.deepcopy(self.decisions)
        reversed_decisions["walls"].reverse()
        self.assertEqual(a["geometry_sha256"], self.model(reversed_decisions)["geometry_sha256"])

    def test_default_height_and_explicit_equal_height_match(self):
        self.assertEqual(self.model(height=None)["geometry_sha256"], self.model(height=2700)["geometry_sha256"])

    def test_scale_conflict_is_rejected(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["calibration"][1]["distance_mm"] = 1500
        with self.assertRaisesRegex(ValueError, "disagree"):
            self.model(decisions)

    def test_duplicate_scale_reference_is_rejected(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["calibration"][1] = decisions["calibration"][0]
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.model(decisions)

    def test_source_mismatch_and_unknown_id_are_rejected(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source"):
            self.model(decisions)
        decisions = copy.deepcopy(self.decisions)
        decisions["walls"][0]["candidate_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.model(decisions)

    def test_stale_selection_is_rejected_after_extraction_change(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["candidates"][0]["id"] = "changed-parser-id"
        with self.assertRaisesRegex(ValueError, "extraction"):
            self.model(evidence=evidence)

    def test_crop_does_not_silently_clip_wall(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["crop_bbox_pt"] = [0, 0, 50, 150]
        with self.assertRaisesRegex(ValueError, "crop"):
            self.model(decisions)

    def test_low_confidence_and_unresolved_block_native_export(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["walls"][0]["confidence"] = 0.7
        decisions["unresolved"] = ["Unknown window height"]
        model = self.model(decisions)
        self.assertEqual(model["status"], "review_required")
        self.assertIn("Unknown window height", model["review_items"])

    def test_mixed_height_overlap_is_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["candidates"].append({**evidence["candidates"][0], "id": "overlap"})
        decisions = copy.deepcopy(self.decisions)
        decisions["evidence_sha256"] = digest(evidence)
        decisions["walls"].append({"candidate_id": "overlap", "height_class": "low", "evidence": "test", "confidence": 1})
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.model(decisions, evidence)

    def test_non_finite_coordinates_and_height_are_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence["candidates"][0]["points_pt"][0][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            self.model(evidence=evidence)
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            self.model(height=float("inf"))
        with self.assertRaisesRegex(ValueError, "height"):
            self.model(height=0)

    def test_schema_rejects_ai_coordinates_and_missing_fields(self):
        decisions = copy.deepcopy(self.decisions)
        decisions["walls"][0]["points_mm"] = [[0, 0], [1, 1]]
        with self.assertRaises(ValidationError):
            self.model(decisions)
        del decisions["walls"][0]["points_mm"]
        del decisions["calibration"]
        with self.assertRaises(ValidationError):
            self.model(decisions)

    def test_curved_fill_is_not_flattened(self):
        self.assertEqual(filled_polygons([("m", (0, 0)), ("c", (1, 0), (1, 1), (0, 1)), ("h",)], False)[1], "curved_path")

    def test_pdf_evenodd_compound_hole_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=150)
            stream = DecodedStreamObject()
            stream.set_data(b"20 20 80 80 re 40 40 40 40 re f*\n")
            page[NameObject("/Contents")] = writer._add_object(stream)
            with open(root / "hole.pdf", "wb") as target:
                writer.write(target)
            evidence = inspect_pdf(root / "hole.pdf", 1, root)
            self.assertEqual(len(evidence["candidates"]), 1)
            self.assertEqual(len(evidence["candidates"][0]["holes_pt"]), 1)
            model = self.model(make_decisions(evidence), evidence)
            self.assertEqual(model["walls"][0]["area_mm2"], 480000)
            self.assertEqual(len(model["walls"][0]["holes_mm"]), 1)

    def test_nonzero_fill_respects_subpath_winding(self):
        outer = [("m", (0, 0)), ("l", (8, 0)), ("l", (8, 8)), ("l", (0, 8)), ("h",)]
        inner = [("m", (2, 2)), ("l", (6, 2)), ("l", (6, 6)), ("l", (2, 6)), ("h",)]
        polygons, reason = filled_polygons(outer + inner, False)
        self.assertIsNone(reason)
        self.assertEqual(polygons[0].area, 64)
        inner_reversed = [("m", (2, 2)), ("l", (2, 6)), ("l", (6, 6)), ("l", (6, 2)), ("h",)]
        polygons, reason = filled_polygons(outer + inner_reversed, False)
        self.assertIsNone(reason)
        self.assertEqual(polygons[0].area, 48)

    def test_rotated_pdf_uses_display_coordinates_and_same_areas(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_pdf(root / "rotated.pdf", 270)
            evidence = inspect_pdf(root / "rotated.pdf", 1, root)
            self.assertEqual([evidence["width_pt"], evidence["height_pt"]], [150, 200])
            model = self.model(make_decisions(evidence), evidence)
            self.assertEqual(sorted(wall["area_mm2"] for wall in model["walls"]), [8000, 36000])


if __name__ == "__main__":
    unittest.main()
