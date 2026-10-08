import hashlib
import json
from pathlib import Path


def read_json(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def new_output(path):
    target = Path(path)
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"Output folder is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    return target
