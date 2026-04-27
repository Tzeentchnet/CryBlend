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
    IntProperty,
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
from .crysis3_tools import (
    CRYSIS3_METADATA_KEY,
    apply_crysis3_settings,
    audit_crytools_asset,
    audit_crysis3_asset,
    format_attachment_xml,
    format_crytools_audit_report,
    format_crysis3_audit_report,
    metadata_to_udp_lines,
    metadata_value_matches,
    parse_metadata_text,
    serialize_metadata,
)
from .crysis2_tools import (
    CRYSIS1,
    CRYSIS2,
    CRYSIS3,
    CRYTOOLS_PROFILES,
    CRYSIS2_EXPORT_OPTIONS_KEY,
    CRYSIS2_OBJECT_PROPERTIES_KEY,
    CRYSIS2_PHYSICALIZE_KEY,
    PHYSICALIZE_LABELS,
    cryexport_node_name_from_filename,
    detect_crysis1_lod_level,
    export_filename_stem,
    format_export_options,
    get_crytools_profile,
    is_crysis1_piece_child,
    is_cryexport_node_name,
    is_excluded_node_name,
    is_valid_export_filename,
    parse_property_rows,
    shape_key_summary,
    skin_validation_summary,
    suggest_crysis1_lod_name,
    summarize_material_ids,
    validate_pieces_references,
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


def _selected_crytools_profile(props):
    return get_crytools_profile(getattr(props, "crytools_target_profile", CRYSIS2))


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


# ==================================================== Crysis 3 tools panel


class VIEW3D_PT_cryblend_crysis3_tools(Panel):
    bl_idname = "VIEW3D_PT_cryblend_crysis3_tools"
    bl_label = "Crysis 3 Tools"
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
        props = context.scene.cryblend_panel_props
        profile = _selected_crytools_profile(props)
        selected = list(context.selected_objects or [])

        layout.prop(props, "crytools_target_profile", text="Target")
        layout.label(text=f"Selected: {len(selected)}", icon="RESTRICT_SELECT_OFF")
        active = context.active_object
        if active is not None:
            metadata = parse_metadata_text(active.get(CRYSIS3_METADATA_KEY, ""))
            udp_lines = metadata_to_udp_lines(metadata)
            box = layout.box()
            box.label(text=f"Active: {active.name}", icon="OBJECT_DATA")
            if udp_lines:
                for line in udp_lines[:8]:
                    box.label(text=line)
                if len(udp_lines) > 8:
                    box.label(text=f"... and {len(udp_lines) - 8} more")
            else:
                box.label(text="No Crysis 3 metadata tags.", icon="INFO")

        col = layout.column(align=True)
        col.label(text="Physics Metadata:")
        row = col.row(align=True)
        row.prop(props, "c3_use_mass", text="Mass")
        mass = row.row(align=True)
        mass.enabled = props.c3_use_mass
        mass.prop(props, "c3_mass", text="")
        row = col.row(align=True)
        row.prop(props, "c3_use_density", text="Density")
        density = row.row(align=True)
        density.enabled = props.c3_use_density
        density.prop(props, "c3_density", text="")
        col.prop(props, "c3_primitive", text="Primitive")

        col = layout.column(align=True)
        col.label(text="Joint Properties:")
        col.prop(props, "c3_use_joint", text="Enable")
        joint = col.column(align=True)
        joint.enabled = props.c3_use_joint
        joint.prop(props, "c3_joint_limit", text="Limit")
        joint.prop(props, "c3_joint_twist", text="Twist")
        joint.prop(props, "c3_joint_bend", text="Bend")
        joint.prop(props, "c3_joint_pull", text="Pull")
        joint.prop(props, "c3_joint_push", text="Push")
        joint.prop(props, "c3_joint_shift", text="Shift")

        col = layout.column(align=True)
        col.label(text="Destroyable Objects:")
        col.prop(props, "c3_object_role", text="Role")
        col.prop(props, "c3_entity", text="Entity")
        col.prop(props, "c3_rotaxes", text="Rot Axes")
        col.prop(props, "c3_sizevar", text="Size Var")
        col.prop(props, "c3_generic", text="Generic")
        layout.operator(
            "cryblend.apply_c3_metadata",
            text="Apply Metadata to Selected",
            icon="PROPERTIES",
        )

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Select Matching Metadata:")
        row = col.row(align=True)
        row.prop(props, "c3_match_key", text="")
        row.prop(props, "c3_match_comparator", text="")
        row.prop(props, "c3_match_value", text="")
        layout.operator(
            "cryblend.select_c3_metadata",
            text="Select Matches in Collection",
            icon="VIEWZOOM",
        )

        layout.separator()
        row = layout.row(align=True)
        row.operator(
            "cryblend.copy_c3_attachment_xml",
            text="Copy Attachment XML",
            icon="COPYDOWN",
        )
        row.operator(
            "cryblend.reset_camera_pivots",
            text="Reset Camera Pivots",
            icon="CAMERA_DATA",
        )

        layout.separator()
        layout.operator(
            "cryblend.audit_c3_asset",
            text=f"Audit {profile.display_label} Asset",
            icon="CHECKMARK",
        )
        report = props.c3_audit_report.strip()
        if report:
            box = layout.box()
            for line in report.splitlines()[:8]:
                icon = "ERROR" if "[ERROR]" in line else "INFO"
                box.label(text=line[:120], icon=icon)
            if len(report.splitlines()) > 8:
                box.label(text="Full report copied to clipboard.", icon="COPYDOWN")


# ==================================================== Crysis 2 tools panel


class VIEW3D_PT_cryblend_crysis2_tools(Panel):
    bl_idname = "VIEW3D_PT_cryblend_crysis2_tools"
    bl_label = "Crysis 2 Tools"
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
        props = context.scene.cryblend_panel_props
        profile = _selected_crytools_profile(props)
        coll = _active_collection(context)
        objects = list(getattr(coll, "all_objects", coll.objects))
        names = [obj.name for obj in objects]

        layout.prop(props, "crytools_target_profile", text="Target")
        layout.label(text=f"Skin limit: {profile.max_skin_influences} influences", icon="MOD_ARMATURE")

        materials = _materials_in_collection(coll)
        mat_summary = summarize_material_ids([mat.name for mat in materials])
        box = layout.box()
        box.label(text=f"Material IDs: {len(materials)}", icon="MATERIAL")
        if mat_summary.missing_ids:
            box.label(text=f"Missing ID names: {len(mat_summary.missing_ids)}", icon="ERROR")
        if mat_summary.out_of_range:
            box.label(text=f"Outside 0-31: {len(mat_summary.out_of_range)}", icon="ERROR")
        if mat_summary.duplicate_ids:
            box.label(text="Duplicate IDs: " + ", ".join(map(str, mat_summary.duplicate_ids)), icon="ERROR")
        if mat_summary.holes:
            box.label(text="ID holes: " + ", ".join(map(str, mat_summary.holes[:12])), icon="INFO")
        if not any((mat_summary.missing_ids, mat_summary.out_of_range, mat_summary.duplicate_ids, mat_summary.holes)):
            box.label(text="Material ID layout is contiguous and in range.", icon="CHECKMARK")
        row = box.row(align=True)
        row.prop(props, "c2_physicalize", text="Physicalize")
        row.operator("cryblend.apply_c2_material_physicalize", text="", icon="CHECKMARK")

        layout.separator()
        box = layout.box()
        box.label(text="CryExport Node", icon="OUTLINER_OB_EMPTY")
        box.prop(props, "c2_export_filename", text="Filename")
        stem = export_filename_stem(props.c2_export_filename)
        icon = "CHECKMARK" if is_valid_export_filename(stem) else "ERROR"
        box.label(text=f"Stem: {stem or '(empty)'}", icon=icon)
        export_nodes = [obj.name for obj in objects if is_cryexport_node_name(obj.name, profile=profile)]
        export_nodes.extend(
            child.name for child in getattr(coll, "children", []) if is_cryexport_node_name(child.name, profile=profile)
        )
        if export_nodes:
            box.label(text="Nodes: " + ", ".join(export_nodes[:3]))
        else:
            box.label(text=f"No {profile.display_label} export marker found.", icon="INFO")
        box.operator("cryblend.create_c2_export_node", text="Create/Update Export Node", icon="EMPTY_AXIS")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Object Properties:")
        col.prop(props, "c2_do_not_merge", text="DoNotMerge")
        col.prop(props, "c2_object_properties", text="Rows")
        selected = list(context.selected_objects or [])
        pieces = validate_pieces_references(props.c2_object_properties, names, profile=profile)
        if pieces.missing:
            col.label(text="Missing pieces: " + ", ".join(pieces.missing[:4]), icon="ERROR")
        if profile.key == CRYSIS1:
            lod_names = [obj.name for obj in objects if detect_crysis1_lod_level(obj.name)]
            piece_names = [obj.name for obj in objects if is_crysis1_piece_child(obj.name)]
            if lod_names:
                col.label(text=f"Legacy LOD markers: {len(lod_names)}", icon="INFO")
                col.label(text=suggest_crysis1_lod_name(lod_names[0])[:120])
            if piece_names:
                col.label(text=f"Breakable -piece children: {len(piece_names)}", icon="INFO")
        excluded = [obj.name for obj in objects if is_excluded_node_name(obj.name)]
        if excluded:
            col.label(text=f"Excluded by _: {len(excluded)}", icon="INFO")
        col.operator("cryblend.apply_c2_object_properties", text=f"Apply to Selected ({len(selected)})", icon="PROPERTIES")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Animation Export Options:")
        col.prop(props, "c2_animation_sample_step", text="Sample Step")
        col.prop(props, "c2_key_optimization", text="Key Optimization")
        col.prop(props, "c2_rotation_precision", text="Rotation Precision")
        col.prop(props, "c2_position_precision", text="Position Precision")
        col.prop(props, "c2_manual_range", text="Manual Range")
        range_col = col.column(align=True)
        range_col.enabled = props.c2_manual_range
        row = range_col.row(align=True)
        row.prop(props, "c2_manual_range_start", text="Start")
        row.prop(props, "c2_manual_range_end", text="End")
        col.operator("cryblend.apply_c2_export_options", text="Store Options on Collection", icon="OPTIONS")

        layout.separator()
        skin_box = layout.box()
        skin_box.label(text="Skin & Morph Validation", icon="ARMATURE_DATA")
        for line in _c2_skin_report(coll, profile=profile)[:6]:
            skin_box.label(text=line)
        morph_lines = _c2_shape_key_report(coll)
        for line in morph_lines[:5]:
            skin_box.label(text=line)
        skin_box.operator("cryblend.copy_c2_shape_report", text="Copy Shape-Key Report", icon="COPYDOWN")


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


class CRYBLEND_OT_apply_c3_metadata(Operator):
    """Apply Crysis 3 CGF metadata tags to selected objects."""

    bl_idname = "cryblend.apply_c3_metadata"
    bl_label = "Apply Crysis 3 Metadata"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.cryblend_panel_props
        targets = list(context.selected_objects or [])
        if not targets:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}

        settings = {
            "use_mass": props.c3_use_mass,
            "mass": props.c3_mass,
            "use_density": props.c3_use_density,
            "density": props.c3_density,
            "primitive": props.c3_primitive,
            "use_joint": props.c3_use_joint,
            "limit": props.c3_joint_limit,
            "twist": props.c3_joint_twist,
            "bend": props.c3_joint_bend,
            "pull": props.c3_joint_pull,
            "push": props.c3_joint_push,
            "shift": props.c3_joint_shift,
            "entity": props.c3_entity,
            "rotaxes": props.c3_rotaxes,
            "sizevar": props.c3_sizevar,
            "generic": props.c3_generic,
        }
        for obj in targets:
            metadata = apply_crysis3_settings(
                obj.get(CRYSIS3_METADATA_KEY, ""),
                settings,
            )
            obj[CRYSIS3_METADATA_KEY] = serialize_metadata(metadata)
            if props.c3_object_role == "MAIN":
                obj.name = "Main"
            elif props.c3_object_role == "REMAIN":
                obj.name = "Remain"
        self.report({"INFO"}, f"Applied Crysis 3 metadata to {len(targets)} object(s).")
        return {"FINISHED"}


