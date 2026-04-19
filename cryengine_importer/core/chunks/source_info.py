"""ChunkSourceInfo.

Port of CgfConverter/CryEngineCore/Chunks/ChunkSourceInfo*.cs.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkSourceInfo(Chunk):
    """Base for SourceInfo readers."""

    def __init__(self) -> None:
        super().__init__()
        self.source_file: str = ""
        self.date: str = ""
        self.author: str = ""


@chunk(ChunkType.SourceInfo, 0x0)
class ChunkSourceInfo0(ChunkSourceInfo):
    """Standard ChunkSourceInfo (CryEngine 0x744..0x900).

    Custom seek behaviour: peek the first u32; if it equals the chunk
    type (or ``+ 0xCCCBF000``), skip the embedded 12-byte preamble.
    Otherwise rewind. This mirrors ChunkSourceInfo_0.cs.
    """

    def read(self, br) -> None:
        assert self.header is not None
        self.chunk_type = self.header.chunk_type
        self.version_raw = self.header.version_raw
        self.offset = self.header.offset
        self.id = self.header.id
        self.size = self.header.size
        self.data_size = self.size

        br.is_big_endian = self.is_big_endian
        br.seek(self.offset)
        peek = br.read_u32()
        source_info = int(ChunkType.SourceInfo)
        if peek == source_info or (peek + 0xCCCBF000) & 0xFFFFFFFF == source_info:
            # Skip the rest of the 16-byte embedded header (we already
            # consumed 4 of the 16 with the peek).
            br.skip(12)
        else:
            br.seek(self.offset)

        self.source_file = br.read_cstring()
        self.date = br.read_cstring().rstrip()
        if "\n" in self.date:
            head, _, tail = self.date.partition("\n")
            self.date = head
            self.author = tail
        else:
            self.author = br.read_cstring()


@chunk(ChunkType.SourceInfo, 0x1)
class ChunkSourceInfo1(ChunkSourceInfo):
    """New World chr files: just a NUL-terminated source path."""

    def read(self, br) -> None:
        assert self.header is not None
        self.chunk_type = self.header.chunk_type
        self.version_raw = self.header.version_raw
        self.offset = self.header.offset
        self.id = self.header.id
        self.size = self.header.size
        self.data_size = self.size

        br.is_big_endian = self.is_big_endian
        br.seek(self.offset)
        self.source_file = br.read_cstring()
