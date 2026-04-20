"""Phase 3 — skinning chunk reader tests."""

from __future__ import annotations

import io
import struct

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.model import Model
from cryengine_importer.enums import ChunkType, FileVersion
from cryengine_importer.io.binary_reader import BinaryReader
import pytest

from cryengine_importer.models.skinning import (
    BonePhysicsGeometry,
    read_bone_physics_geometry,
)


# -- helper ---------------------------------------------------------------


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
    br = BinaryReader(io.BytesIO(body))
    inst.read(br)
    return inst


def _zero(n: int) -> bytes:
    return b"\x00" * n


# -- CompiledBones 0x800 --------------------------------------------------


_PHYSICS_BLOCK = 208  # two PhysicsGeometry records


def _bone_800_record(
    *,
    name: str,
    controller_id: int,
    offset_parent: int,
    num_children: int,
    offset_child: int,
    local_translation=(0.0, 0.0, 0.0),
    world_translation=(0.0, 0.0, 0.0),
) -> bytes:
    body = struct.pack("<I", controller_id)
    body += _zero(_PHYSICS_BLOCK)
    body += struct.pack("<f", 1.0)  # mass
    # local 3x4 — identity rotation, translation in M14/M24/M34
    body += struct.pack(
        "<12f",
        1, 0, 0, local_translation[0],
        0, 1, 0, local_translation[1],
        0, 0, 1, local_translation[2],
    )
    # world 3x4
    body += struct.pack(
        "<12f",
        1, 0, 0, world_translation[0],
        0, 1, 0, world_translation[1],
        0, 0, 1, world_translation[2],
    )
    name_bytes = name.encode("ascii").ljust(256, b"\x00")
    body += name_bytes
    body += struct.pack("<IiiI", 0xFFFFFFFF, offset_parent, num_children, offset_child)
    assert len(body) == 584, len(body)
    return body


def test_compiled_bones_800_root_only() -> None:
    body = _zero(32) + _bone_800_record(
        name="root",
        controller_id=0xCAFEBABE,
        offset_parent=0,
        num_children=0,
        offset_child=0,
        world_translation=(1.0, 2.0, 3.0),
    )
    chunk = _drive((ChunkType.CompiledBones, 0x800), body)
    assert chunk.num_bones == 1
    bone = chunk.bone_list[0]
    assert bone.bone_name == "root"
    assert bone.controller_id == 0xCAFEBABE
    assert bone.parent_bone is None
    assert bone.world_transform_matrix[0][3] == 1.0
    assert bone.world_transform_matrix[1][3] == 2.0
    assert bone.world_transform_matrix[2][3] == 3.0


def test_compiled_bones_800_parent_link() -> None:
    body = _zero(32)
    body += _bone_800_record(
        name="root", controller_id=1,
        offset_parent=0, num_children=1, offset_child=1,
    )
    body += _bone_800_record(
        name="child", controller_id=2,
        offset_parent=-1, num_children=0, offset_child=0,
        local_translation=(0.0, 0.5, 0.0),
    )
    chunk = _drive((ChunkType.CompiledBones, 0x800), body)
    assert chunk.num_bones == 2
    assert chunk.bone_list[0].parent_bone is None
    assert chunk.bone_list[1].parent_bone is chunk.bone_list[0]
    assert chunk.bone_list[1].parent_controller_index == 0


# -- CompiledBones 0x801 --------------------------------------------------


