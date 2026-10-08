"""Small ctypes binding to the public SketchUp C API, used outside SketchUp.

The caller supplies a local native library. No proprietary binaries are bundled.
ABI declarations follow the official API 14.2 reference; all SU*Ref structs
contain one void pointer. Keep API calls on the process's main thread.
"""

import ctypes as c
import threading
from contextlib import contextmanager
from pathlib import Path


class NativeError(RuntimeError):
    pass


class Ref(c.Structure):
    _fields_ = [("ptr", c.c_void_p)]


class Point(c.Structure):
    _fields_ = [("x", c.c_double), ("y", c.c_double), ("z", c.c_double)]


class Transform(c.Structure):
    _fields_ = [("values", c.c_double * 16)]


RP, SP = c.POINTER(Ref), c.POINTER(c.c_size_t)
SIGNATURES = {
    "SUGetAPIVersion": [SP, SP],
    "SUModelCreate": [RP], "SUModelRelease": [RP],
    "SUModelCreateFromFileWithStatus": [RP, c.c_char_p, c.POINTER(c.c_int)],
    "SUModelSaveToFile": [Ref, c.c_char_p], "SUModelGetEntities": [Ref, RP],
    "SUModelAddLayers": [Ref, c.c_size_t, RP],
    "SUModelGetUnits": [Ref, c.POINTER(c.c_int)],
    "SUModelGetOptionsManager": [Ref, RP],
    "SUOptionsManagerGetOptionsProviderByName": [Ref, c.c_char_p, RP],
    "SUOptionsProviderSetValue": [Ref, c.c_char_p, Ref],
    "SULayerCreate": [RP], "SULayerSetName": [Ref, c.c_char_p],
    "SULayerGetName": [Ref, RP],
    "SUGroupCreate": [RP], "SUGroupSetName": [Ref, c.c_char_p],
    "SUGroupGetName": [Ref, RP], "SUGroupGetEntities": [Ref, RP],
    "SUGroupGetTransform": [Ref, c.POINTER(Transform)],
    "SUGroupSetTransform": [Ref, c.POINTER(Transform)],
    "SUEntitiesAddGroup": [Ref, Ref],
    "SUEntitiesAddImage": [Ref, Ref],
    "SUEntitiesGetNumImages": [Ref, SP],
    "SUEntitiesGetImages": [Ref, c.c_size_t, RP, SP],
    "SUImageCreateFromFile": [RP, c.c_char_p],
    "SUImageGetDimensions": [Ref, c.POINTER(c.c_double), c.POINTER(c.c_double)],
    "SUImageSetTransform": [Ref, c.POINTER(Transform)],
    "SUImageGetTransform": [Ref, c.POINTER(Transform)],
    "SUImageRepCreate": [RP], "SUImageRepRelease": [RP],
    "SUImageGetImageRep": [Ref, RP],
    "SUImageRepGetPixelDimensions": [Ref, SP, SP],
    "SUImageRepConvertTo32BitsPerPixel": [Ref],
    "SUImageRepGetDataSize": [Ref, SP, SP],
    "SUImageRepGetData": [Ref, c.c_size_t, c.c_void_p],
    "SUEntitiesGetNumGroups": [Ref, SP],
    "SUEntitiesGetGroups": [Ref, c.c_size_t, RP, SP],
    "SUEntitiesGetNumFaces": [Ref, SP],
    "SUEntitiesGetFaces": [Ref, c.c_size_t, RP, SP],
    "SUEntitiesFill": [Ref, Ref, c.c_bool],
    "SUGeometryInputCreate": [RP], "SUGeometryInputRelease": [RP],
    "SUGeometryInputSetVertices": [Ref, c.c_size_t, c.POINTER(Point)],
    "SUGeometryInputAddFace": [Ref, RP, SP],
    "SUGeometryInputFaceAddInnerLoop": [Ref, c.c_size_t, RP],
    "SULoopInputCreate": [RP], "SULoopInputRelease": [RP],
    "SULoopInputAddVertexIndex": [Ref, c.c_size_t],
    "SUComponentInstanceComputeVolume": [Ref, c.c_void_p, c.POINTER(c.c_double)],
    "SUFaceGetNumVertices": [Ref, SP],
    "SUFaceGetVertices": [Ref, c.c_size_t, RP, SP],
    "SUFaceGetNormal": [Ref, c.POINTER(Point)],
    "SUFaceGetNumInnerLoops": [Ref, SP],
    "SUVertexGetPosition": [Ref, c.POINTER(Point)],
    "SUDrawingElementSetLayer": [Ref, Ref],
    "SUDrawingElementGetLayer": [Ref, RP],
    "SUEntityGetAttributeDictionary": [Ref, c.c_char_p, RP],
    "SUAttributeDictionarySetValue": [Ref, c.c_char_p, Ref],
    "SUAttributeDictionaryGetValue": [Ref, c.c_char_p, RP],
    "SUTypedValueCreate": [RP], "SUTypedValueRelease": [RP],
    "SUTypedValueSetString": [Ref, c.c_char_p],
    "SUTypedValueSetInt32": [Ref, c.c_int32],
    "SUTypedValueGetString": [Ref, RP],
    "SUStringCreate": [RP], "SUStringRelease": [RP],
    "SUStringGetUTF8Length": [Ref, SP],
    "SUStringGetUTF8": [Ref, c.c_size_t, c.c_void_p, SP],
}
CONVERSIONS = ("SUGroupToEntity", "SUGroupToDrawingElement", "SUGroupToComponentInstance")


