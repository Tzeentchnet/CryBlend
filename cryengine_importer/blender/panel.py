"""Phase 11 — CryBlend sidebar panel for the 3D Viewport.

Adds a "CryBlend" tab in the N-panel (`bl_category='CryBlend'`) with
six sub-panels:

* **General** — source path, axes, Re-import.
* **Materials** — library status, Set Object Directory, Reload .mtl,
  Replace Placeholders.
* **Tints** — live colour pickers for ``Tint_*`` PublicParam nodes
  on the active material, plus save/load JSON presets.
* **Textures** — missing-image audit, Relink Directory, Export List.
* **Physics** — collision-shape count + visibility toggle, Add Rigid
  Body World, helper-display switcher.
* **Animation** — list armature actions, Set Active, Push to NLA,
  Import Extra Clip.

Every operator routes through pure-Python helpers in
`cryengine_importer.materials.tint_presets` /
`cryengine_importer.blender.texture_audit` /
`cryengine_importer.blender.asset_metadata` so the bpy-bound code
stays thin and the heavy lifting is unit-testable.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]
from bpy.props import (  # type: ignore[import-not-found]
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
)
from bpy.types import Operator, Panel  # type: ignore[import-not-found]
from bpy_extras.io_utils import ImportHelper, ExportHelper  # type: ignore[import-not-found]

from ..materials.material import (
    extract_color_params,
    is_primary_tint_key,
    parse_color_value,
)
from ..materials.tint_presets import (
    TintPresetError,
    default_preset_path,
    load_preset,
    save_preset,
)
from .asset_metadata import (
    KEY as METADATA_KEY,
    find_active_cryblend_collection,
    read_metadata,
    stamp_collection,
)
from .texture_audit import (
    find_missing_images,
    index_directory,
    plan_relinks,
    write_missing_files_report,
)


logger = logging.getLogger(__name__)

# Heuristic for collision Empties created by `rigid_body_builder`:
# bones use ``<bone_name>_collision`` (+ ``_alive``/``_dead`` suffix);
# mesh-physics shapes use ``<prefix>_<i>_<shape>`` with the default
# prefix ``physics``. Match either form.
def _is_collision_object(obj) -> bool:
    name = getattr(obj, "name", "")
    return "_collision" in name or name.startswith("physics_")


# ============================================================ helpers


def _active_collection(context: Any):
    return find_active_cryblend_collection(context)


def _materials_in_collection(coll) -> list:
    """Return every unique material assigned to objects in ``coll``."""
    seen: set[int] = set()
    out: list = []
    for obj in getattr(coll, "all_objects", coll.objects):
        for slot in getattr(obj, "material_slots", ()):
            mat = slot.material
            if mat is None or id(mat) in seen:
                continue
            seen.add(id(mat))
            out.append(mat)
    return out


def _tint_nodes_for_material(material) -> list:
    """`ShaderNodeRGB` nodes whose name starts with ``Tint_``."""
    if material is None or not material.use_nodes or material.node_tree is None:
        return []
    out = []
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeRGB" and node.name.startswith("Tint_"):
            out.append(node)
    return out


def _tint_key(node) -> str:
    return node.name[len("Tint_") :]


def _placeholder_material_name_pattern(obj_name: str) -> str:
    return f"{obj_name}_mat"


# ====================================================== general panel


class VIEW3D_PT_cryblend(Panel):
    bl_idname = "VIEW3D_PT_cryblend"
    bl_label = "CryBlend"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"

    def draw(self, context):  # type: ignore[no-untyped-def]
        layout = self.layout
        coll = _active_collection(context)
        if coll is None:
            layout.label(text="No imported CryBlend asset selected.", icon="INFO")
            layout.label(text="Import a .cgf/.chr/.skin via File > Import.")
            return

        meta = read_metadata(coll) or {}
        layout.label(text=coll.name, icon="OUTLINER_COLLECTION")
        col = layout.column(align=True)
        col.label(text=f"Source: {Path(meta.get('source_path', '')).name or '?'}")
        if meta.get("object_dir"):
            col.label(text=f"Object Dir: {meta['object_dir']}")
        if meta.get("addon_version"):
            col.label(text=f"Addon: {meta['addon_version']}")


class VIEW3D_PT_cryblend_general(Panel):
    bl_idname = "VIEW3D_PT_cryblend_general"
    bl_label = "General"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):  # type: ignore[no-untyped-def]
        return _active_collection(context) is not None

    def draw(self, context):  # type: ignore[no-untyped-def]
        layout = self.layout
        coll = _active_collection(context)
        meta = read_metadata(coll) or {}

        col = layout.column(align=True)
        col.label(text="Axis Conversion:")
        row = col.row(align=True)
        row.label(text=f"Forward: {meta.get('axis_forward', 'Y')}")
        row.label(text=f"Up: {meta.get('axis_up', 'Z')}")
        col.label(text=f"Convert Axes: {meta.get('convert_axes', True)}")
        col.label(text=f"Import Related: {meta.get('import_related', True)}")

        layout.separator()
        op = layout.operator(
            "cryblend.reimport", text="Re-import Asset", icon="FILE_REFRESH"
        )
        op.collection_name = coll.name


# ===================================================== materials panel


class VIEW3D_PT_cryblend_materials(Panel):
    bl_idname = "VIEW3D_PT_cryblend_materials"
    bl_label = "Materials"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"

    @classmethod
    def poll(cls, context):
        return _active_collection(context) is not None

    def draw(self, context):
        layout = self.layout
        coll = _active_collection(context)
        meta = read_metadata(coll) or {}
        libs = list(meta.get("material_libs", []))
        resolved = set(meta.get("material_libs_resolved", []))

        if not libs:
            layout.label(text="No material libraries referenced.", icon="INFO")
        else:
            box = layout.box()
            box.label(text=f"Libraries ({len(resolved)}/{len(libs)} resolved):")
            for lib in libs:
                stem = Path(lib).stem.lower()
                icon = "CHECKMARK" if stem in resolved else "ERROR"
                box.label(text=lib, icon=icon)

        layout.separator()
        op = layout.operator(
            "cryblend.set_object_dir",
            text="Set Object Directory…",
            icon="FILE_FOLDER",
        )
        op.collection_name = coll.name

        layout.operator(
            "cryblend.replace_placeholders",
            text="Retry Placeholder Materials",
            icon="MATERIAL",
        ).collection_name = coll.name

        layout.operator(
            "cryblend.reload_material_from_mtl",
            text="Replace Active Slot from .mtl…",
            icon="FILE_TICK",
        )


# ========================================================== tints panel


class VIEW3D_PT_cryblend_tints(Panel):
    bl_idname = "VIEW3D_PT_cryblend_tints"
    bl_label = "Tints"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"

    @classmethod
    def poll(cls, context):
        return _active_collection(context) is not None

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        mat = (
            obj.active_material
            if obj is not None and obj.active_material is not None
            else None
        )
        if mat is None:
            layout.label(text="Select an object with an active material.", icon="INFO")
            return

        nodes = _tint_nodes_for_material(mat)
        if not nodes:
            layout.label(
                text=f"No tint inputs on '{mat.name}'.", icon="INFO"
            )
            layout.label(text="(Material has no PublicParams RGB values.)")
            return

        layout.label(text=f"Material: {mat.name}", icon="MATERIAL")
        primary_box = layout.box()
        primary_box.label(text="Primary (Multiply → Base Color)")
        secondary_box = None
        for node in nodes:
            key = _tint_key(node)
            target = primary_box if is_primary_tint_key(key) else None
            if target is None:
                if secondary_box is None:
                    secondary_box = layout.box()
                    secondary_box.label(text="Other (labelled, not auto-wired)")
                target = secondary_box
            row = target.row(align=True)
            row.label(text=key)
            row.prop(node.outputs[0], "default_value", text="")

        layout.separator()
        row = layout.row(align=True)
        row.operator(
            "cryblend.save_tint_preset", text="Save Preset…", icon="EXPORT"
        )
        row.operator(
            "cryblend.load_tint_preset", text="Load Preset…", icon="IMPORT"
        )
        coll = _active_collection(context)
        op = layout.operator(
            "cryblend.reset_tints_from_mtl",
            text="Reset to .mtl Values",
            icon="LOOP_BACK",
        )
        op.collection_name = coll.name if coll else ""
        op.material_name = mat.name


# ======================================================= textures panel


class VIEW3D_PT_cryblend_textures(Panel):
    bl_idname = "VIEW3D_PT_cryblend_textures"
    bl_label = "Textures"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _active_collection(context) is not None

    def draw(self, context):
        layout = self.layout
        coll = _active_collection(context)
        materials = _materials_in_collection(coll)
        missing = find_missing_images(
            materials,
            abspath=lambda p: bpy.path.abspath(p) if p else "",
        )

        layout.label(text=f"Materials: {len(materials)}", icon="MATERIAL")
        if missing:
            layout.label(
                text=f"Missing textures: {len(missing)}", icon="ERROR"
            )
            box = layout.box()
            for m in missing[:8]:
                box.label(text=f"{m.material_name} • {m.image_name}")
            if len(missing) > 8:
                box.label(text=f"… and {len(missing) - 8} more")
        else:
            layout.label(text="All textures resolved.", icon="CHECKMARK")

        layout.separator()
        op = layout.operator(
            "cryblend.relink_textures",
            text="Relink From Directory…",
            icon="FILE_FOLDER",
        )
        op.collection_name = coll.name
        op = layout.operator(
            "cryblend.export_missing_files",
            text="Export Missing List…",
            icon="EXPORT",
        )
        op.collection_name = coll.name


# ======================================================== physics panel


class VIEW3D_PT_cryblend_physics(Panel):
    bl_idname = "VIEW3D_PT_cryblend_physics"
    bl_label = "Physics & Helpers"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _active_collection(context) is not None

    def draw(self, context):
        layout = self.layout
        coll = _active_collection(context)
        collision = [o for o in coll.all_objects if _is_collision_object(o)]
        layout.label(
            text=f"Collision shapes: {len(collision)}", icon="MOD_PHYSICS"
        )
        has_world = bpy.context.scene.rigidbody_world is not None
        if not has_world:
            layout.operator(
                "cryblend.add_rigid_body_world",
                text="Add Rigid Body World",
                icon="WORLD",
            )
        else:
            layout.label(text="Rigid Body World: present", icon="CHECKMARK")
        op = layout.operator(
            "cryblend.toggle_collision_visibility",
            text="Toggle Collision Visibility",
            icon="HIDE_OFF",
        )
        op.collection_name = coll.name

        layout.separator()
        layout.label(text="Helper Display:")
        scene_props = context.scene.cryblend_panel_props
        layout.prop(scene_props, "helper_display_type", text="Type")
        layout.prop(scene_props, "helper_display_size", text="Size")
        layout.operator(
            "cryblend.apply_helper_display",
            text="Apply to Selected Empties",
            icon="EMPTY_DATA",
        )


# ======================================================= animation panel


class VIEW3D_PT_cryblend_animation(Panel):
    bl_idname = "VIEW3D_PT_cryblend_animation"
    bl_label = "Animation"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CryBlend"
    bl_parent_id = "VIEW3D_PT_cryblend"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        coll = _active_collection(context)
        if coll is None:
            return False
        return any(o.type == "ARMATURE" for o in coll.all_objects)

    def draw(self, context):
        layout = self.layout
        coll = _active_collection(context)
        armatures = [o for o in coll.all_objects if o.type == "ARMATURE"]
        if not armatures:
            layout.label(text="No armature in this collection.", icon="INFO")
            return
        arm = armatures[0]
        layout.label(text=f"Armature: {arm.name}", icon="ARMATURE_DATA")

        ad = arm.animation_data
        active_action = ad.action if ad else None
        layout.label(
            text=f"Active: {active_action.name if active_action else '(none)'}"
        )

        # Find every action whose user list includes the armature.
        all_actions = [
            a for a in bpy.data.actions
            if any(u == arm for u in getattr(a, "users", []) if hasattr(a, "users"))
        ] or list(bpy.data.actions)

        if all_actions:
            box = layout.box()
            for a in all_actions[:24]:
                row = box.row(align=True)
                row.label(text=a.name)
                op = row.operator(
                    "cryblend.set_active_action", text="", icon="PLAY"
                )
                op.armature_name = arm.name
                op.action_name = a.name
                op = row.operator(
                    "cryblend.push_action_to_nla", text="", icon="NLA_PUSHDOWN"
                )
                op.armature_name = arm.name
                op.action_name = a.name
            if len(all_actions) > 24:
                box.label(text=f"… and {len(all_actions) - 24} more")

        layout.separator()
        op = layout.operator(
            "cryblend.import_extra_clip",
            text="Import Extra Clip…",
            icon="ANIM_DATA",
        )
        op.collection_name = coll.name
        op.armature_name = arm.name


# ============================================================ operators


class CRYBLEND_OT_set_object_dir(Operator):
    """Pick an Object Directory and re-resolve material libraries."""

    bl_idname = "cryblend.set_object_dir"
    bl_label = "Set Object Directory"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]
    directory: StringProperty(subtype="DIR_PATH")  # type: ignore[valid-type]
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})  # type: ignore[valid-type]

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, f"Collection '{self.collection_name}' not found")
            return {"CANCELLED"}
        meta = read_metadata(coll) or {}
        meta_object_dir = self.directory.rstrip(os.sep) if self.directory else ""

        n_resolved = _reresolve_materials(coll, meta, object_dir=meta_object_dir)

        # Update metadata in place.
        meta["object_dir"] = meta_object_dir
        coll[METADATA_KEY] = meta

        self.report(
            {"INFO"},
            f"Object directory set; {n_resolved} placeholder(s) resolved.",
        )
        return {"FINISHED"}


class CRYBLEND_OT_replace_placeholders(Operator):
    """Retry resolving any placeholder materials in the collection."""

    bl_idname = "cryblend.replace_placeholders"
    bl_label = "Retry Placeholder Materials"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, "Collection not found")
            return {"CANCELLED"}
        meta = read_metadata(coll) or {}
        n = _reresolve_materials(coll, meta, object_dir=meta.get("object_dir") or None)
        self.report({"INFO"}, f"{n} placeholder(s) re-resolved.")
        return {"FINISHED"}


class CRYBLEND_OT_reload_material_from_mtl(Operator, ImportHelper):
    """Replace the active object's active material slot from a .mtl."""

    bl_idname = "cryblend.reload_material_from_mtl"
    bl_label = "Reload Material From .mtl"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".mtl"
    filter_glob: StringProperty(default="*.mtl;*.xml", options={"HIDDEN"})  # type: ignore[valid-type]
    sub_material_index: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Sub-Material Index",
        description="Index into the .mtl <SubMaterials> list",
        default=0,
        min=0,
    )

    def execute(self, context):
        from ..io.pack_fs import RealFileSystem
        from ..materials import load_material
        from .material_builder import build_material

        obj = context.active_object
        if obj is None or not obj.material_slots:
            self.report({"ERROR"}, "No active object with material slots")
            return {"CANCELLED"}
        path = Path(self.filepath)
        if not path.exists():
            self.report({"ERROR"}, f"File not found: {path}")
            return {"CANCELLED"}
        fs = RealFileSystem(path.parent)
        parsed = load_material(path.name, fs)
        if parsed is None:
            self.report({"ERROR"}, f"Failed to parse {path.name}")
            return {"CANCELLED"}
        subs = parsed.sub_materials or [parsed]
        idx = max(0, min(self.sub_material_index, len(subs) - 1))
        new_mat = build_material(subs[idx], pack_fs=fs)
        obj.material_slots[obj.active_material_index].material = new_mat
        self.report(
            {"INFO"},
            f"Replaced slot {obj.active_material_index} with {new_mat.name}",
        )
        return {"FINISHED"}


