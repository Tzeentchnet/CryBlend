"""ChunkSceneProp.

Port of CgfConverter/CryEngineCore/Chunks/ChunkSceneProp*.cs.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkSceneProp(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_props: int = 0
        self.prop_keys: list[str] = []
        self.prop_values: list[str] = []


@chunk(ChunkType.SceneProps, 0x744)
class ChunkSceneProp744(ChunkSceneProp):
    """31 entries on disk; key=String32, value=String64."""

    def read(self, br) -> None:
        super().read(br)
        self.num_props = br.read_u32()
        self.prop_keys = [br.read_fstring(32) for _ in range(self.num_props)]
        self.prop_values = [br.read_fstring(64) for _ in range(self.num_props)]
