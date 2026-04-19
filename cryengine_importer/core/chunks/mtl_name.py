"""ChunkMtlName.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMtlName*.cs.
Implements versions 0x744 / 0x800 / 0x802 / 0x804 (CryEngine path).
The Star Citizen #ivo variants live elsewhere.
"""

from __future__ import annotations

from ...enums import ChunkType, MtlNamePhysicsType, MtlNameType
from ..chunk_registry import Chunk, chunk


class ChunkMtlName(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.mat_type: MtlNameType = MtlNameType.Basic
        self.name: str = ""
        self.physics_type: list[MtlNamePhysicsType | int] = []
        self.num_children: int = 0
        self.child_ids: list[int] = []
        self.n_flags2: int = 0
        self.asset_id: str | None = None
        self.child_names: list[str] | None = None


def _safe_phys(value: int) -> MtlNamePhysicsType | int:
    try:
        return MtlNamePhysicsType(value)
    except ValueError:
        return value


@chunk(ChunkType.MtlName, 0x744)
class ChunkMtlName744(ChunkMtlName):
    def read(self, br) -> None:
        super().read(br)
        self.name = br.read_fstring(128)
        self.num_children = br.read_u32()
        self.mat_type = (
            MtlNameType.Single if self.num_children == 0 else MtlNameType.Library
        )
        self.n_flags2 = 0
        self.physics_type = [_safe_phys(br.read_u32()) for _ in range(self.num_children)]


@chunk(ChunkType.MtlName, 0x800)
class ChunkMtlName800(ChunkMtlName):
    def read(self, br) -> None:
        super().read(br)
        try:
            self.mat_type = MtlNameType(br.read_u32())
        except ValueError:
            self.mat_type = MtlNameType.Basic
        self.n_flags2 = br.read_u32()
        self.name = br.read_fstring(128)
        self.physics_type = [_safe_phys(br.read_u32())]
        self.num_children = br.read_u32()
        self.child_ids = [br.read_u32() for _ in range(self.num_children)]
        # Faithful to C#: a fixed 32-byte pad regardless of NumChildren.
        br.skip(32)


@chunk(ChunkType.MtlName, 0x802)
class ChunkMtlName802(ChunkMtlName):
    """Identical on-disk layout to 0x744 in the reference C#."""

    def read(self, br) -> None:
        super().read(br)
        self.name = br.read_fstring(128)
        self.num_children = br.read_u32()
        self.mat_type = (
            MtlNameType.Single if self.num_children == 0 else MtlNameType.Library
        )
        self.physics_type = [_safe_phys(br.read_u32()) for _ in range(self.num_children)]


@chunk(ChunkType.MtlName, 0x804)
class ChunkMtlName804(ChunkMtlName):
    """GUID-keyed material name."""

    def read(self, br) -> None:
        super().read(br)
        self.asset_id = br.read_fstring(38)
        self.name = self.asset_id or "unknown"
        br.skip(26)
        self.num_children = br.read_u32()
        # Per-child flags (typically 0xFFFFFFFF).
        br.skip(self.num_children * 4)
        self.child_names = [br.read_cstring()]
        for _ in range(self.num_children):
            self.child_names.append(br.read_cstring())