class CRYBLEND_OT_save_tint_preset(Operator, ExportHelper):
    """Save the active material's `Tint_*` colours to a JSON preset."""

    bl_idname = "cryblend.save_tint_preset"
    bl_label = "Save Tint Preset"
    bl_options = {"REGISTER"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})  # type: ignore[valid-type]

    def invoke(self, context, event):
        obj = context.active_object
        mat = obj.active_material if obj else None
        if mat is not None and not self.filepath:
            self.filepath = str(default_preset_path(Path("preset.mtl"), mat.name))
        return super().invoke(context, event)

    def execute(self, context):
        obj = context.active_object
        mat = obj.active_material if obj else None
        if mat is None:
            self.report({"ERROR"}, "No active material")
            return {"CANCELLED"}
        nodes = _tint_nodes_for_material(mat)
        if not nodes:
            self.report({"WARNING"}, "Material has no Tint_* nodes")
            return {"CANCELLED"}
        tints = {
            _tint_key(n): tuple(n.outputs[0].default_value[:3])
            for n in nodes
        }
        save_preset(self.filepath, tints, material_name=mat.name)
        self.report({"INFO"}, f"Saved {len(tints)} tint(s) to {self.filepath}")
        return {"FINISHED"}


class CRYBLEND_OT_load_tint_preset(Operator, ImportHelper):
    """Load a JSON tint preset onto the active material."""

    bl_idname = "cryblend.load_tint_preset"
    bl_label = "Load Tint Preset"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})  # type: ignore[valid-type]

    def execute(self, context):
        obj = context.active_object
        mat = obj.active_material if obj else None
        if mat is None:
            self.report({"ERROR"}, "No active material")
            return {"CANCELLED"}
        try:
            tints = load_preset(self.filepath)
        except (TintPresetError, OSError) as exc:
            self.report({"ERROR"}, f"Failed to load preset: {exc}")
            return {"CANCELLED"}
        n_applied, n_missing = _apply_tints_to_material(mat, tints)
        msg = f"Applied {n_applied} tint(s)"
        if n_missing:
            msg += f"; {n_missing} key(s) had no matching Tint_ node"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class CRYBLEND_OT_reset_tints_from_mtl(Operator):
    """Restore tints from the original `.mtl` PublicParams."""

    bl_idname = "cryblend.reset_tints_from_mtl"
    bl_label = "Reset Tints From .mtl"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]
    material_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        mat = bpy.data.materials.get(self.material_name)
        if coll is None or mat is None:
            self.report({"ERROR"}, "Collection or material not found")
            return {"CANCELLED"}
        meta = read_metadata(coll) or {}
        cache = meta.get("public_params_by_material", {})
        pp = cache.get(self.material_name)
        if not pp:
            self.report(
                {"WARNING"},
                f"No cached PublicParams for '{self.material_name}'",
            )
            return {"CANCELLED"}
        tints: dict[str, tuple[float, float, float]] = {}
        for k, v in pp.items():
            rgb = parse_color_value(str(v))
            if rgb is not None:
                tints[k] = rgb
        n_applied, _ = _apply_tints_to_material(mat, tints)
        self.report({"INFO"}, f"Reset {n_applied} tint(s) from .mtl values.")
        return {"FINISHED"}


