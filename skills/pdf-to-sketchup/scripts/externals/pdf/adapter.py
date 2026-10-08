import hashlib
from collections import Counter
from pathlib import Path

import pdfplumber
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.utils import apply_matrix_pt
from pdfplumber.page import PDFPageAggregatorWithMarkedContent
from pypdf import PdfReader

from externals.pdf.filled_paths import filled_polygons
from externals.pdf.outlined_paths import closed_outline, parallel_footprints


class FillAggregator(PDFPageAggregatorWithMarkedContent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fills = []
        self.outlines = []
        self.capturing = False

    def paint_path(self, gstate, stroke, fill, evenodd, path):
        # pdfminer의 복합 경로 분리 전에 원본 채움 규칙을 보존
        outer_call = not self.capturing
        if outer_call and (fill or stroke):
            transformed = [
                (step[0], *[apply_matrix_pt(self.ctm, pair) for pair in zip(step[1::2], step[2::2])])
                for step in path
            ]
            if fill:
                self.fills.append({"path": transformed, "evenodd": evenodd, "color": gstate.ncolor})
            elif stroke:
                self.outlines.append(transformed)
        self.capturing = True
        try:
            super().paint_path(gstate, stroke, fill, evenodd, path)
        finally:
            if outer_call:
                self.capturing = False


def inspect_pdf(path, page_number, output, outlines=False):
    path = Path(path)
    layers = PdfReader(path).trailer["/Root"].get("/OCProperties", {}).get("/OCGs", [])
    layer_names = sorted(str(layer.get_object().get("/Name", "")) for layer in layers)
    with pdfplumber.open(path) as document:
        if not 1 <= page_number <= len(document.pages):
            raise ValueError("Page number is outside the document")
        page = document.pages[page_number - 1]
        if page.bbox[:2] != (0, 0):
            raise ValueError("Non-zero MediaBox origin is not supported by this PoC")
        device = FillAggregator(document.rsrcmgr, pageno=page_number, laparams=document.laparams)
        PDFPageInterpreter(document.rsrcmgr, device).process_page(page.page_obj)
        page._layout = device.get_result()
        page.to_image(resolution=144, antialias=True, force_mediabox=True).save(output / "page.png")
        candidates = []
        skipped = Counter()
        for index, fill in enumerate(device.fills, 1):
            displayed_path = [(step[0], *[page.point2coord(point) for point in step[1:]]) for step in fill["path"]]
            polygons, reason = filled_polygons(displayed_path, fill["evenodd"])
            if reason:
                skipped[reason] += 1
                continue
            for component, polygon in enumerate(polygons, 1):
                candidates.append({
                    "id": f"p{page_number}-f{index:05d}-{component:03d}",
                    "points_pt": [list(point) for point in list(polygon.exterior.coords)[:-1]],
                    "holes_pt": [[list(point) for point in list(ring.coords)[:-1]] for ring in polygon.interiors],
                    "bbox_pt": list(polygon.bounds),
                    "color": fill["color"], "evenodd": fill["evenodd"],
                })
        if outlines:
            def add(polygon, candidate_id, kind):
                candidates.append({
                    "id": candidate_id, "points_pt": [list(p) for p in list(polygon.exterior.coords)[:-1]],
                    "holes_pt": [[list(p) for p in list(r.coords)[:-1]] for r in polygon.interiors],
                    "bbox_pt": list(polygon.bounds), "color": None, "evenodd": False, "source_kind": kind,
                })
            for index, outline_path in enumerate(device.outlines, 1):
                displayed = [(step[0], *[page.point2coord(p) for p in step[1:]]) for step in outline_path]
                for component, polygon in enumerate(closed_outline(displayed), 1):
                    add(polygon, f"p{page_number}-o{index:05d}-{component:03d}", "closed_outline")
            for index, polygon in enumerate(parallel_footprints([*page.lines, *page.curves]), 1):
                add(polygon, f"p{page_number}-pair{index:05d}", "parallel_lines")
        return {
            "schema_version": "1.0", "extractor_version": "draft-0.3" if outlines else "poc-0.1",
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_name": path.name, "page": page_number,
            "page_count": len(document.pages), "rotation": page.rotation,
            "width_pt": page.width, "height_pt": page.height,
            "coordinate_system": "displayed_page_top_left_points",
            "layer_names": layer_names,
            "primitive_counts": {"lines": len(page.lines), "curves": len(page.curves), "rects": len(page.rects), "images": len(page.images)},
            "skipped_fills": dict(sorted(skipped.items())),
            "words": page.extract_words(),
            "candidates": candidates,
        }
