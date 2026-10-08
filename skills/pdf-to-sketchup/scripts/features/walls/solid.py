"""Validate the model boundary and construct closed, outward-facing prisms in mm."""

import math

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from core.files import digest


def validate_model(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or payload.get("units") != "mm":
        raise ValueError("Unsupported model contract")
    draft = payload.get("delivery") == "draft" and payload.get("status") == "draft_ready"
    if not draft and (payload.get("status") != "ready_for_native_test" or payload.get("review_items") != []):
        raise ValueError("Review is required before export")
    if not isinstance(payload.get("review_items"), list):
        raise ValueError("Invalid review notes")
    if payload.get("scope") not in ("partial", "full_page"):
        raise ValueError("Invalid model scope")
    walls = payload.get("walls")
    if not isinstance(walls, list) or (not walls and not draft):
        raise ValueError("No wall geometry")
    reference = payload.get("reference")
    if reference is not None and not draft:
        raise ValueError("Source plan reference requires a draft model")
    if draft:
        if not isinstance(reference, dict):
            raise ValueError("Draft requires a source plan reference")
        if reference.get("image_path") != "source-plan.png":
            raise ValueError("Invalid reference image path")
        image_hash = reference.get("image_sha256", "")
        if not isinstance(image_hash, str) or len(image_hash) != 64 or any(v not in "0123456789abcdef" for v in image_hash):
            raise ValueError("Invalid reference image hash")
        for key in ("width_mm", "height_mm"):
            value = reference.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 200_000:
                raise ValueError("Invalid reference dimensions")
        if reference.get("origin_mm") != [0, 0, -1]:
            raise ValueError("Invalid reference origin")
    expected_hash = digest({"walls": walls, "reference": reference}) if draft else digest(walls)
    if payload.get("geometry_sha256") != expected_hash:
        raise ValueError("Model geometry hash mismatch")
    source_hash = payload.get("source_sha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash):
        raise ValueError("Invalid source hash")
    ids = set()
    for wall in walls:
        if not isinstance(wall, dict):
            raise ValueError("Invalid wall")
        for key in ("id", "group"):
            if not isinstance(wall.get(key), str) or not wall[key] or "\0" in wall[key]:
                raise ValueError(f"Invalid wall {key}")
        if wall["id"] in ids:
            raise ValueError("Duplicate wall ID")
        ids.add(wall["id"])
        source_ids = wall.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(s, str) or not s or "\0" in s for s in source_ids):
            raise ValueError("Invalid wall source IDs")
        height, area = wall.get("height_mm"), wall.get("area_mm2")
        if type(height) not in (int, float) or not math.isfinite(height) or not 500 <= height <= 10_000:
            raise ValueError("Invalid wall height")
        if type(area) not in (int, float) or not math.isfinite(area) or area <= 0:
            raise ValueError("Invalid footprint area")
        polygon = footprint(wall)
        if abs(polygon.area - area) / area > 0.001:
            raise ValueError("Footprint area does not match geometry")
    return payload


def footprint(wall):
    outer, holes = wall.get("outer_mm"), wall.get("holes_mm")
    if not isinstance(holes, list):
        raise ValueError("Invalid footprint holes")
    for ring in [outer, *holes]:
        if not isinstance(ring, list) or len(ring) < 3:
            raise ValueError("Invalid footprint ring")
        for point in ring:
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 200_000 for v in point):
                raise ValueError("Invalid footprint coordinate")
        if len({tuple(p) for p in ring}) != len(ring):
            raise ValueError("Duplicate footprint vertex")
    polygon = Polygon(outer, holes)
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError("Invalid footprint polygon")
    return orient(polygon, sign=1.0)


def prism(wall):
    """Return vertices and face loops; outer rings CCW, hole rings CW, in mm."""
    polygon = footprint(wall)
    rings = [list(polygon.exterior.coords)[:-1], *[list(h.coords)[:-1] for h in polygon.interiors]]
    vertices, bottom, top = [], [], []
    for ring in rings:
        base = len(vertices)
        vertices.extend((x, y, 0.0) for x, y in ring)
        bottom.append(list(range(base, base + len(ring))))
        base = len(vertices)
        vertices.extend((x, y, wall["height_mm"]) for x, y in ring)
        top.append(list(range(base, base + len(ring))))
    faces = [[list(reversed(r)) for r in bottom], top]
    for lower, upper in zip(bottom, top):
        for i in range(len(lower)):
            j = (i + 1) % len(lower)
            faces.append([[lower[i], lower[j], upper[j], upper[i]]])
    return vertices, faces
