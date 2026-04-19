"""Build a `MeshGeometry` from a `ChunkNode` + its mesh chunks.

Pure-Python (no `bpy`); the Blender bridge in
`blender/scene_builder.py` consumes the result.

The traversal mirrors `WavefrontModelRenderer.WriteObjNode` in the C#
tree: from the node, follow `mesh_data` to a `ChunkMesh`, then look
up each stream id (vertices / indices / normals / uvs / colors) in the
*owning model's* `chunk_map`. Subsets come from `mesh_subsets_data`.

For split-file assets (.cga + .cgam) the aggregator already swapped
`node.mesh_data` to point at the cgam's mesh, so `mesh.model.chunk_map`
is the right lookup table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..enums import DatastreamType
from ..models.geometry import MeshGeometry, MorphTarget, SubsetRange
from .chunks.data_stream import ChunkDataStream
from .chunks.ivo_skin_mesh import ChunkIvoSkinMesh
from .chunks.mesh import ChunkMesh
from .chunks.mesh_subsets import ChunkMeshSubsets
from .chunks.morph_targets import ChunkCompiledMorphTargets

if TYPE_CHECKING:
    from .chunks.node import ChunkNode


def build_geometry(node: "ChunkNode") -> MeshGeometry | None:
    """Return a `MeshGeometry` for ``node``, or ``None`` if ``node``
    has no resolvable mesh (helper / empty stub)."""
    mesh = node.mesh_data
    if isinstance(mesh, ChunkIvoSkinMesh):
        return _build_geometry_ivo(node, mesh)
    if not isinstance(mesh, ChunkMesh) or mesh.num_vertices == 0:
        return None

    model = mesh.model
    if model is None:
        return None
    chunks = model.chunk_map

    geom = MeshGeometry()

    # --- per-stream lookup --------------------------------------------
    verts_chunk = _stream(chunks, mesh.vertices_data, DatastreamType.VERTICES)
    if verts_chunk is not None:
        geom.positions = list(verts_chunk.data)

    indices_chunk = _stream(chunks, mesh.indices_data, DatastreamType.INDICES)
    if indices_chunk is not None:
        geom.indices = list(indices_chunk.data)

    normals_chunk = _stream(chunks, mesh.normals_data, DatastreamType.NORMALS)
    if normals_chunk is not None and normals_chunk.data:
        geom.normals = list(normals_chunk.data)

    uvs_chunk = _stream(chunks, mesh.uvs_data, DatastreamType.UVS)
    if uvs_chunk is not None and uvs_chunk.data:
        geom.uvs = list(uvs_chunk.data)

    colors_chunk = _stream(chunks, mesh.colors_data, DatastreamType.COLORS)
    if colors_chunk is not None and colors_chunk.data:
        geom.colors = list(colors_chunk.data)

    # --- VERTSUVS combined stream fallback ----------------------------
    # Some IVO/Star-Citizen-ish files pack pos + color + uv into a
    # single VERTSUVS stream rather than separate VERTICES/UVS/COLORS.
    if not geom.positions:
        vu = _stream(chunks, mesh.verts_uvs_data, DatastreamType.VERTSUVS)
        if vu is not None and vu.data:
            geom.positions = [v.vertex for v in vu.data]
            geom.uvs = [v.uv for v in vu.data]
            geom.colors = [v.color for v in vu.data]

    # --- subsets ------------------------------------------------------
    subsets_chunk = chunks.get(mesh.mesh_subsets_data)
    if isinstance(subsets_chunk, ChunkMeshSubsets):
        geom.subsets = [
            SubsetRange(
                first_index=s.first_index,
                num_indices=s.num_indices,
                first_vertex=s.first_vertex,
                num_vertices=s.num_vertices,
                mat_id=s.mat_id,
            )
            for s in subsets_chunk.mesh_subsets
        ]
    elif geom.indices:
        # No subsets chunk — treat the whole index buffer as one slot.
        geom.subsets = [
            SubsetRange(
                first_index=0,
                num_indices=len(geom.indices),
                first_vertex=0,
                num_vertices=len(geom.positions),
                mat_id=0,
            )
        ]

    geom.morph_targets = _collect_morph_targets(chunks, len(geom.positions))

    return geom


def _stream(
    chunks: dict, chunk_id: int, expected: DatastreamType
) -> ChunkDataStream | None:
    """Look up a `ChunkDataStream` by id and verify its type."""
    if chunk_id == 0:
        return None
    ds = chunks.get(chunk_id)
    if not isinstance(ds, ChunkDataStream):
        return None
    if ds.data_stream_type != expected:
        return None
    return ds


def _build_geometry_ivo(
    node: "ChunkNode", mesh: ChunkIvoSkinMesh
) -> MeshGeometry | None:
    """Build a :class:`MeshGeometry` from an IVO :class:`ChunkIvoSkinMesh`.

    The IvoSkinMesh carries its own vertex/index/UV/colour streams
    inline (no separate ChunkDataStream lookups), and its subsets
    each tag a ``node_parent_index`` identifying which NodeMeshCombo
    entry owns them. Mirrors C# ``CryEngine.BuildNodeStructure``
    which filters ``skinMesh.MeshSubsets`` by
    ``NodeParentIndex == index`` per node.

    For skin / chr files (single synthesized root, ``ivo_node_index``
    is ``None``) all subsets are emitted.
    """
    if not mesh.verts_uvs or not mesh.indices:
        return None

    geom = MeshGeometry()
    geom.positions = [v.vertex for v in mesh.verts_uvs]
    geom.uvs = [v.uv for v in mesh.verts_uvs]
    if mesh.colors:
        geom.colors = list(mesh.colors)
    elif mesh.verts_uvs:
        geom.colors = [v.color for v in mesh.verts_uvs]
    if mesh.normals:
        geom.normals = list(mesh.normals)

    node_idx = node.ivo_node_index
    matching = [
        s for s in mesh.mesh_subsets
        if node_idx is None or s.node_parent_index == node_idx
    ]
    if not matching:
        return None

    # IVO index buffer is encoded per-subset relative to the *first*
    # index value of that subset, not as absolute vertex indices.
    # Mirror C# ColladaModelRenderer.Geometry.cs:
    #   firstGlobal = indices[subset.FirstIndex]
    #   global_idx  = (indices[k] - firstGlobal) + subset.FirstVertex
    # For "well-behaved" subsets indices[FirstIndex] already == FirstVertex
    # (no-op), but Star Citizen meshes pack later subsets starting at 0.
    raw_indices = mesh.indices
    rebased = list(raw_indices)
    for s in mesh.mesh_subsets:
        if s.num_indices <= 0 or s.first_index >= len(raw_indices):
            continue
        first_global = raw_indices[s.first_index]
        delta = s.first_vertex - first_global
        if delta == 0:
            continue
        end = s.first_index + s.num_indices
        for k in range(s.first_index, end):
            rebased[k] = raw_indices[k] + delta
    geom.indices = rebased
    geom.subsets = [
        SubsetRange(
            first_index=s.first_index,
            num_indices=s.num_indices,
            first_vertex=s.first_vertex,
            num_vertices=s.num_vertices,
            mat_id=s.mat_id,
        )
        for s in matching
    ]

    if mesh.model is not None:
        geom.morph_targets = _collect_morph_targets(
            mesh.model.chunk_map, len(geom.positions)
        )

    return geom


def _collect_morph_targets(
    chunks: dict, num_vertices: int
) -> list[MorphTarget]:
    """Pull every :class:`ChunkCompiledMorphTargets` out of ``chunks``
    and convert it to a :class:`MorphTarget`.

    The C# chunk has no per-target name or grouping — every chunk maps
    to one anonymous shape key. We name them ``Morph_{chunk_id:X}`` so
    multiple morph chunks on the same model stay distinguishable in
    Blender's UI. Out-of-range vertex indices are dropped (defensive
    against split-file companions where the chunk-id space might not
    match the displayed mesh).
    """
    out: list[MorphTarget] = []
    for chunk_id, c in chunks.items():
        if not isinstance(c, ChunkCompiledMorphTargets):
            continue
        if not c.morph_target_vertices:
            continue
        verts: list[tuple[int, tuple[float, float, float]]] = []
        for v in c.morph_target_vertices:
            if num_vertices and v.vertex_id >= num_vertices:
                continue
            verts.append((v.vertex_id, v.vertex))
        if not verts:
            continue
        out.append(MorphTarget(name=f"Morph_{chunk_id:X}", vertices=verts))
    return out