class CRYBLEND_OT_relink_textures(Operator):
    """Walk a directory and relink any missing textures by basename."""

    bl_idname = "cryblend.relink_textures"
    bl_label = "Relink Textures"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]
    directory: StringProperty(subtype="DIR_PATH")  # type: ignore[valid-type]
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})  # type: ignore[valid-type]

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, "Collection not found")
            return {"CANCELLED"}
        materials = _materials_in_collection(coll)
        missing = find_missing_images(
            materials,
            abspath=lambda p: bpy.path.abspath(p) if p else "",
        )
        index = index_directory(self.directory)
        plan = plan_relinks(missing, index)
        n_relinked = 0
        for img_name, new_path in plan.items():
            img = bpy.data.images.get(img_name)
            if img is None:
                continue
            img.filepath = new_path
            try:
                img.reload()
            except Exception:
                logger.debug("image reload failed for %s", img_name, exc_info=True)
            n_relinked += 1
        self.report(
            {"INFO"},
            f"Relinked {n_relinked}/{len(missing)} texture(s) from {self.directory}",
        )
        return {"FINISHED"}


class CRYBLEND_OT_export_missing_files(Operator, ExportHelper):
    """Export a tab-separated list of missing texture files."""

    bl_idname = "cryblend.export_missing_files"
    bl_label = "Export Missing Files List"
    bl_options = {"REGISTER"}

    collection_name: StringProperty()  # type: ignore[valid-type]
    filename_ext = ".txt"
    filter_glob: StringProperty(default="*.txt", options={"HIDDEN"})  # type: ignore[valid-type]

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, "Collection not found")
            return {"CANCELLED"}
        materials = _materials_in_collection(coll)
        missing = find_missing_images(
            materials,
            abspath=lambda p: bpy.path.abspath(p) if p else "",
        )
        n = write_missing_files_report(self.filepath, missing)
        self.report({"INFO"}, f"Wrote {n} entries to {self.filepath}")
        return {"FINISHED"}


