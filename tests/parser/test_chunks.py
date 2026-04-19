"""Phase 1.4 chunk reader tests.

Each test synthesises the chunk body bytes, drives a chunk subclass
directly, and checks the resulting fields. We use file_version=0x746
(no per-chunk preamble strip) so the synthetic body starts at offset 0.
"""

from __future__ import annotations

import io
import struct

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chunks.mesh_subsets import MeshSubset
from cryengine_importer.core.chunks.data_stream import VertUV, BoneMap
from cryengine_importer.core.model import Model
from cryengine_importer.enums import (
    ChunkType,
    DatastreamType,
    FileVersion,
    HelperType,
    MtlNamePhysicsType,
    MtlNameType,
)
from cryengine_importer.io.binary_reader import BinaryReader


def _drive(chunk_cls_key: tuple[ChunkType, int], body: bytes):
    """Run a chunk's `read` against ``body`` placed at offset 0."""
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


# --------------------------------------------------------------- SourceInfo


def test_source_info_0_no_preamble() -> None:
    body = b"path/to/file.max\x00" b"2024-01-02\x00" b"alice\x00"
    chunk = _drive((ChunkType.SourceInfo, 0x0), body)
    assert chunk.source_file == "path/to/file.max"
    assert chunk.date == "2024-01-02"
    assert chunk.author == "alice"


def test_source_info_0_newline_in_date() -> None:
    body = b"src.max\x00" b"2024-05\nbob\x00"
    chunk = _drive((ChunkType.SourceInfo, 0x0), body)
    assert chunk.source_file == "src.max"
    assert chunk.date == "2024-05"
    assert chunk.author == "bob"


def test_source_info_1() -> None:
    body = b"only/source.path\x00"
    chunk = _drive((ChunkType.SourceInfo, 0x1), body)
    assert chunk.source_file == "only/source.path"


# --------------------------------------------------------------- ExportFlags


def test_export_flags_1() -> None:
    body = struct.pack("<I", int(ChunkType.ExportFlags))  # repeated chunk type
    body += struct.pack("<III", 0x1, 0x100, 42)            # version, offset, id
    body += struct.pack("<I", 0xDEADBEEF)                  # flags (was Skip in C#)
    body += struct.pack("<4I", 1, 2, 3, 4)                 # rc_version
    body += b"3.5.0.0".ljust(16, b"\x00")                  # rc_version_string
    chunk = _drive((ChunkType.ExportFlags, 0x1), body)
    assert chunk.chunk_type == ChunkType.ExportFlags
    assert chunk.version_raw == 0x1
    assert chunk.chunk_offset == 0x100
    assert chunk.id == 42
    assert chunk.flags == 0xDEADBEEF
    assert chunk.rc_version == (1, 2, 3, 4)
    assert chunk.rc_version_string == "3.5.0.0"


# --------------------------------------------------------------- TimingFormat


def test_timing_format_918() -> None:
    body = struct.pack("<f i", 0.001, 30) + b"main".ljust(32, b"\x00") + struct.pack("<ii", 0, 90)
    chunk = _drive((ChunkType.Timing, 0x918), body)
    assert chunk.secs_per_tick == struct.unpack("<f", struct.pack("<f", 0.001))[0]
    assert chunk.ticks_per_frame == 30
    assert chunk.global_range.name == "main"
    assert chunk.global_range.start == 0
    assert chunk.global_range.end == 90


# --------------------------------------------------------------- SceneProp


def test_scene_prop_744() -> None:
    body = struct.pack("<I", 2)
    body += b"key1".ljust(32, b"\x00")
    body += b"key2".ljust(32, b"\x00")
    body += b"value1".ljust(64, b"\x00")
    body += b"value2".ljust(64, b"\x00")
    chunk = _drive((ChunkType.SceneProps, 0x744), body)
    assert chunk.num_props == 2
    assert chunk.prop_keys == ["key1", "key2"]
    assert chunk.prop_values == ["value1", "value2"]


