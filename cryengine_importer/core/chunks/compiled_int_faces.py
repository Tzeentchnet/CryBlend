"""ChunkCompiledIntFaces.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledIntFaces*.cs.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import TFace
from ..chunk_registry import Chunk, chunk


class ChunkCompiledIntFaces(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_int_faces: int = 0
        self.faces: list[TFace] = []


@chunk(ChunkType.CompiledIntFaces, 0x800)
class ChunkCompiledIntFaces800(ChunkCompiledIntFaces):
    """Array of TFaces (3 uint16 per face)."""

    def read(self, br) -> None:
        super().read(br)
        # In old (0x744/0x745) files Chunk.read consumes 16 bytes of
        # preamble and updates data_size accordingly; in newer files
        # data_size == size. We use data_size to size the array.
        self.num_int_faces = self.data_size // 6
        for _ in range(self.num_int_faces):
            self.faces.append(
                TFace(i0=br.read_u16(), i1=br.read_u16(), i2=br.read_u16())
            )
