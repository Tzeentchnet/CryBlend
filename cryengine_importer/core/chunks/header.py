"""Chunk header readers.

Port of CgfConverter/CryEngineCore/Chunks/ChunkHeader{,_744,_745,_746,_900}.cs.
Each file version stores the chunk-table entries differently.
"""

from __future__ import annotations

import random

from ...enums import ChunkType, FileVersion
from ..chunk_registry import Chunk, header_for


def _safe_chunk_type(value: int) -> ChunkType | int:
    """Match the C# `(ChunkType)value` cast which silently accepts
    unknown values. The chunk factory falls through to ChunkUnknown
    for unrecognised types so partial coverage doesn't abort parsing."""
    try:
        return ChunkType(value)
    except ValueError:
        return value


class ChunkHeader(Chunk):
    """Base class. Subclasses set chunk_type / version_raw / offset /
    id / size from the file's chunk table layout."""

    def read(self, br) -> None:  # type: ignore[override]
        # Headers don't use the parent Chunk.read seek/preamble logic;
        # they're driven directly from the model loader's chunk-table
        # cursor.
        raise NotImplementedError


@header_for(FileVersion.x0744)
class ChunkHeader744(ChunkHeader):
    """16-byte header, no size field (sizes are derived from the next
    entry's offset)."""

    def read(self, br) -> None:
        self.chunk_type = _safe_chunk_type(br.read_u32())
        self.version_raw = br.read_u32()
        self.offset = br.read_u32()
        self.id = br.read_i32()
        self.size = 0


@header_for(FileVersion.x0745)
class ChunkHeader745(ChunkHeader):
    """20-byte header: type, version, offset, id, size."""

    def read(self, br) -> None:
        self.chunk_type = _safe_chunk_type(br.read_u32())
        self.version_raw = br.read_u32()
        self.offset = br.read_u32()
        self.id = br.read_i32()
        self.size = br.read_u32()


@header_for(FileVersion.x0746)
class ChunkHeader746(ChunkHeader):
    """16-byte header. Type is a u16 added to 0xCCCBF000."""

    def read(self, br) -> None:
        self.chunk_type = _safe_chunk_type(br.read_u16() + 0xCCCBF000)
        self.version_raw = br.read_u16()
        self.id = br.read_i32()
        self.size = br.read_u32()
        self.offset = br.read_u32()


@header_for(FileVersion.x0900)
class ChunkHeader900(ChunkHeader):
    """20-byte header. Offsets are u64; chunks have no IDs (we mint
    randoms to keep ChunkMap unique)."""

    _rng = random.Random(0)
    _used: set[int] = set()

    def read(self, br) -> None:
        self.chunk_type = _safe_chunk_type(br.read_u32())
        self.version_raw = br.read_u32()
        self.offset = br.read_u64()
        # Mint a unique synthetic id in [1, 1_000_000).
        while True:
            cand = ChunkHeader900._rng.randrange(1, 1_000_000)
            if cand not in ChunkHeader900._used:
                ChunkHeader900._used.add(cand)
                self.id = cand
                break
        self.size = 0  # 0x900 has no per-entry size; derived from next.
