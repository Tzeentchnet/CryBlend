"""ChunkBoneNameList.

Port of CgfConverter/CryEngineCore/Chunks/ChunkBoneNameList*.cs.
Only the legacy 0x745 layout is implemented.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkBoneNameList(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_entities: int = 0
        self.bone_names: list[str] = []


@chunk(ChunkType.BoneNameList, 0x745)
class ChunkBoneNameList745(ChunkBoneNameList):
    def read(self, br) -> None:
        super().read(br)
        size_of_list = br.read_i32()
        upper_offset = self.offset + self.size

        i = 0
        while i < size_of_list and br.tell() < upper_offset:
            self.bone_names.append(br.read_cstring())
            i += 1
        self.num_entities = i
        if i < size_of_list:
            raise ValueError(
                f"Only {i} out of {size_of_list} bones found in BoneNameList"
            )
