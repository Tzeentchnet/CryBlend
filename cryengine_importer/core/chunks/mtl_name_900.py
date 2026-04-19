"""ChunkMtlName_900 — IVO material name.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMtlName_900.cs.

Trivial: a single 128-byte fixed-length name. NumChildren is forced
to zero in the C# port (the IVO file format doesn't store children
for this chunk).

Registered against both ``MtlNameIvo`` (0x8335674E) and
``MtlNameIvo320`` (0x83353333), matching the C# Chunk.New routing.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import chunk
from .mtl_name import ChunkMtlName


@chunk(ChunkType.MtlNameIvo, 0x900)
@chunk(ChunkType.MtlNameIvo320, 0x900)
class ChunkMtlName900(ChunkMtlName):
    def read(self, br) -> None:
        super().read(br)
        self.name = br.read_fstring(128)
        self.num_children = 0