class CRYBLEND_OT_select_c3_metadata(Operator):
    """Select objects whose Crysis 3 metadata matches a numeric test."""

    bl_idname = "cryblend.select_c3_metadata"
    bl_label = "Select Crysis 3 Metadata Matches"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = _active_collection(context)
        if coll is None:
            self.report({"ERROR"}, "No active CryBlend collection")
            return {"CANCELLED"}
        props = context.scene.cryblend_panel_props
        matches = []
        for obj in coll.all_objects:
            if metadata_value_matches(
                obj.get(CRYSIS3_METADATA_KEY, ""),
                props.c3_match_key,
                props.c3_match_comparator,
                props.c3_match_value,
            ):
                matches.append(obj)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in matches:
            obj.select_set(True)
        if matches:
            context.view_layer.objects.active = matches[0]
        self.report({"INFO"}, f"Selected {len(matches)} matching object(s).")
        return {"FINISHED"}


class CRYBLEND_OT_copy_c3_attachment_xml(Operator):
    """Copy CryEngine attachment-helper XML for selected objects."""

    bl_idname = "cryblend.copy_c3_attachment_xml"
    bl_label = "Copy Crysis 3 Attachment XML"
    bl_options = {"REGISTER"}

    def execute(self, context):
        targets = list(context.selected_objects or [])
        if not targets:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}
        lines = ["======== Begin Attachment Helpers ========"]
        for obj in targets:
            quat = obj.rotation_euler.to_quaternion()
            lines.append(
                format_attachment_xml(
                    obj.name,
                    tuple(obj.location),
                    (quat.w, quat.x, quat.y, quat.z),
                )
            )
        lines.append("======== End Attachment Helpers ========")
        context.window_manager.clipboard = "\n".join(lines)
        self.report({"INFO"}, f"Copied {len(targets)} attachment helper(s).")
        return {"FINISHED"}