def _bone_801_record(*, name: str, offset_parent: int) -> bytes:
    body = struct.pack("<II", 0xAA, 0xBB)  # controller, limb
    body += _zero(_PHYSICS_BLOCK)
    body += name.encode("ascii").ljust(48, b"\x00")
    body += struct.pack("<iii", offset_parent, 0, 0)
    body += struct.pack("<12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
    assert len(body) == 324, len(body)
    return body


def test_compiled_bones_801_size() -> None:
    body = _zero(32) + _bone_801_record(name="root", offset_parent=0) + _zero(16)
    # Reference uses (size - 48) / 324; pad an extra 16 to satisfy.
    chunk = _drive((ChunkType.CompiledBones, 0x801), body)
    assert chunk.num_bones == 1
    assert chunk.bone_list[0].bone_name == "root"


# -- CompiledIntSkinVertices ---------------------------------------------


def test_compiled_int_skin_vertices_800() -> None:
    body = _zero(32)
    # 64-byte record: 3*vec3 + 4 ushort + 4 float + 4 byte color
    body += struct.pack("<3f", 0.0, 0.0, 0.0)  # obsolete0
    body += struct.pack("<3f", 1.0, 2.0, 3.0)  # position
    body += struct.pack("<3f", 0.0, 0.0, 0.0)  # obsolete2
    body += struct.pack("<4H", 0, 1, 2, 3)
    body += struct.pack("<4f", 0.5, 0.25, 0.125, 0.125)
    body += struct.pack("<4B", 255, 128, 0, 255)
    chunk = _drive((ChunkType.CompiledIntSkinVertices, 0x800), body)
    assert chunk.num_int_vertices == 1
    v = chunk.int_skin_vertices[0]
    assert v.position == (1.0, 2.0, 3.0)
    assert v.bone_mapping.bone_index == (0, 1, 2, 3)
    assert v.bone_mapping.weight == (0.5, 0.25, 0.125, 0.125)


def test_compiled_int_skin_vertices_801() -> None:
    body = _zero(32)
    body += struct.pack("<3f", 1.0, 2.0, 3.0)
    body += struct.pack("<4H", 5, 6, 7, 8)
    body += struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
    body += struct.pack("<4B", 0, 0, 0, 255)
    chunk = _drive((ChunkType.CompiledIntSkinVertices, 0x801), body)
    assert chunk.num_int_vertices == 1
    assert chunk.int_skin_vertices[0].bone_mapping.bone_index == (5, 6, 7, 8)


# -- CompiledIntFaces ----------------------------------------------------


def test_compiled_int_faces_800() -> None:
    body = struct.pack("<3H", 0, 1, 2) + struct.pack("<3H", 2, 3, 0)
    chunk = _drive((ChunkType.CompiledIntFaces, 0x800), body)
    assert chunk.num_int_faces == 2
    assert (chunk.faces[0].i0, chunk.faces[0].i1, chunk.faces[0].i2) == (0, 1, 2)
    assert (chunk.faces[1].i0, chunk.faces[1].i1, chunk.faces[1].i2) == (2, 3, 0)


# -- CompiledExtToIntMap -------------------------------------------------


def test_compiled_ext_to_int_map_800() -> None:
    body = struct.pack("<5H", 0, 0, 1, 2, 3)
    chunk = _drive((ChunkType.CompiledExt2IntMap, 0x800), body)
    assert chunk.num_ext_vertices == 5
    assert chunk.source == [0, 0, 1, 2, 3]


# -- CompiledPhysicalProxies ---------------------------------------------


def test_compiled_physical_proxies_800() -> None:
    body = struct.pack("<I", 1)  # num proxies
    body += struct.pack("<IIII", 0xDEAD, 3, 3, 0)  # id, nVerts, nIndices, material
    body += struct.pack("<3f", 0, 0, 0)
    body += struct.pack("<3f", 1, 0, 0)
    body += struct.pack("<3f", 0, 1, 0)
    body += struct.pack("<3H", 0, 1, 2)
    chunk = _drive((ChunkType.CompiledPhysicalProxies, 0x800), body)
    assert chunk.num_physical_proxies == 1
    p = chunk.physical_proxies[0]
    assert p.id == 0xDEAD
    assert len(p.vertices) == 3
    assert p.indices == [0, 1, 2]


# -- CompiledPhysicalBones -----------------------------------------------


def _phys_bone_800_record(*, controller_id: int, parent_offset: int) -> bytes:
    body = struct.pack(
        "<IIII", 0, parent_offset & 0xFFFFFFFF, 0, controller_id
    )
    body += _zero(32)  # prop
    body += _zero(104)  # PhysicsGeometry
    assert len(body) == 152, len(body)
    return body


def test_compiled_physical_bones_800() -> None:
    body = _zero(32)
    body += _phys_bone_800_record(controller_id=1, parent_offset=0)
    body += _phys_bone_800_record(controller_id=2, parent_offset=-1)
    chunk = _drive((ChunkType.CompiledPhysicalBones, 0x800), body)
    assert chunk.num_bones == 2
    assert chunk.physical_bone_list[0].controller_id == 1
    assert chunk.physical_bone_list[1].controller_id == 2
    assert chunk.physical_bone_list[1].parent_id == 1
    assert 2 in chunk.physical_bone_list[0].child_ids


# -- BoneNameList --------------------------------------------------------


def test_bone_name_list_745() -> None:
    body = struct.pack("<i", 3) + b"root\x00" + b"hip\x00" + b"thigh\x00"
    chunk = _drive((ChunkType.BoneNameList, 0x745), body)
    assert chunk.num_entities == 3
    assert chunk.bone_names == ["root", "hip", "thigh"]


# -- BonePhysicsGeometry decode (Phase 10) --------------------------------


def _physics_geometry_record(
    *,
    physics_geom: int = 0,
    flags: int = 0,
    aabb_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    aabb_max: tuple[float, float, float] = (0.0, 0.0, 0.0),
    spring_angle: tuple[float, float, float] = (0.0, 0.0, 0.0),
    spring_tension: tuple[float, float, float] = (0.0, 0.0, 0.0),
    damping: tuple[float, float, float] = (0.0, 0.0, 0.0),
    frame_matrix: tuple[tuple[float, ...], ...] = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ),
) -> bytes:
    body = struct.pack("<II", physics_geom, flags)
    body += struct.pack("<3f", *aabb_min)
    body += struct.pack("<3f", *aabb_max)
    body += struct.pack("<3f", *spring_angle)
    body += struct.pack("<3f", *spring_tension)
    body += struct.pack("<3f", *damping)
    for row in frame_matrix:
        body += struct.pack("<3f", *row)
    assert len(body) == 104, len(body)
    return body


