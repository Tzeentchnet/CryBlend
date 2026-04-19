"""ChunkTimingFormat.

Port of CgfConverter/CryEngineCore/Chunks/ChunkTimingFormat*.cs.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


@dataclass
class RangeEntity:
    name: str = ""
    start: int = 0
    end: int = 0


class ChunkTimingFormat(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.secs_per_tick: float = 0.0
        self.ticks_per_frame: int = 0
        self.global_range: RangeEntity = RangeEntity()
        self.num_sub_ranges: int = 0


@chunk(ChunkType.Timing, 0x918)
class ChunkTimingFormat918(ChunkTimingFormat):
    def read(self, br) -> None:
        super().read(br)
        self.secs_per_tick = br.read_f32()
        self.ticks_per_frame = br.read_i32()
        self.global_range = RangeEntity(
            name=br.read_fstring(32),
            start=br.read_i32(),
            end=br.read_i32(),
        )


@chunk(ChunkType.Timing, 0x919)
class ChunkTimingFormat919(ChunkTimingFormat):
    """Same layout as 918 (the C# port carries a 'not tested' note)."""

    def read(self, br) -> None:
        super().read(br)
        self.secs_per_tick = br.read_f32()
        self.ticks_per_frame = br.read_i32()
        self.global_range = RangeEntity(
            name=br.read_fstring(32),
            start=br.read_i32(),
            end=br.read_i32(),
        )
