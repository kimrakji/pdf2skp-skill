import math

from shapely import set_precision
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from core.files import digest


def finite_numbers(value):
    if isinstance(value, dict):
        for item in value.values():
            finite_numbers(item)
    elif isinstance(value, list):
        for item in value:
            finite_numbers(item)
    elif isinstance(value, (float, int)) and not math.isfinite(value):
        raise ValueError("Non-finite number")


def ring_points(ring):
    points = [[round(x, 8), round(y, 8)] for x, y in list(ring.coords)[:-1]]
    first = min(range(len(points)), key=lambda index: tuple(points[index]))
    return points[first:] + points[:first]


def build_model(evidence, decisions, rules, wall_height_mm, draft=False):
    finite_numbers([evidence, decisions, rules, wall_height_mm])
    if evidence.get("schema_version") != "1.0" or evidence.get("coordinate_system") != "displayed_page_top_left_points":
        raise ValueError("Unsupported evidence contract")
    if (decisions["source_sha256"], decisions["page"]) != (evidence["source_sha256"], evidence["page"]):
        raise ValueError("Decisions do not match the source PDF/page")
    if decisions["evidence_sha256"] != digest(evidence):
        raise ValueError("Decisions do not match this extraction; regenerate selections")
    lo, hi = rules["height_range_mm"]
    height = float(rules["default_wall_height_mm"] if wall_height_mm is None else wall_height_mm)
    if not lo <= height <= hi or not lo <= rules["low_wall_height_mm"] <= hi:
        raise ValueError(f"Wall height must be between {lo} and {hi} mm")
    precision = rules["precision_mm"]
    if precision <= 0 or rules["min_footprint_area_mm2"] <= 0:
        raise ValueError("Invalid geometry policy")
    x0, y0, x1, y1 = decisions["crop_bbox_pt"]
    if not (0 <= x0 < x1 <= evidence["width_pt"] and 0 <= y0 < y1 <= evidence["height_pt"]):
        raise ValueError("Crop must be inside the displayed page")
    scales = []
    review = list(decisions["unresolved"])
    used_pairs = set()
    for calibration in decisions["calibration"]:
        a, b = calibration["p1_pt"], calibration["p2_pt"]
        for px, py in (a, b):
            if not (0 <= px <= evidence["width_pt"] and 0 <= py <= evidence["height_pt"]):
                raise ValueError("Calibration point is outside the page")
        pair = tuple(sorted((tuple(a), tuple(b))))
        if pair in used_pairs:
            raise ValueError("Two distinct dimension references are required")
        used_pairs.add(pair)
        length = math.dist(a, b)
        if length < 1:
            raise ValueError("Calibration reference is too short")
        scales.append(calibration["distance_mm"] / length)
        if calibration["confidence"] < rules["min_confidence"]:
            review.append("Low confidence in scale calibration")
    if not draft and len(scales) != 2:
        raise ValueError("Two dimension references are required")
    if len(scales) == 2 and abs(scales[0] - scales[1]) / scales[0] > rules["max_scale_disagreement_ratio"]:
        if not draft:
            raise ValueError("Dimension references disagree on scale")
        review.append("Dimension references disagree; used the first reference")
    if scales:
        scale = scales[0]
        scale_source = "dimension_references"
        if len(scales) == 1:
            review.append("Scale has only one dimension reference")
    else:
        hint = decisions.get("scale_hint")
        scale = hint["mm_per_pt"] if hint else rules.get("draft_scale_denominator", 100) * 25.4 / 72
        scale_source = hint["evidence"] if hint else "Assumed printed scale 1:100"
        review.append("Scale is provisional: " + scale_source)
    if scale <= 0:
        raise ValueError("Invalid scale")
    if max((x1 - x0) * scale, (y1 - y0) * scale) > rules["max_model_extent_mm"]:
        raise ValueError("Model extent exceeds policy; check the scale")
    candidates = {candidate["id"]: candidate for candidate in evidence["candidates"]}
    selected = {"default": [], "low": []}
    if draft:
        selected.update({"default_suggested": [], "low_suggested": []})
    seen = set()
    crop = box(x0, y0, x1, y1)
    for wall in decisions["walls"]:
        candidate_id = wall["candidate_id"]
        if candidate_id in seen:
            raise ValueError(f"Duplicate wall selection: {candidate_id}")
        seen.add(candidate_id)
        if candidate_id not in candidates:
            raise ValueError(f"Unknown candidate: {candidate_id}")
        points = candidates[candidate_id]["points_pt"]
        holes = candidates[candidate_id].get("holes_pt", [])
        source_polygon = Polygon(points, holes)
        if not source_polygon.is_valid or source_polygon.area <= 0:
            raise ValueError(f"Invalid source polygon: {candidate_id}")
        if not crop.covers(source_polygon):
            raise ValueError(f"Candidate crosses the crop: {candidate_id}")
        def transform(ring):
            return [((x - x0) * scale, (y1 - y) * scale) for x, y in ring]

        polygon = Polygon(transform(points), [transform(hole) for hole in holes])
        key = wall["height_class"]
        if draft and (wall["confidence"] < rules["min_confidence"] or candidates[candidate_id].get("source_kind")):
            key += "_suggested"
        selected[key].append((candidate_id, polygon))
        if wall["confidence"] < rules["min_confidence"]:
            review.append(f"Low confidence in wall {candidate_id}")
    merged = {key: set_precision(unary_union([p for _, p in items]), precision) for key, items in selected.items()}
    if not draft and merged["default"].intersection(merged["low"]).area > precision ** 2:
        raise ValueError("Different height classes overlap")
    if draft:
        # Confirmed geometry wins; full-height geometry wins over low geometry.
        merged["default_suggested"] = merged["default_suggested"].difference(merged["default"])
        full = unary_union([merged["default"], merged["default_suggested"]])
        if full.intersection(unary_union([merged["low"], merged["low_suggested"]])).area > precision ** 2:
            review.append("Overlapping height classes: full-height footprint takes precedence")
        merged["low"] = merged["low"].difference(full)
        merged["low_suggested"] = merged["low_suggested"].difference(full.union(merged["low"]))
    walls = []
    for key in selected:
        height_class = key.split("_")[0]
        shape = merged[key]
        pieces = [] if shape.is_empty else ([shape] if shape.geom_type == "Polygon" else list(shape.geoms))
        if any(piece.geom_type != "Polygon" for piece in pieces):
            raise ValueError("Geometry union produced a non-polygon")
        pieces.sort(key=lambda polygon: (polygon.bounds, polygon.area))
        for piece in pieces:
            if not piece.is_valid or piece.area < rules["min_footprint_area_mm2"]:
                raise ValueError("Footprint is invalid or below the minimum area")
            piece = orient(piece, sign=1.0)
            sources = sorted(candidate_id for candidate_id, polygon in selected[key] if polygon.intersection(piece).area > precision ** 2)
            if not sources:
                raise ValueError("Footprint lost its source provenance")
            walls.append({
                "id": f"W{len(walls) + 1:04d}", "group": ("Walls_Suggested" if height_class == "default" else "Walls_Low_Suggested") if key.endswith("_suggested") else rules["group_names"][height_class],
                "height_mm": height if height_class == "default" else float(rules["low_wall_height_mm"]),
                "outer_mm": ring_points(piece.exterior),
                "holes_mm": sorted((ring_points(ring) for ring in piece.interiors), key=str),
                "area_mm2": round(piece.area, 4), "source_ids": sources,
            })
    if not walls and not draft:
        raise ValueError("No wall footprints")
    result = {
        "schema_version": "1.0", "generator_version": "draft-0.3" if draft else "poc-0.1", "units": "mm",
        "status": "draft_ready" if draft else ("review_required" if review else "ready_for_native_test"),
        "scope": decisions["scope"], "source_sha256": evidence["source_sha256"],
        "page": evidence["page"], "evidence_sha256": digest(evidence),
        "rules_sha256": digest(rules), "decisions_sha256": digest(decisions),
        "mm_per_pt": scale, "origin_pt": [x0, y1], "wall_height_mm": height,
        "geometry_sha256": digest(walls), "walls": walls,
        "review_items": sorted(set(review)), "native_export": "not_executed",
    }
    if draft:
        result.update({"delivery": "draft", "scale_source": scale_source,
                       "reference": {"image_path": "source-plan.png", "width_mm": (x1-x0)*scale,
                                     "height_mm": (y1-y0)*scale, "origin_mm": [0, 0, -1]}})
        if not walls:
            result["review_items"].append("No walls selected; delivered the source plan as a tracing reference")
    return result
