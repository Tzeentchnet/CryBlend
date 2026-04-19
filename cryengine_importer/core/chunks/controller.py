"""ChunkController.

Port of CgfConverter/CryEngineCore/Chunks/ChunkController*.cs.
Implements 0x826 (legacy keyed controller), 0x829 (header-only stub
matching the C# reference), and 0x905 (Star Citizen / new CryAnimation
controller with compressed quaternion / vec3 tracks).
"""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

from ...enums import (
    ChunkType,
    CompressionFormat,
    CtrlType,
    KeyTimesFormat,
)
from ...models.animation import (
    Animation905,
    ControllerInfo,
    ControllerKey,
    MotionParams905,
)
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkController(Chunk):
    pass


# -- 0x826 ---------------------------------------------------------------


@chunk(ChunkType.Controller, 0x826)
class ChunkController826(ChunkController):
    """Legacy CryTek Key[] controller."""

    def __init__(self) -> None:
        super().__init__()
        self.controller_type: CtrlType = CtrlType.NONE
        self.num_keys: int = 0
        self.controller_flags: int = 0
        self.controller_id: int = 0
        self.keys: list[ControllerKey] = []

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self.controller_type = CtrlType(br.read_u32())
        self.num_keys = br.read_i32()
        self.controller_flags = br.read_u32()
        self.controller_id = br.read_u32()
        for _ in range(self.num_keys):
            self.keys.append(
                ControllerKey(
                    time=br.read_i32(),
                    abs_pos=br.read_vec3(),
                    rel_pos=br.read_vec3(),
                )
            )


# -- 0x829 ---------------------------------------------------------------


@chunk(ChunkType.Controller, 0x829)
class ChunkController829(ChunkController):
    """Header-only controller stub.

    The C# reference (ChunkController_829.cs) only forces the reader
    back to little-endian and reads no body; the actual on-disk layout
    is unknown / undocumented. We mirror that behaviour so files
    containing this chunk-type don't crash the loader.
    """

    def __init__(self) -> None:
        super().__init__()
        self.controller_id: int = 0
        self.num_rotation_keys: int = 0
        self.num_position_keys: int = 0
        self.rotation_format: int = 0
        self.rotation_time_format: int = 0
        self.position_format: int = 0
        self.position_keys_info: int = 0
        self.position_time_format: int = 0
        self.tracks_aligned: int = 0

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        br.is_big_endian = False
        # Body intentionally not parsed (matches C# reference).


# -- 0x905 ---------------------------------------------------------------


def _decode_key_times(
    br: "BinaryReader",
    *,
    track_offset: int,
    lengths: list[int],
    offsets: list[int],
    formats: list[int],
) -> list[list[float]]:
    """Decode the per-track time arrays for Controller_905."""
    out: list[list[float]] = []
    formats = list(formats)  # copy — we mutate via "consume one of format X"
    for length, frm in zip(lengths, offsets):
        br.seek(track_offset + frm)
        if formats[KeyTimesFormat.eF32] > 0:
            formats[KeyTimesFormat.eF32] -= 1
            data = [br.read_f32() for _ in range(length)]
        elif formats[KeyTimesFormat.eUINT16] > 0:
            formats[KeyTimesFormat.eUINT16] -= 1
            data = [float(br.read_u16()) for _ in range(length)]
        elif formats[KeyTimesFormat.eByte] > 0:
            formats[KeyTimesFormat.eByte] -= 1
            data = [float(b) for b in br.read_bytes(length)]
        elif formats[KeyTimesFormat.eBitset] > 0:
            formats[KeyTimesFormat.eBitset] -= 1
            start = br.read_u16()
            end = br.read_u16()
            size = br.read_u16()
            data = []
            key_value = start
            for _ in range(3, length):
                curr = br.read_u16()
                for j in range(16):
                    if (curr >> j) & 1:
                        data.append(float(key_value))
                    key_value += 1
            # Trim oversize bitsets to declared size
            del data[size:]
        else:
            # Unknown / unsupported (StartStop variants are unused)
            data = []
        # Drop trailing zero-pads (decreasing tail).
        while len(data) >= 2 and data[-2] > data[-1]:
            data.pop()
        out.append(data)
    return out