# --------------------------------------------------------------- Helper


def test_helper_744_known_type() -> None:
    body = struct.pack("<I fff", int(HelperType.DUMMY), 1.0, 2.0, 3.0)
    chunk = _drive((ChunkType.Helper, 0x744), body)
    assert chunk.helper_type == HelperType.DUMMY
    assert chunk.pos == (1.0, 2.0, 3.0)


# --------------------------------------------------------------- MtlName


def test_mtl_name_744_single() -> None:
    body = b"steel".ljust(128, b"\x00") + struct.pack("<I", 0)
    chunk = _drive((ChunkType.MtlName, 0x744), body)
    assert chunk.name == "steel"
    assert chunk.num_children == 0
    assert chunk.mat_type == MtlNameType.Single
    assert chunk.physics_type == []


def test_mtl_name_744_library() -> None:
    body = b"lib".ljust(128, b"\x00") + struct.pack("<I", 2)
    body += struct.pack("<II", int(MtlNamePhysicsType.DEFAULT), int(MtlNamePhysicsType.NOCOLLIDE))
    chunk = _drive((ChunkType.MtlName, 0x744), body)
    assert chunk.num_children == 2
    assert chunk.mat_type == MtlNameType.Library
    assert chunk.physics_type == [MtlNamePhysicsType.DEFAULT, MtlNamePhysicsType.NOCOLLIDE]


def test_mtl_name_800() -> None:
    body = struct.pack("<II", int(MtlNameType.Library), 0)
    body += b"top".ljust(128, b"\x00")
    body += struct.pack("<II", int(MtlNamePhysicsType.DEFAULT), 3)  # phys + numChildren
    body += struct.pack("<III", 0xAA, 0xBB, 0xCC)  # ChildIDs
    body += b"\x00" * 32  # fixed pad
    chunk = _drive((ChunkType.MtlName, 0x800), body)
    assert chunk.mat_type == MtlNameType.Library
    assert chunk.name == "top"
    assert chunk.num_children == 3
    assert chunk.child_ids == [0xAA, 0xBB, 0xCC]


# --------------------------------------------------------------- Node


def test_node_823() -> None:
    body = b"root".ljust(64, b"\x00")
    body += struct.pack("<iiiii", 7, -1, 0, 5, 0)  # objId, parent, numChild, mat, pad
    # 4x4 matrix row-major; row 4 (positions) gets *VERTEX_SCALE applied.
    matrix_floats = [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        100.0, 200.0, 300.0, 1,
    ]
    body += struct.pack("<16f", *matrix_floats)
    body += struct.pack("<3f", 0.0, 0.0, 0.0)  # pos
    body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)  # rot
    body += struct.pack("<3f", 1.0, 1.0, 1.0)  # scale
    body += struct.pack("<iiii", -1, -1, -1, 0)  # ctrls + propLen

    chunk = _drive((ChunkType.Node, 0x823), body)
    assert chunk.name == "root"
    assert chunk.object_node_id == 7
    assert chunk.parent_node_id == -1
    assert chunk.material_id == 5
    # Position row scaled by 1/100
    assert chunk.transform[3][:3] == (1.0, 2.0, 3.0)


# --------------------------------------------------------------- Mesh


def test_mesh_800() -> None:
    body = struct.pack("<iiiiI", 0, 0, 24, 36, 1)  # flags1, flags2, nv, ni, nss
    # mesh_subsets, vertsAnim, vertices, normals, uvs, colors, colors2, indices,
    # tangents, sh, shape, bone, face, vertMats, qTan, skin, dummy2, vertsUVs
    body += struct.pack("<18i", *range(100, 118))
    body += struct.pack("<4i", 0, 0, 0, 0)
    body += struct.pack("<3f", 0.0, 0.0, 0.0)  # min
    body += struct.pack("<3f", 1.0, 1.0, 1.0)  # max
    chunk = _drive((ChunkType.Mesh, 0x800), body)
    assert chunk.num_vertices == 24
    assert chunk.num_indices == 36
    assert chunk.num_vert_subsets == 1
    assert chunk.mesh_subsets_data == 100
    assert chunk.vertices_data == 102
    assert chunk.max_bound == (1.0, 1.0, 1.0)


