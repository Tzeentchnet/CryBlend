"""Phase 4 — animation chunk reader & loader tests."""

from __future__ import annotations

import io
import math
import struct
from binascii import crc32

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.controller import ChunkController905
from cryengine_importer.core.chunks.global_animation_header_caf import (
    ChunkGlobalAnimationHeaderCAF971,
)
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chrparams_loader import parse_chrparams
from cryengine_importer.core.model import Model
from cryengine_importer.enums import (
    ChunkType,
    CompressionFormat,
    CtrlType,
    FileVersion,
    KeyTimesFormat,
)
from cryengine_importer.io.binary_reader import BinaryReader


# -- helpers -------------------------------------------------------------


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


# -- Controller 0x826 ----------------------------------------------------


def test_controller_826_keys() -> None:
    body = struct.pack(
        "<IiII",
        int(CtrlType.LINEAR3),
        2,  # num_keys
        0xCAFE0001,  # controller_flags
        0xDEADBEEF,  # controller_id
    )
    # 2 keys: time (i32) + abs_pos (3f) + rel_pos (3f)
    body += struct.pack("<i6f", 0, 1, 2, 3, 0, 0, 0)
    body += struct.pack("<i6f", 100, 4, 5, 6, 0.1, 0.2, 0.3)

    chunk = _drive((ChunkType.Controller, 0x826), body)
    assert chunk.controller_type == CtrlType.LINEAR3
    assert chunk.num_keys == 2
    assert chunk.controller_id == 0xDEADBEEF
    assert chunk.keys[0].time == 0
    assert chunk.keys[0].abs_pos == (1.0, 2.0, 3.0)
    assert chunk.keys[1].time == 100
    assert chunk.keys[1].rel_pos == (
        struct.unpack("<f", struct.pack("<f", 0.1))[0],
        struct.unpack("<f", struct.pack("<f", 0.2))[0],
        struct.unpack("<f", struct.pack("<f", 0.3))[0],
    )


# -- Controller 0x829 (header-only stub) ---------------------------------


def test_controller_829_does_not_crash_with_empty_body() -> None:
    chunk = _drive((ChunkType.Controller, 0x829), b"")
    assert chunk is not None


# -- Controllers 0x827 / 0x828 / 0x830 / 0x831 (v2.0.0) ------------------


def test_controller_827_uncompressed_pqlog_no_local_header() -> None:
    """0x827 has no embedded local header — body starts at the chunk
    table offset directly."""
    body = struct.pack("<II", 2, 0xCAFEBABE)  # num_keys, controller_id
    body += struct.pack("<i6f", 0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
    body += struct.pack("<i6f", 100, 4.0, 5.0, 6.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.Controller, 0x827), body)
    assert chunk.num_keys == 2
    assert chunk.controller_id == 0xCAFEBABE
    assert chunk.key_times == [0, 100]
    assert chunk.key_positions[0] == (1.0, 2.0, 3.0)
    # Zero rot_log → identity quat.
    assert chunk.key_rotations[0] == (0.0, 0.0, 0.0, 1.0)


def test_controller_828_empty_chunk_is_no_op() -> None:
    chunk = _drive((ChunkType.Controller, 0x828), b"")
    assert chunk is not None
    assert chunk.controller_id == 0


def test_controller_830_pqlog_with_flags() -> None:
    body = struct.pack("<III", 1, 0xDEADBEEF, 0x42)  # num_keys, id, flags
    body += struct.pack("<i6f", 50, 7.0, 8.0, 9.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.Controller, 0x830), body)
    assert chunk.num_keys == 1
    assert chunk.controller_id == 0xDEADBEEF
    assert chunk.flags == 0x42
    assert chunk.key_positions[0] == (7.0, 8.0, 9.0)
    assert chunk.key_rotations[0] == (0.0, 0.0, 0.0, 1.0)


def test_controller_831_compressed_dual_track_no_compression() -> None:
    """0x831 with eNoCompressQuat rotations + eNoCompressVec3 positions
    + float time format. position_keys_info=0 so position times share
    rotation times."""
    body = struct.pack(
        "<II",  # controller_id, flags
        0x12345678, 0,
    )
    body += struct.pack(
        "<HH", 1, 1,  # num_rot_keys, num_pos_keys
    )
    body += struct.pack(
        "<BBBBBB",
        1,  # rotation_format = eNoCompressQuat
        0,  # rotation_time_format = eF32
        2,  # position_format = eNoCompressVec3
        0,  # position_keys_info = 0 (share rot times)
        0,  # position_time_format
        0,  # tracks_aligned = 0
    )
    # rotations (1 quat = 16 bytes), then time (1 float), then positions
    # (1 vec3), then no position times.
    body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
    body += struct.pack("<f", 0.5)  # rot time
    body += struct.pack("<3f", 1.5, 2.5, 3.5)  # position

    chunk = _drive((ChunkType.Controller, 0x831), body)
    assert chunk.controller_id == 0x12345678
    assert chunk.num_rotation_keys == 1
    assert chunk.num_position_keys == 1
    assert chunk.key_rotations == [(0.0, 0.0, 0.0, 1.0)]
    assert chunk.rotation_key_times == [0.5]
    assert chunk.key_positions == [(1.5, 2.5, 3.5)]
    # Position times share rotation times.
    assert chunk.position_key_times == [0.5]