class CRYBLEND_OT_add_rigid_body_world(Operator):
    bl_idname = "cryblend.add_rigid_body_world"
    bl_label = "Add Rigid Body World"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.scene.rigidbody_world is None:
            try:
                bpy.ops.rigidbody.world_add()
            except Exception as exc:
                self.report({"ERROR"}, f"Failed to add Rigid Body World: {exc}")
                return {"CANCELLED"}
        return {"FINISHED"}


class CRYBLEND_OT_toggle_collision_visibility(Operator):
    bl_idname = "cryblend.toggle_collision_visibility"
    bl_label = "Toggle Collision Visibility"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, "Collection not found")
            return {"CANCELLED"}
        targets = [o for o in coll.all_objects if _is_collision_object(o)]
        if not targets:
            self.report({"INFO"}, "No collision shapes found.")
            return {"CANCELLED"}
        new_state = not targets[0].hide_viewport
        for o in targets:
            o.hide_viewport = new_state
        self.report(
            {"INFO"},
            f"{'Hid' if new_state else 'Showed'} {len(targets)} collision shape(s).",
        )
        return {"FINISHED"}


class CRYBLEND_OT_apply_helper_display(Operator):
    bl_idname = "cryblend.apply_helper_display"
    bl_label = "Apply Helper Display"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.cryblend_panel_props
        n = 0
        for obj in context.selected_objects:
            if obj.type != "EMPTY":
                continue
            obj.empty_display_type = props.helper_display_type
            obj.empty_display_size = props.helper_display_size
            n += 1
        self.report({"INFO"}, f"Applied to {n} empty(s).")
        return {"FINISHED"}