class CAPI:
    def __init__(self, library):
        self.path = Path(library).resolve(strict=True)
        self.lib = c.CDLL(str(self.path))
        for name, args in SIGNATURES.items():
            function = getattr(self.lib, name)
            function.argtypes = args
            function.restype = None if name == "SUGetAPIVersion" else c.c_int
        for name in CONVERSIONS:
            function = getattr(self.lib, name)
            function.argtypes, function.restype = [Ref], Ref
        for name in ("SUInitialize", "SUTerminate"):
            function = getattr(self.lib, name)
            function.argtypes, function.restype = [], None

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread():
            raise NativeError("SketchUp C API must run on the main thread")
        self.lib.SUInitialize()
        return self

    def __exit__(self, *_):
        self.lib.SUTerminate()

    def call(self, name, *args):
        result = getattr(self.lib, name)(*args)
        if result != 0:
            raise NativeError(f"{name} failed with SUResult={result}")

    @property
    def version(self):
        major, minor = c.c_size_t(), c.c_size_t()
        self.lib.SUGetAPIVersion(c.byref(major), c.byref(minor))
        return [major.value, minor.value]

    def ref(self, name, *args):
        result = Ref()
        self.call(name, *args, c.byref(result))
        return result

    @contextmanager
    def owned(self, create, release):
        result = self.ref(create)
        try:
            yield result
        finally:
            if result.ptr:
                self.call(release, c.byref(result))

    @contextmanager
    def model(self, path=None):
        model = Ref()
        try:
            if path is None:
                self.call("SUModelCreate", c.byref(model))
            else:
                status = c.c_int()
                self.call("SUModelCreateFromFileWithStatus", c.byref(model), str(Path(path).resolve()).encode(), c.byref(status))
                if status.value != 0:
                    raise NativeError(f"Model load warning: status={status.value}")
            yield model
        finally:
            if model.ptr:
                self.call("SUModelRelease", c.byref(model))

    def string(self, getter, *args):
        with self.owned("SUStringCreate", "SUStringRelease") as value:
            self.call(getter, *args, c.byref(value))
            length, copied = c.c_size_t(), c.c_size_t()
            self.call("SUStringGetUTF8Length", value, c.byref(length))
            buffer = c.create_string_buffer(length.value + 1)
            self.call("SUStringGetUTF8", value, len(buffer), buffer, c.byref(copied))
            return buffer.value.decode("utf-8")

    def collection(self, owner, kind):
        count = c.c_size_t()
        self.call(f"SUEntitiesGetNum{kind}", owner, c.byref(count))
        if not count.value:
            return []
        items, actual = (Ref * count.value)(), c.c_size_t()
        self.call(f"SUEntitiesGet{kind}", owner, count.value, items, c.byref(actual))
        return list(items)[:actual.value]

    def identity_transform(self, group):
        transform = Transform()
        self.call("SUGroupGetTransform", group, c.byref(transform))
        identity = [1.0 if i % 5 == 0 else 0.0 for i in range(16)]
        if any(not abs(value - wanted) <= 1e-9 for value, wanted in zip(transform.values, identity)):
            raise NativeError("Unexpected group transform; model coordinates changed")

    def group(self, entities, name):
        group = self.ref("SUGroupCreate")
        # API 14.2 requires attachment to the model before filling child entities.
        self.call("SUEntitiesAddGroup", entities, group)
        self.call("SUGroupSetName", group, name.encode())
        return group

    def attributes(self, group, values):
        dictionary = self.ref("SUEntityGetAttributeDictionary", self.lib.SUGroupToEntity(group), b"InteriorOS")
        for key, text in values.items():
            with self.owned("SUTypedValueCreate", "SUTypedValueRelease") as value:
                self.call("SUTypedValueSetString", value, text.encode())
                self.call("SUAttributeDictionarySetValue", dictionary, key.encode(), value)

    def attribute(self, group, key):
        dictionary = self.ref("SUEntityGetAttributeDictionary", self.lib.SUGroupToEntity(group), b"InteriorOS")
        with self.owned("SUTypedValueCreate", "SUTypedValueRelease") as value:
            self.call("SUAttributeDictionaryGetValue", dictionary, key.encode(), c.byref(value))
            return self.string("SUTypedValueGetString", value)

    def millimeters(self, model):
        manager = self.ref("SUModelGetOptionsManager", model)
        provider = self.ref("SUOptionsManagerGetOptionsProviderByName", manager, b"UnitsOptions")
        for key, number in ((b"LengthUnit", 2), (b"LengthFormat", 0)):
            with self.owned("SUTypedValueCreate", "SUTypedValueRelease") as value:
                self.call("SUTypedValueSetInt32", value, number)
                self.call("SUOptionsProviderSetValue", provider, key, value)

    def fill(self, entities, vertices_mm, faces):
        with self.owned("SUGeometryInputCreate", "SUGeometryInputRelease") as geometry:
            points = (Point * len(vertices_mm))(*(Point(*(v / 25.4 for v in point)) for point in vertices_mm))
            self.call("SUGeometryInputSetVertices", geometry, len(points), points)
            for loops in faces:
                index = c.c_size_t()
                for i, indices in enumerate(loops):
                    loop = self.ref("SULoopInputCreate")
                    transferred = False
                    try:
                        for vertex in indices:
                            self.call("SULoopInputAddVertexIndex", loop, vertex)
                        if i == 0:
                            self.call("SUGeometryInputAddFace", geometry, c.byref(loop), c.byref(index))
                        else:
                            self.call("SUGeometryInputFaceAddInnerLoop", geometry, index.value, c.byref(loop))
                        transferred = True
                    finally:
                        if not transferred and loop.ptr:
                            self.call("SULoopInputRelease", c.byref(loop))
            self.call("SUEntitiesFill", entities, geometry, True)