def test_read_bone_physics_geometry_decodes_full_record() -> None:
    record = _physics_geometry_record(
        physics_geom=0x12345678,
        flags=0x0C,
        aabb_min=(-1.0, -2.0, -3.0),
        aabb_max=(1.0, 2.0, 3.0),
        spring_angle=(0.1, 0.2, 0.3),
        spring_tension=(10.0, 20.0, 30.0),
        damping=(0.5, 0.6, 0.7),
        frame_matrix=((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    )
    geom = read_bone_physics_geometry(BinaryReader(io.BytesIO(record)))
    assert isinstance(geom, BonePhysicsGeometry)
    assert geom.physics_geom == 0x12345678
    assert geom.flags == 0x0C
    assert geom.min == (-1.0, -2.0, -3.0)
    assert geom.max == (1.0, 2.0, 3.0)
    assert geom.spring_angle == pytest.approx((0.1, 0.2, 0.3), rel=1e-6)
    assert geom.spring_tension == (10.0, 20.0, 30.0)
    assert geom.damping == pytest.approx((0.5, 0.6, 0.7), rel=1e-6)
    assert geom.frame_matrix == ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert not geom.is_empty
    assert geom.center == (0.0, 0.0, 0.0)
    assert geom.extent == (1.0, 2.0, 3.0)


def test_bone_physics_geometry_is_empty_default() -> None:
    record = _physics_geometry_record()
    geom = read_bone_physics_geometry(BinaryReader(io.BytesIO(record)))
    assert geom.is_empty
    assert geom.extent == (0.0, 0.0, 0.0)


def test_compiled_bones_800_decodes_physics_geometry() -> None:
    """Patch a non-zero ``PhysicsGeometry`` block into the bone record
    fixture and confirm both alive + dead LODs are populated."""
    alive = _physics_geometry_record(
        physics_geom=0xAA, aabb_min=(-0.5, -0.5, -0.5), aabb_max=(0.5, 0.5, 0.5)
    )
    dead = _physics_geometry_record(physics_geom=0xBB)

    body = struct.pack("<I", 0xCAFE)  # controller_id
    body += alive + dead
    body += struct.pack("<f", 1.0)  # mass
    body += struct.pack(
        "<12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0
    )  # local 3x4
    body += struct.pack(
        "<12f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0
    )  # world 3x4
    body += b"root".ljust(256, b"\x00")
    body += struct.pack("<IiiI", 0xFFFFFFFF, 0, 0, 0)
    assert len(body) == 584

    chunk = _drive((ChunkType.CompiledBones, 0x800), _zero(32) + body)
    bone = chunk.bone_list[0]
    assert bone.physics_alive is not None
    assert bone.physics_alive.physics_geom == 0xAA
    assert bone.physics_alive.min == (-0.5, -0.5, -0.5)
    assert bone.physics_alive.max == (0.5, 0.5, 0.5)
    assert bone.physics_dead is not None
    assert bone.physics_dead.physics_geom == 0xBB
    # Min/max are zero on the dead LOD even though physics_geom != 0.
    assert bone.physics_dead.min == bone.physics_dead.max == (0.0, 0.0, 0.0)


def test_compiled_physical_bones_800_decodes_physics_geometry() -> None:
    body = struct.pack("<IIII", 0, 0, 0, 0xC001)  # bone, parent_off, nChild, ctrl
    body += _zero(32)  # prop char[32]
    body += _physics_geometry_record(
        physics_geom=0xDEAD,
        flags=0x05,
        aabb_min=(-1.0, 0.0, 0.0),
        aabb_max=(1.0, 0.5, 0.25),
    )
    assert len(body) == 152

    chunk = _drive((ChunkType.CompiledPhysicalBones, 0x800), _zero(32) + body)
    bone = chunk.physical_bone_list[0]
    assert bone.controller_id == 0xC001
    assert bone.physics_geometry is not None
    assert bone.physics_geometry.physics_geom == 0xDEAD
    assert bone.physics_geometry.flags == 0x05
    assert bone.physics_geometry.center == (0.0, 0.25, 0.125)
    assert bone.physics_geometry.extent == (1.0, 0.25, 0.125)
