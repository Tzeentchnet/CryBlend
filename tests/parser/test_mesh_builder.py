"""Phase A — `core.mesh_builder.build_geometry` and node `world_matrix`.

These tests construct chunk objects directly (no binary parsing) and
exercise the dereferencing logic + matrix composition.
"""

from __future__ import annotations

import math

from cryengine_importer.core.chunks.data_stream import ChunkDataStream800, VertUV
from cryengine_importer.core.chunks.ivo_skin_mesh import ChunkIvoSkinMesh900
from cryengine_importer.core.chunks.mesh import ChunkMesh800
from cryengine_importer.core.chunks.mesh_subsets import (
    ChunkMeshSubsets800,
    MeshSubset,
)
from cryengine_importer.core.chunks.node import ChunkNode823
from cryengine_importer.core.mesh_builder import build_geometry
from cryengine_importer.core.model import Model
from cryengine_importer.enums import DatastreamType
from cryengine_importer.models.ivo import (
    IvoGeometryMeshDetails,
    IvoMeshSubset,
)


# --------------------------------------------------------------- helpers


def _make_stream(
    chunk_id: int, dst: DatastreamType, data: list
) -> ChunkDataStream800:
    s = ChunkDataStream800()
    s.id = chunk_id
    s.data_stream_type = dst
    s.num_elements = len(data)
    s.data = data
    return s


def _make_subsets(chunk_id: int, subsets: list[MeshSubset]) -> ChunkMeshSubsets800:
    c = ChunkMeshSubsets800()
    c.id = chunk_id
    c.num_mesh_subset = len(subsets)
    c.mesh_subsets = subsets
    return c


def _make_mesh(
    chunk_id: int,
    *,
    num_vertices: int,
    num_indices: int,
    vertices_id: int = 0,
    indices_id: int = 0,
    normals_id: int = 0,
    uvs_id: int = 0,
    colors_id: int = 0,
    subsets_id: int = 0,
) -> ChunkMesh800:
    m = ChunkMesh800()
    m.id = chunk_id
    m.num_vertices = num_vertices
    m.num_indices = num_indices
    m.vertices_data = vertices_id
    m.indices_data = indices_id
    m.normals_data = normals_id
    m.uvs_data = uvs_id
    m.colors_data = colors_id
    m.mesh_subsets_data = subsets_id
    return m


def _make_model(chunks: list) -> Model:
    m = Model()
    m.chunk_map = {c.id: c for c in chunks}
    for c in chunks:
        c.model = m
    return m


# --------------------------------------------------------------- build_geometry


def test_build_geometry_returns_none_when_node_has_no_mesh() -> None:
    n = ChunkNode823()
    n.mesh_data = None
    assert build_geometry(n) is None


def test_build_geometry_returns_none_for_empty_mesh_stub() -> None:
    """Split-file .cga with MESH_IS_EMPTY before the .cgam is loaded."""
    mesh = _make_mesh(10, num_vertices=0, num_indices=0)
    _make_model([mesh])
    n = ChunkNode823()
    n.mesh_data = mesh
    assert build_geometry(n) is None


def test_build_geometry_assembles_positions_indices_normals_uvs() -> None:
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    norms = [(0.0, 0.0, 1.0)] * 3
    uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    indices = [0, 1, 2]

    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    n_chunk = _make_stream(21, DatastreamType.NORMALS, norms)
    u_chunk = _make_stream(22, DatastreamType.UVS, uvs)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)

    mesh = _make_mesh(
        10,
        num_vertices=3,
        num_indices=3,
        vertices_id=20,
        normals_id=21,
        uvs_id=22,
        indices_id=23,
    )
    _make_model([mesh, v_chunk, n_chunk, u_chunk, i_chunk])

    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert geom.positions == verts
    assert geom.normals == norms
    assert geom.uvs == uvs
    assert geom.indices == indices
    assert geom.triangles == [(0, 1, 2)]
    assert geom.num_vertices == 3
    assert geom.num_triangles == 1


def test_build_geometry_synthesises_default_subset_when_chunk_missing() -> None:
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    indices = [0, 1, 2]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    mesh = _make_mesh(
        10, num_vertices=3, num_indices=3, vertices_id=20, indices_id=23
    )
    _make_model([mesh, v_chunk, i_chunk])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert len(geom.subsets) == 1
    s = geom.subsets[0]
    assert (s.first_index, s.num_indices, s.first_vertex, s.num_vertices, s.mat_id) == (
        0, 3, 0, 3, 0,
    )


