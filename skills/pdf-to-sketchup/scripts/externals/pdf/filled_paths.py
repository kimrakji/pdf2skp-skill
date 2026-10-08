from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union


def filled_polygons(path, evenodd):
    if any(step[0] not in ("m", "l", "h") for step in path):
        return [], "curved_path"
    rings = []
    current = []
    for step in path:
        if step[0] == "m":
            if current:
                rings.append(current)
            current = [step[1]]
        elif step[0] == "l":
            current.append(step[1])
    if current:
        rings.append(current)
    valid = []
    for ring in rings:
        while len(ring) > 1 and ring[-1] == ring[0]:
            ring.pop()
        if len(ring) < 3:
            continue
        polygon = Polygon(ring)
        if polygon.area == 0:
            continue
        if not polygon.is_valid:
            return [], "invalid_subpath"
        area_sign = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
        valid.append((polygon, 1 if area_sign > 0 else -1))
    if not valid:
        return [], "degenerate_path"
    boundaries = unary_union([LineString(list(polygon.exterior.coords)) for polygon, _ in valid])
    selected = []
    for face in polygonize(boundaries):
        point = face.representative_point()
        inside = [sign for polygon, sign in valid if polygon.contains(point)]
        filled = len(inside) % 2 == 1 if evenodd else sum(inside) != 0
        if filled:
            selected.append(face)
    shape = unary_union(selected)
    if shape.is_empty:
        return [], "empty_fill"
    pieces = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    if any(piece.geom_type != "Polygon" for piece in pieces):
        return [], "unsupported_fill"
    return sorted(pieces, key=lambda polygon: (polygon.bounds, polygon.area)), None
