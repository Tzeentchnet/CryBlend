"""ChunkCompiledPhysicalBones.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledPhysicalBones*.cs.
Only 0x800 is implemented (152-byte CompiledPhysicalBone records).

PhysicsGeometry payload is decoded into
``CompiledPhysicalBone.physics_geometry`` for downstream Blender Rigid
Body collision wiring.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import CompiledPhysicalBone, read_bone_physics_geometry
from ..chunk_registry import Chunk, chunk


class ChunkCompiledPhysicalBones(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_bones: int = 0
        self.physical_bone_list: list[CompiledPhysicalBone] = []

    @property
    def root_physical_bone(self) -> CompiledPhysicalBone | None:
        return self.physical_bone_list[0] if self.physical_bone_list else None


@chunk(ChunkType.CompiledPhysicalBones, 0x800)
class ChunkCompiledPhysicalBones800(ChunkCompiledPhysicalBones):
    """152-byte CompiledPhysicalBone records."""

    def read(self, br) -> None:
        super().read(br)
        br.skip(32)  # padding before the first bone

        record_size = 152
        self.num_bones = (self.size - 32) // record_size

        for _ in range(self.num_bones):
            bone = CompiledPhysicalBone()
            bone.bone_index = br.read_u32()
            bone.parent_offset = br.read_u32()
            bone.num_children = br.read_u32()
            bone.controller_id = br.read_u32()
            br.skip(32)  # prop char[32]
            bone.physics_geometry = read_bone_physics_geometry(br)
            self.physical_bone_list.append(bone)

        # Resolve parent_id / child_ids by ControllerID.
        bones_by_controller = {b.controller_id: b for b in self.physical_bone_list}
        for i, bone in enumerate(self.physical_bone_list):
            if bone.parent_offset == 0:
                bone.parent_id = 0
                continue
            # parent_offset is signed when reinterpreted (negative => earlier bone).
            signed_offset = bone.parent_offset
            if signed_offset >= 0x80000000:
                signed_offset -= 0x100000000
            parent_idx = i + signed_offset
            if 0 <= parent_idx < len(self.physical_bone_list):
                parent = self.physical_bone_list[parent_idx]
                bone.parent_id = parent.controller_id
                parent.child_ids.append(bone.controller_id)
            else:
                bone.parent_id = 0

        # Defensive: also resolve by ControllerID lookup when parent_id was set.
        for bone in self.physical_bone_list:
            if bone.parent_id and bone.parent_id in bones_by_controller:
                # No-op if already linked above.
                pass
