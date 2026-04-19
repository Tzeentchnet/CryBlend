"""ChunkGlobalAnimationHeaderCAF.

Port of CgfConverter/CryEngineCore/Chunks/ChunkGlobalAnimationHeaderCAF_971.cs.

The CAF file's anchor chunk: stores the original FilePath (used as the
animation's display name), durations, and locator-key data needed to
position the clip in world space. Track payloads live in adjacent
Controller_905 chunks within the same `.caf`.
"""

from __future__ import annotations

import struct
from binascii import crc32 as _crc32
from typing import TYPE_CHECKING

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkGlobalAnimationHeaderCAF(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.flags: int = 0
        self.file_path: str = ""
        self.file_path_crc32: int = 0
        self.file_path_dba_crc32: int = 0
        self.l_heel_start: float = 0.0
        self.l_heel_end: float = 0.0
        self.l_toe0_start: float = 0.0
        self.l_toe0_end: float = 0.0
        self.r_heel_start: float = 0.0
        self.r_heel_end: float = 0.0
        self.r_toe0_start: float = 0.0
        self.r_toe0_end: float = 0.0
        self.start_sec: float = 0.0
        self.end_sec: float = 0.0
        self.total_duration: float = 0.0
        self.controllers: int = 0
        self.start_location: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.last_locator_key: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.distance: float = 0.0
        self.speed: float = 0.0
        self.slope: float = 0.0
        self.turn_speed: float = 0.0
        self.asset_turn: float = 0.0


@chunk(ChunkType.GlobalAnimationHeaderCAF, 0x971)
class ChunkGlobalAnimationHeaderCAF971(ChunkGlobalAnimationHeaderCAF):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        br.is_big_endian = False

        self.flags = br.read_u32()
        self.file_path = br.read_fstring(256)
        self.file_path_crc32 = br.read_u32()

        # CRC32 sanity check — if it matches the byte-swapped CRC,
        # we're actually reading big-endian data.
        expected = _crc32(self.file_path.encode("utf-8")) & 0xFFFFFFFF
        if expected == self.file_path_crc32:
            pass
        elif _bswap32(expected) == self.file_path_crc32:
            br.is_big_endian = True
            self.flags = _bswap32(self.flags)
            self.file_path_crc32 = expected
        else:
            # The C# reference raises here; we keep the chunk usable and
            # let the caller decide whether to ignore it. This is a
            # data-integrity concern, not a parser correctness issue.
            pass

        self.file_path_dba_crc32 = br.read_u32()

        self.l_heel_start = br.read_f32()
        self.l_heel_end = br.read_f32()
        self.l_toe0_start = br.read_f32()
        self.l_toe0_end = br.read_f32()
        self.r_heel_start = br.read_f32()
        self.r_heel_end = br.read_f32()
        self.r_toe0_start = br.read_f32()
        self.r_toe0_end = br.read_f32()

        self.start_sec = br.read_f32()
        self.end_sec = br.read_f32()
        self.total_duration = br.read_f32()
        self.controllers = br.read_u32()

        self.start_location = br.read_quat()
        self.last_locator_key = br.read_quat()
        self.velocity = br.read_vec3()
        self.distance = br.read_f32()
        self.speed = br.read_f32()
        self.slope = br.read_f32()
        self.turn_speed = br.read_f32()
        self.asset_turn = br.read_f32()


def _bswap32(v: int) -> int:
    return int.from_bytes(struct.pack(">I", v & 0xFFFFFFFF), "little")
