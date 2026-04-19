"""`MeshGeometry` — flat per-mesh data ready for Blender consumption.

Built by `core.mesh_builder.build_geometry` from a `ChunkNode` whose
`mesh_data` resolves to a `ChunkMesh` plus its accompanying
`ChunkDataStream` and `ChunkMeshSubsets` chunks.

The shapes are deliberately the ones `bpy.types.Mesh.from_pydata`
wants:

- ``positions``  — list of ``(x, y, z)`` float triples
- ``triangles``  — list of ``(i0, i1, i2)`` int triples
- ``uvs``        — per-vertex UV ``(u, v)`` (optional)
- ``normals``    — per-vertex normals ``(x, y, z)`` (optional)
- ``colors``     — per-vertex RGBA in ``[0, 1]`` (optional)
- ``subsets``    — index ranges with material id, for splitting into
  Blender material slots
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubsetRange:
    """Slice of the index buffer that belongs to one material."""

    first_index: int
    num_indices: int
    first_vertex: int
    num_vertices: int
    mat_id: int

    @property
    def num_triangles(self) -> int:
        return self.num_indices // 3


@dataclass
class MorphTarget:
    """One named blend-shape attached to a mesh.

    ``vertices`` is a list of ``(vertex_id, (x, y, z))`` pairs where
    the position is the absolute deformed coordinate (Blender's
    ``shape_key.data[vertex_id].co`` accepts this directly; the delta
    vs. the Basis is computed by Blender).
    """

    name: str
    vertices: list[tuple[int, tuple[float, float, float]]] = field(
        default_factory=list
    )


@dataclass
class MeshGeometry:
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    normals: list[tuple[float, float, float]] | None = None
    uvs: list[tuple[float, float]] | None = None
    colors: list[tuple[float, float, float, float]] | None = None
    subsets: list[SubsetRange] = field(default_factory=list)
    morph_targets: list[MorphTarget] = field(default_factory=list)

    @property
    def num_vertices(self) -> int:
        return len(self.positions)

    @property
    def num_triangles(self) -> int:
        return len(self.indices) // 3

    @property
    def triangles(self) -> list[tuple[int, int, int]]:
        idx = self.indices
        return [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx) - 2, 3)]
