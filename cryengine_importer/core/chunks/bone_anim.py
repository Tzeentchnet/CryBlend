"""ChunkBoneAnim.

Port of CgfConverter/CryEngineCore/Chunks/ChunkBoneAnim_290.cs.

The C# reference is a TODO stub — it reads no body. We mirror that:
the chunk type registers so files that contain it don't bomb the
loader, but no fields are populated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkBoneAnim(Chunk):
    pass


@chunk(ChunkType.BoneAnim, 0x290)
class ChunkBoneAnim290(ChunkBoneAnim):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        # Body intentionally not parsed (matches C# reference).
