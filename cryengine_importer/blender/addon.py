"""Blender operator + addon registration."""

from __future__ import annotations

import os

import bpy  # type: ignore[import-not-found]
from bpy.props import (  # type: ignore[import-not-found]
    BoolProperty,
    CollectionProperty,
    StringProperty,
)
from bpy.types import Operator, OperatorFileListElement  # type: ignore[import-not-found]
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
    # Populated by the file browser (multi-select) and by the
    # drag-and-drop FileHandler when several files are dropped at once.
    files: CollectionProperty(  # type: ignore[valid-type]
        type=OperatorFileListElement,
        options={"HIDDEN", "SKIP_SAVE"},
    )
    directory: StringProperty(  # type: ignore[valid-type]
        subtype="DIR_PATH",
        options={"HIDDEN", "SKIP_SAVE"},
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
    import_related: BoolProperty(  # type: ignore[valid-type]
        name="Import Related Files",
        description=(
            "Also load sibling files referenced by the imported asset: "
            "geometry companions (.cgam/.chrm), chrparams animation "
            "lists, and the CAF/ANIM clips they reference."
        ),
        default=True,
    )

    def draw(self, context):  # type: ignore[no-untyped-def]
        layout = self.layout
        layout.prop(self, "import_related")
        layout.prop(self, "object_dir")

    def invoke(self, context, event):  # type: ignore[no-untyped-def]
        # When invoked via drag-and-drop the FileHandler pre-fills
        # ``filepath`` (and possibly ``files``/``directory``); skip the
        # file browser in that case and run immediately.
        if self.filepath:
            return self.execute(context)
        return super().invoke(context, event)

    def _iter_filepaths(self):
        """Yield absolute paths for every file selected/dropped."""
        if self.files and self.directory:
            seen: set[str] = set()
            for item in self.files:
                name = item.name
                if not name:
                    continue
                full = os.path.join(self.directory, name)
                if full in seen:
                    continue
                seen.add(full)
                yield full
            return
        if self.filepath:
            yield self.filepath

    def _import_one(self, filepath: str) -> tuple[bool, str]:
        from ..io.pack_fs import CascadedPackFileSystem

        root_dir = os.path.dirname(filepath) or "."
        pack_fs: object = RealFileSystem(root_dir)
        if self.object_dir:
            obj_dir_fs = RealFileSystem(self.object_dir)
            pack_fs = CascadedPackFileSystem([obj_dir_fs, pack_fs])
        rel_path = os.path.basename(filepath)

        try:
            asset = CryEngine(
                rel_path,
                pack_fs,  # type: ignore[arg-type]
                object_dir=self.object_dir or None,
                load_related=self.import_related,
            )
            asset.process()
        except UnsupportedFileError as exc:
            return False, str(exc)
        except Exception as exc:  # pragma: no cover - exercised in Blender
            return False, f"Failed to parse {filepath}: {exc}"

        try:
            collection = build_scene(asset)
        except Exception as exc:  # pragma: no cover - exercised in Blender
            return False, f"Failed to build scene for {filepath}: {exc}"

        return True, (
            f"Imported {asset.name}: {len(asset.nodes)} nodes, "
            f"{len(collection.objects)} objects, "
            f"{len(asset.materials)}/{len(asset.material_library_files)} "
            f"material libs loaded, "
            f"{len(asset.animation_clips)} animation clips"
        )

    def execute(self, context):  # type: ignore[no-untyped-def]
        paths = list(self._iter_filepaths())
        if not paths:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}

        successes = 0
        last_error = ""
        for path in paths:
            ok, message = self._import_one(path)
            if ok:
                successes += 1
                self.report({"INFO"}, message)
            else:
                last_error = message
                self.report({"WARNING"}, message)

        if successes == 0:
            self.report({"ERROR"}, last_error or "No files imported")
            return {"CANCELLED"}
        if successes < len(paths):
            self.report(
                {"WARNING"},
                f"Imported {successes}/{len(paths)} files; see log for details.",
            )
        return {"FINISHED"}


class IO_FH_cryengine(bpy.types.FileHandler):
    """Drag-and-drop handler for CryEngine model files (Blender 4.1+)."""

    bl_idname = "IO_FH_cryengine"
    bl_label = "CryEngine"
    bl_import_operator = IMPORT_OT_cryengine.bl_idname
    bl_file_extensions = ".cgf;.cga;.cgam;.chr;.skin"

    @classmethod
    def poll_drop(cls, context):  # type: ignore[no-untyped-def]
        # Accept drops onto the 3D viewport and the Outliner.
        area = getattr(context, "area", None)
        return area is not None and area.type in {"VIEW_3D", "OUTLINER"}


def menu_func_import(self, context):  # type: ignore[no-untyped-def]
    self.layout.operator(IMPORT_OT_cryengine.bl_idname, text="CryEngine (.cgf/.chr/.skin)")


_classes = (IMPORT_OT_cryengine, IO_FH_cryengine)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
