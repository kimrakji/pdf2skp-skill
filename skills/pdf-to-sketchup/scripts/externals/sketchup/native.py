"""Export a prepared prism model through the standalone C API and read it back."""

import ctypes as c
import hashlib
import math
import os
import tempfile
from pathlib import Path

from core.files import digest, write_json
from externals.sketchup.c_api import CAPI, NativeError, Point, Ref, Transform


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def root_name(payload):
    if payload.get("delivery") == "draft":
        return "InteriorOS_Draft"
    return "InteriorOS_Partial_Test" if payload["scope"] == "partial" else "InteriorOS_Wall_Test"


def tagged_group(api, model, entities, name):
    group = api.group(entities, name)
    layer = api.ref("SULayerCreate")
    api.call("SULayerSetName", layer, name.encode())
    api.call("SUModelAddLayers", model, 1, (Ref * 1)(layer))
    api.call("SUDrawingElementSetLayer", api.lib.SUGroupToDrawingElement(group), layer)
    return group


def image_signature(api, image):
    with api.owned("SUImageRepCreate", "SUImageRepRelease") as rep:
        api.call("SUImageGetImageRep", image, c.byref(rep))
        api.call("SUImageRepConvertTo32BitsPerPixel", rep)
        width, height, size, bits = c.c_size_t(), c.c_size_t(), c.c_size_t(), c.c_size_t()
        api.call("SUImageRepGetPixelDimensions", rep, c.byref(width), c.byref(height))
        api.call("SUImageRepGetDataSize", rep, c.byref(size), c.byref(bits))
        if not size.value or not width.value or not height.value:
            raise NativeError("Empty source plan image")
        data = c.create_string_buffer(size.value)
        api.call("SUImageRepGetData", rep, size.value, data)
        return digest([width.value, height.value, bits.value, hashlib.sha256(data.raw).hexdigest()])


def populate(api, model, payload, prisms, reference_path=None):
    api.millimeters(model)
    root = api.group(api.ref("SUModelGetEntities", model), root_name(payload))
    api.attributes(root, {key: payload[key] for key in ("geometry_sha256", "source_sha256", "scope")})
    entities = api.ref("SUGroupGetEntities", root)
    if reference_path is not None:
        reference = payload["reference"]
        group = tagged_group(api, model, entities, "Source_Plan")
        image = Ref()
        api.call("SUImageCreateFromFile", c.byref(image), str(reference_path).encode())
        api.call("SUEntitiesAddImage", api.ref("SUGroupGetEntities", group), image)
        width, height = c.c_double(), c.c_double()
        api.call("SUImageGetDimensions", image, c.byref(width), c.byref(height))
        transform = Transform()
        transform.values[0] = reference["width_mm"] / 25.4 / width.value
        transform.values[5] = reference["height_mm"] / 25.4 / height.value
        transform.values[10] = transform.values[15] = 1
        for i, v in enumerate(reference["origin_mm"], 12):
            transform.values[i] = v / 25.4
        api.call("SUImageSetTransform", image, c.byref(transform))
        api.attributes(group, {"reference_sha256": digest(reference), "pixel_sha256": image_signature(api, image)})
    parents = {}
    for wall, (vertices, faces) in zip(payload["walls"], prisms):
        name = wall["group"]
        if name not in parents:
            parent = tagged_group(api, model, entities, name)
            parents[name] = api.ref("SUGroupGetEntities", parent)
        group = api.group(parents[name], wall["id"])
        api.attributes(group, {"source_ids": ",".join(wall["source_ids"])})
        api.fill(api.ref("SUGroupGetEntities", group), vertices, faces)