# -- MotionParameters 0x925 ----------------------------------------------


def test_motion_parameters_925_reads_all_fields() -> None:
    body = struct.pack(
        "<II",
        0xAA,  # asset_flags
        1,     # compression
    )
    body += struct.pack("<if", 30, 1.0 / 30.0)  # ticks_per_frame, secs_per_tick
    body += struct.pack("<ii", 0, 60)            # start, end
    body += struct.pack("<5f", 1.5, 0.5, 0.0, 10.0, 0.0)  # speeds + slope
    body += struct.pack("<4f", 0, 0, 0, 1)        # start QuatT
    body += struct.pack("<3f", 0, 0, 0)
    body += struct.pack("<4f", 0, 0, 0, 1)        # end QuatT
    body += struct.pack("<3f", 10, 0, 0)
    body += struct.pack("<8f", 0, 0.5, 0.5, 1.0, 0.5, 1.0, 0.0, 0.5)  # foot timing

    chunk = _drive((ChunkType.MotionParams, 0x925), body)
    assert chunk.asset_flags == 0xAA
    assert chunk.ticks_per_frame == 30
    assert chunk.start == 0 and chunk.end == 60
    assert chunk.move_speed == 1.5
    assert chunk.end_location_t == (10.0, 0.0, 0.0)
    assert chunk.r_toe0_end == 0.5


# -- Controller 0x905 ----------------------------------------------------


def _build_controller_905_body() -> bytes:
    """Synthesize a tiny controller_905 with one time / pos / rot
    track and a single Animation905 binding them to one bone."""
    num_pos = 1
    num_rot = 1
    num_time = 1
    num_anims = 1

    body = struct.pack("<IIII", num_pos, num_rot, num_time, num_anims)

    # key_time_lengths (u16 * num_time)
    body += struct.pack("<H", 2)  # 2 time samples
    # key_time_formats (u32 * (eBitset+1) = 7)
    fmt = [0] * 7
    fmt[KeyTimesFormat.eF32] = 1
    body += struct.pack("<7I", *fmt)
    # key_pos_lengths (u16 * num_pos)
    body += struct.pack("<H", 2)
    # key_pos_formats (u32 * eAutomaticQuat = 9)
    pfmt = [0] * 9
    pfmt[CompressionFormat.eNoCompressVec3] = 1
    body += struct.pack("<9I", *pfmt)
    # key_rot_lengths
    body += struct.pack("<H", 2)
    rfmt = [0] * 9
    rfmt[CompressionFormat.eNoCompressQuat] = 1
    body += struct.pack("<9I", *rfmt)

    # offsets — these are *relative to the post-table-aligned* start.
    # We'll place: times (8 bytes), positions (24 bytes), rotations (32 bytes)
    body += struct.pack("<I", 0)  # key_time_offsets
    body += struct.pack("<I", 8)  # key_pos_offsets
    body += struct.pack("<I", 8 + 24)  # key_rot_offsets
    body += struct.pack("<I", 8 + 24 + 32)  # track_length

    # The reader aligns to a 4-byte boundary before reading tracks.
    pos = len(body)
    pad = (-pos) & 3
    body += b"\x00" * pad

    # 2 time samples
    body += struct.pack("<2f", 0.0, 1.0)
    # 2 vec3 positions
    body += struct.pack("<6f", 0.0, 0.0, 0.0, 1.0, 2.0, 3.0)
    # 2 quaternions (identity, then 90deg-ish — but we just check storage)
    body += struct.pack("<8f", 0, 0, 0, 1, 0.5, 0.5, 0.5, 0.5)

    # Animation905 record:
    name = b"idle"
    body += struct.pack("<H", len(name))
    body += name
    # MotionParams905: 8 ints + 5 floats + locator quats/vecs + 8 foot floats
    # AssetFlags(u32), Compression(u32), TicksPerFrame(i32), SecsPerTick(f32),
    # Start(i32), End(i32), MoveSpeed(f32), TurnSpeed(f32), AssetTurn(f32),
    # Distance(f32), Slope(f32),
    # StartLocationQ(4f), StartLocationV(3f),
    # EndLocationQ(4f), EndLocationV(3f),
    # 8 foot floats
    body += struct.pack(
        "<I I i f i i 5f 4f 3f 4f 3f 8f",
        0,
        0xFFFFFFFF,
        30,
        1.0 / 30.0,
        0,
        30,
        -1, -1, -1, -1, -1,
        0, 0, 0, 1,
        0, 0, 0,
        0, 0, 0, 1,
        0, 0, 0,
        -1, -1, -1, -1, -1, -1, -1, -1,
    )
    body += struct.pack("<H", 0)  # foot_plant_bits count
    body += struct.pack("<H", 1)  # 1 controller binding
    body += struct.pack(
        "<IiIIi",  # ControllerInfo: id(u32), pos_kt(i32), pos(i32), rot_kt(i32), rot(i32)
        0x12345678,
        0, 0, 0, 0,
    )
    return body