class CRYBLEND_OT_set_active_action(Operator):
    bl_idname = "cryblend.set_active_action"
    bl_label = "Set Active Action"
    bl_options = {"REGISTER", "UNDO"}

    armature_name: StringProperty()  # type: ignore[valid-type]
    action_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        arm = bpy.data.objects.get(self.armature_name)
        action = bpy.data.actions.get(self.action_name)
        if arm is None or action is None:
            self.report({"ERROR"}, "Armature or action not found")
            return {"CANCELLED"}
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = action
        return {"FINISHED"}


class CRYBLEND_OT_push_action_to_nla(Operator):
    bl_idname = "cryblend.push_action_to_nla"
    bl_label = "Push Action to NLA"
    bl_options = {"REGISTER", "UNDO"}

    armature_name: StringProperty()  # type: ignore[valid-type]
    action_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        arm = bpy.data.objects.get(self.armature_name)
        action = bpy.data.actions.get(self.action_name)
        if arm is None or action is None:
            self.report({"ERROR"}, "Armature or action not found")
            return {"CANCELLED"}
        if arm.animation_data is None:
            arm.animation_data_create()
        track = arm.animation_data.nla_tracks.new()
        track.name = action.name
        track.strips.new(action.name, int(action.frame_range[0]), action)
        return {"FINISHED"}