def verify_model(api, model, payload, prisms):
    units = c.c_int()
    api.call("SUModelGetUnits", model, c.byref(units))
    if units.value != 2:
        raise NativeError("Model display units are not millimeters")
    model_entities = api.ref("SUModelGetEntities", model)
    roots = api.collection(model_entities, "Groups")
    if len(roots) != 1 or api.collection(model_entities, "Faces") or api.string("SUGroupGetName", roots[0]) != root_name(payload):
        raise NativeError("Unexpected root structure")
    root = roots[0]
    api.identity_transform(root)
    for key in ("geometry_sha256", "source_sha256", "scope"):
        if api.attribute(root, key) != payload[key]:
            raise NativeError(f"Root attribute mismatch: {key}")
    root_entities = api.ref("SUGroupGetEntities", root)
    if api.collection(root_entities, "Faces"):
        raise NativeError("Unexpected loose geometry in root")
    expected = {wall["id"]: (wall, prism) for wall, prism in zip(payload["walls"], prisms)}
    found, parent_names, checks = set(), [], []
    reference_found = False
    for parent in api.collection(root_entities, "Groups"):
        api.identity_transform(parent)
        parent_name = api.string("SUGroupGetName", parent)
        parent_names.append(parent_name)
        layer = api.ref("SUDrawingElementGetLayer", api.lib.SUGroupToDrawingElement(parent))
        if api.string("SULayerGetName", layer) != parent_name:
            raise NativeError("Parent tag mismatch")
        parent_entities = api.ref("SUGroupGetEntities", parent)
        if parent_name == "Source_Plan" and "reference" in payload:
            reference_found = True
            parent_names.pop()
            reference = payload["reference"]
            images = api.collection(parent_entities, "Images")
            if len(images) != 1 or api.collection(parent_entities, "Faces") or api.collection(parent_entities, "Groups"):
                raise NativeError("Unexpected source plan structure")
            image = images[0]
            width, height, transform = c.c_double(), c.c_double(), Transform()
            api.call("SUImageGetDimensions", image, c.byref(width), c.byref(height))
            api.call("SUImageGetTransform", image, c.byref(transform))
            if abs(width.value*25.4-reference["width_mm"]) > 0.1 or abs(height.value*25.4-reference["height_mm"]) > 0.1:
                raise NativeError("Source plan dimensions mismatch")
            for i, value in enumerate(transform.values):
                wanted = reference["origin_mm"][i-12]/25.4 if i in (12, 13, 14) else (1 if i in (10, 15) else 0)
                if i in (0, 5):
                    if not math.isfinite(value) or value <= 0:
                        raise NativeError("Invalid source plan scale")
                elif not math.isfinite(value) or abs(value-wanted) > 1e-9:
                    raise NativeError("Source plan transform mismatch")
            if api.attribute(parent, "reference_sha256") != digest(reference) or api.attribute(parent, "pixel_sha256") != image_signature(api, image):
                raise NativeError("Source plan content mismatch")
            continue
        if api.collection(parent_entities, "Faces"):
            raise NativeError("Unexpected loose geometry in wall category")
        for group in api.collection(parent_entities, "Groups"):
            api.identity_transform(group)
            name = api.string("SUGroupGetName", group)
            if name in found or name not in expected:
                raise NativeError("Unexpected or duplicate wall group")
            found.add(name)
            wall, (vertices, _) = expected[name]
            if wall["group"] != parent_name or api.attribute(group, "source_ids") != ",".join(wall["source_ids"]):
                raise NativeError("Wall provenance/group mismatch")
            entities = api.ref("SUGroupGetEntities", group)
            if api.collection(entities, "Groups"):
                raise NativeError("Unexpected nested group in wall")
            volume = c.c_double()
            api.call("SUComponentInstanceComputeVolume", api.lib.SUGroupToComponentInstance(group), None, c.byref(volume))
            actual_volume = abs(volume.value) * 25.4 ** 3
            expected_volume = wall["area_mm2"] * wall["height_mm"]
            ratio = abs(actual_volume - expected_volume) / expected_volume
            if not math.isfinite(ratio) or ratio > 0.001:
                raise NativeError(f"Wall volume mismatch: {name}")
            positions, cap_holes = set(), []
            faces = api.collection(entities, "Faces")
            for face in faces:
                face_positions = []
                normal, hole_count, vertex_count = Point(), c.c_size_t(), c.c_size_t()
                api.call("SUFaceGetNormal", face, c.byref(normal))
                api.call("SUFaceGetNumInnerLoops", face, c.byref(hole_count))
                if abs(normal.z) > 0.999:
                    cap_holes.append(hole_count.value)
                api.call("SUFaceGetNumVertices", face, c.byref(vertex_count))
                refs, actual = (Ref * vertex_count.value)(), c.c_size_t()
                api.call("SUFaceGetVertices", face, vertex_count.value, refs, c.byref(actual))
                for vertex in list(refs)[:actual.value]:
                    point = Point()
                    api.call("SUVertexGetPosition", vertex, c.byref(point))
                    positions.add(tuple(v * 25.4 for v in (point.x, point.y, point.z)))
                    face_positions.append((point.x * 25.4, point.y * 25.4, point.z * 25.4))
                if abs(normal.z) > 0.999 and face_positions:
                    z = face_positions[0][2]
                    if (abs(z) < 0.1 and normal.z > 0) or (abs(z - wall["height_mm"]) < 0.1 and normal.z < 0):
                        raise NativeError(f"Cap normal points inward: {name}")
            if not positions or sorted(cap_holes) != [len(wall["holes_mm"])] * 2:
                raise NativeError(f"Cap holes mismatch: {name}")
            if any(not all(math.isfinite(v) for v in p) for p in positions):
                raise NativeError("Non-finite native coordinates")
            distances = [min(math.dist(p, v) for v in vertices) for p in positions]
            distances += [min(math.dist(v, p) for p in positions) for v in vertices]
            max_error = max(distances)
            bottom, top = min(p[2] for p in positions), max(p[2] for p in positions)
            if max_error > 0.1 or abs(bottom) > 0.1 or abs(top - wall["height_mm"]) > 0.1:
                raise NativeError(f"Wall vertex/height mismatch: {name}")
            checks.append({"id": name, "group": parent_name, "solid": True, "height_mm": wall["height_mm"],
                           "actual_height_mm": top - bottom, "expected_volume_mm3": expected_volume,
                           "actual_volume_mm3": actual_volume, "volume_error_ratio": ratio,
                           "max_vertex_error_mm": max_error, "cap_hole_counts": cap_holes,
                           "face_count": len(faces), "source_ids_match": True,
                           "group_transform_identity": True, "cap_normals_outward": True})
    if reference_found != ("reference" in payload):
        raise NativeError("Missing source plan reference")
    if found != set(expected) or sorted(parent_names) != sorted({w["group"] for w in payload["walls"]}):
        raise NativeError("Wall/category group set mismatch")
    return sorted(checks, key=lambda check: check["id"])


