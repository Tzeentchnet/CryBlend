"""Phase 5c-E — Star Citizen #ivo animation chunk reader tests."""

from __future__ import annotations

import io
import struct

import pytest

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.header import ChunkHeader900
from cryengine_importer.core.chunks.ivo_anim_info import ChunkIvoAnimInfo901
from cryengine_importer.core.chunks.ivo_caf import ChunkIvoCAF900
from cryengine_importer.core.chunks.ivo_dba_data import ChunkIvoDBAData900
from cryengine_importer.core.chunks.ivo_dba_metadata import (
    ChunkIvoDBAMetadata900,
    ChunkIvoDBAMetadata901,
)
from cryengine_importer.core.model import Model
from cryengine_importer.enums import ChunkType, FileVersion
from cryengine_importer.io.binary_reader import BinaryReader
from cryengine_importer.models.ivo_animation import (
    FLT_MAX_SENTINEL,
    IvoPositionFormat,
    decompress_snorm,
    get_position_format,
    get_time_format,
    is_channel_active,
    read_position_keys,
    read_rotation_keys,
    read_time_keys,
)


# ----------------------------------------------------- helpers ----------


def _drive(chunk_type: ChunkType, version: int, body: bytes):
    inst = make_chunk(chunk_type, version)
    hdr = ChunkHeader900()
    hdr.chunk_type = chunk_type
    hdr.version_raw = version
    hdr.id = 1
    hdr.offset = 0
    hdr.size = len(body)

    model = Model()
    model.file_version = FileVersion.x0900
    model.file_signature = "#ivo"

    inst.load(model, hdr)  # type: ignore[arg-type]
    inst.read(BinaryReader(io.BytesIO(body)))
    return inst


def _br(payload: bytes) -> BinaryReader:
    return BinaryReader(io.BytesIO(payload))


# ----------------------------------------------- helper unit tests ------


def test_get_position_format_extracts_high_byte() -> None:
    assert get_position_format(0x0000) == IvoPositionFormat.NONE
    assert get_position_format(0xC042) == IvoPositionFormat.FloatVector3
    assert get_position_format(0xC100) == IvoPositionFormat.SNormFull
    assert get_position_format(0xC200) == IvoPositionFormat.SNormPacked
    assert get_position_format(0xAB00) == IvoPositionFormat.NONE


def test_get_time_format_returns_low_nibble() -> None:
    assert get_time_format(0x8040) == 0
    assert get_time_format(0x8042) == 2
    assert get_time_format(0x000F) == 0xF


def test_decompress_snorm_scales_int16() -> None:
    assert decompress_snorm(32767, 2.0) == 2.0
    assert decompress_snorm(-32767, 2.0) == -2.0
    assert decompress_snorm(0, 5.0) == 0.0


def test_is_channel_active_uses_flt_max_sentinel() -> None:
    assert is_channel_active(0.0)
    assert is_channel_active(123.456)
    assert not is_channel_active(FLT_MAX_SENTINEL)
    assert not is_channel_active(FLT_MAX_SENTINEL + 1.0)


def test_read_time_keys_ubyte_format() -> None:
    payload = bytes([0, 5, 10, 30])
    times = read_time_keys(_br(payload), 4, 0x8040)
    assert times == [0.0, 5.0, 10.0, 30.0]


def test_read_time_keys_uint16_header_interpolates() -> None:
    payload = struct.pack("<HHI", 10, 30, 0)  # start, end, marker
    times = read_time_keys(_br(payload), 3, 0x8042)
    assert times[0] == 10.0
    assert times[-1] == 30.0
    assert times[1] == 20.0  # halfway


def test_read_time_keys_uint16_header_single_key_uses_start() -> None:
    payload = struct.pack("<HHI", 7, 99, 0)
    times = read_time_keys(_br(payload), 1, 0x8042)
    assert times == [7.0]


def test_read_rotation_keys_returns_quats() -> None:
    payload = struct.pack("<4f", 0.1, 0.2, 0.3, 0.9) + struct.pack(
        "<4f", 1.0, 0.0, 0.0, 0.0
    )
    quats = read_rotation_keys(_br(payload), 2)
    assert len(quats) == 2
    assert quats[0] == pytest.approx((0.1, 0.2, 0.3, 0.9), rel=1e-6)
    assert quats[1] == (1.0, 0.0, 0.0, 0.0)


