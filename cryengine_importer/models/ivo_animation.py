"""IVO (Star Citizen) animation data structs.

Port of CgfConverter/Models/Structs/IvoAnimationStructs.cs (v2.0.0).

Pure-Python data classes + helper functions used by the IVO #caf and
#dba chunk readers (``core/chunks/ivo_caf.py``,
``core/chunks/ivo_dba_data.py``). No ``bpy`` dependency.

Format summary (per the 010 template referenced in the C# source):

- A ``#caf`` or ``#dba`` block starts with a 12-byte
  :class:`IvoAnimBlockHeader`, followed by a u32 CRC32 bone-hash array
  and a flat array of 24-byte :class:`IvoAnimControllerEntry` records.
- Each controller entry has independent rotation / position tracks. The
  offsets it carries are **relative to the controller's own start
  position** in the file (not the start of the array).
- Rotation tracks store uncompressed quaternions (16 bytes per key).
  Position tracks come in three flavours indicated by the high byte of
  ``pos_format_flags`` (see :class:`IvoPositionFormat`).
- Time formats are determined by the low nibble of the format flags:
  ``0x0`` = ubyte time array; ``0x2`` = 8-byte time header + linearly
  interpolated keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..io.binary_reader import BinaryReader


_VEC3 = tuple[float, float, float]
_QUAT = tuple[float, float, float, float]


# --- enums + constants --------------------------------------------------


class IvoPositionFormat(IntEnum):
    """Position-data format codes (high byte of ``pos_format_flags``)."""

    NONE = 0x00
    FloatVector3 = 0xC0
    SNormFull = 0xC1
    SNormPacked = 0xC2


# FLT_MAX sentinel: SNormPacked uses this in the channel-mask vector
# to indicate that a channel is *inactive* (no data on disk for it).
# Stored as IEEE-754 float32 on disk, so the value we compare against
# must also be the float32-quantized representation — otherwise the
# round-tripped value compares slightly less than a Python double of
# 3.4028235e38 and we'd misread an inactive channel as active.
import struct as _struct

FLT_MAX_SENTINEL: float = _struct.unpack(
    "<f", _struct.pack("<f", 3.4028235e38)
)[0]


# --- helper functions ---------------------------------------------------


def get_position_format(pos_format_flags: int) -> IvoPositionFormat:
    """Return the position-data flavour from the format-flags word."""
    if pos_format_flags == 0:
        return IvoPositionFormat.NONE
    high = (pos_format_flags >> 8) & 0xFF
    if high == 0xC0:
        return IvoPositionFormat.FloatVector3
    if high == 0xC1:
        return IvoPositionFormat.SNormFull
    if high == 0xC2:
        return IvoPositionFormat.SNormPacked
    return IvoPositionFormat.NONE


def get_time_format(format_flags: int) -> int:
    """Return the time-format nibble (0 = ubyte, 2 = u16-header)."""
    return format_flags & 0x0F


def decompress_snorm(snorm: int, scale: float) -> float:
    """Decompress a signed-normalized i16 to float using ``scale``."""
    return (snorm / 32767.0) * scale


def is_channel_active(channel_mask_value: float) -> bool:
    """True when a SNormPacked channel-mask entry is *not* the
    FLT_MAX inactive sentinel."""
    return channel_mask_value < FLT_MAX_SENTINEL


def read_time_keys(
    br: "BinaryReader", count: int, format_flags: int
) -> list[float]:
    """Read ``count`` time keys per the format-flag's low nibble.

    - ``0x0`` (ubyte time array): ``count`` u8 values.
    - ``0x2`` (u16 time header): u16 startTime, u16 endTime, u32 marker,
      then ``count`` linearly interpolated values across [start, end].
    """
    times: list[float] = []
    tf = get_time_format(format_flags)
    if tf == 0x00:
        for _ in range(count):
            times.append(float(br.read_u8()))
    else:
        start = br.read_u16()
        end = br.read_u16()
        br.read_u32()  # marker (unused)
        if count == 1:
            times.append(float(start))
        else:
            span = end - start
            for t in range(count):
                norm = t / (count - 1)
                times.append(start + norm * span)
    return times


def read_rotation_keys(br: "BinaryReader", count: int) -> list[_QUAT]:
    """Read ``count`` uncompressed quaternions (16 bytes each).

    All four bit-pattern variants seen in the wild (0x00, 0x40, 0x42)
    are still uncompressed quats; the C# code unifies them.
    """
    return [br.read_quat() for _ in range(count)]


def read_position_keys(
    br: "BinaryReader", count: int, format_flags: int
) -> list[_VEC3]:
    """Read ``count`` position keys per :func:`get_position_format`.

    Returns an empty list when the format is unknown (matches the C#
    behaviour of falling through the switch).
    """
    positions: list[_VEC3] = []
    fmt = get_position_format(format_flags)

    if fmt == IvoPositionFormat.FloatVector3:
        for _ in range(count):
            positions.append(br.read_vec3())

    elif fmt == IvoPositionFormat.SNormFull:
        # 24-byte header: channelMask (12 bytes) + scale (12 bytes).
        br.read_vec3()  # channel mask (unused for "full")
        scale = br.read_vec3()
        for _ in range(count):
            sx = br.read_i16()
            sy = br.read_i16()
            sz = br.read_i16()
            positions.append((
                decompress_snorm(sx, scale[0]),
                decompress_snorm(sy, scale[1]),
                decompress_snorm(sz, scale[2]),
            ))

    elif fmt == IvoPositionFormat.SNormPacked:
        channel_mask = br.read_vec3()
        scale = br.read_vec3()
        x_active = is_channel_active(channel_mask[0])
        y_active = is_channel_active(channel_mask[1])
        z_active = is_channel_active(channel_mask[2])
        for _ in range(count):
            x = decompress_snorm(br.read_i16(), scale[0]) if x_active else 0.0
            y = decompress_snorm(br.read_i16(), scale[1]) if y_active else 0.0
            z = decompress_snorm(br.read_i16(), scale[2]) if z_active else 0.0
            positions.append((x, y, z))

    return positions


# --- data classes -------------------------------------------------------


@dataclass
class IvoAnimBlockHeader:
    """12-byte header at the start of every #caf / #dba block."""

    signature: str = ""        # "#caf" or "#dba"
    bone_count: int = 0        # u16, controllers in this block
    magic: int = 0             # u16, 0xAA55 for DBA, 0xFFFF for CAF
    data_size: int = 0         # u32, total block size after header


