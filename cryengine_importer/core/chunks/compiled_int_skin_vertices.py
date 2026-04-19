"""ChunkCompiledIntSkinVertices.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledIntSkinVertices*.cs.
Implements 0x800 (64-byte records) and 0x801 (40-byte records).
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import IntSkinVertex, MeshBoneMapping
from ..chunk_registry import Chunk, chunk


class ChunkCompiledIntSkinVertices(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_int_vertices: int = 0
        self.int_skin_vertices: list[IntSkinVertex] = []


def _read_bone_mapping(br) -> MeshBoneMapping:
    indices = (br.read_u16(), br.read_u16(), br.read_u16(), br.read_u16())
    weights = (br.read_f32(), br.read_f32(), br.read_f32(), br.read_f32())
    return MeshBoneMapping(bone_index=indices, weight=weights)


@chunk(ChunkType.CompiledIntSkinVertices, 0x800)
class ChunkCompiledIntSkinVertices800(ChunkCompiledIntSkinVertices):
    """64-byte IntSkinVertex records (with two obsolete vec3 fields)."""

    def read(self, br) -> None:
        super().read(br)
        br.skip(32)  # padding

        record_size = 64
        self.num_int_vertices = (self.size - 32) // record_size

        for _ in range(self.num_int_vertices):
            v = IntSkinVertex()
            v.obsolete0 = br.read_vec3()
            v.position = br.read_vec3()
            v.obsolete2 = br.read_vec3()
            v.bone_mapping = _read_bone_mapping(br)
            v.color = br.read_irgba()
            self.int_skin_vertices.append(v)


@chunk(ChunkType.CompiledIntSkinVertices, 0x801)
class ChunkCompiledIntSkinVertices801(ChunkCompiledIntSkinVertices):
    """40-byte IntSkinVertex records (no obsolete fields)."""

    def read(self, br) -> None:
        super().read(br)
        br.skip(32)  # padding

        record_size = 40
        self.num_int_vertices = (self.size - 32) // record_size

        for _ in range(self.num_int_vertices):
            v = IntSkinVertex()
            v.position = br.read_vec3()
            v.bone_mapping = _read_bone_mapping(br)
            v.color = br.read_irgba()
            self.int_skin_vertices.append(v)
