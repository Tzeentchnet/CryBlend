"""Phase 6 — morph target / blend shape tests."""

from __future__ import annotations

import io
import struct

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chunks.morph_targets import (
    ChunkCompiledMorphTargets,
    ChunkCompiledMorphTargets800,
    ChunkCompiledMorphTargets801,
    ChunkCompiledMorphTargets802,
)
from cryengine_importer.core.mesh_builder import build_geometry
from cryengine_importer.core.model import Model
from cryengine_importer.enums import ChunkType, FileVersion
from cryengine_importer.io.binary_reader import BinaryReader

from .test_mesh_builder import _make_mesh, _make_model, _make_stream
from cryengine_importer.core.chunks.node import ChunkNode823
from cryengine_importer.enums import DatastreamType


# -- helpers --------------------------------------------------------------


def _drive(chunk_cls_key, body: bytes):
    chunk_type, version = chunk_cls_key
    inst = make_chunk(chunk_type, version)
    hdr = ChunkHeader746()
    hdr.chunk_type = chunk_type
    hdr.version_raw = version
    hdr.id = 1
    hdr.offset = 0
    hdr.size = len(body)

    model = Model()
    model.file_version = FileVersion.x0746

    inst.load(model, hdr)  # type: ignore[arg-type]
    inst.read(BinaryReader(io.BytesIO(body)))
    return inst


def _vertex_record(vertex_id: int, x: float, y: float, z: float) -> bytes:
    return struct.pack("<I3f", vertex_id, x, y, z)


# -- chunk reader: 0x800 --------------------------------------------------


def test_compiled_morph_targets_800_registered() -> None:
    inst = make_chunk(ChunkType.CompiledMorphTargets, 0x800)
    assert isinstance(inst, ChunkCompiledMorphTargets800)


def test_compiled_morph_targets_800_reads_count_and_records() -> None:
    body = struct.pack("<I", 2)
    body += _vertex_record(7, 1.0, 2.0, 3.0)
    body += _vertex_record(42, 0.5, -0.25, 0.125)

    chunk = _drive((ChunkType.CompiledMorphTargets, 0x800), body)
    assert isinstance(chunk, ChunkCompiledMorphTargets)
    assert chunk.number_of_morph_targets == 2
    assert len(chunk.morph_target_vertices) == 2

    v0 = chunk.morph_target_vertices[0]
    assert v0.vertex_id == 7
    assert v0.vertex == (1.0, 2.0, 3.0)

    v1 = chunk.morph_target_vertices[1]
    assert v1.vertex_id == 42
    assert v1.vertex == (0.5, -0.25, 0.125)


def test_compiled_morph_targets_800_empty_chunk() -> None:
    body = struct.pack("<I", 0)
    chunk = _drive((ChunkType.CompiledMorphTargets, 0x800), body)
    assert chunk.number_of_morph_targets == 0
    assert chunk.morph_target_vertices == []


# -- chunk reader: 0x801 (no-op, mirrors C#) ------------------------------


def test_compiled_morph_targets_801_is_noop() -> None:
    inst = make_chunk(ChunkType.CompiledMorphTargets, 0x801)
    assert isinstance(inst, ChunkCompiledMorphTargets801)
    chunk = _drive((ChunkType.CompiledMorphTargets, 0x801), b"")
    assert chunk.number_of_morph_targets == 0
    assert chunk.morph_target_vertices == []


# -- chunk reader: 0x802 --------------------------------------------------


def test_compiled_morph_targets_802_same_layout_as_800() -> None:
    inst = make_chunk(ChunkType.CompiledMorphTargets, 0x802)
    assert isinstance(inst, ChunkCompiledMorphTargets802)

    body = struct.pack("<I", 1) + _vertex_record(99, -1.0, 0.0, 1.0)
    chunk = _drive((ChunkType.CompiledMorphTargets, 0x802), body)
    assert chunk.number_of_morph_targets == 1
    assert chunk.morph_target_vertices[0].vertex_id == 99
    assert chunk.morph_target_vertices[0].vertex == (-1.0, 0.0, 1.0)


