"""Draft candidates from closed strokes and overlapping parallel lines.

These are geometry candidates, not wall classification. Never bridge line gaps.
"""

from shapely.geometry import Polygon

from externals.pdf.filled_paths import filled_polygons


def closed_outline(path):
    start = end = None
    for step in path:
        if step[0] == "m":
            if start is not None and end != start:
                return []
            start = end = step[1]
        elif step[0] == "l":
            end = step[1]
        elif step[0] == "h":
            end = start
        else:
            return []
    if start is None or end != start:
        return []
    polygons, reason = filled_polygons(path, False)
    return [] if reason else polygons


def parallel_footprints(objects):
    axes = {"h": set(), "v": set()}
    for obj in objects:
        if not obj.get("stroke") or obj.get("fill"):
            continue
        previous = None
        for step in obj.get("path", []):
            if step[0] == "m":
                previous = step[1]
            elif step[0] == "l" and previous is not None:
                a, b = previous, step[1]
                previous = b
                if abs(a[1] - b[1]) < 0.01:
                    axis, level, lo, hi = "h", a[1], min(a[0], b[0]), max(a[0], b[0])
                elif abs(a[0] - b[0]) < 0.01:
                    axis, level, lo, hi = "v", a[0], min(a[1], b[1]), max(a[1], b[1])
                else:
                    continue
                if hi - lo >= 18:
                    axes[axis].add(tuple(round(v, 4) for v in (level, lo, hi)))
            else:
                previous = None
    for axis, segments in axes.items():
        ordered = sorted(segments)
        seen = set()
        for i, (a, a0, a1) in enumerate(ordered):
            for b, b0, b1 in ordered[i + 1:]:
                width = b - a
                if width > 12:
                    break
                lo, hi = max(a0, b0), min(a1, b1)
                if width < 0.5 or hi - lo < max(18, width * 6):
                    continue
                bounds = (lo, a, hi, b) if axis == "h" else (a, lo, b, hi)
                if bounds in seen:
                    continue
                seen.add(bounds)
                x0, y0, x1, y1 = bounds
                yield Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