def test_build_geometry_uses_real_subsets_when_chunk_present() -> None:
    verts = [(0.0, 0.0, 0.0)] * 6
    indices = list(range(6))
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    sub_chunk = _make_subsets(
        30,
        [
            MeshSubset(first_index=0, num_indices=3, first_vertex=0, num_vertices=3, mat_id=7),
            MeshSubset(first_index=3, num_indices=3, first_vertex=3, num_vertices=3, mat_id=9),
        ],
    )
    mesh = _make_mesh(
        10,
        num_vertices=6,
        num_indices=6,
        vertices_id=20,
        indices_id=23,
        subsets_id=30,
    )
    _make_model([mesh, v_chunk, i_chunk, sub_chunk])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert [(s.mat_id, s.num_indices) for s in geom.subsets] == [(7, 3), (9, 3)]
    assert geom.subsets[1].num_triangles == 1


def test_build_geometry_ignores_wrong_stream_type() -> None:
    """If a stream-id field accidentally points at a chunk of the
    wrong DatastreamType, it should be silently dropped (not crash)."""
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    # uvs_id points at a stream typed as NORMALS — must be ignored.
    bad = _make_stream(22, DatastreamType.NORMALS, [(0.0, 0.0, 1.0)] * 3)
    mesh = _make_mesh(
        10, num_vertices=3, num_indices=0, vertices_id=20, uvs_id=22
    )
    _make_model([mesh, v_chunk, bad])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert geom.positions == verts
    assert geom.uvs is None


# --------------------------------------------------------------- world_matrix


def _identity() -> tuple[tuple[float, ...], ...]:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _translation(x: float, y: float, z: float) -> tuple[tuple[float, ...], ...]:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (x, y, z, 1.0),
    )


def test_world_matrix_returns_local_when_no_parent() -> None:
    n = ChunkNode823()
    n.transform = _translation(5.0, 0.0, 0.0)
    assert n.world_matrix == _translation(5.0, 0.0, 0.0)


def test_world_matrix_composes_translations_through_parent_chain() -> None:
    grandparent = ChunkNode823()
    grandparent.transform = _translation(10.0, 0.0, 0.0)

    parent = ChunkNode823()
    parent.transform = _translation(0.0, 20.0, 0.0)
    parent.parent_node = grandparent

    child = ChunkNode823()
    child.transform = _translation(0.0, 0.0, 30.0)
    child.parent_node = parent

    w = child.world_matrix
    # Translation row should be (10, 20, 30, 1).
    assert w[3] == (10.0, 20.0, 30.0, 1.0)
    # Upper-left 3x3 stays identity.
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            assert math.isclose(w[i][j], expected)