def test_read_position_keys_float_vector3() -> None:
    payload = struct.pack("<3f", 1.0, 2.0, 3.0) + struct.pack(
        "<3f", 4.0, 5.0, 6.0
    )
    positions = read_position_keys(_br(payload), 2, 0xC042)
    assert positions == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]


def test_read_position_keys_snorm_full() -> None:
    # 24-byte header: channel mask (ignored) + scale.
    header = struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack(
        "<3f", 2.0, 4.0, 8.0
    )
    payload = header + struct.pack("<3h", 32767, -32767, 0)
    positions = read_position_keys(_br(payload), 1, 0xC142)
    assert positions[0] == (2.0, -4.0, 0.0)


def test_read_position_keys_snorm_packed_skips_inactive() -> None:
    # X active (mask=0), Y inactive (FLT_MAX), Z active (mask=0).
    header = struct.pack("<3f", 0.0, FLT_MAX_SENTINEL, 0.0) + struct.pack(
        "<3f", 2.0, 1.0, 3.0
    )
    # Only X and Z are read for each key (4 bytes per key).
    payload = header + struct.pack("<2h", 32767, -32767)
    positions = read_position_keys(_br(payload), 1, 0xC242)
    assert positions[0] == (2.0, 0.0, -3.0)


# ----------------------------------------------- ChunkIvoAnimInfo -------


def test_ivo_anim_info_901_parses_48_byte_record() -> None:
    body = struct.pack("<I", 0)            # flags
    body += struct.pack("<HH", 30, 42)     # FPS, num bones
    body += struct.pack("<II", 0, 60)      # reserved, end frame
    body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)  # start rotation
    body += struct.pack("<3f", 1.0, 2.0, 3.0)        # start position
    body += struct.pack("<I", 0xDEADBEEF)            # padding

    chunk = _drive(ChunkType.IvoAnimInfo, 0x901, body)
    assert isinstance(chunk, ChunkIvoAnimInfo901)
    assert chunk.frames_per_second == 30
    assert chunk.num_bones == 42
    assert chunk.end_frame == 60
    assert chunk.start_position == (1.0, 2.0, 3.0)
    assert chunk.padding == 0xDEADBEEF


# ----------------------------------------------- ChunkIvoCAF_900 --------


def _make_caf_block_with_one_bone() -> bytes:
    """Build a minimal valid #caf block: 1 bone, 1 rot key, 1 pos key."""
    bone_hash = 0x12345678

    # Controller header lives at offset = 12 (block hdr) + 4 (bone hash) = 16
    controller_start = 12 + 4
    # Lay out keyframe data right after the 24-byte controller entry.
    # Rotation: 8-byte time header (HHI) + 16-byte quat = 24 bytes.
    # Position: 8-byte time header + 12-byte float-vec3 = 20 bytes.
    rot_time_offset_local = 24                      # right after controller
    rot_data_offset_local = 24 + 8                  # after the 8-byte time hdr
    pos_time_offset_local = 24 + 8 + 16             # after the rotation data
    pos_data_offset_local = pos_time_offset_local + 8  # after pos time hdr

    controller = struct.pack(
        "<HHII HHII",
        1,                       # num rot keys
        0x8042,                  # rot format flags (u16 time hdr + uncompressed quat)
        rot_time_offset_local,   # rot time offset
        rot_data_offset_local,   # rot data offset
        1,                       # num pos keys
        0xC042,                  # pos format flags (u16 time hdr + float vec3)
        pos_time_offset_local,
        pos_data_offset_local,
    )

    rot_time = struct.pack("<HHI", 0, 0, 0)
    rot_data = struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
    pos_time = struct.pack("<HHI", 0, 0, 0)
    pos_data = struct.pack("<3f", 7.0, 8.0, 9.0)

    payload = (
        struct.pack("<I", bone_hash)
        + controller
        + rot_time
        + rot_data
        + pos_time
        + pos_data
    )

    # Block header: signature + bone count + magic + data size (incl header).
    data_size = 12 + len(payload)
    header = b"#caf" + struct.pack("<HHI", 1, 0xFFFF, data_size)
    return header + payload


