"""ChunkExportFlags.

Port of CgfConverter/CryEngineCore/Chunks/ChunkExportFlags*.cs.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkExportFlags(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.chunk_offset: int = 0
        self.flags: int = 0
        self.rc_version: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.rc_version_string: str = ""


@chunk(ChunkType.ExportFlags, 0x1)
class ChunkExportFlags1(ChunkExportFlags):
    def read(self, br) -> None:
        super().read(br)
        # For 0x744/0x745 files base.read already consumed a 16-byte
        # chunk preamble; the format then repeats those 4 fields here
        # (CryTek quirk — the C# port assigns them back over ChunkType
        # / VersionRaw / Offset / ID). For 0x746+/0x900 these are simply
        # the first on-disk fields. Either way: 4 uints, then 4 bytes
        # of Flags, then RCVersion[4], RCVersionString[16].
        try:
            self.chunk_type = ChunkType(br.read_u32())
        except ValueError:
            # Unknown raw type — leave header's value in place.
            pass
        self.version_raw = br.read_u32()
        self.chunk_offset = br.read_u32()
        self.id = br.read_i32()
        self.flags = br.read_u32()
        self.rc_version = (
            br.read_u32(),
            br.read_u32(),
            br.read_u32(),
            br.read_u32(),
        )
        self.rc_version_string = br.read_fstring(16)
        # Model._read_chunks calls skip_to_end after this; no trailing
        # SkipBytes needed.
