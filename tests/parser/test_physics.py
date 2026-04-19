"""Phase 7 — physics & misc tests."""

from __future__ import annotations

import io

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chunks.mesh_physics_data import (
    ChunkMeshPhysicsData,
    ChunkMeshPhysicsData800,
)
from cryengine_importer.core.model import Model
from cryengine_importer.enums import ChunkType, FileVersion
from cryengine_importer.io.binary_reader import BinaryReader


def _drive(chunk_type: ChunkType, version: int, body: bytes):
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


def test_mesh_physics_data_800_registered() -> None:
    inst = make_chunk(ChunkType.MeshPhysicsData, 0x800)
    assert isinstance(inst, ChunkMeshPhysicsData800)
    assert isinstance(inst, ChunkMeshPhysicsData)


def test_mesh_physics_data_800_is_noop_read() -> None:
    """Mirrors the C# ``ChunkMeshPhysicsData_800.Read`` stub: it
    consumes nothing from the stream and leaves the public fields at
    their defaults."""
    body = b"\x01\x02\x03\x04" * 16  # arbitrary payload
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.physics_data_size == 0
    assert chunk.flags == 0
    assert chunk.tetrahedra_data_size == 0
    assert chunk.tetrahedra_id == 0
    assert chunk.reserved1 == 0
    assert chunk.reserved2 == 0


def test_mesh_physics_data_800_empty_chunk() -> None:
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, b"")
    assert isinstance(chunk, ChunkMeshPhysicsData800)