# --------------------------------------------------------------- MeshSubsets


def test_mesh_subsets_800() -> None:
    body = struct.pack("<II", 0, 1)  # flags, num
    body += b"\x00" * 8  # padding
    body += struct.pack("<iiiii f 3f", 0, 36, 0, 24, 7, 1.5, 0.5, 0.5, 0.5)
    chunk = _drive((ChunkType.MeshSubsets, 0x800), body)
    assert chunk.num_mesh_subset == 1
    sub = chunk.mesh_subsets[0]
    assert isinstance(sub, MeshSubset)
    assert sub.num_indices == 36
    assert sub.num_vertices == 24
    assert sub.mat_id == 7
    assert sub.radius == 1.5
    assert sub.center == (0.5, 0.5, 0.5)


# --------------------------------------------------------------- DataStream


def _datastream_800_body(dst: int, n: int, bpe: int, payload: bytes, sc_flag: int = 0) -> bytes:
    head = struct.pack("<III", 0, dst, n)
    head += struct.pack("<HH", bpe, sc_flag)
    head += b"\x00" * 8
    return head + payload


def test_datastream_800_vertices() -> None:
    payload = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    body = _datastream_800_body(int(DatastreamType.VERTICES), 3, 12, payload)
    chunk = _drive((ChunkType.DataStream, 0x800), body)
    assert chunk.data_stream_type == DatastreamType.VERTICES
    assert chunk.data == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]


def test_datastream_800_indices_u16() -> None:
    payload = struct.pack("<6H", 0, 1, 2, 2, 1, 3)
    body = _datastream_800_body(int(DatastreamType.INDICES), 6, 2, payload)
    chunk = _drive((ChunkType.DataStream, 0x800), body)
    assert chunk.data == [0, 1, 2, 2, 1, 3]


def test_datastream_800_uvs() -> None:
    payload = struct.pack("<4f", 0.0, 0.0, 1.0, 1.0)
    body = _datastream_800_body(int(DatastreamType.UVS), 2, 8, payload)
    chunk = _drive((ChunkType.DataStream, 0x800), body)
    assert chunk.data == [(0.0, 0.0), (1.0, 1.0)]


def test_datastream_800_colors_rgba() -> None:
    payload = bytes([255, 0, 0, 255, 0, 255, 0, 128])
    body = _datastream_800_body(int(DatastreamType.COLORS), 2, 4, payload)
    chunk = _drive((ChunkType.DataStream, 0x800), body)
    assert chunk.data[0] == (1.0, 0.0, 0.0, 1.0)
    assert chunk.data[1][3] == 128 / 255.0


def test_datastream_800_bonemap_8byte() -> None:
    payload = bytes([0, 1, 2, 3, 255, 0, 0, 0])  # 4 indices, 4 weights
    body = _datastream_800_body(int(DatastreamType.BONEMAP), 1, 8, payload)
    chunk = _drive((ChunkType.DataStream, 0x800), body)
    bm = chunk.data[0]
    assert isinstance(bm, BoneMap)
    assert bm.bone_index == (0, 1, 2, 3)
    assert bm.weight == (1.0, 0.0, 0.0, 0.0)


def test_datastream_801_indices() -> None:
    head = struct.pack("<III", 0, int(DatastreamType.INDICES), 0)  # flags, type, streamIdx
    head += struct.pack("<I", 3)  # numElements
    head += struct.pack("<Hh", 2, 0)  # bpe, scFlag
    head += b"\x00" * 8
    payload = struct.pack("<3H", 9, 8, 7)
    body = head + payload
    chunk = _drive((ChunkType.DataStream, 0x801), body)
    assert chunk.data == [9, 8, 7]
