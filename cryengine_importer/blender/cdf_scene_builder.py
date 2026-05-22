"""Blender bridge for CryEngine Character Definition (`.cdf`) files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]
from mathutils import Matrix, Quaternion, Vector  # type: ignore[import-not-found]

from ..core.cdf_assembly import (
    CdfAssemblyPlan,
    CdfAttachmentPlan,
    build_cdf_assembly_plan,
)
from ..core.cdf_loader import load_cdf
from ..core.cryengine import CryEngine
from ..models.cdf import CdfAttachment, CdfDefinition
from .import_visibility import set_imported_object_visibility
from .scene_builder import SceneBuildResult, build_scene_result

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem


@dataclass
class CdfBuiltAttachment:
    plan: CdfAttachmentPlan
    collection: "bpy.types.Collection | None" = None
    objects: list["bpy.types.Object"] = field(default_factory=list)
    asset: CryEngine | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CdfBuildResult:
    collection: "bpy.types.Collection"
    definition: CdfDefinition
    plan: CdfAssemblyPlan
    base_asset: CryEngine | None = None
    base_scene: SceneBuildResult | None = None
    attachments: list[CdfBuiltAttachment] = field(default_factory=list)
    material_library_files: list[str] = field(default_factory=list)
    material_library_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_cdf_scene(
    cdf_path: str,
    pack_fs: "IPackFileSystem",
    *,
    collection: "bpy.types.Collection | None" = None,
    object_dir: str | None = None,
    load_related: bool = True,
    global_matrix: Matrix | None = None,
    visibility_mode: str = "auto",
) -> CdfBuildResult:
    """Build the CDF base model and attachments into Blender."""
    definition = load_cdf(cdf_path, pack_fs)
    if definition is None:
        raise FileNotFoundError(cdf_path)

    plan = build_cdf_assembly_plan(
        definition,
        pack_fs,
        cdf_path=cdf_path,
        visibility_mode=visibility_mode,
    )
    if collection is None:
        name = PurePosixPath(cdf_path).stem.lower()
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)

    result = CdfBuildResult(
        collection=collection,
        definition=definition,
        plan=plan,
        warnings=list(plan.warnings),
    )

    if plan.model_path is None:
        return result

    base_collection = _new_child_collection(collection, "base")
    base_asset = _load_asset(
        plan.model_path,
        pack_fs,
        material=plan.model_material,
        object_dir=object_dir,
        load_related=load_related,
        load_animations=True,
    )
    base_scene = build_scene_result(base_asset, collection=base_collection)
    result.base_asset = base_asset
    result.base_scene = base_scene
    _record_materials(result, base_asset)

    for attachment_plan in plan.attachments:
        built = _build_attachment(
            attachment_plan,
            result,
            pack_fs,
            object_dir=object_dir,
            load_related=load_related,
        )
        result.attachments.append(built)

    if global_matrix is not None:
        _apply_global_matrix(collection, global_matrix)

    return result


def _build_attachment(
    attachment_plan: CdfAttachmentPlan,
    result: CdfBuildResult,
    pack_fs: "IPackFileSystem",
    *,
    object_dir: str | None,
    load_related: bool,
) -> CdfBuiltAttachment:
    attachment = attachment_plan.attachment
    built = CdfBuiltAttachment(
        plan=attachment_plan,
        warnings=list(attachment_plan.warnings),
    )

    if attachment_plan.status == "empty":
        built.objects.extend(_create_empty_attachment(result, attachment_plan))
        return built
    if attachment_plan.status != "bound" or attachment_plan.resolved_binding is None:
        return built

    coll_name = attachment.name or PurePosixPath(attachment_plan.resolved_binding).stem
    att_collection = _new_child_collection(result.collection, coll_name)
    built.collection = att_collection

    try:
        asset = _load_asset(
            attachment_plan.resolved_binding,
            pack_fs,
            material=attachment_plan.material,
            object_dir=object_dir,
            load_related=load_related,
            load_animations=False,
        )
    except Exception as exc:
        built.warnings.append(f"Failed to load attachment {attachment.name}: {exc}")
        return built

    built.asset = asset
    base_armature = result.base_scene.armature_obj if result.base_scene else None
    reuse_base_armature = attachment.type == "CA_SKIN" and base_armature is not None
    scene = build_scene_result(
        asset,
        collection=att_collection,
        existing_armature_obj=base_armature if reuse_base_armature else None,
        build_armature_enabled=not reuse_base_armature,
        build_actions_enabled=not reuse_base_armature,
        build_rigid_bodies_enabled=not reuse_base_armature,
    )
    built.objects.extend(_iter_collection_objects(att_collection))
    _record_materials(result, asset)

    if attachment.type == "CA_BONE":
        roots = [obj for obj in _iter_collection_objects(att_collection) if obj.parent is None]
        for obj in roots:
            warning = _parent_to_bone_or_apply_transform(obj, base_armature, attachment)
            if warning:
                built.warnings.append(warning)
    elif attachment.type == "CA_SKIN" and base_armature is None and scene.armature_obj is None:
        built.warnings.append(
            f"CA_SKIN attachment {attachment.name!r} has no armature to bind to"
        )

    _stamp_attachment_objects(built.objects, attachment_plan)
    _set_visible(built.objects, attachment_plan.visible)
    return built


def _create_empty_attachment(
    result: CdfBuildResult,
    attachment_plan: CdfAttachmentPlan,
) -> list["bpy.types.Object"]:
    attachment = attachment_plan.attachment
    name = attachment.name or "cdf_attachment"
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "ARROWS" if attachment.type == "CA_BONE" else "PLAIN_AXES"
    empty.empty_display_size = 0.1
    result.collection.objects.link(empty)
    base_armature = result.base_scene.armature_obj if result.base_scene else None
    warning = _parent_to_bone_or_apply_transform(empty, base_armature, attachment)
    if warning:
        result.warnings.append(warning)

    objects = [empty]
    if attachment.is_rope:
        objects.extend(_create_rope_helpers(result, attachment))
    _stamp_attachment_objects(objects, attachment_plan)
    _set_visible(objects, attachment_plan.visible)
    return objects


def _create_rope_helpers(
    result: CdfBuildResult,
    attachment: CdfAttachment,
) -> list["bpy.types.Object"]:
    armature = result.base_scene.armature_obj if result.base_scene else None
    if armature is None or not attachment.bone_name:
        return []

    bone_name = _safe_bone_name(attachment.bone_name)
    if bone_name not in armature.data.bones:
        return []

    prefix = attachment.bone_name.rsplit(" ", 1)[0]
    candidates = [
        b for b in armature.data.bones
        if b.name.replace("_", " ").startswith(prefix)
    ]
    if not candidates:
        candidates = [armature.data.bones[bone_name]]
    candidates.sort(key=lambda b: b.name)

    thickness = _rope_thickness(attachment)
    curve_data = bpy.data.curves.new((attachment.name or bone_name) + "_rope", "CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = thickness * 0.5
    curve_data.resolution_u = 1
    spline = curve_data.splines.new("POLY")
    spline.points.add(max(len(candidates) - 1, 0))
    for point, bone in zip(spline.points, candidates):
        head = armature.matrix_world @ bone.head_local
        point.co = (head.x, head.y, head.z, 1.0)
    curve_obj = bpy.data.objects.new((attachment.name or bone_name) + "_rope", curve_data)
    result.collection.objects.link(curve_obj)
    curve_obj["cryblend_cdf_rope"] = attachment.name or bone_name
    curve_obj["cryblend_cdf_rope_lods"] = str(attachment.rope_lods)
    return [curve_obj]


def _load_asset(
    path: str,
    pack_fs: "IPackFileSystem",
    *,
    material: str | None,
    object_dir: str | None,
    load_related: bool,
    load_animations: bool,
) -> CryEngine:
    asset = CryEngine(
        path,
        pack_fs,
        material_files=[material] if material else None,
        object_dir=object_dir,
        load_related=load_related,
        load_animations=load_animations,
    )
    asset.process()
    return asset


def _new_child_collection(
    parent: "bpy.types.Collection",
    name: str,
) -> "bpy.types.Collection":
    child = bpy.data.collections.new(name or "attachment")
    parent.children.link(child)
    return child


def _parent_to_bone_or_apply_transform(
    obj: "bpy.types.Object",
    armature: "bpy.types.Object | None",
    attachment: CdfAttachment,
) -> str | None:
    desired_world = _attachment_matrix(attachment)
    bone_name = _safe_bone_name(attachment.bone_name)
    warning = None
    if armature is not None and bone_name and bone_name in armature.data.bones:
        bone = armature.data.bones[bone_name]
        parent_world = (
            armature.matrix_world
            @ bone.matrix_local
            @ Matrix.Translation((0.0, bone.length, 0.0))
        )
        obj.parent = armature
        obj.parent_type = "BONE"
        obj.parent_bone = bone_name
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = parent_world.inverted() @ desired_world
    elif attachment.bone_name:
        warning = f"Attachment bone not found: {attachment.bone_name}"
        obj.matrix_world = desired_world
    else:
        obj.matrix_world = desired_world

    return warning


def _attachment_matrix(attachment: CdfAttachment) -> Matrix:
    rotation = Quaternion(attachment.rotation).normalized()
    return Matrix.Translation(Vector(attachment.position)) @ rotation.to_matrix().to_4x4()


def _safe_bone_name(raw: str) -> str:
    return raw.replace(" ", "_") if raw else ""


def _iter_collection_objects(
    collection: "bpy.types.Collection",
) -> list["bpy.types.Object"]:
    objects = list(collection.objects)
    for child in collection.children:
        objects.extend(_iter_collection_objects(child))
    return objects


def _set_visible(objects: list["bpy.types.Object"], visible: bool) -> None:
    for obj in objects:
        set_imported_object_visibility(
            obj,
            visible and not bool(obj.get("cryblend_cdf_rope")),
        )


def _stamp_attachment_objects(
    objects: list["bpy.types.Object"],
    attachment_plan: CdfAttachmentPlan,
) -> None:
    attachment = attachment_plan.attachment
    for obj in objects:
        obj["cryblend_cdf_attachment"] = attachment.name
        obj["cryblend_cdf_attachment_type"] = attachment.type
        obj["cryblend_cdf_attachment_flags"] = int(attachment.flags)
        obj["cryblend_cdf_attachment_visible"] = bool(attachment_plan.visible)


def _record_materials(result: CdfBuildResult, asset: CryEngine) -> None:
    for name in asset.material_library_files:
        if name not in result.material_library_files:
            result.material_library_files.append(name)
    for key in asset.materials.keys():
        if key not in result.material_library_keys:
            result.material_library_keys.append(key)


def _apply_global_matrix(
    collection: "bpy.types.Collection",
    global_matrix: Matrix,
) -> None:
    for obj in _iter_collection_objects(collection):
        if obj.parent is None:
            obj.matrix_world = global_matrix @ obj.matrix_world


def _rope_thickness(attachment: CdfAttachment) -> float:
    for level in sorted(attachment.rope_lods):
        value = attachment.rope_lods[level].get("Thickness")
        if value is None:
            continue
        try:
            return max(float(value), 0.001)
        except ValueError:
            continue
    return 0.01


__all__ = ["CdfBuildResult", "CdfBuiltAttachment", "build_cdf_scene"]