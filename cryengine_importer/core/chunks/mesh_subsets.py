"""ChunkMeshSubsets.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMeshSubsets*.cs.
Implements version 0x800.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


@dataclass
class MeshSubset:
    first_index: int = 0
    num_indices: int = 0
    first_vertex: int = 0
    num_vertices: int = 0
    mat_id: int = 0
    radius: float = 0.0
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)


class ChunkMeshSubsets(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.flags: int = 0
        self.num_mesh_subset: int = 0
        self.mesh_subsets: list[MeshSubset] = []


@chunk(ChunkType.MeshSubsets, 0x800)
class ChunkMeshSubsets800(ChunkMeshSubsets):
    def read(self, br) -> None:
        super().read(br)
        self.flags = br.read_u32()
        self.num_mesh_subset = br.read_u32()
        br.skip(8)
        self.mesh_subsets = [
            MeshSubset(
                first_index=br.read_i32(),
                num_indices=br.read_i32(),
                first_vertex=br.read_i32(),
                num_vertices=br.read_i32(),
                mat_id=br.read_i32(),
                radius=br.read_f32(),
                center=br.read_vec3(),
            )
            for _ in range(self.num_mesh_subset)
        ]
