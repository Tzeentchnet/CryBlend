"""ChunkCompiledMorphTargets.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledMorphTargets*.cs.

Three concrete versions:

- ``0x800`` : ``u32 count`` followed by ``count`` × 16-byte
  :class:`MorphTargetVertex` records (``u32 vertex_id`` + ``vec3 pos``).
  The position is the *absolute deformed coordinate*, not a delta.
- ``0x801`` : C# reader is a no-op (its body is commented out). We
  mirror that — the chunk is registered so it parses cleanly, but
  produces an empty vertex list.
- ``0x802`` : Identical layout to ``0x800``.

The C# tree never *consumes* morph data — no renderer touches it. The
Blender bridge in :mod:`cryengine_importer.blender.scene_builder`
materialises one shape key per ``ChunkCompiledMorphTargets`` chunk
attached to the mesh's owning model.

Note: the legacy 0xCCCC0011 ``MeshMorphTarget`` chunk is intentionally
not handled — its concrete C# reader (``ChunkMeshMorphTargets_001``)
is also a TODO no-op and the abstract base is annotated "no longer
used".
"""

from __future__ import annotations

from dataclasses import dataclass

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk


@dataclass
class MorphTargetVertex:
    """One displaced vertex inside a ``CompiledMorphTargets`` chunk.

    ``vertex`` is the absolute deformed position (not a delta vs the
    base mesh).
    """

    vertex_id: int
    vertex: tuple[float, float, float]


class ChunkCompiledMorphTargets(Chunk):
    """Common base for all CompiledMorphTargets versions."""

    def __init__(self) -> None:
        super().__init__()
        self.number_of_morph_targets: int = 0
        self.morph_target_vertices: list[MorphTargetVertex] = []


def _read_morph_vertex(br) -> MorphTargetVertex:
    return MorphTargetVertex(
        vertex_id=br.read_u32(),
        vertex=br.read_vec3(),
    )


def _read_count_then_vertices(self: ChunkCompiledMorphTargets, br) -> None:
    self.number_of_morph_targets = br.read_u32()
    self.morph_target_vertices = [
        _read_morph_vertex(br) for _ in range(self.number_of_morph_targets)
    ]


@chunk(ChunkType.CompiledMorphTargets, 0x800)
class ChunkCompiledMorphTargets800(ChunkCompiledMorphTargets):
    def read(self, br) -> None:
        super().read(br)
        _read_count_then_vertices(self, br)


@chunk(ChunkType.CompiledMorphTargets, 0x801)
class ChunkCompiledMorphTargets801(ChunkCompiledMorphTargets):
    """No-op: C# reader's body is commented out in v1.7.1 and v2.0.0."""

    def read(self, br) -> None:
        super().read(br)


@chunk(ChunkType.CompiledMorphTargets, 0x802)
class ChunkCompiledMorphTargets802(ChunkCompiledMorphTargets):
    def read(self, br) -> None:
        super().read(br)
        _read_count_then_vertices(self, br)


# Star Citizen variant — same factory routing as upstream
# (ChunkType.CompiledMorphTargetsSC -> ChunkCompiledMorphTargets in
# CgfConverter/CryEngineCore/Chunks/Chunk.cs).
@chunk(ChunkType.CompiledMorphTargetsSC, 0x800)
class ChunkCompiledMorphTargetsSC800(ChunkCompiledMorphTargets800):
    pass


@chunk(ChunkType.CompiledMorphTargetsSC, 0x801)
class ChunkCompiledMorphTargetsSC801(ChunkCompiledMorphTargets801):
    pass


@chunk(ChunkType.CompiledMorphTargetsSC, 0x802)
class ChunkCompiledMorphTargetsSC802(ChunkCompiledMorphTargets802):
    pass