def _decode_quat_track(
    br: "BinaryReader", length: int, fmt: CompressionFormat
) -> list[tuple[float, float, float, float]]:
    """Decode a length-N rotation track in one of the compressed
    quaternion formats."""
    if fmt == CompressionFormat.eNoCompressQuat:
        return [br.read_quat() for _ in range(length)]
    if fmt == CompressionFormat.eNoCompressVec3:
        # C# stores w as NaN here; we return (x,y,z,nan) so callers
        # can detect & re-derive if desired.
        return [(*br.read_vec3(), float("nan")) for _ in range(length)]
    if fmt == CompressionFormat.eShotInt3Quat:
        return [br.read_short_int3_quat() for _ in range(length)]
    if fmt == CompressionFormat.eSmallTreeDWORDQuat:
        return [br.read_small_tree_dword_quat() for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree48BitQuat:
        return [br.read_small_tree_48bit_quat() for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree64BitQuat:
        return [br.read_small_tree_64bit_quat() for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree64BitExtQuat:
        return [br.read_small_tree_64bit_ext_quat() for _ in range(length)]
    raise NotImplementedError(f"Unsupported quat format {fmt!r}")


def _decode_pos_track(
    br: "BinaryReader", length: int, fmt: CompressionFormat
) -> list[tuple[float, float, float]]:
    """Decode a length-N position track. Compressed-quat formats are
    used for positions too — the C# code reads a quat then drops W."""
    if fmt == CompressionFormat.eNoCompressVec3:
        return [br.read_vec3() for _ in range(length)]
    if fmt == CompressionFormat.eNoCompressQuat:
        return [br.read_quat()[:3] for _ in range(length)]
    if fmt == CompressionFormat.eShotInt3Quat:
        return [br.read_short_int3_quat()[:3] for _ in range(length)]
    if fmt == CompressionFormat.eSmallTreeDWORDQuat:
        return [br.read_small_tree_dword_quat()[:3] for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree48BitQuat:
        return [br.read_small_tree_48bit_quat()[:3] for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree64BitQuat:
        return [br.read_small_tree_64bit_quat()[:3] for _ in range(length)]
    if fmt == CompressionFormat.eSmallTree64BitExtQuat:
        return [br.read_small_tree_64bit_ext_quat()[:3] for _ in range(length)]
    raise NotImplementedError(f"Unsupported pos format {fmt!r}")


def _pick_format(formats: list[int]) -> CompressionFormat:
    """Find the first non-zero format slot (and consume it)."""
    for i, count in enumerate(formats):
        if count > 0:
            formats[i] = count - 1
            return CompressionFormat(i)
    raise ValueError("No remaining track format slot")


def _read_motion_params_905(br: "BinaryReader") -> MotionParams905:
    return MotionParams905(
        asset_flags=br.read_u32(),
        compression=br.read_u32(),
        ticks_per_frame=br.read_i32(),
        secs_per_tick=br.read_f32(),
        start=br.read_i32(),
        end=br.read_i32(),
        move_speed=br.read_f32(),
        turn_speed=br.read_f32(),
        asset_turn=br.read_f32(),
        distance=br.read_f32(),
        slope=br.read_f32(),
        start_location_q=br.read_quat(),
        start_location_v=br.read_vec3(),
        end_location_q=br.read_quat(),
        end_location_v=br.read_vec3(),
        l_heel_start=br.read_f32(),
        l_heel_end=br.read_f32(),
        l_toe0_start=br.read_f32(),
        l_toe0_end=br.read_f32(),
        r_heel_start=br.read_f32(),
        r_heel_end=br.read_f32(),
        r_toe0_start=br.read_f32(),
        r_toe0_end=br.read_f32(),
    )


def _read_animation_905(br: "BinaryReader") -> Animation905:
    name_len = br.read_u16()
    name = br.read_bytes(name_len).decode("utf-8", errors="replace")
    motion = _read_motion_params_905(br)
    foot_plant_count = br.read_u16()
    foot_plant_bits = br.read_bytes(foot_plant_count)
    controller_count = br.read_u16()
    controllers = [
        ControllerInfo(
            controller_id=br.read_u32(),
            pos_key_time_track=br.read_i32(),
            pos_track=br.read_i32(),
            rot_key_time_track=br.read_i32(),
            rot_track=br.read_i32(),
        )
        for _ in range(controller_count)
    ]
    return Animation905(
        name=name,
        motion_params=motion,
        foot_plant_bits=foot_plant_bits,
        controllers=controllers,
    )


@chunk(ChunkType.Controller, 0x905)
class ChunkController905(ChunkController):
    """Star Citizen / new CryAnimation controller chunk.

    Holds N independent key-time / position / rotation tracks plus M
    `Animation905` entries that bind tracks to bones (by controller_id).
    Track payloads use a small zoo of compressed quaternion formats —
    see `_decode_quat_track`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.num_key_pos: int = 0
        self.num_key_rot: int = 0
        self.num_key_time: int = 0
        self.num_anims: int = 0
        self.key_times: list[list[float]] = []
        self.key_positions: list[list[tuple[float, float, float]]] = []
        self.key_rotations: list[list[tuple[float, float, float, float]]] = []
        self.animations: list[Animation905] = []

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        br.is_big_endian = False

        self.num_key_pos = br.read_u32()
        self.num_key_rot = br.read_u32()
        self.num_key_time = br.read_u32()
        self.num_anims = br.read_u32()

        # Endianness probe: any count >= 0x10000 means we're misreading.
        endian_check = (
            (1 if self.num_key_pos >= 0x10000 else 0)
            | (2 if self.num_key_rot >= 0x10000 else 0)
            | (4 if self.num_key_time >= 0x10000 else 0)
            | (8 if self.num_anims >= 0x10000 else 0)
        )
        if endian_check == 15:
            self.num_key_pos = _bswap32(self.num_key_pos)
            self.num_key_rot = _bswap32(self.num_key_rot)
            self.num_key_time = _bswap32(self.num_key_time)
            self.num_anims = _bswap32(self.num_anims)
            br.is_big_endian = True
        # else: assume little-endian (matches C# fall-through)

        key_time_lengths = [br.read_u16() for _ in range(self.num_key_time)]
        key_time_formats = [
            br.read_u32() for _ in range(int(KeyTimesFormat.eBitset) + 1)
        ]
        key_pos_lengths = [br.read_u16() for _ in range(self.num_key_pos)]
        key_pos_formats = [
            br.read_u32() for _ in range(int(CompressionFormat.eAutomaticQuat))
        ]
        key_rot_lengths = [br.read_u16() for _ in range(self.num_key_rot)]
        key_rot_formats = [
            br.read_u32() for _ in range(int(CompressionFormat.eAutomaticQuat))
        ]

        key_time_offsets = [br.read_u32() for _ in range(self.num_key_time)]
        key_pos_offsets = [br.read_u32() for _ in range(self.num_key_pos)]
        key_rot_offsets = [br.read_u32() for _ in range(self.num_key_rot)]
        track_length = br.read_u32()

        # The C# loader appends sentinel offsets so each track ends at
        # the next track's start; we don't actually use these here, but
        # we keep the math symmetric for clarity.
        key_rot_offsets.append(track_length)
        if key_rot_offsets:
            key_pos_offsets.append(key_rot_offsets[0])
        if key_pos_offsets:
            key_time_offsets.append(key_pos_offsets[0])

        track_offset = br.tell()
        if track_offset & 3:
            track_offset = (track_offset & ~3) + 4

        # --- decode tracks -------------------------------------------
        self.key_times = _decode_key_times(
            br,
            track_offset=track_offset,
            lengths=key_time_lengths,
            offsets=key_time_offsets,
            formats=key_time_formats,
        )

        pos_fmts = list(key_pos_formats)
        self.key_positions = []
        for length, frm in zip(key_pos_lengths, key_pos_offsets):
            br.seek(track_offset + frm)
            fmt = _pick_format(pos_fmts)
            self.key_positions.append(_decode_pos_track(br, length, fmt))

        rot_fmts = list(key_rot_formats)
        self.key_rotations = []
        for length, frm in zip(key_rot_lengths, key_rot_offsets):
            br.seek(track_offset + frm)
            fmt = _pick_format(rot_fmts)
            self.key_rotations.append(_decode_quat_track(br, length, fmt))

        # --- animation table -----------------------------------------
        br.seek(track_offset + track_length)
        self.animations = [
            _read_animation_905(br) for _ in range(self.num_anims)
        ]


def _bswap32(v: int) -> int:
    return int.from_bytes(struct.pack(">I", v & 0xFFFFFFFF), "little")


# -- 0x827 / 0x830 — uncompressed CryKeyPQLog ---------------------------


import math


def _log_to_quat_half_angle(
    rot_log: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    """CryEngine ``Quat::exp(Vec3)`` — vRotLog is axis × half-angle.
    Returns ``(x, y, z, w)`` with w = cos(theta), xyz = axis * sin(theta)/theta.

    This matches v2.0.0 ``ChunkController_827.LogToQuaternion``."""
    x, y, z = rot_log
    theta = math.sqrt(x * x + y * y + z * z)
    if theta < 1e-4:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(theta) / theta
    return (x * s, y * s, z * s, math.cos(theta))


def _log_to_quat_full_angle(
    rot_log: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    """v2.0.0 ``ChunkController_830`` variant — vRotLog is axis × angle
    (not half-angle). Returns ``(x, y, z, w)`` with w = cos(theta/2)
    and xyz = axis * sin(theta/2)."""
    x, y, z = rot_log
    theta = math.sqrt(x * x + y * y + z * z)
    if theta < 1e-4:
        return (0.0, 0.0, 0.0, 1.0)
    half = theta * 0.5
    s = math.sin(half) / theta
    return (x * s, y * s, z * s, math.cos(half))


@chunk(ChunkType.Controller, 0x827)
class ChunkController827(ChunkController):
    """Uncompressed CryKeyPQLog (legacy, no embedded local header).

    Used by old 0x744-format CAF files (e.g. ArcheAge). Layout::

        u32 numKeys
        u32 controllerId
        [numKeys × CryKeyPQLog]:
            i32   nTime
            float3 vPos
            float3 vRotLog   (axis × half-angle)
    """

    def __init__(self) -> None:
        super().__init__()
        self.num_keys: int = 0
        self.controller_id: int = 0
        self.key_times: list[int] = []
        self.key_positions: list[tuple[float, float, float]] = []
        self.key_rotations: list[tuple[float, float, float, float]] = []

    def read(self, br: "BinaryReader") -> None:
        # 0x827 has no embedded local header — bypass base.read() and
        # initialise straight from the chunk-table header (matches v2).
        self.chunk_type = self.header.chunk_type
        self.version_raw = self.header.version_raw
        self.offset = self.header.offset
        self.id = self.header.id
        self.size = self.header.size
        self.data_size = self.size

        br.seek(self.header.offset)
        br.is_big_endian = False

        self.num_keys = br.read_u32()
        self.controller_id = br.read_u32()
        for _ in range(self.num_keys):
            self.key_times.append(br.read_i32())
            self.key_positions.append(br.read_vec3())
            self.key_rotations.append(_log_to_quat_half_angle(br.read_vec3()))


@chunk(ChunkType.Controller, 0x828)
class ChunkController828(ChunkController):
    """Empty / unsupported.

    v2.0.0 reference ``CONTROLLER_CHUNK_DESC_0828`` is an empty struct
    that the engine itself logs and skips. We mirror the no-op."""

    def __init__(self) -> None:
        super().__init__()
        self.controller_id: int = 0

    def read(self, br: "BinaryReader") -> None:
        self.chunk_type = self.header.chunk_type
        self.version_raw = self.header.version_raw
        self.offset = self.header.offset
        self.id = self.header.id
        self.size = self.header.size
        self.data_size = self.size
        # No body to parse.


@chunk(ChunkType.Controller, 0x830)
class ChunkController830(ChunkController):
    """CryKeyPQLog with embedded local header + a Flags u32.

    Used by current CryEngine CAF files. Same per-key layout as 0x827
    but vRotLog is interpreted with v2's half-angle math (axis*angle,
    not axis*half-angle)."""

    def __init__(self) -> None:
        super().__init__()
        self.num_keys: int = 0
        self.controller_id: int = 0
        self.flags: int = 0
        self.key_times: list[int] = []
        self.key_positions: list[tuple[float, float, float]] = []
        self.key_rotations: list[tuple[float, float, float, float]] = []

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        br.is_big_endian = False
        self.num_keys = br.read_u32()
        self.controller_id = br.read_u32()
        self.flags = br.read_u32()
        for _ in range(self.num_keys):
            self.key_times.append(br.read_i32())
            self.key_positions.append(br.read_vec3())
            self.key_rotations.append(_log_to_quat_full_angle(br.read_vec3()))


# -- 0x831 — compressed dual-track --------------------------------------


class _831CompressionFormat:
    """Local enum for ChunkController_831 (distinct from
    :class:`CompressionFormat` which is keyed differently)."""

    eNoCompress = 0
    eNoCompressQuat = 1
    eNoCompressVec3 = 2
    eShotInt3Quat = 3
    eSmallTreeDWORDQuat = 4
    eSmallTree48BitQuat = 5
    eSmallTree64BitQuat = 6
    ePolarQuat = 7
    eSmallTree64BitExtQuat = 8
    eAutomaticQuat = 9


def _831_read_rotation(
    br: "BinaryReader", fmt: int
) -> tuple[float, float, float, float]:
    f = _831CompressionFormat
    if fmt == f.eNoCompressQuat:
        return br.read_quat()
    if fmt == f.eShotInt3Quat:
        return br.read_short_int3_quat()
    if fmt == f.eSmallTreeDWORDQuat:
        return br.read_small_tree_dword_quat()
    if fmt == f.eSmallTree48BitQuat:
        return br.read_small_tree_48bit_quat()
    if fmt == f.eSmallTree64BitQuat:
        return br.read_small_tree_64bit_quat()
    if fmt == f.eSmallTree64BitExtQuat:
        return br.read_small_tree_64bit_ext_quat()
    return (0.0, 0.0, 0.0, 1.0)


def _831_read_position(br: "BinaryReader", fmt: int) -> tuple[float, float, float]:
    f = _831CompressionFormat
    if fmt in (f.eNoCompress, f.eNoCompressVec3):
        return br.read_vec3()
    return (0.0, 0.0, 0.0)


def _831_read_time(br: "BinaryReader", fmt: int) -> float:
    # 0/3 = eF32 / eF32StartStop, 1/4 = eU16 / eU16StartStop,
    # 2/5 = eByte / eByteStartStop, 6 = eBitset (u16)
    if fmt in (0, 3):
        return br.read_f32()
    if fmt in (1, 4, 6):
        return float(br.read_u16())
    if fmt in (2, 5):
        return float(br.read_u8())
    return br.read_f32()


@chunk(ChunkType.Controller, 0x831)
class ChunkController831(ChunkController):
    """Compressed dual-track controller (v2.0.0).

    Separate rotation and position tracks, each with its own time
    encoding and compression format. Position times share the rotation
    times unless ``position_keys_info`` is non-zero. ``tracks_aligned``
    inserts 4-byte padding between sections.
    """

    def __init__(self) -> None:
        super().__init__()
        self.controller_id: int = 0
        self.flags: int = 0
        self.num_rotation_keys: int = 0
        self.num_position_keys: int = 0
        self.rotation_format: int = 0
        self.rotation_time_format: int = 0
        self.position_format: int = 0
        self.position_keys_info: int = 0
        self.position_time_format: int = 0
        self.tracks_aligned: int = 0
        self.rotation_key_times: list[float] = []
        self.position_key_times: list[float] = []
        self.key_rotations: list[tuple[float, float, float, float]] = []
        self.key_positions: list[tuple[float, float, float]] = []

    def _align4(self, br: "BinaryReader") -> None:
        if self.tracks_aligned:
            pad = (-br.tell()) & 3
            if pad:
                br.skip(pad)

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        br.is_big_endian = False

        self.controller_id = br.read_u32()
        self.flags = br.read_u32()
        self.num_rotation_keys = br.read_u16()
        self.num_position_keys = br.read_u16()
        self.rotation_format = br.read_u8()
        self.rotation_time_format = br.read_u8()
        self.position_format = br.read_u8()
        self.position_keys_info = br.read_u8()
        self.position_time_format = br.read_u8()
        self.tracks_aligned = br.read_u8()

        # Layout: [rot values] -> pad -> [rot times] -> pad ->
        #         [pos values] -> pad -> [pos times if PositionKeysInfo!=0]
        self.key_rotations = [
            _831_read_rotation(br, self.rotation_format)
            for _ in range(self.num_rotation_keys)
        ]
        self._align4(br)

        self.rotation_key_times = [
            _831_read_time(br, self.rotation_time_format)
            for _ in range(self.num_rotation_keys)
        ]
        self._align4(br)

        self.key_positions = [
            _831_read_position(br, self.position_format)
            for _ in range(self.num_position_keys)
        ]
        self._align4(br)

        if self.position_keys_info != 0:
            self.position_key_times = [
                _831_read_time(br, self.position_time_format)
                for _ in range(self.num_position_keys)
            ]
        else:
            self.position_key_times = list(self.rotation_key_times)


# -- 0x925 — MotionParameters (read-only metadata, no Blender wiring) ----


@chunk(ChunkType.MotionParams, 0x925)
class ChunkMotionParameters925(Chunk):
    """132-byte motion-params record. Read-only; not wired into the
    Blender layer (informational only)."""

    def __init__(self) -> None:
        super().__init__()
        self.asset_flags: int = 0
        self.compression: int = 0
        self.ticks_per_frame: int = 0
        self.secs_per_tick: float = 0.0
        self.start: int = 0
        self.end: int = 0
        self.move_speed: float = 0.0
        self.turn_speed: float = 0.0
        self.asset_turn: float = 0.0
        self.distance: float = 0.0
        self.slope: float = 0.0
        self.start_location_q: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.start_location_t: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.end_location_q: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.end_location_t: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.l_heel_start: float = 0.0
        self.l_heel_end: float = 0.0
        self.l_toe0_start: float = 0.0
        self.l_toe0_end: float = 0.0
        self.r_heel_start: float = 0.0
        self.r_heel_end: float = 0.0
        self.r_toe0_start: float = 0.0
        self.r_toe0_end: float = 0.0

    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self.asset_flags = br.read_u32()
        self.compression = br.read_u32()
        self.ticks_per_frame = br.read_i32()
        self.secs_per_tick = br.read_f32()
        self.start = br.read_i32()
        self.end = br.read_i32()
        self.move_speed = br.read_f32()
        self.turn_speed = br.read_f32()
        self.asset_turn = br.read_f32()
        self.distance = br.read_f32()
        self.slope = br.read_f32()
        self.start_location_q = br.read_quat()
        self.start_location_t = br.read_vec3()
        self.end_location_q = br.read_quat()
        self.end_location_t = br.read_vec3()
        self.l_heel_start = br.read_f32()
        self.l_heel_end = br.read_f32()
        self.l_toe0_start = br.read_f32()
        self.l_toe0_end = br.read_f32()
        self.r_heel_start = br.read_f32()
        self.r_heel_end = br.read_f32()
        self.r_toe0_start = br.read_f32()
        self.r_toe0_end = br.read_f32()