def test_ivo_caf_900_parses_minimal_block() -> None:
    body = _make_caf_block_with_one_bone()
    chunk = _drive(ChunkType.IvoCAFData, 0x900, body)
    assert isinstance(chunk, ChunkIvoCAF900)
    assert chunk.block_header.signature == "#caf"
    assert chunk.block_header.bone_count == 1
    assert chunk.bone_hashes == [0x12345678]
    assert len(chunk.controllers) == 1
    assert chunk.rotations[0x12345678] == [(0.0, 0.0, 0.0, 1.0)]
    assert chunk.positions[0x12345678] == [(7.0, 8.0, 9.0)]
    assert chunk.rotation_times[0x12345678] == [0.0]
    assert chunk.position_times[0x12345678] == [0.0]


def test_ivo_caf_900_bails_on_bad_signature() -> None:
    body = b"junk" + struct.pack("<HHI", 0, 0, 12)
    chunk = _drive(ChunkType.IvoCAFData, 0x900, body)
    assert isinstance(chunk, ChunkIvoCAF900)
    assert chunk.block_header.signature != "#caf"
    assert chunk.bone_hashes == []
    assert chunk.controllers == []


# ----------------------------------------------- ChunkIvoDBAData_900 ----


def test_ivo_dba_data_900_parses_two_blocks() -> None:
    """Two back-to-back #dba blocks; verify count + signatures."""
    bone_hash = 0xAA000001

    def build_block() -> bytes:
        # Empty controller (no rotation, no position) keeps payload tiny.
        controller = struct.pack(
            "<HHII HHII",
            0, 0, 0, 0,
            0, 0, 0, 0,
        )
        body = struct.pack("<I", bone_hash) + controller
        # data_size includes the 12-byte header.
        return b"#dba" + struct.pack("<HHI", 1, 0xAA55, 12 + len(body)) + body

    block_a = build_block()
    block_b = build_block()
    payload = block_a + block_b
    body = struct.pack("<I", len(payload) + 4) + payload  # +4 for the size word itself

    chunk = _drive(ChunkType.IvoDBAData, 0x900, body)
    assert isinstance(chunk, ChunkIvoDBAData900)
    assert len(chunk.animation_blocks) == 2
    for blk in chunk.animation_blocks:
        assert blk.header.signature == "#dba"
        assert blk.header.magic == 0xAA55
        assert blk.bone_hashes == [bone_hash]


# ----------------------------------------------- ChunkIvoDBAMetadata ----


def _make_metadata_body(paths: list[str]) -> bytes:
    body = struct.pack("<I", len(paths))
    for _ in paths:
        body += struct.pack("<I", 2)             # flags
        body += struct.pack("<HH", 30, 5)        # FPS, num controllers
        body += struct.pack("<II", 0, 17)        # unknown1, unknown2
        body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        body += struct.pack("<3f", 1.0, 2.0, 3.0)
    for p in paths:
        body += p.encode("ascii") + b"\x00"
    return body


def test_ivo_dba_metadata_900_parses_entries_and_paths() -> None:
    body = _make_metadata_body(["anim/idle.caf", "anim/walk.caf"])
    chunk = _drive(ChunkType.IvoDBAMetadata, 0x900, body)
    assert isinstance(chunk, ChunkIvoDBAMetadata900)
    assert chunk.anim_count == 2
    assert chunk.anim_paths == ["anim/idle.caf", "anim/walk.caf"]
    assert chunk.entries[0].frames_per_second == 30
    assert chunk.entries[0].num_controllers == 5
    assert chunk.entries[1].start_position == (1.0, 2.0, 3.0)


def test_ivo_dba_metadata_901_uses_same_layout() -> None:
    body = _make_metadata_body(["only.caf"])
    chunk = _drive(ChunkType.IvoDBAMetadata, 0x901, body)
    assert isinstance(chunk, ChunkIvoDBAMetadata901)
    assert chunk.anim_paths == ["only.caf"]