class CRYBLEND_OT_import_extra_clip(Operator, ImportHelper):
    """Import an extra .caf/.anim/.cal clip onto the collection's armature."""

    bl_idname = "cryblend.import_extra_clip"
    bl_label = "Import Extra Animation Clip"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]
    armature_name: StringProperty()  # type: ignore[valid-type]
    filename_ext = ".caf"
    filter_glob: StringProperty(  # type: ignore[valid-type]
        default="*.caf;*.anim;*.cal", options={"HIDDEN"}
    )

    def execute(self, context):
        from ..core.cryengine import CryEngine, UnsupportedFileError
        from ..io.pack_fs import RealFileSystem
        from .action_builder import build_actions

        coll = bpy.data.collections.get(self.collection_name)
        arm = bpy.data.objects.get(self.armature_name)
        if coll is None or arm is None:
            self.report({"ERROR"}, "Collection or armature not found")
            return {"CANCELLED"}
        meta = read_metadata(coll) or {}
        source = meta.get("source_path", "")
        if not source or not Path(source).exists():
            self.report({"ERROR"}, "Original source asset not available for re-parse")
            return {"CANCELLED"}
        source_path = Path(source)
        clip_path = Path(self.filepath)

        # Copy the clip into the source asset's folder so the chrparams
        # auto-discovery picks it up; if it's already there, skip.
        target = source_path.parent / clip_path.name
        if not target.exists():
            try:
                target.write_bytes(clip_path.read_bytes())
            except Exception as exc:
                self.report({"ERROR"}, f"Couldn't stage clip: {exc}")
                return {"CANCELLED"}

        try:
            asset = CryEngine(
                source_path.name,
                RealFileSystem(source_path.parent),
                object_dir=meta.get("object_dir") or None,
                load_related=True,
            )
            asset.process()
        except UnsupportedFileError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not asset.animation_clips:
            self.report({"WARNING"}, "No animation clips parsed")
            return {"CANCELLED"}
        before = len(bpy.data.actions)
        build_actions(asset, arm)
        after = len(bpy.data.actions)
        self.report({"INFO"}, f"Imported {after - before} new action(s)")
        return {"FINISHED"}


