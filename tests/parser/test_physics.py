"""Phase 7 / Phase 10 — physics & misc tests."""

from __future__ import annotations

import io
import struct

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chunks.mesh_physics_data import (
    ChunkMeshPhysicsData,
    ChunkMeshPhysicsData800,
)
from cryengine_importer.core.model import Model
from cryengine_importer.enums import ChunkType, FileVersion
from cryengine_importer.io.binary_reader import BinaryReader
from cryengine_importer.models.physics import (
    PhysicsCube,
    PhysicsCylinder,
    PhysicsData,
    PhysicsPrimitiveType,
    read_physics_cube,
    read_physics_cylinder,
    read_physics_data,
)


# ---------------------------------------------------------------- helpers --


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


def _mat3() -> bytes:
    return struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1)


def _struct1_bytes() -> bytes:
    # Matrix33 + i32 + 6 floats = 64 bytes
    return _mat3() + struct.pack("<i", 7) + struct.pack("<6f", 1, 2, 3, 4, 5, 6)


def _data_type2_bytes() -> bytes:
    # Matrix33 + i32 + 6 floats + i32 = 68 bytes
    return _mat3() + struct.pack("<i", 9) + struct.pack("<6f", 1, 2, 3, 4, 5, 6) + struct.pack("<i", 11)


def _physics_data_prefix(primitive_type: int) -> bytes:
    # 60 bytes: 2 ints + 3 floats + quat + vec3 + float + 2 ints + 2 floats + uint
    return (
        struct.pack("<ii", 1, 0)
        + struct.pack("<3f", 0.1, 0.2, 0.3)  # inertia
        + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)  # rot quat
        + struct.pack("<3f", 1.0, 2.0, 3.0)  # center
        + struct.pack("<f", 42.0)  # mass
        + struct.pack("<ii", 1, 0)
        + struct.pack("<2f", 0.0, 0.0)
        + struct.pack("<I", primitive_type)
    )


# ---------------------------------------------------------- registration --


def test_mesh_physics_data_800_registered() -> None:
    inst = make_chunk(ChunkType.MeshPhysicsData, 0x800)
    assert isinstance(inst, ChunkMeshPhysicsData800)
    assert isinstance(inst, ChunkMeshPhysicsData)


# --------------------------------------------------------- empty / header --


def test_mesh_physics_data_800_empty_chunk() -> None:
    """Empty chunk (size==0) keeps all fields at defaults."""
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, b"")
    assert isinstance(chunk, ChunkMeshPhysicsData800)
    assert chunk.physics_data_size == 0
    assert chunk.physics_data is None
    assert chunk.tetrahedra_data == b""


def test_mesh_physics_data_800_header_only_no_payload() -> None:
    """24-byte header with physics_data_size==0 and no tetrahedra."""
    body = struct.pack("<6I", 0, 0xC0DE, 0, 99, 0, 0)
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.physics_data_size == 0
    assert chunk.flags == 0xC0DE
    assert chunk.tetrahedra_id == 99
    assert chunk.physics_data is None
    assert chunk.tetrahedra_data == b""


def test_mesh_physics_data_800_tetrahedra_only() -> None:
    """Header + tetrahedra payload, no PhysicsData."""
    payload = bytes(range(8))
    body = struct.pack("<6I", 0, 0, len(payload), 7, 0, 0) + payload
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.tetrahedra_data_size == 8
    assert chunk.tetrahedra_data == payload
    assert chunk.physics_data is None


def test_mesh_physics_data_800_tetrahedra_capped_by_chunk_size() -> None:
    """If tetrahedra_data_size overruns the chunk, we read only what's there."""
    # claim 1024 bytes but only provide 4
    payload = b"\xaa\xbb\xcc\xdd"
    body = struct.pack("<6I", 0, 0, 1024, 0, 0, 0) + payload
    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.tetrahedra_data_size == 1024
    assert chunk.tetrahedra_data == payload  # capped at 4


# ---------------------------------------------------- PhysicsData payload --


def test_physics_data_prefix_only_unknown_primitive() -> None:
    """Unknown primitive-type values leave both ``cube`` and ``cylinder`` None."""
    body = _physics_data_prefix(99)
    pd = read_physics_data(BinaryReader(io.BytesIO(body)))
    assert pd.primitive_type == 99
    assert pd.primitive is None
    assert pd.cube is None
    assert pd.cylinder is None
    assert pd.polyhedron_skipped is False
    assert pd.mass == 42.0
    assert pd.center == (1.0, 2.0, 3.0)


