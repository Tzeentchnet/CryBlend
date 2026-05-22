"""Blender operator + addon registration."""

from __future__ import annotations

import os
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from bpy.props import (  # type: ignore[import-not-found]
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    StringProperty,
)
from bpy.types import Operator, OperatorFileListElement  # type: ignore[import-not-found]
from bpy_extras.io_utils import ImportHelper, axis_conversion  # type: ignore[import-not-found]

from ..core.cryengine import CryEngine, UnsupportedFileError
from ..io.pack_fs import RealFileSystem
from .._logging import attach_for_operator
from .asset_metadata import stamp_collection
from .import_dedup import canonicalize_import_paths as _canonicalize_import_paths
from .scene_builder import build_scene


def _addon_version_string() -> str:
    """Return the addon version as ``"X.Y.Z"`` from the package
    ``bl_info`` dict, falling back to ``"0.0.0"``."""
    try:
        from .. import bl_info  # type: ignore[attr-defined]

        version = bl_info.get("version", (0, 0, 0))
        return ".".join(str(v) for v in version)
    except Exception:  # pragma: no cover - defensive
        return "0.0.0"


class IMPORT_OT_cryengine(Operator, ImportHelper):
    """Import a CryEngine model file."""

    bl_idname = "import_scene.cryengine"
    bl_label = "Import CryEngine (.cgf/.chr/.skin/.cdf)"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".cgf"
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default=(
            "*.cgf;*.cga;*.cgam;*.cgfm;*.chr;*.chrm;*.skin;*.skinm;*.cdf"
        ),
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
    animations_dir: StringProperty(  # type: ignore[valid-type]
        name="Animations Directory",
        description=(
            "Optional Crysis 2 animation root used to resolve .chrparams "
            "wildcards when animations are extracted outside the asset root."
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
    import_cdf_composition: BoolProperty(  # type: ignore[valid-type]
        name="Import CDF Composition",
        description=(
            "When importing a .cdf, assemble its base model and attachments. "
            "When importing a .chr/.skin, use a uniquely matching nearby CDF "
            "when one can be found."
        ),
        default=True,
    )
    convert_axes: BoolProperty(  # type: ignore[valid-type]
        name="Convert to Blender Orientation",
        description=(
            "Rotate the imported asset so its CryEngine axes "
            "(Z-up, +Y-forward) align with Blender's "
            "(Z-up, -Y-forward). Disable to keep the raw "
            "CryEngine orientation."
        ),
        default=True,
    )
    axis_forward: EnumProperty(  # type: ignore[valid-type]
        name="Forward",
        description="Which CryEngine axis points forward in the source asset",
        items=(
            ("X", "X", ""),
            ("Y", "Y", ""),
            ("Z", "Z", ""),
            ("-X", "-X", ""),
            ("-Y", "-Y", ""),
            ("-Z", "-Z", ""),
        ),
        default="Y",
    )
    axis_up: EnumProperty(  # type: ignore[valid-type]
        name="Up",
        description="Which CryEngine axis points up in the source asset",
        items=(
            ("X", "X", ""),
            ("Y", "Y", ""),
            ("Z", "Z", ""),
            ("-X", "-X", ""),
            ("-Y", "-Y", ""),
            ("-Z", "-Z", ""),
        ),
        default="Z",
    )
    verbose: BoolProperty(  # type: ignore[valid-type]
        name="Verbose Logging",
        description=(
            "Emit DEBUG-level logs from the importer to Blender's "
            "System Console. Use this when an import looks wrong but "
            "completes without an error message."
        ),
        default=False,
    )

    def draw(self, context):  # type: ignore[no-untyped-def]
        layout = self.layout
        layout.prop(self, "import_related")
        layout.prop(self, "import_cdf_composition")
        layout.prop(self, "object_dir")
        layout.prop(self, "animations_dir")
        layout.prop(self, "convert_axes")
        col = layout.column()
        col.enabled = self.convert_axes
        col.prop(self, "axis_forward")
        col.prop(self, "axis_up")
        layout.prop(self, "verbose")

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

    def _global_matrix(self):
        if not self.convert_axes:
            return None
        return axis_conversion(
            from_forward=self.axis_forward,
            from_up=self.axis_up,
            to_forward="-Y",
            to_up="Z",
        ).to_4x4()

    def _guess_game_root(self, filepath: str) -> str | None:
        path = Path(filepath).resolve()
        parts = path.parts
        for i, part in enumerate(parts):
            if part.lower() == "objects" and i > 0:
                return str(Path(*parts[:i]))
        return None

    def _relative_to_root(self, filepath: str, root: str) -> str | None:
        try:
            return Path(filepath).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return None

    def _with_animation_layer(self, pack_fs):
        from ..io.pack_fs import CascadedPackFileSystem

        if not self.animations_dir:
            return pack_fs
        return CascadedPackFileSystem(
            [pack_fs, RealFileSystem(self.animations_dir)]
        )

    def _geometry_context(self, filepath: str):
        from ..io.pack_fs import CascadedPackFileSystem

        root_dir = os.path.dirname(filepath) or "."
        object_root = self.object_dir or self._guess_game_root(filepath)
        if object_root:
            rel = self._relative_to_root(filepath, object_root)
            if rel is not None:
                return self._with_animation_layer(RealFileSystem(object_root)), rel, object_root
            pack_fs = CascadedPackFileSystem(
                [RealFileSystem(object_root), RealFileSystem(root_dir)]
            )
            return self._with_animation_layer(pack_fs), os.path.basename(filepath), object_root
        return self._with_animation_layer(RealFileSystem(root_dir)), os.path.basename(filepath), None

    def _cdf_context(self, filepath: str):
        from ..io.pack_fs import CascadedPackFileSystem

        root_dir = os.path.dirname(filepath) or "."
        object_root = self.object_dir or self._guess_game_root(filepath)
        if object_root:
            rel = self._relative_to_root(filepath, object_root)
            if rel is not None:
                return self._with_animation_layer(RealFileSystem(object_root)), rel, object_root
            pack_fs = CascadedPackFileSystem(
                [RealFileSystem(object_root), RealFileSystem(root_dir)]
            )
            return self._with_animation_layer(pack_fs), os.path.basename(filepath), object_root
        return self._with_animation_layer(RealFileSystem(root_dir)), os.path.basename(filepath), None

    def _auto_cdf_context(self, filepath: str):
        from ..core.cdf_assembly import find_cdfs_for_model

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in {".chr", ".skin"} or not self.import_cdf_composition:
            return None

        object_root = self.object_dir or self._guess_game_root(filepath)
        if object_root:
            rel = self._relative_to_root(filepath, object_root)
            if rel is not None:
                pack_fs = RealFileSystem(object_root)
                matches = find_cdfs_for_model(rel, pack_fs)
                if len(matches) == 1:
                    return self._with_animation_layer(pack_fs), matches[0], object_root
                if len(matches) > 1:
                    self.report(
                        {"WARNING"},
                        f"Multiple CDFs reference {os.path.basename(filepath)}; "
                        "import a .cdf directly to choose one.",
                    )
                    return None

        root_dir = os.path.dirname(filepath) or "."
        pack_fs = RealFileSystem(root_dir)
        matches = find_cdfs_for_model(os.path.basename(filepath), pack_fs)
        if len(matches) == 1:
            return self._with_animation_layer(pack_fs), matches[0], None
        if len(matches) > 1:
            self.report(
                {"WARNING"},
                f"Multiple CDFs reference {os.path.basename(filepath)}; "
                "import a .cdf directly to choose one.",
            )
        return None

    def _import_one(self, filepath: str) -> tuple[bool, str]:
        with attach_for_operator(self, verbose=self.verbose):
            ext = os.path.splitext(filepath)[1].lower()
            global_matrix = self._global_matrix()

            try:
                if ext == ".cdf":
                    pack_fs, rel_path, object_dir = self._cdf_context(filepath)
                    return self._import_cdf(
                        filepath,
                        rel_path,
                        pack_fs,
                        object_dir,
                        global_matrix,
                    )

                auto_cdf = self._auto_cdf_context(filepath)
                if auto_cdf is not None:
                    pack_fs, rel_path, object_dir = auto_cdf
                    return self._import_cdf(
                        filepath,
                        rel_path,
                        pack_fs,
                        object_dir,
                        global_matrix,
                    )

                pack_fs, rel_path, object_dir = self._geometry_context(filepath)
                asset = CryEngine(
                    rel_path,
                    pack_fs,  # type: ignore[arg-type]
                    object_dir=object_dir,
                    load_related=self.import_related,
                )
                asset.process()
            except UnsupportedFileError as exc:
                return False, str(exc)
            except Exception as exc:  # pragma: no cover - exercised in Blender
                return False, f"Failed to parse {filepath}: {exc}"

            try:
                collection = build_scene(asset, global_matrix=global_matrix)
            except Exception as exc:  # pragma: no cover - exercised in Blender
                return False, f"Failed to build scene for {filepath}: {exc}"

            # Stamp post-import metadata for the Phase-11 sidebar UI.
            try:
                pp_cache: dict[str, dict[str, str]] = {}
                for lib in asset.materials.values():
                    for sub in lib.sub_materials or [lib]:
                        if sub.name and sub.public_params:
                            pp_cache[sub.name] = dict(sub.public_params)
                stamp_collection(
                    collection,
                    source_path=filepath,
                    object_dir=object_dir,
                    material_libs=asset.material_library_files,
                    material_libs_resolved=list(asset.materials.keys()),
                    axis_forward=self.axis_forward,
                    axis_up=self.axis_up,
                    convert_axes=self.convert_axes,
                    import_related=self.import_related,
                    import_cdf_composition=self.import_cdf_composition,
                    animations_dir=self.animations_dir or None,
                    addon_version=_addon_version_string(),
                    public_params_by_material=pp_cache or None,
                )
            except Exception:  # pragma: no cover - defensive
                logger = __import__("logging").getLogger(__name__)
                logger.debug("failed to stamp cryblend metadata", exc_info=True)

            # Surface a hint when material libraries silently failed to
            # resolve and the user didn't supply an object directory.
            if (
                asset.material_library_files
                and len(asset.materials) < len(asset.material_library_files)
            ):
                missing = len(asset.material_library_files) - len(asset.materials)
                if object_dir:
                    self.report(
                        {"WARNING"},
                        f"{missing} material librar(y/ies) failed to resolve.",
                    )
                else:
                    self.report(
                        {"WARNING"},
                        f"{missing} material librar(y/ies) failed to resolve. Set the "
                        f"'Object Directory' field in the import dialog to your "
                        f"game's data root (where 'Objects/' lives).",
                    )

        return True, (
            f"Imported {asset.name}: {len(asset.nodes)} nodes, "
            f"{len(collection.objects)} objects, "
            f"{len(asset.materials)}/{len(asset.material_library_files)} "
            f"material libs loaded, "
            f"{len(asset.animation_clips)} skeletal clips, "
            f"{len(getattr(asset, 'object_animation_clips', []))} object clips"
        )

    def _import_cdf(
        self,
        source_path: str,
        cdf_path: str,
        pack_fs,
        object_dir: str | None,
        global_matrix,
    ) -> tuple[bool, str]:
        from .cdf_scene_builder import build_cdf_scene

        try:
            result = build_cdf_scene(
                cdf_path,
                pack_fs,
                object_dir=object_dir,
                load_related=self.import_related,
                global_matrix=global_matrix,
            )
        except Exception as exc:  # pragma: no cover - exercised in Blender
            return False, f"Failed to import CDF {source_path}: {exc}"

        cdf_attachments = []
        cdf_warnings = list(result.warnings)
        for built in result.attachments:
            att = built.plan.attachment
            cdf_attachments.append(
                {
                    "name": att.name,
                    "type": att.type,
                    "binding": att.binding,
                    "resolved_binding": built.plan.resolved_binding or "",
                    "bone_name": att.bone_name,
                    "flags": int(att.flags),
                    "visible": bool(built.plan.visible),
                    "status": built.plan.status,
                    "material": built.plan.material or "",
                    "phys_prop_type": att.phys_prop_type or "",
                    "rope_lods": att.rope_lods,
                }
            )
            cdf_warnings.extend(built.warnings)

        try:
            stamp_collection(
                result.collection,
                source_path=source_path,
                object_dir=object_dir,
                material_libs=result.material_library_files,
                material_libs_resolved=result.material_library_keys,
                axis_forward=self.axis_forward,
                axis_up=self.axis_up,
                convert_axes=self.convert_axes,
                import_related=self.import_related,
                import_cdf_composition=self.import_cdf_composition,
                animations_dir=self.animations_dir or None,
                addon_version=_addon_version_string(),
                cdf_source_path=cdf_path,
                cdf_attachments=cdf_attachments,
                cdf_warnings=cdf_warnings,
            )
        except Exception:  # pragma: no cover - defensive
            logger = __import__("logging").getLogger(__name__)
            logger.debug("failed to stamp cdf metadata", exc_info=True)

        if cdf_warnings:
            self.report({"WARNING"}, f"CDF imported with {len(cdf_warnings)} warning(s).")

        object_count = _collection_object_count(result.collection)
        return True, (
            f"Imported CDF {Path(cdf_path).stem}: "
            f"{len(result.attachments)} attachments, {object_count} objects, "
            f"{len(result.material_library_keys)}/{len(result.material_library_files)} "
            f"material libs loaded"
        )

    def execute(self, context):  # type: ignore[no-untyped-def]
        raw_paths = list(self._iter_filepaths())
        if not raw_paths:
            self.report({"ERROR"}, "No file selected")
            return {"CANCELLED"}

        paths, skipped_companions = _canonicalize_import_paths(raw_paths)
        if skipped_companions:
            self.report(
                {"INFO"},
                f"Skipped {skipped_companions} companion file(s) "
                f"already covered by their primary.",
            )
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
    bl_file_extensions = ".cgf;.cga;.cgam;.cgfm;.chr;.chrm;.skin;.skinm;.cdf"

    @classmethod
    def poll_drop(cls, context):  # type: ignore[no-untyped-def]
        # Accept drops onto the 3D viewport and the Outliner.
        area = getattr(context, "area", None)
        return area is not None and area.type in {"VIEW_3D", "OUTLINER"}


def menu_func_import(self, context):  # type: ignore[no-untyped-def]
    self.layout.operator(
        IMPORT_OT_cryengine.bl_idname,
        text="CryEngine (.cgf/.chr/.skin/.cdf)",
    )


def _collection_object_count(collection) -> int:  # type: ignore[no-untyped-def]
    count = len(collection.objects)
    for child in collection.children:
        count += _collection_object_count(child)
    return count


_classes = (IMPORT_OT_cryengine, IO_FH_cryengine)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    # Phase 11 sidebar panel + operators.
    from . import panel

    panel.register()


def unregister() -> None:
    from . import panel

    panel.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