def _c3_material_value(material, *keys: str):
    for key in keys:
        try:
            value = material.get(key)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return None


def _c3_degenerate_face_count(mesh) -> int:
    count = 0
    for polygon in getattr(mesh, "polygons", ()):  # pragma: no branch - Blender data
        vertices = tuple(getattr(polygon, "vertices", ()))
        area = float(getattr(polygon, "area", 1.0) or 0.0)
        if len(set(vertices)) < 3 or area <= 1.0e-10:
            count += 1
    return count


def _c3_weight_stats(obj, *, max_skin_influences: int = 8) -> tuple[bool, int, int]:
    bad_totals = 0
    too_many = 0
    weighted = False
    data = getattr(obj, "data", None)
    for vertex in getattr(data, "vertices", ()):  # pragma: no branch - Blender data
        weights = [g.weight for g in getattr(vertex, "groups", ()) if g.weight > 0.0]
        if not weights:
            continue
        weighted = True
        if abs(sum(weights) - 1.0) > 0.001:
            bad_totals += 1
        if len(weights) > max_skin_influences:
            too_many += 1
    return weighted, bad_totals, too_many


def _c3_descendants(obj, children_by_parent: dict[int, list]) -> list:
    out = []
    stack = list(children_by_parent.get(id(obj), ()))
    while stack:
        child = stack.pop()
        out.append(child)
        stack.extend(children_by_parent.get(id(child), ()))
    return out