def test_physics_data_polyhedron_is_skipped_with_flag() -> None:
    """Polyhedron primitive is recorded but its payload is not decoded."""
    body = _physics_data_prefix(int(PhysicsPrimitiveType.POLYHEDRON))
    pd = read_physics_data(BinaryReader(io.BytesIO(body)))
    assert pd.primitive is PhysicsPrimitiveType.POLYHEDRON
    assert pd.polyhedron_skipped is True
    assert pd.cube is None
    assert pd.cylinder is None


def test_physics_cube_decoded() -> None:
    body = _struct1_bytes() + _struct1_bytes() + struct.pack("<i", 13)
    cube = read_physics_cube(BinaryReader(io.BytesIO(body)))
    assert isinstance(cube, PhysicsCube)
    assert cube.unknown_16 == 13
    assert cube.a.unknown_2 == 7
    assert cube.b.unknown_3 == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)


def test_physics_cylinder_decoded() -> None:
    body = (
        struct.pack("<8f", 1, 2, 3, 4, 5, 6, 7, 8)
        + struct.pack("<i", 17)
        + _data_type2_bytes()
    )
    cyl = read_physics_cylinder(BinaryReader(io.BytesIO(body)))
    assert isinstance(cyl, PhysicsCylinder)
    assert cyl.unknown_2 == 17
    assert cyl.unknown_3.unknown_4 == 11


# ----------------------------------------- end-to-end via ChunkMeshPhysicsData


def test_mesh_physics_data_800_with_cube_payload() -> None:
    cube_bytes = _struct1_bytes() + _struct1_bytes() + struct.pack("<i", 13)
    pd_bytes = _physics_data_prefix(int(PhysicsPrimitiveType.CUBE)) + cube_bytes
    body = struct.pack("<6I", len(pd_bytes), 0, 0, 5, 0, 0) + pd_bytes

    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.physics_data_size == len(pd_bytes)
    assert chunk.tetrahedra_id == 5
    assert isinstance(chunk.physics_data, PhysicsData)
    assert chunk.physics_data.primitive is PhysicsPrimitiveType.CUBE
    assert chunk.physics_data.cube is not None
    assert chunk.physics_data.cube.unknown_16 == 13


def test_mesh_physics_data_800_with_cylinder_payload_and_tetrahedra() -> None:
    cyl_bytes = (
        struct.pack("<8f", 1, 2, 3, 4, 5, 6, 7, 8)
        + struct.pack("<i", 17)
        + _data_type2_bytes()
    )
    pd_bytes = _physics_data_prefix(int(PhysicsPrimitiveType.CYLINDER)) + cyl_bytes
    tet = b"TETRAHED"
    body = (
        struct.pack("<6I", len(pd_bytes), 0, len(tet), 0, 0, 0)
        + pd_bytes
        + tet
    )

    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.physics_data is not None
    assert chunk.physics_data.primitive is PhysicsPrimitiveType.CYLINDER
    assert chunk.physics_data.cylinder is not None
    assert chunk.physics_data.cylinder.unknown_2 == 17
    assert chunk.tetrahedra_data == tet


def test_mesh_physics_data_800_unknown6_uses_cylinder_layout() -> None:
    """PrimitiveType.UNKNOWN6 (6) uses the same 104-byte layout as CYLINDER."""
    cyl_bytes = (
        struct.pack("<8f", 0, 0, 0, 0, 0, 0, 0, 0)
        + struct.pack("<i", 0)
        + _data_type2_bytes()
    )
    pd_bytes = _physics_data_prefix(int(PhysicsPrimitiveType.UNKNOWN6)) + cyl_bytes
    body = struct.pack("<6I", len(pd_bytes), 0, 0, 0, 0, 0) + pd_bytes

    chunk = _drive(ChunkType.MeshPhysicsData, 0x800, body)
    assert chunk.physics_data is not None
    assert chunk.physics_data.primitive is PhysicsPrimitiveType.UNKNOWN6
    assert chunk.physics_data.cylinder is not None
    assert chunk.physics_data.cube is None
