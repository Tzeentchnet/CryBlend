"""ChunkMeshPhysicsData.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMeshPhysicsData*.cs.

The C# tree only ever provides a no-op reader for this chunk
(``ChunkMeshPhysicsData_800.Read`` is a TODO stub that just calls
``base.Read``). Nothing downstream — Wavefront, Collada, glTF, USD —
ever consumes the parsed body, and the on-disk layout for the
``PhysicsData`` payload (``Models/PhysicsData.cs`` +
``Models/Structs/Structs.cs``) is annotated as unverified.

We mirror that behaviour: the chunk is registered so the file's chunk
table resolves cleanly to a typed instance (rather than falling
through to the generic "unknown" skip path) and exposes the small set
of header fields the C# class declares, but the trailing physics
payload is left unread. Vertex / triangle data for collision meshes
is irrelevant to Blender import — Blender users wire physics through
the Rigid Body / Collision modifiers, not via baked CryEngine
tetrahedra.
"""

from __future__ import annotations

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


class ChunkMeshPhysicsData(Chunk):
    """Common base for all MeshPhysicsData versions."""

    def __init__(self) -> None:
        super().__init__()
        # Mirrors the public surface of the C# ``ChunkMeshPhysicsData``
        # base class. All zero unless a concrete version's ``read``
        # populates them.
        self.physics_data_size: int = 0
        self.flags: int = 0
        self.tetrahedra_data_size: int = 0
        self.tetrahedra_id: int = 0
        self.reserved1: int = 0
        self.reserved2: int = 0


@chunk(ChunkType.MeshPhysicsData, 0x800)
class ChunkMeshPhysicsData800(ChunkMeshPhysicsData):
    """No-op MeshPhysicsData reader (matches C# ``ChunkMeshPhysicsData_800``).

    The C# concrete class is a TODO stub that just calls ``base.Read``;
    we do the same. The chunk's bytes remain in the underlying stream
    unread — the chunk-table walker advances past them via the offset
    + size recorded in the header.
    """

    def read(self, br) -> None:  # noqa: ARG002 - intentionally unused
        super().read(br)
