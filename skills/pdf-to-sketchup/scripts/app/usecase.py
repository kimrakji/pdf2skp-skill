import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from PIL import Image

from core.files import digest, new_output, read_json, write_json
from externals.pdf.adapter import inspect_pdf
from externals.pdf.preview import selected_preview
from externals.sketchup.c_api import NativeError
from externals.sketchup.native import export_file, verify_file
from features.walls.service import build_model
from features.walls.solid import prism, validate_model


SKILL_ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description="PDF wall conversion and standalone SketchUp C API export PoC")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("pdf", type=Path)
    inspect.add_argument("--page", type=int, default=1)
    inspect.add_argument("--out", type=Path, required=True)
    inspect.add_argument("--outlines", action="store_true", help="Include draft candidates from stroke outlines and parallel lines")
    compile_parser = commands.add_parser("compile")
    compile_parser.add_argument("--evidence", type=Path, required=True)
    compile_parser.add_argument("--decisions", type=Path, required=True)
    compile_parser.add_argument("--wall-height-mm", type=float)
    compile_parser.add_argument("--rules", type=Path, default=SKILL_ROOT / "references/company-rules.json")
    compile_parser.add_argument("--out", type=Path, required=True)
    compile_parser.add_argument("--strict", action="store_true", help="Require two dimensions and no unresolved decisions; draft is the default")
    for name in ("export-native", "verify-native"):
        native_parser = commands.add_parser(name)
        native_parser.add_argument("--model", type=Path, required=True)
        native_parser.add_argument("--library", type=Path, required=True, help="Local SketchUp C SDK library binary")
        native_parser.add_argument("--out", type=Path, required=True)
        if name == "verify-native":
            native_parser.add_argument("--skp", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            output = new_output(args.out)
            evidence = inspect_pdf(args.pdf, args.page, output, outlines=args.outlines)
            write_json(output / "evidence.json", evidence)
            summary = {key: value for key, value in evidence.items() if key not in ("words", "candidates")}
            summary["candidate_count"] = len(evidence["candidates"])
            summary["evidence_sha256"] = digest(evidence)
            summary["extraction_status"] = "candidates_only_not_wall_classification"
            write_json(output / "summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False))
        elif args.command == "compile":
            evidence, decisions, rules = read_json(args.evidence), read_json(args.decisions), read_json(args.rules)
            Draft202012Validator(read_json(SKILL_ROOT / "references/decisions.schema.json")).validate(decisions)
            model = build_model(evidence, decisions, rules, args.wall_height_mm, draft=not args.strict)
            output = new_output(args.out)
            image_path = args.evidence.parent / "page.png"
            if "reference" in model:
                with Image.open(image_path) as image:
                    x0, y0, x1, y1 = decisions["crop_bbox_pt"]
                    sx, sy = image.width/evidence["width_pt"], image.height/evidence["height_pt"]
                    # Fractional crop avoids changing the reference-to-wall alignment.
                    size = (max(1, round((x1-x0)*sx)), max(1, round((y1-y0)*sy)))
                    image.convert("RGB").resize(size, Image.Resampling.BICUBIC, box=(x0*sx,y0*sy,x1*sx,y1*sy)).save(output / "source-plan.png")
                model["reference"]["image_sha256"] = hashlib.sha256((output / "source-plan.png").read_bytes()).hexdigest()
                model["geometry_sha256"] = digest({"walls": model["walls"], "reference": model["reference"]})
            write_json(output / "model.json", model)
            report = {key: value for key, value in model.items() if key != "walls"}
            report.update({"wall_count": len(model["walls"]), "selected_candidate_count": len(decisions["walls"]), "expected_volume_mm3": sum(wall["area_mm2"] * wall["height_mm"] for wall in model["walls"])})
            write_json(output / "validation.json", report)
            if image_path.exists():
                selected_preview(evidence, decisions, image_path, output / "selection.png")
            print(json.dumps(report, ensure_ascii=False))
            if model["status"] == "review_required":
                return 2
        else:
            payload = validate_model(read_json(args.model))
            prisms = [prism(wall) for wall in payload["walls"]]
            if args.command == "export-native":
                result = export_file(args.library, args.out, args.model, payload, prisms)
            else:
                if args.out.exists():
                    raise ValueError("Output already exists")
                result = verify_file(args.library, args.skp, payload, prisms)
                with args.out.open("x", encoding="utf-8") as target:
                    target.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError, NativeError, ValidationError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0