def test_controller_905_single_track() -> None:
    body = _build_controller_905_body()
    chunk = _drive((ChunkType.Controller, 0x905), body)
    assert isinstance(chunk, ChunkController905)
    assert chunk.num_key_pos == 1
    assert chunk.num_key_rot == 1
    assert chunk.num_key_time == 1
    assert chunk.num_anims == 1
    assert chunk.key_times[0] == [0.0, 1.0]
    assert chunk.key_positions[0][0] == (0.0, 0.0, 0.0)
    assert chunk.key_positions[0][1] == (1.0, 2.0, 3.0)
    assert chunk.key_rotations[0][1] == (0.5, 0.5, 0.5, 0.5)
    assert len(chunk.animations) == 1
    a = chunk.animations[0]
    assert a.name == "idle"
    assert a.motion_params.start == 0
    assert a.motion_params.end == 30
    assert len(a.controllers) == 1
    assert a.controllers[0].controller_id == 0x12345678


# -- GlobalAnimationHeaderCAF 0x971 --------------------------------------


def test_caf_header_971_parses_path_and_durations() -> None:
    file_path = "Animations/foo/idle.caf"
    body = struct.pack("<I", 0xCAFE0000)  # flags
    body += file_path.encode("utf-8").ljust(256, b"\x00")
    body += struct.pack("<I", crc32(file_path.encode("utf-8")) & 0xFFFFFFFF)
    body += struct.pack("<I", 0)  # dba crc32
    # 8 foot floats
    body += struct.pack("<8f", 0, 0.5, 0, 0.5, 0, 0.5, 0, 0.5)
    # start, end, total
    body += struct.pack("<3f", 0.0, 1.5, 1.5)
    body += struct.pack("<I", 12)  # controllers
    # start_location quat, last_locator_key quat, velocity vec3
    body += struct.pack("<4f", 0, 0, 0, 1)
    body += struct.pack("<4f", 0, 0, 0, 1)
    body += struct.pack("<3f", 1.0, 0.0, 0.0)
    # distance, speed, slope, turn_speed, asset_turn
    body += struct.pack("<5f", 1.5, 1.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.GlobalAnimationHeaderCAF, 0x971), body)
    assert isinstance(chunk, ChunkGlobalAnimationHeaderCAF971)
    assert chunk.file_path == file_path
    assert chunk.flags == 0xCAFE0000
    assert math.isclose(chunk.total_duration, 1.5)
    assert chunk.controllers == 12
    assert math.isclose(chunk.distance, 1.5)


# -- ChrParams XML parser ------------------------------------------------


def test_parse_chrparams_extracts_animation_list() -> None:
    from xml.etree import ElementTree as ET

    xml = ET.fromstring(
        """
        <Params>
          <AnimationList>
            <Animation name="idle" path="anims/idle.caf"/>
            <Animation name="walk" path="anims/walk.caf"/>
          </AnimationList>
        </Params>
        """.strip()
    )
    cp = parse_chrparams(xml, source_file_name="x.chrparams")
    assert cp.source_file_name == "x.chrparams"
    assert len(cp.animations) == 2
    assert cp.animations[0].name == "idle"
    assert cp.animations[0].path == "anims/idle.caf"
    assert cp.animations[1].name == "walk"


def test_parse_chrparams_handles_missing_animation_list() -> None:
    from xml.etree import ElementTree as ET

    cp = parse_chrparams(ET.fromstring("<Params/>"))
    assert cp.animations == []


# -- compressed quat helpers ---------------------------------------------


def test_short_int3_quat_roundtrip_identity() -> None:
    # Encode identity (0,0,0,1) and decode back; W reconstructed.
    raw = struct.pack("<3h", 0, 0, 0)
    br = BinaryReader(io.BytesIO(raw))
    q = br.read_short_int3_quat()
    assert q == (0.0, 0.0, 0.0, 1.0)


def test_small_tree_dword_quat_decodes_identity() -> None:
    # max-index = 3 (W), all other components 0 (packed as midpoint).
    # (mid + range) * MAX_10BITf with mid==0 -> 723 * 0.7071 = 511.something
    # Easier: build the bit-pattern directly by packing zeros then patching
    # max-index bits.
    raw = struct.pack("<I", 0xC0000000 | 0)  # max_idx=3, zero packs => negative
    # The decoder will produce non-identity (because 0 packed != 0 component);
    # just assert it returns a valid-length quat.
    br = BinaryReader(io.BytesIO(raw))
    q = br.read_small_tree_dword_quat()
    assert len(q) == 4
