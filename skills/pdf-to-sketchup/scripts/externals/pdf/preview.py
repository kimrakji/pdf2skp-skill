from pathlib import Path

from PIL import Image, ImageDraw


def selected_preview(evidence, decisions, image_path, output):
    with Image.open(image_path) as original:
        image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        sx, sy = image.width / evidence["width_pt"], image.height / evidence["height_pt"]
        selections = {wall["candidate_id"]: wall["height_class"] for wall in decisions["walls"]}
        for candidate in evidence["candidates"]:
            height_class = selections.get(candidate["id"])
            if height_class:
                points = [(x * sx, y * sy) for x, y in candidate["points_pt"]]
                color = "#e43b33" if height_class == "default" else "#2878c8"
                draw.line(points + points[:1], fill=color, width=3)
                for hole in candidate.get("holes_pt", []):
                    points = [(x * sx, y * sy) for x, y in hole]
                    draw.line(points + points[:1], fill=color, width=3)
        image.save(Path(output))
