"""ChunkIvoAnimInfo — Star Citizen #ivo animation metadata.

Port of CgfConverter/CryEngineCore/Chunks/ChunkIvoAnimInfo.cs +
ChunkIvoAnimInfo_901.cs (v2.0.0).

48-byte chunk that lives alongside a :class:`ChunkIvoCAF` in a #ivo
``.caf`` file. Carries the FPS, bone count, end frame, and reference
pose for the animation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkIvoAnimInfo(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.flags: int = 0
        self.frames_per_second: int = 0
        self.num_bones: int = 0
        self.reserved: int = 0
        self.end_frame: int = 0
        self.start_rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.start_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.padding: int = 0


@chunk(ChunkType.IvoAnimInfo, 0x901)
class ChunkIvoAnimInfo901(ChunkIvoAnimInfo):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self.flags = br.read_u32()
        self.frames_per_second = br.read_u16()
        self.num_bones = br.read_u16()
        self.reserved = br.read_u32()
        self.end_frame = br.read_u32()
        self.start_rotation = br.read_quat()
        self.start_position = br.read_vec3()
        self.padding = br.read_u32()