def _collect_c3_audit_records(
    context,
    coll,
    *,
    profile=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target = get_crytools_profile(profile or CRYSIS3)
    objects = list(getattr(coll, "all_objects", coll.objects))
    children_by_parent: dict[int, list] = {}
    for obj in objects:
        parent = getattr(obj, "parent", None)
        if parent is not None:
            children_by_parent.setdefault(id(parent), []).append(obj)

    records: list[dict[str, Any]] = []
    for obj in objects:
        data = getattr(obj, "data", None)
        weighted, bad_totals, too_many = _c3_weight_stats(
            obj,
            max_skin_influences=target.max_skin_influences,
        )
        descendants = _c3_descendants(obj, children_by_parent)
        has_armature = any(getattr(mod, "type", "") == "ARMATURE" for mod in obj.modifiers)
        records.append(
            {
                "name": obj.name,
                "type": obj.type,
                "export_type": obj.get("cryblend_c3_export_type", obj.get("c3_export_type", "")),
                "filename": obj.get("cryblend_c3_filename", obj.get("c3_filename", "")),
                "child_count": len(children_by_parent.get(id(obj), ())),
                "vertices": len(getattr(data, "vertices", ())),
                "faces": len(getattr(data, "polygons", ())),
                "uv_layers": len(getattr(data, "uv_layers", ())),
                "color_sets": len(getattr(data, "color_attributes", getattr(data, "vertex_colors", ()))),
                "degenerate_faces": _c3_degenerate_face_count(data) if data else 0,
                "vertices_without_uv": len(getattr(data, "vertices", ())) if data and not getattr(data, "uv_layers", ()) else 0,
                "scale": tuple(obj.scale),
                "is_skinned": weighted,
                "has_armature": has_armature,
                "has_skeleton": any(
                    child.type == "ARMATURE"
                    or any(getattr(mod, "type", "") == "ARMATURE" for mod in child.modifiers)
                    for child in descendants
                ),
                "bad_weight_totals": bad_totals,
                "too_many_influences": too_many,
            }
        )

    material_records = []
    for material in _materials_in_collection(coll):
        material_records.append(
            {
                "name": material.name,
                "material_id": _c3_material_value(
                    material,
                    "MaterialID",
                    "material_id",
                    "cryMaterialID",
                    "cryblend_material_id",
                ),
                "physicalize": _c3_material_value(
                    material,
                    "physicalize",
                    "Physicalize",
                    CRYSIS2_PHYSICALIZE_KEY,
                ),
            }
        )
    return records, material_records


class CRYBLEND_OT_audit_c3_asset(Operator):
    """Run Crysis 3 asset checks inspired by Max/Maya/XSI CryTools."""

    bl_idname = "cryblend.audit_c3_asset"
    bl_label = "Audit Crysis 3 Asset"
    bl_options = {"REGISTER"}

    def execute(self, context):
        coll = _active_collection(context)
        if coll is None:
            self.report({"ERROR"}, "No active CryBlend collection")
            return {"CANCELLED"}

        props = context.scene.cryblend_panel_props
        profile = _selected_crytools_profile(props)
        object_records, material_records = _collect_c3_audit_records(
            context,
            coll,
            profile=profile,
        )
        render = context.scene.render
        fps = float(render.fps) / float(render.fps_base or 1.0)
        issues = audit_crytools_asset(
            object_records,
            material_records,
            profile=profile,
            fps=fps,
            unit_system=context.scene.unit_settings.system,
        )
        report = format_crytools_audit_report(issues, profile=profile)
        props.c3_audit_report = report
        context.window_manager.clipboard = report
        errors = sum(1 for issue in issues if issue.severity == "error")
        warnings = sum(1 for issue in issues if issue.severity == "warning")
        self.report(
            {"ERROR" if errors else "WARNING" if warnings else "INFO"},
            f"{profile.display_label} audit: {errors} error(s), {warnings} warning(s). Report copied.",
        )
        return {"FINISHED"}


class CRYBLEND_OT_reset_camera_pivots(Operator):
    """Reset camera data offsets on selected cameras, or all cameras."""

    bl_idname = "cryblend.reset_camera_pivots"
    bl_label = "Reset Camera Pivots"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = [obj for obj in context.selected_objects if obj.type == "CAMERA"]
        cameras = selected or [obj for obj in bpy.data.objects if obj.type == "CAMERA"]
        for obj in cameras:
            data = obj.data
            data.shift_x = 0.0
            data.shift_y = 0.0
        self.report({"INFO"}, f"Reset {len(cameras)} camera pivot offset(s).")
        return {"FINISHED"}


class CRYBLEND_OT_apply_c2_material_physicalize(Operator):
    """Store a Crysis 2 physicalization label on the active material."""

    bl_idname = "cryblend.apply_c2_material_physicalize"
    bl_label = "Apply Crysis 2 Physicalize Label"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        mat = obj.active_material if obj else None
        if mat is None:
            self.report({"ERROR"}, "No active material")
            return {"CANCELLED"}
        mat[CRYSIS2_PHYSICALIZE_KEY] = context.scene.cryblend_panel_props.c2_physicalize
        self.report({"INFO"}, f"Stored Crysis 2 physicalize label on {mat.name}.")
        return {"FINISHED"}


class CRYBLEND_OT_create_c2_export_node(Operator):
    """Create or update a CryExportNode marker for the active collection."""

    bl_idname = "cryblend.create_c2_export_node"
    bl_label = "Create Crysis 2 Export Node"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = _active_collection(context)
        if coll is None:
            self.report({"ERROR"}, "No active CryBlend collection")
            return {"CANCELLED"}
        props = context.scene.cryblend_panel_props
        profile = _selected_crytools_profile(props)
        stem = export_filename_stem(props.c2_export_filename) or coll.name
        if not is_valid_export_filename(stem):
            self.report({"ERROR"}, "Export filename must use letters, numbers, and underscores")
            return {"CANCELLED"}
        node_name = cryexport_node_name_from_filename(stem, profile=profile)
        active = context.active_object
        if active is not None and active.type == "EMPTY" and active.name in {obj.name for obj in coll.all_objects}:
            active.name = node_name
            active[CRYSIS2_EXPORT_OPTIONS_KEY] = _c2_export_options_text(props)
            target = active
        else:
            target = bpy.data.objects.new(node_name, None)
            target.empty_display_type = "CUBE"
            target.empty_display_size = 1.0
            coll.objects.link(target)
            target[CRYSIS2_EXPORT_OPTIONS_KEY] = _c2_export_options_text(props)
        self.report({"INFO"}, f"Tagged {target.name} as a {profile.display_label} export node.")
        return {"FINISHED"}


class CRYBLEND_OT_apply_c2_object_properties(Operator):
    """Apply portable Crysis 2 object-property rows to selected objects."""

    bl_idname = "cryblend.apply_c2_object_properties"
    bl_label = "Apply Crysis 2 Object Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        targets = list(context.selected_objects or [])
        if not targets:
            self.report({"ERROR"}, "No objects selected")
            return {"CANCELLED"}
        props = context.scene.cryblend_panel_props
        rows = parse_property_rows(props.c2_object_properties)
        if props.c2_do_not_merge:
            rows["DoNotMerge"] = "true"
        text = "\n".join(
            key if value == "true" else f"{key}={value}"
            for key, value in rows.items()
        )
        for obj in targets:
            obj[CRYSIS2_OBJECT_PROPERTIES_KEY] = text
        self.report({"INFO"}, f"Applied Crysis 2 properties to {len(targets)} object(s).")
        return {"FINISHED"}


class CRYBLEND_OT_apply_c2_export_options(Operator):
    """Store Crysis 2 animation/export option metadata on the collection."""

    bl_idname = "cryblend.apply_c2_export_options"
    bl_label = "Store Crysis 2 Export Options"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = _active_collection(context)
        if coll is None:
            self.report({"ERROR"}, "No active CryBlend collection")
            return {"CANCELLED"}
        coll[CRYSIS2_EXPORT_OPTIONS_KEY] = _c2_export_options_text(context.scene.cryblend_panel_props)
        self.report({"INFO"}, "Stored Crysis 2 export options on the collection.")
        return {"FINISHED"}


class CRYBLEND_OT_copy_c2_shape_report(Operator):
    """Copy the Crysis 2 shape-key report for the active collection."""

    bl_idname = "cryblend.copy_c2_shape_report"
    bl_label = "Copy Crysis 2 Shape-Key Report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        coll = _active_collection(context)
        if coll is None:
            self.report({"ERROR"}, "No active CryBlend collection")
            return {"CANCELLED"}
        lines = _c2_shape_key_report(coll)
        context.window_manager.clipboard = "\n".join(lines)
        self.report({"INFO"}, f"Copied {len(lines)} Crysis 2 shape-key report line(s).")
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


def _c2_export_options_text(props) -> str:
    options = {
        "animationSampleStep": props.c2_animation_sample_step,
        "enableKeyOptimization": props.c2_key_optimization,
        "rotationPrecision": props.c2_rotation_precision,
        "positionPrecision": props.c2_position_precision,
        "enableManualRange": props.c2_manual_range,
        "manualRangeStart": props.c2_manual_range_start,
        "manualRangeEnd": props.c2_manual_range_end,
    }
    return format_export_options(options)


def _c2_skin_report(coll, *, profile=None) -> list[str]:
    target = get_crytools_profile(profile or CRYSIS2)
    meshes = [obj for obj in coll.all_objects if obj.type == "MESH"]
    meshes_without_armature = 0
    missing_armatures = 0
    unweighted_vertices = 0
    non_normalized_vertices = 0
    too_many_influences = 0
    skeleton_roots: set[str] = set()

    for obj in meshes:
        armature_mods = [mod for mod in getattr(obj, "modifiers", []) if mod.type == "ARMATURE"]
        if not armature_mods:
            meshes_without_armature += 1
        for mod in armature_mods:
            armature = getattr(mod, "object", None)
            if armature is None:
                missing_armatures += 1
            elif getattr(armature, "type", "") == "ARMATURE":
                roots = [bone.name for bone in armature.data.bones if bone.parent is None]
                skeleton_roots.update(roots)

        vertex_groups = list(getattr(obj, "vertex_groups", []))
        group_names = {group.index: group.name for group in vertex_groups}
        if not group_names:
            unweighted_vertices += len(getattr(obj.data, "vertices", []))
            continue
        for vertex in getattr(obj.data, "vertices", []):
            weights = [group.weight for group in vertex.groups if group.group in group_names]
            total = sum(weights)
            if total == 0.0:
                unweighted_vertices += 1
            elif abs(total - 1.0) > 0.01:
                non_normalized_vertices += 1
            if len([weight for weight in weights if weight > 0.0]) > target.max_skin_influences:
                too_many_influences += 1

    lines = skin_validation_summary(
        mesh_count=len(meshes),
        meshes_without_armature=meshes_without_armature,
        missing_armature_objects=missing_armatures,
        unweighted_vertices=unweighted_vertices,
        non_normalized_vertices=non_normalized_vertices,
        skeleton_roots=sorted(skeleton_roots),
    )
    if too_many_influences:
        lines.append(
            f"Vertices over {target.max_skin_influences} influences: {too_many_influences}"
        )
    return lines


def _c2_shape_key_report(coll) -> list[str]:
    lines: list[str] = []
    for obj in coll.all_objects:
        if obj.type != "MESH":
            continue
        shape_keys = getattr(obj.data, "shape_keys", None)
        if shape_keys is None:
            continue
        keys = list(getattr(shape_keys, "key_blocks", []))
        if not keys:
            continue
        muted_or_zero = [
            key.name
            for key in keys
            if key.name != "Basis"
            and (getattr(key, "mute", False) or getattr(key, "value", 0.0) == 0.0)
        ]
        lines.extend(shape_key_summary(obj.name, [key.name for key in keys], muted_or_zero))
    return lines or ["No shape keys found."]


# ============================================================ scene props


class CryBlendPanelProps(bpy.types.PropertyGroup):
    crytools_target_profile: EnumProperty(  # type: ignore[valid-type]
        name="Target",
        items=tuple(
            (key, profile.display_label, profile.rc_note)
            for key, profile in CRYTOOLS_PROFILES.items()
        ),
        default=CRYSIS2,
    )
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
    c3_use_mass: BoolProperty(name="Mass", default=False)  # type: ignore[valid-type]
    c3_mass: FloatProperty(name="Mass", default=0.0, min=0.0)  # type: ignore[valid-type]
    c3_use_density: BoolProperty(name="Density", default=False)  # type: ignore[valid-type]
    c3_density: FloatProperty(name="Density", default=0.0, min=0.0)  # type: ignore[valid-type]
    c3_primitive: EnumProperty(  # type: ignore[valid-type]
        name="Primitive",
        items=(
            ("NONE", "None", ""),
            ("BOX", "Box", ""),
            ("CYLINDER", "Cylinder", ""),
            ("SPHERE", "Sphere", ""),
            ("CAPSULE", "Capsule", ""),
        ),
        default="NONE",
    )
    c3_use_joint: BoolProperty(name="Joint", default=False)  # type: ignore[valid-type]
    c3_joint_limit: FloatProperty(name="Limit", default=0.0)  # type: ignore[valid-type]
    c3_joint_twist: FloatProperty(name="Twist", default=0.0)  # type: ignore[valid-type]
    c3_joint_bend: FloatProperty(name="Bend", default=0.0)  # type: ignore[valid-type]
    c3_joint_pull: FloatProperty(name="Pull", default=0.0)  # type: ignore[valid-type]
    c3_joint_push: FloatProperty(name="Push", default=0.0)  # type: ignore[valid-type]
    c3_joint_shift: FloatProperty(name="Shift", default=0.0)  # type: ignore[valid-type]
    c3_object_role: EnumProperty(  # type: ignore[valid-type]
        name="Role",
        items=(
            ("UNCHANGED", "Unchanged", ""),
            ("MAIN", "Main", ""),
            ("REMAIN", "Remain", ""),
        ),
        default="UNCHANGED",
    )
    c3_entity: BoolProperty(name="Entity", default=False)  # type: ignore[valid-type]
    c3_rotaxes: EnumProperty(  # type: ignore[valid-type]
        name="Rot Axes",
        items=(
            ("NONE", "None", ""),
            ("X", "X", ""),
            ("Y", "Y", ""),
            ("Z", "Z", ""),
            ("XY", "XY", ""),
            ("XZ", "XZ", ""),
            ("YZ", "YZ", ""),
            ("XYZ", "XYZ", ""),
        ),
        default="NONE",
    )
    c3_sizevar: FloatProperty(name="Size Var", default=0.0, min=0.0)  # type: ignore[valid-type]
    c3_generic: FloatProperty(name="Generic", default=0.0, min=0.0)  # type: ignore[valid-type]
    c3_match_key: EnumProperty(  # type: ignore[valid-type]
        name="Key",
        items=(
            ("mass", "mass", ""),
            ("density", "density", ""),
            ("limit", "limit", ""),
            ("twist", "twist", ""),
            ("bend", "bend", ""),
            ("pull", "pull", ""),
            ("push", "push", ""),
            ("shift", "shift", ""),
            ("sizevar", "sizevar", ""),
            ("generic", "generic", ""),
        ),
        default="mass",
    )
    c3_match_comparator: EnumProperty(  # type: ignore[valid-type]
        name="Compare",
        items=(("=", "=", ""), (">", ">", ""), ("<", "<", "")),
        default="=",
    )
    c3_match_value: FloatProperty(name="Value", default=0.0)  # type: ignore[valid-type]
    c3_audit_report: StringProperty(name="Audit Report", default="")  # type: ignore[valid-type]
    c2_export_filename: StringProperty(name="Filename", default="export_node.cgf")  # type: ignore[valid-type]
    c2_physicalize: EnumProperty(  # type: ignore[valid-type]
        name="Physicalize",
        items=tuple((label, label, "") for label in PHYSICALIZE_LABELS),
        default="Default",
    )
    c2_do_not_merge: BoolProperty(name="DoNotMerge", default=False)  # type: ignore[valid-type]
    c2_object_properties: StringProperty(name="Object Properties", default="")  # type: ignore[valid-type]
    c2_animation_sample_step: FloatProperty(name="Sample Step", default=1.0, min=0.001)  # type: ignore[valid-type]
    c2_key_optimization: BoolProperty(name="Key Optimization", default=True)  # type: ignore[valid-type]
    c2_rotation_precision: FloatProperty(name="Rotation Precision", default=0.01, min=0.0)  # type: ignore[valid-type]
    c2_position_precision: FloatProperty(name="Position Precision", default=0.01, min=0.0)  # type: ignore[valid-type]
    c2_manual_range: BoolProperty(name="Manual Range", default=False)  # type: ignore[valid-type]
    c2_manual_range_start: IntProperty(name="Start", default=0)  # type: ignore[valid-type]
    c2_manual_range_end: IntProperty(name="End", default=0)  # type: ignore[valid-type]


# ============================================================ register


_classes: tuple = (
    CryBlendPanelProps,
    VIEW3D_PT_cryblend,
    VIEW3D_PT_cryblend_general,
    VIEW3D_PT_cryblend_materials,
    VIEW3D_PT_cryblend_tints,
    VIEW3D_PT_cryblend_textures,
    VIEW3D_PT_cryblend_physics,
    VIEW3D_PT_cryblend_crysis2_tools,
    VIEW3D_PT_cryblend_crysis3_tools,
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
    CRYBLEND_OT_apply_c3_metadata,
    CRYBLEND_OT_select_c3_metadata,
    CRYBLEND_OT_copy_c3_attachment_xml,
    CRYBLEND_OT_audit_c3_asset,
    CRYBLEND_OT_reset_camera_pivots,
    CRYBLEND_OT_apply_c2_material_physicalize,
    CRYBLEND_OT_create_c2_export_node,
    CRYBLEND_OT_apply_c2_object_properties,
    CRYBLEND_OT_apply_c2_export_options,
    CRYBLEND_OT_copy_c2_shape_report,
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
