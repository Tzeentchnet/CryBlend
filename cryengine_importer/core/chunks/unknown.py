"""Fallback chunk used when no implementation is registered.

Port of CgfConverter/CryEngineCore/Chunks/ChunkUnknown.cs. Just records
the position; ``Model.read_chunks`` will skip past the body using the
header's declared size.
"""

from __future__ import annotations

from ..chunk_registry import Chunk


class ChunkUnknown(Chunk):
    def read(self, br) -> None:
        super().read(br)
        # No body interpretation; advance happens via skip_to_end().
