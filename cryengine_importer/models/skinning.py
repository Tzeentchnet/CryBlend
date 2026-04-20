"""Skinning data classes — port of CgfConverter/Models/SkinningInfo.cs
and the CompiledBone / IntSkinVertex / TFace / PhysicalProxy structs.

Plain `dataclass`-based, bpy-free contracts shared between the chunk
readers and the (Phase 3) Blender armature builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ----------------------------------------------------------- physics ------


# Default identity matrix for `BonePhysicsGeometry.frame_matrix`.
_IDENTITY_3X3: tuple[tuple[float, ...], ...] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


@dataclass
class BonePhysicsGeometry:
    """Port of `Models/Structs/Structs.cs#PhysicsGeometry` (104 bytes).

    The on-disk record exists once per "alive" / "dead" LOD on each
    :class:`CompiledBone` (so 2 × 104 = 208 bytes per bone), and once
    on each :class:`CompiledPhysicalBone`. Previously skipped — now
    decoded so consumers can derive Blender Rigid Body collision
    primitives from the per-bone bounding box (``min`` / ``max``
    define an axis-aligned box in bone-local space).

    ``physics_geom`` is the geometry-id reference (links to a
    physicalised mesh elsewhere in the asset); ``flags`` carries the
    primitive type plus material flags. The remaining fields drive
    CryEngine's joint constraint solver — kept on the dataclass for
    completeness but not consumed by the Blender bridge yet.
    """

    physics_geom: int = 0
    flags: int = 0
    min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    max: tuple[float, float, float] = (0.0, 0.0, 0.0)
    spring_angle: tuple[float, float, float] = (0.0, 0.0, 0.0)
    spring_tension: tuple[float, float, float] = (0.0, 0.0, 0.0)
    damping: tuple[float, float, float] = (0.0, 0.0, 0.0)
    frame_matrix: tuple[tuple[float, ...], ...] = _IDENTITY_3X3

    @property
    def is_empty(self) -> bool:
        """``True`` when the on-disk record carried no geometry id and
        an empty bounding box (typical for "dead" LOD on rigid bones).
        """
        return self.physics_geom == 0 and self.min == self.max == (0.0, 0.0, 0.0)

    @property
    def extent(self) -> tuple[float, float, float]:
        """Half-extent of the AABB ``(max - min) / 2``."""
        return (
            (self.max[0] - self.min[0]) * 0.5,
            (self.max[1] - self.min[1]) * 0.5,
            (self.max[2] - self.min[2]) * 0.5,
        )

    @property
    def center(self) -> tuple[float, float, float]:
        """Geometric centre of the AABB."""
        return (
            (self.max[0] + self.min[0]) * 0.5,
            (self.max[1] + self.min[1]) * 0.5,
            (self.max[2] + self.min[2]) * 0.5,
        )


def read_bone_physics_geometry(br) -> BonePhysicsGeometry:
    """Read one 104-byte ``PhysicsGeometry`` record from ``br``.

    Mirrors `PhysicsGeometry.ReadPhysicsGeometry` in the C# tree:
    u32 + u32 + 5 × Vec3 + Mat3x3 = 4+4+60+36 = 104 bytes.
    """
    geom = BonePhysicsGeometry()
    geom.physics_geom = br.read_u32()
    geom.flags = br.read_u32()
    geom.min = br.read_vec3()
    geom.max = br.read_vec3()
    geom.spring_angle = br.read_vec3()
    geom.spring_tension = br.read_vec3()
    geom.damping = br.read_vec3()
    geom.frame_matrix = br.read_matrix3x3()
    return geom


# ----------------------------------------------------------- bones --------


@dataclass
class CompiledBone:
    """Port of CgfConverter/Models/CompiledBone.cs.

    The on-disk record carries two ``PhysicsGeometry`` payloads (alive
    / dead LOD); both are now decoded into ``physics_alive`` /
    ``physics_dead`` rather than skipped. Defaults to "empty" geometry
    so legacy callers behave the same.
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

    # Per-LOD physics geometry (legacy 0x800 / 0x801 only). ``None``
    # when the source chunk doesn't carry physics records (IVO 0x900 /
    # 0x901 readers leave both fields as ``None``).
    physics_alive: Optional[BonePhysicsGeometry] = None
    physics_dead: Optional[BonePhysicsGeometry] = None


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
    # Decoded 104-byte ``PhysicsGeometry`` (was previously skipped).
    # ``None`` only when the dataclass is constructed directly without
    # a chunk reader (e.g. in test fixtures).
    physics_geometry: Optional[BonePhysicsGeometry] = None


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
