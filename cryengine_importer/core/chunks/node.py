"""ChunkNode.

Port of CgfConverter/CryEngineCore/Chunks/ChunkNode*.cs.
Implements 0x823 and 0x824 (functionally identical in the reference).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from .helper import ChunkHelper
    from .mesh import ChunkMesh

# Position columns in the row-major 4x4 matrix are scaled to metres
# (CryEngine stores positions in centimetres in some formats).
VERTEX_SCALE = 1.0 / 100.0


class ChunkNode(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.name: str = ""
        self.object_node_id: int = 0
        self.parent_node_id: int = -1
        self.parent_node_index: int = 0
        self.num_children: int = 0
        self.material_id: int = 0
        self.transform: tuple[tuple[float, ...], ...] = (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        self.pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.rot: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
        self.scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
        self.pos_ctrl_id: int = 0
        self.rot_ctrl_id: int = 0
        self.scl_ctrl_id: int = 0
        self.properties: str = ""
        self.property_string_length: int = 0

        # Populated by the CryEngine aggregator (Phase 1.5+), not by
        # the chunk reader itself. Mirrors fields on the C# ChunkNode.
        self.parent_node: "ChunkNode | None" = None
        self.children: list["ChunkNode"] = []
        self.mesh_data: "ChunkMesh | None" = None
        self.chunk_helper: "ChunkHelper | None" = None
        self.material_file_name: str | None = None
        # Phase 5 — IVO only. When set, identifies this node's index
        # in the originating ChunkNodeMeshCombo, used by mesh_builder
        # to filter the shared IvoSkinMesh's subsets via NodeParentIndex.
        self.ivo_node_index: int | None = None

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------

    @property
    def world_matrix(self) -> tuple[tuple[float, ...], ...]:
        """Local-to-world 4x4, row-major (translation in last row).

        Mirrors C# `WavefrontModelRenderer.GetNestedTransformations`:
        ``world = local * parent.world``. Walks the `parent_node`
        chain wired up by the CryEngine aggregator.
        """
        m = self.transform
        parent = self.parent_node
        while parent is not None:
            m = _matmul4(m, parent.transform)
            parent = parent.parent_node
        return m


def _matmul4(
    a: tuple[tuple[float, ...], ...],
    b: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    """4x4 row-major multiply: ``(a * b)[i][j] = sum_k a[i][k] * b[k][j]``."""
    return tuple(
        tuple(
            a[i][0] * b[0][j]
            + a[i][1] * b[1][j]
            + a[i][2] * b[2][j]
            + a[i][3] * b[3][j]
            for j in range(4)
        )
        for i in range(4)
    )


def _read_node_body(self: ChunkNode, br) -> None:
    self.name = br.read_fstring(64) or "unknown"
    self.object_node_id = br.read_i32()
    self.parent_node_id = br.read_i32()
    self.num_children = br.read_i32()
    self.material_id = br.read_i32()
    br.skip(4)

    rows = []
    for r in range(4):
        row = (br.read_f32(), br.read_f32(), br.read_f32(), br.read_f32())
        if r == 3:
            row = (
                row[0] * VERTEX_SCALE,
                row[1] * VERTEX_SCALE,
                row[2] * VERTEX_SCALE,
                row[3],
            )
        rows.append(row)
    self.transform = tuple(rows)

    self.pos = br.read_vec3()
    self.rot = br.read_quat()
    self.scale = br.read_vec3()

    self.pos_ctrl_id = br.read_i32()
    self.rot_ctrl_id = br.read_i32()
    self.scl_ctrl_id = br.read_i32()
    self.property_string_length = br.read_i32()


@chunk(ChunkType.Node, 0x823)
class ChunkNode823(ChunkNode):
    def read(self, br) -> None:
        super().read(br)
        _read_node_body(self, br)


@chunk(ChunkType.Node, 0x824)
class ChunkNode824(ChunkNode):
    def read(self, br) -> None:
        super().read(br)
        _read_node_body(self, br)