def verify_file(library, path, payload, prisms):
    with CAPI(library) as api:
        with api.model(path) as model:
            checks = verify_model(api, model, payload, prisms)
        return {"reopen_verified": True, "method": "standalone_c_api_read_from_file", "api_version": api.version,
                "native_library": str(api.path), "skp_sha256": file_hash(path), "geometry_sha256": payload["geometry_sha256"],
                "scope": payload["scope"], "wall_count": len(checks), "walls": checks,
                "delivery": payload.get("delivery", "strict"), "review_items": payload["review_items"],
                "reference_verified": "reference" in payload}


def export_file(library, path, model_json_path, payload, prisms):
    path = Path(path).resolve()
    report_path = Path(str(path) + ".validation.json")
    if path.suffix.lower() != ".skp" or not path.parent.is_dir():
        raise ValueError("Output must be a .skp path in an existing folder")
    if path.exists() or report_path.exists():
        raise ValueError("Output already exists")
    with tempfile.TemporaryDirectory(prefix=".interior-export-", dir=path.parent) as temporary:
        staged = Path(temporary) / "model.skp"
        with CAPI(library) as api:
            with api.model() as model:
                reference_path = None
                if "reference" in payload:
                    reference_path = Path(model_json_path).resolve().parent / payload["reference"]["image_path"]
                    if file_hash(reference_path) != payload["reference"]["image_sha256"]:
                        raise ValueError("Source plan image hash mismatch")
                populate(api, model, payload, prisms, reference_path)
                before = verify_model(api, model, payload, prisms)
                api.call("SUModelSaveToFile", model, str(staged).encode())
            # Release the model entirely, then load the serialized file as a new model.
            with api.model(staged) as model:
                after = verify_model(api, model, payload, prisms)
            report = {"native_export": "saved_by_standalone_c_api", "api_version": api.version,
                      "native_library": str(api.path), "native_library_sha256": file_hash(api.path),
                      "runtime": "python_ctypes_in_independent_process", "desktop_api_used": False,
                      "model_json_sha256": file_hash(model_json_path), "geometry_sha256": payload["geometry_sha256"],
                      "skp_sha256": file_hash(staged), "scope": payload["scope"], "wall_count": len(after),
                      "validation_before_save": before, "walls": after, "reopen_verified": True,
                      "reopen_method": "released_model_then_loaded_saved_file_via_c_api",
                      "desktop_reopen_verified": False}
            report.update({"delivery": payload.get("delivery", "strict"), "review_items": payload["review_items"],
                           "reference_verified": "reference" in payload})
        staged_report = Path(temporary) / "validation.json"
        write_json(staged_report, report)
        # Hard links publish fully validated files without overwriting existing outputs.
        os.link(staged, path)
        try:
            os.link(staged_report, report_path)
        except OSError:
            path.unlink()
            raise
    return {"skp_path": str(path), "validation_path": str(report_path), "wall_count": len(after), "reopen_verified": True}