def test_world_matrix_applies_local_before_parent() -> None:
    """Order matters: child translation should be transformed by
    parent rotation. With identity rotations this collapses to a sum,
    but order is still verifiable via a rotation."""
    parent = ChunkNode823()
    # 180° around Z: x -> -x, y -> -y.
    parent.transform = (
        (-1.0, 0.0, 0.0, 0.0),
        (0.0, -1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    child = ChunkNode823()
    child.transform = _translation(2.0, 3.0, 0.0)
    child.parent_node = parent

    w = child.world_matrix
    # child's translation row (2, 3, 0, 1) should be rotated by parent
    # to (-2, -3, 0, 1).
    assert math.isclose(w[3][0], -2.0)
    assert math.isclose(w[3][1], -3.0)
    assert math.isclose(w[3][2], 0.0)
    assert math.isclose(w[3][3], 1.0)


# --------------------------------------------------------------- IVO


def _make_ivo_skin_mesh(
    *,
    verts_uvs: list[VertUV],
    indices: list[int],
    subsets: list[IvoMeshSubset],
    normals: list[tuple[float, float, float]] | None = None,
    colors: list[tuple[float, float, float, float]] | None = None,
) -> ChunkIvoSkinMesh900:
    m = ChunkIvoSkinMesh900()
    m.mesh_details = IvoGeometryMeshDetails(
        number_of_vertices=len(verts_uvs),
        number_of_indices=len(indices),
        number_of_submeshes=len(subsets),
    )
    m.mesh_subsets = subsets
    m.verts_uvs = verts_uvs
    m.indices = indices
    if normals is not None:
        m.normals = normals
    if colors is not None:
        m.colors = colors
    return m


def _vu(
    pos: tuple[float, float, float],
    uv: tuple[float, float] = (0.0, 0.0),
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
) -> VertUV:
    return VertUV(vertex=pos, color=color, uv=uv)


def test_build_geometry_ivo_translates_inline_streams_to_mesh_geometry() -> None:
    verts_uvs = [
        _vu((0.0, 0.0, 0.0), (0.0, 0.0)),
        _vu((1.0, 0.0, 0.0), (1.0, 0.0)),
        _vu((0.0, 1.0, 0.0), (0.0, 1.0)),
    ]
    normals = [(0.0, 0.0, 1.0)] * 3
    indices = [0, 1, 2]
    subset = IvoMeshSubset(
        mat_id=4,
        node_parent_index=0,
        first_index=0,
        num_indices=3,
        first_vertex=0,
        num_vertices=3,
    )
    skin = _make_ivo_skin_mesh(
        verts_uvs=verts_uvs,
        indices=indices,
        subsets=[subset],
        normals=normals,
    )

    node = ChunkNode823()
    node.ivo_node_index = 0
    node.mesh_data = skin  # type: ignore[assignment]

    geom = build_geometry(node)
    assert geom is not None
    assert geom.positions == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    assert geom.uvs == [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    assert geom.normals == normals
    assert geom.indices == [0, 1, 2]
    assert geom.colors == [(1.0, 1.0, 1.0, 1.0)] * 3
    assert len(geom.subsets) == 1
    s = geom.subsets[0]
    assert (s.first_index, s.num_indices, s.mat_id) == (0, 3, 4)


def test_build_geometry_ivo_filters_subsets_by_node_parent_index() -> None:
    verts_uvs = [_vu((float(i), 0.0, 0.0)) for i in range(6)]
    indices = list(range(6))
    subsets = [
        IvoMeshSubset(
            mat_id=1,
            node_parent_index=0,
            first_index=0,
            num_indices=3,
            first_vertex=0,
            num_vertices=3,
        ),
        IvoMeshSubset(
            mat_id=2,
            node_parent_index=1,
            first_index=3,
            num_indices=3,
            first_vertex=3,
            num_vertices=3,
        ),
    ]
    skin = _make_ivo_skin_mesh(
        verts_uvs=verts_uvs, indices=indices, subsets=subsets
    )

    node1 = ChunkNode823()
    node1.ivo_node_index = 1
    node1.mesh_data = skin  # type: ignore[assignment]

    geom = build_geometry(node1)
    assert geom is not None
    assert [s.mat_id for s in geom.subsets] == [2]
    # The IVO index buffer is sliced down to only the matching subsets
    # and the vertex pool is compacted, so the surviving subset is
    # rebased to start at 0 of the new (per-node) buffer.
    assert geom.subsets[0].first_index == 0
    assert geom.subsets[0].num_indices == 3
    assert geom.indices == [0, 1, 2]
    assert geom.positions == [(3.0, 0.0, 0.0), (4.0, 0.0, 0.0), (5.0, 0.0, 0.0)]


def test_build_geometry_ivo_returns_none_when_node_has_no_matching_subsets() -> None:
    skin = _make_ivo_skin_mesh(
        verts_uvs=[_vu((0.0, 0.0, 0.0))] * 3,
        indices=[0, 1, 2],
        subsets=[
            IvoMeshSubset(
                mat_id=1,
                node_parent_index=0,
                first_index=0,
                num_indices=3,
                first_vertex=0,
                num_vertices=3,
            )
        ],
    )
    node = ChunkNode823()
    node.ivo_node_index = 99  # no subset binds to this index
    node.mesh_data = skin  # type: ignore[assignment]

    assert build_geometry(node) is None


def test_build_geometry_ivo_skin_root_emits_all_subsets_when_index_unset() -> None:
    """``ivo_node_index is None`` is the skin/chr single-root case
    in :meth:`CryEngine._build_ivo_skin_root` — emit every subset."""
    verts_uvs = [_vu((0.0, 0.0, 0.0))] * 6
    subsets = [
        IvoMeshSubset(
            mat_id=1, node_parent_index=0,
            first_index=0, num_indices=3,
            first_vertex=0, num_vertices=3,
        ),
        IvoMeshSubset(
            mat_id=2, node_parent_index=1,
            first_index=3, num_indices=3,
            first_vertex=3, num_vertices=3,
        ),
    ]
    skin = _make_ivo_skin_mesh(
        verts_uvs=verts_uvs, indices=list(range(6)), subsets=subsets
    )
    node = ChunkNode823()
    assert node.ivo_node_index is None
    node.mesh_data = skin  # type: ignore[assignment]

    geom = build_geometry(node)
    assert geom is not None
    assert [s.mat_id for s in geom.subsets] == [1, 2]


def test_build_geometry_ivo_returns_none_for_empty_skin_mesh() -> None:
    skin = _make_ivo_skin_mesh(verts_uvs=[], indices=[], subsets=[])
    node = ChunkNode823()
    node.mesh_data = skin  # type: ignore[assignment]
    assert build_geometry(node) is None


def test_build_geometry_ivo_prefers_explicit_colors_over_per_vertex_color() -> None:
    verts_uvs = [_vu((0.0, 0.0, 0.0), color=(0.0, 0.0, 0.0, 0.0))] * 3
    explicit = [(1.0, 0.5, 0.25, 1.0)] * 3
    skin = _make_ivo_skin_mesh(
        verts_uvs=verts_uvs,
        indices=[0, 1, 2],
        subsets=[
            IvoMeshSubset(
                mat_id=0, node_parent_index=0,
                first_index=0, num_indices=3,
                first_vertex=0, num_vertices=3,
            )
        ],
        colors=explicit,
    )
    node = ChunkNode823()
    node.ivo_node_index = 0
    node.mesh_data = skin  # type: ignore[assignment]

    geom = build_geometry(node)
    assert geom is not None
    assert geom.colors == explicit
