"""Skinning data classes — port of CgfConverter/Models/SkinningInfo.cs
and the CompiledBone / IntSkinVertex / TFace / PhysicalProxy structs.

Plain `dataclass`-based, bpy-free contracts shared between the chunk
readers and the (Phase 3) Blender armature builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ----------------------------------------------------------- bones --------


@dataclass
class CompiledBone:
    """Port of CgfConverter/Models/CompiledBone.cs.

    Skips the per-bone PhysicsGeometry payload (we don't render it),
    but keeps all transform / hierarchy fields.
    """

    controller_id: int = 0
    limb_id: int = 0
    bone_name: str = ""

    # Offsets in units of CompiledBone records (per the on-disk struct).
    offset_parent: int = 0
    offset_child: int = 0
    number_of_children: int = 0

    # Row-major 3x4 (3 rows of 4 floats), as parsed from disk.
    local_transform_matrix: tuple[tuple[float, ...], ...] = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    world_transform_matrix: tuple[tuple[float, ...], ...] = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    # Inverse of (worldQuat | worldTranslation), used by the IVO 0x900
    # / 0x901 readers. Defaults to identity for legacy 0x800 / 0x801.
    bind_pose_matrix: tuple[tuple[float, ...], ...] = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    # IVO-specific (0x900 / 0x901) hierarchy fields.
    parent_index: int = -1
    object_node_index: int = -1

    # Wired up after the chunk is read.
    parent_bone: Optional["CompiledBone"] = None
    parent_controller_index: int = 0
    child_ids: list[int] = field(default_factory=list)


# ----------------------------------------------------------- physical -----


@dataclass
class CompiledPhysicalBone:
    """Port of Models/Structs/Structs.cs#CompiledPhysicalBone."""

    bone_index: int = 0
    parent_offset: int = 0
    num_children: int = 0
    controller_id: int = 0
    parent_id: int = 0
    child_ids: list[int] = field(default_factory=list)


@dataclass
class PhysicalProxy:
    """Port of Models/Structs/Structs.cs#PhysicalProxy."""

    id: int = 0
    material: int = 0
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


# ----------------------------------------------------------- skin verts ---


@dataclass
class MeshBoneMapping:
    """Port of Models/Structs/Structs.cs#MeshBoneMapping (4 influences)."""

    bone_index: tuple[int, int, int, int] = (0, 0, 0, 0)
    weight: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


@dataclass
class IntSkinVertex:
    """Port of Models/Structs/Structs.cs#IntSkinVertex."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bone_mapping: MeshBoneMapping = field(default_factory=MeshBoneMapping)
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    obsolete0: tuple[float, float, float] = (0.0, 0.0, 0.0)
    obsolete2: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class TFace:
    """3 ushort indices (port of Models/Structs/Structs.cs#TFace)."""

    i0: int = 0
    i1: int = 0
    i2: int = 0


# ----------------------------------------------------------- aggregate ----


@dataclass
class SkinningInfo:
    """Port of CgfConverter/Models/SkinningInfo.cs.

    Populated by `CryEngine._build_skinning()` after every chunk in
    every loaded model has been parsed. Consumers (the armature
    builder) read ``compiled_bones`` and ``ext_to_int_map`` to weight
    the imported mesh.
    """

    compiled_bones: list[CompiledBone] = field(default_factory=list)
    physical_bones: list[CompiledPhysicalBone] = field(default_factory=list)
    physical_proxies: list[PhysicalProxy] = field(default_factory=list)
    int_vertices: list[IntSkinVertex] = field(default_factory=list)
    int_faces: list[TFace] = field(default_factory=list)
    ext_to_int_map: list[int] = field(default_factory=list)
    bone_names: list[str] = field(default_factory=list)

    @property
    def has_skinning_info(self) -> bool:
        return bool(self.compiled_bones)

    @property
    def has_int_to_ext_mapping(self) -> bool:
        return bool(self.ext_to_int_map)

    @property
    def root_bone(self) -> CompiledBone | None:
        return self.compiled_bones[0] if self.compiled_bones else None

    def get_bone_index_by_name(self, name: str) -> int:
        for i, b in enumerate(self.compiled_bones):
            if b.bone_name == name:
                return i
        return -1

    def get_bone_name_by_index(self, index: int) -> str:
        if 0 <= index < len(self.compiled_bones):
            return self.compiled_bones[index].bone_name
        return ""


__all__ = [
    "CompiledBone",
    "CompiledPhysicalBone",
    "PhysicalProxy",
    "MeshBoneMapping",
    "IntSkinVertex",
    "TFace",
    "SkinningInfo",
]
