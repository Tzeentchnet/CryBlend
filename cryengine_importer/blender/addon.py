"""Blender operator + addon registration."""

from __future__ import annotations

import os

import bpy  # type: ignore[import-not-found]
from bpy.props import StringProperty  # type: ignore[import-not-found]
from bpy.types import Operator  # type: ignore[import-not-found]
from bpy_extras.io_utils import ImportHelper  # type: ignore[import-not-found]

from ..core.cryengine import CryEngine, UnsupportedFileError
from ..io.pack_fs import RealFileSystem
from .scene_builder import build_scene


class IMPORT_OT_cryengine(Operator, ImportHelper):
    """Import a CryEngine model file."""

    bl_idname = "import_scene.cryengine"
    bl_label = "Import CryEngine (.cgf/.chr/.skin)"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".cgf"
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.cgf;*.cga;*.cgam;*.chr;*.skin",
        options={"HIDDEN"},
    )
    object_dir: StringProperty(  # type: ignore[valid-type]
        name="Object Directory",
        description=(
            "Optional asset root used to resolve material library / "
            "texture references that are stored as paths relative to "
            "the game's Objects/ directory (mirrors the C# converter's "
            "-objectdir argument)."
        ),
        default="",
        subtype="DIR_PATH",
    )

    def execute(self, context):  # type: ignore[no-untyped-def]
        # Pack FS rooted at the file's directory so companion .cgam /
        # .chrm files can be auto-resolved relative to it. When the
        # user supplies an object_dir, layer that on top so material
        # libraries / textures stored game-relative are reachable too.
        from ..io.pack_fs import CascadedPackFileSystem

        root_dir = os.path.dirname(self.filepath) or "."
        pack_fs: object = RealFileSystem(root_dir)
        if self.object_dir:
            obj_dir_fs = RealFileSystem(self.object_dir)
            pack_fs = CascadedPackFileSystem([obj_dir_fs, pack_fs])
        rel_path = os.path.basename(self.filepath)

        try:
            asset = CryEngine(
                rel_path,
                pack_fs,  # type: ignore[arg-type]
                object_dir=self.object_dir or None,
            )
            asset.process()
        except UnsupportedFileError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        except Exception as exc:  # pragma: no cover - exercised in Blender
            self.report({"ERROR"}, f"Failed to parse {self.filepath}: {exc}")
            return {"CANCELLED"}

        try:
            collection = build_scene(asset)
        except Exception as exc:  # pragma: no cover - exercised in Blender
            self.report({"ERROR"}, f"Failed to build scene: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Imported {asset.name}: {len(asset.nodes)} nodes, "
            f"{len(collection.objects)} objects, "
            f"{len(asset.materials)}/{len(asset.material_library_files)} "
            f"material libs loaded, "
            f"{len(asset.animation_clips)} animation clips",
        )
        return {"FINISHED"}


def menu_func_import(self, context):  # type: ignore[no-untyped-def]
    self.layout.operator(IMPORT_OT_cryengine.bl_idname, text="CryEngine (.cgf/.chr/.skin)")


_classes = (IMPORT_OT_cryengine,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
"""Blender operator + addon registration.

Phase 0: a no-op Import operator that opens the file picker and runs
the Model loader + reports the chunk inventory. Phase 1 will replace
the report with actual mesh creation.
"""

from __future__ import annotations

import bpy  # type: ignore[import-not-found]
from bpy.props import StringProperty  # type: ignore[import-not-found]
from bpy.types import Operator  # type: ignore[import-not-found]
from bpy_extras.io_utils import ImportHelper  # type: ignore[import-not-found]

from ..core.model import Model


class IMPORT_OT_cryengine(Operator, ImportHelper):
    """Import a CryEngine model file."""

    bl_idname = "import_scene.cryengine"
    bl_label = "Import CryEngine (.cgf/.chr/.skin)"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".cgf"
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.cgf;*.cga;*.cgam;*.chr;*.skin",
        options={"HIDDEN"},
    )

    def execute(self, context):  # type: ignore[no-untyped-def]
        try:
            model = Model.from_path(self.filepath)
        except Exception as exc:  # pragma: no cover - exercised in Blender
            self.report({"ERROR"}, f"Failed to parse {self.filepath}: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Parsed {self.filepath}: signature={model.file_signature} "
            f"version=0x{int(model.file_version):X} chunks={len(model.chunk_map)}",
        )
        # Phase 1 will create bpy.data.meshes / objects here.
        return {"FINISHED"}


def menu_func_import(self, context):  # type: ignore[no-untyped-def]
    self.layout.operator(IMPORT_OT_cryengine.bl_idname, text="CryEngine (.cgf/.chr/.skin)")


_classes = (IMPORT_OT_cryengine,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
