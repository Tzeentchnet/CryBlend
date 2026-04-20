"""ChunkCompiledBones.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledBones*.cs.
Implements 0x800 (584-byte bone records) and 0x801 (324-byte records).

Per-bone PhysicsGeometry payload (104 bytes per LOD, 2 LODs per bone)
is decoded into ``CompiledBone.physics_alive`` / ``physics_dead`` —
useful for downstream Blender Rigid Body collision wiring.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import CompiledBone, read_bone_physics_geometry
from ..chunk_registry import Chunk, chunk


class ChunkCompiledBones(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_bones: int = 0
        self.bone_list: list[CompiledBone] = []

    @property
    def root_bone(self) -> CompiledBone | None:
        return self.bone_list[0] if self.bone_list else None


def _wire_parents(chunk: ChunkCompiledBones) -> None:
    bones = chunk.bone_list
    for i, bone in enumerate(bones):
        if bone.offset_parent != 0:
            parent_idx = i + bone.offset_parent
            if 0 <= parent_idx < len(bones):
                bone.parent_bone = bones[parent_idx]
                bone.parent_controller_index = parent_idx


@chunk(ChunkType.CompiledBones, 0x800)
class ChunkCompiledBones800(ChunkCompiledBones):
    """584-byte CompiledBone records."""

    def read(self, br) -> None:
        super().read(br)
        br.skip(32)  # padding before the first bone

        record_size = 584
        self.num_bones = (self.size - 32) // record_size

        for _ in range(self.num_bones):
            bone = CompiledBone()
            bone.controller_id = br.read_u32()
            bone.physics_alive = read_bone_physics_geometry(br)
            bone.physics_dead = read_bone_physics_geometry(br)
            br.skip(4)  # mass (single float, unused by importer)
            bone.local_transform_matrix = br.read_matrix3x4()
            bone.world_transform_matrix = br.read_matrix3x4()
            bone.bone_name = br.read_fstring(256)
            bone.limb_id = br.read_u32()
            bone.offset_parent = br.read_i32()
            bone.number_of_children = br.read_i32()
            bone.offset_child = br.read_i32()
            self.bone_list.append(bone)

        _wire_parents(self)


@chunk(ChunkType.CompiledBones, 0x801)
class ChunkCompiledBones801(ChunkCompiledBones):
    """324-byte CompiledBone records (Archeage variant)."""

    def read(self, br) -> None:
        super().read(br)
        br.skip(32)  # padding before the first bone

        record_size = 324
        # Reference C# uses `(Size - 48) / 324`.
        self.num_bones = (self.size - 48) // record_size

        for _ in range(self.num_bones):
            bone = CompiledBone()
            bone.controller_id = br.read_u32()
            bone.limb_id = br.read_u32()
            bone.physics_alive = read_bone_physics_geometry(br)
            bone.physics_dead = read_bone_physics_geometry(br)
            bone.bone_name = br.read_fstring(48)
            bone.offset_parent = br.read_i32()
            bone.number_of_children = br.read_i32()
            bone.offset_child = br.read_i32()
            bone.local_transform_matrix = br.read_matrix3x4()
            # World transform isn't stored in 0x801 — leave identity.
            self.bone_list.append(bone)

        _wire_parents(self)
