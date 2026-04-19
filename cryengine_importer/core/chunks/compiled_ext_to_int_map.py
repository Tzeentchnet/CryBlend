"""ChunkCompiledExtToIntMap.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledExtToIntMap*.cs.
Maps external (rendered) vertex indices to internal (skinning) ones.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkCompiledExtToIntMap(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_ext_vertices: int = 0
        self.source: list[int] = []


@chunk(ChunkType.CompiledExt2IntMap, 0x800)
class ChunkCompiledExtToIntMap800(ChunkCompiledExtToIntMap):
    def read(self, br) -> None:
        super().read(br)
        self.num_ext_vertices = self.data_size // 2  # sizeof(uint16)
        self.source = [br.read_u16() for _ in range(self.num_ext_vertices)]
