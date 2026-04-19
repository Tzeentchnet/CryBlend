"""ChunkMesh.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMesh*.cs.
Implements versions 0x800 / 0x801 / 0x802.
"""

from __future__ import annotations

from ...enums import ChunkType, MeshChunkFlag
from ..chunk_registry import Chunk, chunk


class ChunkMesh(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.flags1: MeshChunkFlag | int = MeshChunkFlag(0)
        self.flags2: int = 0
        self.num_vertices: int = 0
        self.num_indices: int = 0
        self.num_vert_subsets: int = 0
        self.verts_anim_id: int = 0
        self.mesh_subsets_data: int = 0
        self.vertices_data: int = 0
        self.normals_data: int = 0
        self.uvs_data: int = 0
        self.colors_data: int = 0
        self.colors2_data: int = 0
        self.indices_data: int = 0
        self.tangents_data: int = 0
        self.sh_coeffs_data: int = 0
        self.shape_deformation_data: int = 0
        self.bone_map_data: int = 0
        self.face_map_data: int = 0
        self.vert_mats_data: int = 0
        self.q_tangents_data: int = 0
        self.skin_data: int = 0
        self.dummy2_data: int = 0
        self.verts_uvs_data: int = 0
        self.physics_data: list[int] = [0, 0, 0, 0]
        self.min_bound: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.max_bound: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _safe_mesh_flag(value: int) -> MeshChunkFlag | int:
    try:
        return MeshChunkFlag(value)
    except ValueError:
        return value


def _read_packed(self: ChunkMesh, br) -> None:
    """Layout shared by 0x800 and 0x801 (no per-stream padding)."""
    self.flags1 = _safe_mesh_flag(br.read_i32())
    self.flags2 = br.read_i32()
    self.num_vertices = br.read_i32()
    self.num_indices = br.read_i32()
    self.num_vert_subsets = br.read_u32()
    self.mesh_subsets_data = br.read_i32()
    self.verts_anim_id = br.read_i32()
    self.vertices_data = br.read_i32()
    self.normals_data = br.read_i32()
    self.uvs_data = br.read_i32()
    self.colors_data = br.read_i32()
    self.colors2_data = br.read_i32()
    self.indices_data = br.read_i32()
    self.tangents_data = br.read_i32()
    self.sh_coeffs_data = br.read_i32()
    self.shape_deformation_data = br.read_i32()
    self.bone_map_data = br.read_i32()
    self.face_map_data = br.read_i32()
    self.vert_mats_data = br.read_i32()
    self.q_tangents_data = br.read_i32()
    self.skin_data = br.read_i32()
    self.dummy2_data = br.read_i32()
    self.verts_uvs_data = br.read_i32()
    self.physics_data = [br.read_i32() for _ in range(4)]
    self.min_bound = br.read_vec3()
    self.max_bound = br.read_vec3()


@chunk(ChunkType.Mesh, 0x800)
class ChunkMesh800(ChunkMesh):
    def read(self, br) -> None:
        super().read(br)
        _read_packed(self, br)


@chunk(ChunkType.Mesh, 0x801)
class ChunkMesh801(ChunkMesh):
    def read(self, br) -> None:
        super().read(br)
        _read_packed(self, br)


@chunk(ChunkType.Mesh, 0x802)
class ChunkMesh802(ChunkMesh):
    """Same fields as 0x800/0x801, but each stream-id field is followed
    by 28 bytes of padding (slots for additional stream indices)."""

    def read(self, br) -> None:
        super().read(br)
        self.flags1 = _safe_mesh_flag(br.read_i32())
        self.flags2 = br.read_i32()
        self.num_vertices = br.read_i32()
        self.num_indices = br.read_i32()
        self.num_vert_subsets = br.read_u32()
        self.mesh_subsets_data = br.read_i32()
        self.verts_anim_id = br.read_i32()
        self.vertices_data = br.read_i32(); br.skip(28)
        self.normals_data = br.read_i32(); br.skip(28)
        self.uvs_data = br.read_i32(); br.skip(28)
        self.colors_data = br.read_i32(); br.skip(28)
        self.colors2_data = br.read_i32(); br.skip(28)
        self.indices_data = br.read_i32(); br.skip(28)
        self.tangents_data = br.read_i32(); br.skip(28)
        self.sh_coeffs_data = br.read_i32(); br.skip(28)
        self.shape_deformation_data = br.read_i32(); br.skip(28)
        self.bone_map_data = br.read_i32(); br.skip(28)
        self.face_map_data = br.read_i32(); br.skip(28)
        self.vert_mats_data = br.read_i32(); br.skip(28)
        self.q_tangents_data = br.read_i32(); br.skip(28)
        self.skin_data = br.read_i32(); br.skip(28)
        self.dummy2_data = br.read_i32(); br.skip(28)
        self.verts_uvs_data = br.read_i32(); br.skip(28)
        self.physics_data = [br.read_i32() for _ in range(4)]
        self.min_bound = br.read_vec3()
        self.max_bound = br.read_vec3()