class CRYBLEND_OT_reimport(Operator):
    """Re-import the asset using the cached metadata settings."""

    bl_idname = "cryblend.reimport"
    bl_label = "Re-import CryBlend Asset"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        coll = bpy.data.collections.get(self.collection_name)
        if coll is None:
            self.report({"ERROR"}, "Collection not found")
            return {"CANCELLED"}
        meta = read_metadata(coll) or {}
        source = meta.get("source_path", "")
        if not source or not Path(source).exists():
            self.report({"ERROR"}, f"Source missing: {source}")
            return {"CANCELLED"}
        # Delete current contents (objects + the collection itself).
        # Keep the user's selection alive: just queue a fresh import.
        for obj in list(coll.all_objects):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                logger.debug("failed to remove %s", obj.name, exc_info=True)
        try:
            bpy.context.scene.collection.children.unlink(coll)
        except Exception:
            logger.debug("failed to unlink old collection", exc_info=True)
        try:
            bpy.data.collections.remove(coll)
        except Exception:
            logger.debug("failed to remove old collection", exc_info=True)

        try:
            bpy.ops.import_scene.cryengine(
                "EXEC_DEFAULT",
                filepath=source,
                object_dir=meta.get("object_dir", "") or "",
                axis_forward=meta.get("axis_forward", "Y"),
                axis_up=meta.get("axis_up", "Z"),
                convert_axes=bool(meta.get("convert_axes", True)),
                import_related=bool(meta.get("import_related", True)),
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Re-import failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ============================================================ helpers


def _reresolve_materials(coll, meta: dict, *, object_dir: str | None) -> int:
    """Re-run material library resolution and replace placeholder slots.

    Returns the number of placeholder material slots that got upgraded
    to a real material. Updates ``meta['material_libs_resolved']`` in
    place but does *not* write it back to the collection — caller is
    expected to do that.
    """
    from ..io.pack_fs import RealFileSystem
    from ..materials import load_material_libraries
    from .material_builder import build_material

    libs = list(meta.get("material_libs", []))
    if not libs:
        return 0
    source = Path(meta.get("source_path", ""))
    if not source.exists():
        return 0
    fs = RealFileSystem(source.parent)
    pack_fs: Any = fs
    if object_dir:
        from ..io.pack_fs import CascadedPackFileSystem

        pack_fs = CascadedPackFileSystem([RealFileSystem(object_dir), fs])

    libraries = load_material_libraries(libs, pack_fs, object_dir=object_dir)
    meta["material_libs_resolved"] = list(libraries.keys())

    # Walk every mesh; for each material slot whose name looks like a
    # placeholder, look up the matching parsed material by stem and
    # build a real one.
    n = 0
    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        for idx, slot_mat in enumerate(mesh.materials):
            if slot_mat is None:
                continue
            # Placeholders have no nodes (or only the default ones) and
            # match the ``<name>_mat<N>`` pattern. We stay conservative:
            # require the explicit ``_mat`` infix.
            if "_mat" not in slot_mat.name:
                continue
            # Best-effort: find a matching parsed sub-material by name
            # inside any library. The original mat_id is encoded as the
            # numeric suffix on the placeholder name.
            try:
                mat_id = int(slot_mat.name.rsplit("_mat", 1)[1])
            except (ValueError, IndexError):
                continue
            for lib in libraries.values():
                subs = lib.sub_materials or [lib]
                if 0 <= mat_id < len(subs):
                    new_mat = build_material(subs[mat_id], pack_fs=pack_fs)
                    mesh.materials[idx] = new_mat
                    n += 1
                    break
    return n


def _apply_tints_to_material(
    material, tints: dict[str, tuple[float, float, float]]
) -> tuple[int, int]:
    """Write ``tints`` into the matching ``Tint_*`` nodes.

    Returns ``(n_applied, n_missing)``. Keys with no matching node are
    silently skipped (count returned for the report message).
    """
    nodes_by_key = {_tint_key(n): n for n in _tint_nodes_for_material(material)}
    n_applied = 0
    n_missing = 0
    for key, rgb in tints.items():
        node = nodes_by_key.get(key)
        if node is None:
            n_missing += 1
            continue
        node.outputs[0].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        n_applied += 1
    return n_applied, n_missing


# ============================================================ scene props


class CryBlendPanelProps(bpy.types.PropertyGroup):
    helper_display_type: EnumProperty(  # type: ignore[valid-type]
        name="Helper Display",
        items=(
            ("PLAIN_AXES", "Plain Axes", ""),
            ("ARROWS", "Arrows", ""),
            ("CONE", "Cone", ""),
            ("CUBE", "Cube", ""),
            ("SPHERE", "Sphere", ""),
        ),
        default="PLAIN_AXES",
    )
    helper_display_size: FloatProperty(  # type: ignore[valid-type]
        name="Helper Size",
        default=1.0,
        min=0.001,
        max=100.0,
    )


# ============================================================ register


_classes: tuple = (
    CryBlendPanelProps,
    VIEW3D_PT_cryblend,
    VIEW3D_PT_cryblend_general,
    VIEW3D_PT_cryblend_materials,
    VIEW3D_PT_cryblend_tints,
    VIEW3D_PT_cryblend_textures,
    VIEW3D_PT_cryblend_physics,
    VIEW3D_PT_cryblend_animation,
    CRYBLEND_OT_set_object_dir,
    CRYBLEND_OT_replace_placeholders,
    CRYBLEND_OT_reload_material_from_mtl,
    CRYBLEND_OT_save_tint_preset,
    CRYBLEND_OT_load_tint_preset,
    CRYBLEND_OT_reset_tints_from_mtl,
    CRYBLEND_OT_relink_textures,
    CRYBLEND_OT_export_missing_files,
    CRYBLEND_OT_add_rigid_body_world,
    CRYBLEND_OT_toggle_collision_visibility,
    CRYBLEND_OT_apply_helper_display,
    CRYBLEND_OT_set_active_action,
    CRYBLEND_OT_push_action_to_nla,
    CRYBLEND_OT_import_extra_clip,
    CRYBLEND_OT_reimport,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cryblend_panel_props = bpy.props.PointerProperty(
        type=CryBlendPanelProps
    )


def unregister() -> None:
    try:
        del bpy.types.Scene.cryblend_panel_props
    except Exception:
        pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
