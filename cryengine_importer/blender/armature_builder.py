"""Build a Blender armature + vertex groups from a `SkinningInfo`.

This is the Phase 3 counterpart of `scene_builder.build_scene`. It is
called from the operator after the meshes are created; it doesn't
modify any existing meshes itself, only adds the armature object,
parent-with-armature on each skinned mesh, and per-bone vertex groups.

Bones are placed via their world-transform 4x4 (translation = head,
+Y axis = bone direction). The 0x801 variant of CompiledBones lacks a
world transform on disk; in that case we walk parent chains to derive
one from the local transforms (see `_world_matrix`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]
from mathutils import Matrix, Vector  # type: ignore[import-not-found]

from ..models.skinning import CompiledBone, SkinningInfo

if TYPE_CHECKING:
    from ..core.cryengine import CryEngine


# Default bone length when a leaf bone has no obvious tail target.
_DEFAULT_BONE_LENGTH = 0.05


def build_armature(
    cryengine: "CryEngine",
    *,
    collection: "bpy.types.Collection | None" = None,
    name: str | None = None,
) -> "bpy.types.Object | None":
    """Materialize ``cryengine.skinning_info`` as a Blender armature.

    Returns the armature Object, or ``None`` if no skinning info is
    present.
    """
    info = cryengine.skinning_info
    if not info.has_skinning_info:
        return None

    if collection is None:
        collection = bpy.context.scene.collection

    arm_data = bpy.data.armatures.new((name or cryengine.name) + "_armature")
    arm_obj = bpy.data.objects.new(name or cryengine.name, arm_data)
    collection.objects.link(arm_obj)

    # World matrix per CompiledBone — derived once before edit-mode.
    world_by_bone: dict[int, Matrix] = {
        id(b): _world_matrix(b) for b in info.compiled_bones
    }

    # Edit mode: create EditBones with head/tail/parent/matrix.
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        edit_bones = arm_data.edit_bones
        edit_by_index: list[bpy.types.EditBone] = []

        for bone in info.compiled_bones:
            eb = edit_bones.new(_safe_bone_name(bone.bone_name))
            eb.head = (0.0, 0.0, 0.0)
            eb.tail = (0.0, _DEFAULT_BONE_LENGTH, 0.0)
            world = world_by_bone[id(bone)]
            eb.matrix = world
            edit_by_index.append(eb)

        for bone, eb in zip(info.compiled_bones, edit_by_index):
            if bone.parent_bone is not None:
                parent_idx = info.compiled_bones.index(bone.parent_bone)
                eb.parent = edit_by_index[parent_idx]

        # Adjust tails so each bone points toward its (single) child for
        # nicer visualisation. Bones with multiple or no children keep
        # the default length along +Y.
        children: dict[int, list[int]] = {}
        for i, b in enumerate(info.compiled_bones):
            if b.parent_bone is not None:
                p = info.compiled_bones.index(b.parent_bone)
                children.setdefault(p, []).append(i)

        for i, eb in enumerate(edit_by_index):
            ch = children.get(i, [])
            if len(ch) == 1:
                child_head = edit_by_index[ch[0]].head
                if (child_head - eb.head).length > 1e-6:
                    eb.tail = child_head
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    return arm_obj


def attach_skin(
    arm_obj: "bpy.types.Object",
    mesh_obj: "bpy.types.Object",
    cryengine: "CryEngine",
) -> None:
    """Add an Armature modifier on ``mesh_obj`` and create vertex
    groups + weights from the int-skin-vertex / ext-to-int data."""
    info = cryengine.skinning_info
    if not info.has_skinning_info:
        return

    mesh_obj.parent = arm_obj
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True

    if not info.int_vertices:
        return

    bone_names = [_safe_bone_name(b.bone_name) for b in info.compiled_bones]
    groups: dict[int, bpy.types.VertexGroup] = {}

    def _ensure_group(bone_idx: int) -> "bpy.types.VertexGroup | None":
        if bone_idx < 0 or bone_idx >= len(bone_names):
            return None
        if bone_idx not in groups:
            groups[bone_idx] = mesh_obj.vertex_groups.new(name=bone_names[bone_idx])
        return groups[bone_idx]

    ext_map = info.ext_to_int_map
    int_verts = info.int_vertices
    num_ext = len(mesh_obj.data.vertices)

    for ext_idx in range(num_ext):
        if ext_map:
            if ext_idx >= len(ext_map):
                continue
            int_idx = ext_map[ext_idx]
        else:
            int_idx = ext_idx
        if int_idx < 0 or int_idx >= len(int_verts):
            continue

        bm = int_verts[int_idx].bone_mapping
        for bone_idx, weight in zip(bm.bone_index, bm.weight):
            if weight <= 0.0:
                continue
            grp = _ensure_group(bone_idx)
            if grp is None:
                continue
            grp.add([ext_idx], weight, "ADD")


# ---------------------------------------------------------------- helpers


def _safe_bone_name(raw: str) -> str:
    """Blender bone names cannot contain spaces in the most common
    reference files (the C# Collada renderer also strips them)."""
    return raw.replace(" ", "_") if raw else "bone"


def _world_matrix(bone: CompiledBone) -> "Matrix":
    """Return the bone's world-space 4x4 ``mathutils.Matrix``.

    For 0x800 the world transform is on disk. For 0x801 (and any case
    where the world matrix is identity), accumulate the local
    transforms by walking the parent chain.
    """
    rows = bone.world_transform_matrix
    if not _is_identity_3x4(rows):
        return _row_3x4_to_matrix4(rows)

    # Derive from local transforms.
    m = _row_3x4_to_matrix4(bone.local_transform_matrix)
    parent = bone.parent_bone
    while parent is not None:
        m = _row_3x4_to_matrix4(parent.local_transform_matrix) @ m
        parent = parent.parent_bone
    return m


def _row_3x4_to_matrix4(rows: tuple) -> "Matrix":
    """Convert ``((M11..M14), (M21..M24), (M31..M34))`` to a 4x4."""
    return Matrix(
        (
            (rows[0][0], rows[0][1], rows[0][2], rows[0][3]),
            (rows[1][0], rows[1][1], rows[1][2], rows[1][3]),
            (rows[2][0], rows[2][1], rows[2][2], rows[2][3]),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def _is_identity_3x4(rows: tuple) -> bool:
    expected = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    for r in range(3):
        for c in range(4):
            if abs(rows[r][c] - expected[r][c]) > 1e-6:
                return False
    return True


__all__ = ["build_armature", "attach_skin"]
