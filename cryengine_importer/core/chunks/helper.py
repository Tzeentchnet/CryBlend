"""ChunkHelper.

Port of CgfConverter/CryEngineCore/Chunks/ChunkHelper*.cs. Only the
0x744 path is implemented here; the legacy 0x362 layout is skipped.
"""

from __future__ import annotations

from ...enums import ChunkType, HelperType
from ..chunk_registry import Chunk, chunk


class ChunkHelper(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.name: str = ""
        self.helper_type: HelperType | int = HelperType.POINT
        self.pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
        # transform stays as None unless the legacy 0x362 path adds it.
        self.transform: tuple[tuple[float, ...], ...] | None = None


@chunk(ChunkType.Helper, 0x744)
class ChunkHelper744(ChunkHelper):
    def read(self, br) -> None:
        super().read(br)
        try:
            self.helper_type = HelperType(br.read_u32())
        except ValueError:
            # Unknown helper type — keep the raw int.
            br.seek(br.tell() - 4)
            self.helper_type = br.read_u32()
        self.pos = br.read_vec3()
