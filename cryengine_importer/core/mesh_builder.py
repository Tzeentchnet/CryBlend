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

import logging
from pathlib import PurePosixPath
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

logger = logging.getLogger(__name__)


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

    # Dequantize SNORM16-packed positions back to model-space metres
    # using the bbox carried in the IvoGeometryMeshDetails. Mirrors C#
    # ColladaModelRenderer.WriteGeometries / BaseGltfRenderer for IVO
    # CGF/CGA assets (skin / chr files keep snorm coordinates because
    # bones supply the world transform). Without this step Star Citizen
    # vehicles like the Greycat PTV import as a unit cube and look
    # squished along whichever axes the bbox extends past 1 m.
    _apply_ivo_position_scale(geom, mesh, node)

    node_idx = node.ivo_node_index
    matching = [
        s for s in mesh.mesh_subsets
        if node_idx is None or s.node_parent_index == node_idx
    ]
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "ivo node %r idx=%s: %d/%d subsets, verts=%d indices=%d",
            node.name,
            node_idx,
            len(matching),
            len(mesh.mesh_subsets),
            len(geom.positions),
            len(mesh.indices),
        )
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
    # Slice the (shared) index buffer down to only the matching
    # subsets, then compact the vertex pool so this per-node Blender
    # mesh holds only its own triangles + their referenced vertices.
    # Without this slice, every Geometry-type NodeMeshCombo entry
    # would receive the entire combined index buffer and therefore
    # render the whole mech, producing N stacked duplicates in the
    # scene (one per geometry node) — see ARGO ATLS Mcarog.cga.
    sliced_indices: list[int] = []
    sliced_subsets: list[SubsetRange] = []
    for s in matching:
        end = s.first_index + s.num_indices
        if s.num_indices <= 0 or end > len(rebased):
            logger.debug(
                "ivo node %r: skipping subset first_index=%d num_indices=%d "
                "(rebased len=%d)",
                node.name,
                s.first_index,
                s.num_indices,
                len(rebased),
            )
            continue
        if logger.isEnabledFor(logging.DEBUG):
            first_global = (
                raw_indices[s.first_index] if s.first_index < len(raw_indices) else -1
            )
            delta = s.first_vertex - first_global
            logger.debug(
                "ivo node %r subset: first_index=%d num_indices=%d "
                "first_vertex=%d num_vertices=%d mat_id=%d delta=%d",
                node.name,
                s.first_index,
                s.num_indices,
                s.first_vertex,
                s.num_vertices,
                s.mat_id,
                delta,
            )
        new_first = len(sliced_indices)
        sliced_indices.extend(rebased[s.first_index:end])
        sliced_subsets.append(
            SubsetRange(
                first_index=new_first,
                num_indices=s.num_indices,
                first_vertex=s.first_vertex,
                num_vertices=s.num_vertices,
                mat_id=s.mat_id,
            )
        )

    if not sliced_indices:
        return None

    # Compact the vertex pool to only the vertices this node uses.
    # Subsets' first_vertex/num_vertices are no longer authoritative
    # after compaction, but the Blender bridge only consumes
    # first_index/num_indices/mat_id on the SubsetRange.
    old_to_new: dict[int, int] = {}
    new_positions: list[tuple[float, float, float]] = []
    new_uvs = [] if geom.uvs is not None else None
    new_colors = [] if geom.colors is not None else None
    new_normals = [] if geom.normals is not None else None
    pos_src = geom.positions
    uv_src = geom.uvs
    col_src = geom.colors
    nrm_src = geom.normals
    for old_idx in sliced_indices:
        if old_idx not in old_to_new:
            old_to_new[old_idx] = len(new_positions)
            new_positions.append(pos_src[old_idx])
            if new_uvs is not None and uv_src is not None and old_idx < len(uv_src):
                new_uvs.append(uv_src[old_idx])
            if new_colors is not None and col_src is not None and old_idx < len(col_src):
                new_colors.append(col_src[old_idx])
            if new_normals is not None and nrm_src is not None and old_idx < len(nrm_src):
                new_normals.append(nrm_src[old_idx])

    geom.positions = new_positions
    geom.uvs = new_uvs
    geom.colors = new_colors
    geom.normals = new_normals
    geom.indices = [old_to_new[i] for i in sliced_indices]
    geom.subsets = sliced_subsets

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "ivo node %r: compacted to %d verts, %d indices, %d subsets",
            node.name,
            len(geom.positions),
            len(geom.indices),
            len(geom.subsets),
        )

    if mesh.model is not None:
        # Morph targets reference the IvoSkinMesh's *original* vertex
        # ids; remap them through the compaction map and drop entries
        # that don't touch this node's vertices.
        morphs = _collect_morph_targets(
            mesh.model.chunk_map, len(pos_src)
        )
        if morphs:
            remapped: list[MorphTarget] = []
            for m in morphs:
                verts = [
                    (old_to_new[old_id], pos)
                    for old_id, pos in m.vertices
                    if old_id in old_to_new
                ]
                if verts:
                    remapped.append(MorphTarget(name=m.name, vertices=verts))
            geom.morph_targets = remapped

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


def _apply_ivo_position_scale(
    geom: MeshGeometry, mesh: ChunkIvoSkinMesh, node: "ChunkNode"
) -> None:
    """Map snorm16 IVO vertex positions back to model-space metres.

    Mirrors C# ``ColladaModelRenderer.WriteGeometries`` for IVO files:
    when the source asset is a CGF/CGA, vertices are stored as snorm16
    in [-1, 1] and must be re-scaled by the mesh's bounding box (or
    ScalingBoundingBox when present)::

        center  = (max + min) / 2
        extent  = abs(max - min) / 2          # min-capped to 1 / axis
        vertex' = vertex * extent + center

    Skinned meshes (``.skin`` / ``.chr``) keep snorm coordinates because
    their bones supply the world transform.

    No-ops when the verts/UV stream is uncompressed (``bpe == 20``,
    full float32 positions) or when the vertex range is already outside
    [-1, 1].
    """
    if not geom.positions:
        return
    if mesh.verts_uvs_bpe and mesh.verts_uvs_bpe != 16:
        return
    file_name = mesh.model.file_name if mesh.model is not None else None
    if file_name is not None:
        ext = PurePosixPath(file_name).suffix.lower()
        if ext in (".skin", ".chr"):
            return

    details = mesh.mesh_details
    bbox = details.scaling_bounding_box
    if bbox == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)):
        bbox = details.bounding_box
    (mn, mx) = bbox
    if mn == mx:
        return

    cx = (mx[0] + mn[0]) * 0.5
    cy = (mx[1] + mn[1]) * 0.5
    cz = (mx[2] + mn[2]) * 0.5
    ex = max(1.0, abs(mx[0] - mn[0]) * 0.5)
    ey = max(1.0, abs(mx[1] - mn[1]) * 0.5)
    ez = max(1.0, abs(mx[2] - mn[2]) * 0.5)

    geom.positions = [
        (px * ex + cx, py * ey + cy, pz * ez + cz)
        for (px, py, pz) in geom.positions
    ]
