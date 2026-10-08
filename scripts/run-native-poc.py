"""Retain artifacts from real C API exports and independent-process readbacks."""

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/pdf-to-sketchup"
sys.path.insert(0, str(SKILL / "scripts"))

from core.files import digest, new_output, read_json, write_json


def desktop_processes():
    result = subprocess.run(["pgrep", "-x", "SketchUp"], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        return {"status": "unavailable", "error": result.stderr.strip()}
    return {"status": "observed", "pids": result.stdout.split()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-model", type=Path)
    parser.add_argument("--reference-skp", type=Path)
    args = parser.parse_args()
    if bool(args.reference_model) != bool(args.reference_skp):
        parser.error("Both reference model and .skp are required together")
    output = new_output(args.out).resolve()
    before = desktop_processes()

    def command(*arguments):
        result = subprocess.run([sys.executable, str(SKILL / "scripts/main.py"), *map(str, arguments), "--library", str(args.library)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        return json.loads(result.stdout)

    def roundtrip(model, name):
        skp = output / f"{name}.skp"
        command("export-native", "--model", model, "--out", skp)
        return command("verify-native", "--model", model, "--skp", skp, "--out", output / f"{name}.reopen.json")

    sample = ROOT / "examples/native-prisms.json"
    reports = [roundtrip(sample, f"synthetic-{i + 1}") for i in range(3)]
    if any(report["walls"] != reports[0]["walls"] for report in reports[1:]):
        raise RuntimeError("Repeated semantic geometry differs")
    changed = copy.deepcopy(read_json(sample))
    for wall in changed["walls"]:
        if wall["group"] != "Walls_Low":
            wall["height_mm"] = 3200
    changed["geometry_sha256"] = digest(changed["walls"])
    write_json(output / "synthetic-3200.json", changed)
    height_report = roundtrip(output / "synthetic-3200.json", "synthetic-3200")
    baseline = {wall["id"]: wall for wall in reports[0]["walls"]}
    for wall in height_report["walls"]:
        ratio = 1 if wall["group"] == "Walls_Low" else 3200 / 2700
        actual = wall["actual_volume_mm3"] / baseline[wall["id"]]["actual_volume_mm3"]
        if abs(actual - ratio) > 1e-8:
            raise RuntimeError("Volume does not follow requested height")
    real = None
    if args.reference_model:
        real_report = roundtrip(args.reference_model, "knou-2700-c-api")
        reference_report = command("verify-native", "--model", args.reference_model, "--skp", args.reference_skp,
                                   "--out", output / "ruby-reference.reopen.json")
        comparisons = []
        by_id = {wall["id"]: wall for wall in reference_report["walls"]}
        for wall in real_report["walls"]:
            original = by_id[wall["id"]]
            volume_error = abs(wall["actual_volume_mm3"] - original["actual_volume_mm3"]) / original["actual_volume_mm3"]
            if wall["group"] != original["group"] or abs(wall["actual_height_mm"] - original["actual_height_mm"]) > 0.1 or volume_error > 0.001:
                raise RuntimeError("C API and Ruby reference differ")
            comparisons.append({"id": wall["id"], "relative_volume_difference": volume_error,
                                "group_matches": True, "height_matches": True,
                                "both_vertex_sets_match_input": True})
        real = {"wall_count": len(comparisons), "ruby_reference_skp": str(args.reference_skp.resolve()),
                "model_json": str(args.reference_model.resolve()), "comparisons": comparisons}
    summary = {"status": "passed", "synthetic_wall_count": reports[0]["wall_count"],
               "synthetic_cases": [wall["id"] for wall in reports[0]["walls"]],
               "independent_process_reopens": 4 + (2 if real else 0), "same_input_runs": 3,
               "semantic_geometry_repeatable": True, "height_2700_to_3200_verified": True,
               "low_wall_height_1200_preserved": True, "native_library": str(args.library.resolve()),
               "native_library_source": "caller_supplied_local_library", "api_version": reports[0]["api_version"],
               "sketchup_processes_before": before, "sketchup_processes_after": desktop_processes(),
               "desktop_reopen_verified": False, "real_drawing_comparison": real}
    write_json(output / "poc-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
