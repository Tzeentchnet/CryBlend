"""ChunkIvoDBAMetadata — Star Citizen #ivo DBA library metadata.

Port of CgfConverter/CryEngineCore/Chunks/ChunkIvoDBAMetadata.cs +
ChunkIvoDBAMetadata_900.cs + ChunkIvoDBAMetadata_901.cs (v2.0.0).

Carries the per-animation metadata (44 bytes each: flags, FPS,
controller count, two unknowns, reference pose) and a parallel
null-terminated string table giving each animation's path. Pairs with
:class:`ChunkIvoDBAData` to give each ``IvoAnimationBlock`` a name.

The 0x900 and 0x901 variants share an identical on-disk layout; only
the C# logging differs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ...models.ivo_animation import IvoDBAMetaEntry
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkIvoDBAMetadata(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.anim_count: int = 0
        self.entries: list[IvoDBAMetaEntry] = []
        self.anim_paths: list[str] = []

    def _read_body(self, br: "BinaryReader") -> None:
        self.anim_count = br.read_u32()
        for _ in range(self.anim_count):
            self.entries.append(
                IvoDBAMetaEntry(
                    flags=br.read_u32(),
                    frames_per_second=br.read_u16(),
                    num_controllers=br.read_u16(),
                    unknown1=br.read_u32(),
                    unknown2=br.read_u32(),
                    start_rotation=br.read_quat(),
                    start_position=br.read_vec3(),
                )
            )
        for _ in range(self.anim_count):
            self.anim_paths.append(br.read_cstring())


@chunk(ChunkType.IvoDBAMetadata, 0x900)
class ChunkIvoDBAMetadata900(ChunkIvoDBAMetadata):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self._read_body(br)


@chunk(ChunkType.IvoDBAMetadata, 0x901)
class ChunkIvoDBAMetadata901(ChunkIvoDBAMetadata):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self._read_body(br)