# -- Star Citizen variant -------------------------------------------------


def test_compiled_morph_targets_sc_routes_to_same_factory() -> None:
    body = struct.pack("<I", 1) + _vertex_record(1, 0.0, 0.0, 0.0)
    chunk = _drive((ChunkType.CompiledMorphTargetsSC, 0x800), body)
    assert isinstance(chunk, ChunkCompiledMorphTargets)
    assert chunk.number_of_morph_targets == 1


# -- mesh_builder integration --------------------------------------------


def _make_morph_chunk(chunk_id: int, records: list[tuple[int, tuple[float, float, float]]]):
    c = ChunkCompiledMorphTargets800()
    c.id = chunk_id
    c.number_of_morph_targets = len(records)
    from cryengine_importer.core.chunks.morph_targets import MorphTargetVertex

    c.morph_target_vertices = [
        MorphTargetVertex(vertex_id=vid, vertex=pos) for vid, pos in records
    ]
    return c


def test_build_geometry_attaches_morph_targets_from_owning_model() -> None:
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    indices = [0, 1, 2]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    morph = _make_morph_chunk(0xAB, [(0, (0.0, 0.0, 1.0)), (2, (1.0, 1.0, 0.0))])

    mesh = _make_mesh(
        10, num_vertices=3, num_indices=3, vertices_id=20, indices_id=23
    )
    _make_model([mesh, v_chunk, i_chunk, morph])

    node = ChunkNode823()
    node.mesh_data = mesh
    geom = build_geometry(node)

    assert geom is not None
    assert len(geom.morph_targets) == 1
    mt = geom.morph_targets[0]
    assert mt.name == "Morph_AB"
    assert mt.vertices == [(0, (0.0, 0.0, 1.0)), (2, (1.0, 1.0, 0.0))]


def test_build_geometry_drops_out_of_range_morph_indices() -> None:
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    indices = [0, 1, 0]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    # vertex_id=5 is past the 2-vertex mesh.
    morph = _make_morph_chunk(0xAB, [(0, (1.0, 1.0, 1.0)), (5, (9.0, 9.0, 9.0))])
    mesh = _make_mesh(
        10, num_vertices=2, num_indices=3, vertices_id=20, indices_id=23
    )
    _make_model([mesh, v_chunk, i_chunk, morph])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert len(geom.morph_targets) == 1
    assert geom.morph_targets[0].vertices == [(0, (1.0, 1.0, 1.0))]


def test_build_geometry_skips_empty_morph_chunks() -> None:
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    indices = [0, 1, 2]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    empty_morph = _make_morph_chunk(0xCD, [])

    mesh = _make_mesh(
        10, num_vertices=3, num_indices=3, vertices_id=20, indices_id=23
    )
    _make_model([mesh, v_chunk, i_chunk, empty_morph])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    assert geom.morph_targets == []


def test_build_geometry_collects_multiple_morph_chunks() -> None:
    verts = [(0.0, 0.0, 0.0)] * 4
    indices = [0, 1, 2, 0, 2, 3]
    v_chunk = _make_stream(20, DatastreamType.VERTICES, verts)
    i_chunk = _make_stream(23, DatastreamType.INDICES, indices)
    m1 = _make_morph_chunk(0x100, [(0, (1.0, 0.0, 0.0))])
    m2 = _make_morph_chunk(0x200, [(1, (0.0, 1.0, 0.0))])

    mesh = _make_mesh(
        10, num_vertices=4, num_indices=6, vertices_id=20, indices_id=23
    )
    _make_model([mesh, v_chunk, i_chunk, m1, m2])
    node = ChunkNode823()
    node.mesh_data = mesh

    geom = build_geometry(node)
    assert geom is not None
    names = sorted(m.name for m in geom.morph_targets)
    assert names == ["Morph_100", "Morph_200"]
