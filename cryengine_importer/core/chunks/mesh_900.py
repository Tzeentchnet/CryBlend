"""ChunkMesh_900 — IVO mesh header.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMesh_900.cs.

The 0x900 mesh header is much smaller than the legacy 0x800 one;
it just records counts + bounds and uses fixed datastream IDs
(4..9). The actual mesh payload lives in ChunkIvoSkinMesh_900.

Registered against both ``MeshIvo`` (0x9293B9D8) and
``MeshInfo`` (0x92914444), matching the C# Chunk.New routing.
"""

from __future__ import annotations

from ...enums import ChunkType, MeshChunkFlag
from ..chunk_registry import chunk
from .mesh import ChunkMesh


@chunk(ChunkType.MeshIvo, 0x900)
@chunk(ChunkType.MeshInfo, 0x900)
class ChunkMesh900(ChunkMesh):
    def read(self, br) -> None:
        super().read(br)
        self.flags1 = MeshChunkFlag(0)
        self.flags2 = br.read_i32()
        self.num_vertices = br.read_i32()
        self.num_indices = br.read_i32()
        self.num_vert_subsets = br.read_u32()
        br.skip(4)
        self.min_bound = br.read_vec3()
        self.max_bound = br.read_vec3()

        # Faithful to the C# reference: hard-coded datastream chunk IDs.
        # Node chunk ID = 1, mesh = 2.
        self.id = 2
        self.indices_data = 4
        self.verts_uvs_data = 5
        self.normals_data = 6
        self.tangents_data = 7
        self.bone_map_data = 8
        self.colors_data = 9
