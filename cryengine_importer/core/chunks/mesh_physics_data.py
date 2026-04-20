"""ChunkMeshPhysicsData.

Port of CgfConverter/CryEngineCore/Chunks/ChunkMeshPhysicsData*.cs
plus the on-disk payload layout from PyFFI's ``cgf.xml`` schema.

The C# tree provides only a no-op reader for this chunk
(``ChunkMeshPhysicsData_800.Read`` is a TODO stub) and never actually
decodes the trailing ``PhysicsData`` payload. PyFFI does have a full
schema for the chunk in ``pyffi/formats/cgf/cgf.xml`` (struct
``MeshPhysicsDataChunk`` + ``PhysicsData`` + ``PhysicsCube`` /
``PhysicsCylinder`` / ``PhysicsShape6``), so we use that as the
authoritative spec for the parts that are well-defined.

See :mod:`cryengine_importer.models.physics` for which primitive types
are decoded vs. deferred.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.physics import PhysicsData, read_physics_data
from ..chunk_registry import Chunk, chunk


class ChunkMeshPhysicsData(Chunk):
    """Common base for all MeshPhysicsData versions."""

    def __init__(self) -> None:
        super().__init__()
        # Mirrors the public surface of the C# ``ChunkMeshPhysicsData``
        # base class, populated by the 0x800 reader below.
        self.physics_data_size: int = 0
        self.flags: int = 0
        self.tetrahedra_data_size: int = 0
        self.tetrahedra_id: int = 0
        self.reserved1: int = 0
        self.reserved2: int = 0
        # Decoded payload (None when ``physics_data_size == 0``).
        self.physics_data: PhysicsData | None = None
        # Raw tetrahedra bytes (kept as bytes — pyffi only models
        # them as ``ubyte[]`` and they are not consumed downstream).
        self.tetrahedra_data: bytes = b""


@chunk(ChunkType.MeshPhysicsData, 0x800)
class ChunkMeshPhysicsData800(ChunkMeshPhysicsData):
    """MeshPhysicsData v0x800 reader.

    Layout per pyffi ``cgf.xml#MeshPhysicsDataChunk`` (version 800):

    * 24-byte header: ``physics_data_size`` / ``flags`` /
      ``tetrahedra_data_size`` / ``tetrahedra`` (chunk-id ref) /
      ``reserved1`` / ``reserved2`` (all uint32).
    * If ``physics_data_size != 0``: one :class:`PhysicsData` record.
    * Then ``tetrahedra_data_size`` raw bytes.

    The chunk-table walker advances past any unread trailing bytes via
    the chunk header's ``size`` field, so it's safe to early-exit (e.g.
    on a polyhedron primitive whose layout we don't ship).
    """

    def read(self, br) -> None:
        super().read(br)

        # Empty / undersized chunks keep their defaults — matches the
        # previous no-op behaviour that some test fixtures rely on.
        # ``size == 0`` happens for IVO-style chunks that have no
        # declared per-entry size; we currently don't ship a 0x900
        # MeshPhysicsData reader, so the safe thing is to bail.
        if self.size < 24:
            return

        self.physics_data_size = br.read_u32()
        self.flags = br.read_u32()
        self.tetrahedra_data_size = br.read_u32()
        self.tetrahedra_id = br.read_u32()
        self.reserved1 = br.read_u32()
        self.reserved2 = br.read_u32()

        if self.physics_data_size != 0:
            self.physics_data = read_physics_data(br)

        # Tetrahedra payload is just raw bytes per pyffi. Cap by what's
        # left in the chunk so a short / corrupt header can't
        # over-consume the stream.
        if self.tetrahedra_data_size:
            remaining = self._remaining_in_chunk(br)
            n = self.tetrahedra_data_size
            if remaining >= 0:
                n = min(n, max(remaining, 0))
            if n:
                self.tetrahedra_data = br.read_bytes(n)

    # --- helpers -------------------------------------------------------

    def _remaining_in_chunk(self, br) -> int:
        """Bytes left between current position and chunk end (or
        ``-1`` if the chunk has no declared size — IVO-style)."""
        if self.size <= 0:
            return -1
        end = self.offset + self.size
        return end - br.tell()