@dataclass
class IvoAnimControllerEntry:
    """24-byte per-bone controller entry (rotation + position track).

    All ``*_offset`` values are relative to the entry's own start
    position in the file.
    """

    # Rotation track (12 bytes).
    num_rot_keys: int = 0
    rot_format_flags: int = 0
    rot_time_offset: int = 0
    rot_data_offset: int = 0

    # Position track (12 bytes).
    num_pos_keys: int = 0
    pos_format_flags: int = 0
    pos_time_offset: int = 0
    pos_data_offset: int = 0

    @property
    def has_rotation(self) -> bool:
        return self.rot_format_flags != 0

    @property
    def has_position(self) -> bool:
        return self.pos_format_flags != 0


@dataclass
class IvoDBAMetaEntry:
    """44-byte per-animation metadata record from a DBA library."""

    flags: int = 0
    frames_per_second: int = 0
    num_controllers: int = 0
    unknown1: int = 0
    unknown2: int = 0
    start_rotation: _QUAT = (0.0, 0.0, 0.0, 1.0)
    start_position: _VEC3 = (0.0, 0.0, 0.0)


@dataclass
class IvoAnimationBlock:
    """One parsed #caf or #dba block (header + per-bone tracks).

    Used by :class:`ChunkIvoDBAData` to hold each of N animations in a
    DBA library; for #caf the chunk class itself stores the equivalent
    fields directly (one block per chunk).
    """

    header: IvoAnimBlockHeader = field(default_factory=IvoAnimBlockHeader)
    bone_hashes: list[int] = field(default_factory=list)
    controllers: list[IvoAnimControllerEntry] = field(default_factory=list)
    controller_offsets: list[int] = field(default_factory=list)

    rotations: dict[int, list[_QUAT]] = field(default_factory=dict)
    positions: dict[int, list[_VEC3]] = field(default_factory=dict)
    rotation_times: dict[int, list[float]] = field(default_factory=dict)
    position_times: dict[int, list[float]] = field(default_factory=dict)


__all__ = [
    "IvoPositionFormat",
    "FLT_MAX_SENTINEL",
    "get_position_format",
    "get_time_format",
    "decompress_snorm",
    "is_channel_active",
    "read_time_keys",
    "read_rotation_keys",
    "read_position_keys",
    "IvoAnimBlockHeader",
    "IvoAnimControllerEntry",
    "IvoDBAMetaEntry",
    "IvoAnimationBlock",
]
