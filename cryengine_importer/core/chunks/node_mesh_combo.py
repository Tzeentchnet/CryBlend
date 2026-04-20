"""ChunkNodeMeshCombo_900 — IVO node table.

Port of CgfConverter/CryEngineCore/Chunks/ChunkNodeMeshCombo_900.cs.

The IVO equivalent of the traditional ChunkNode graph: one record
per scene node with world+local transforms, parent index, and a
geometry-type tag (Geometry / Helper). Material indices and node
names follow as separate tables.

The bound mesh chunk is identified by ``mesh_chunk_id`` per node;
real mesh data lives in a sibling :class:`ChunkIvoSkinMesh` (the
``.skinm`` companion file).
"""

from __future__ import annotations

import logging

from ...enums import ChunkType, IvoGeometryType
from ...models.ivo import NodeMeshCombo
from ..chunk_registry import Chunk, chunk

logger = logging.getLogger(__name__)


class ChunkNodeMeshCombo(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.zero_pad: int = 0
        self.number_of_nodes: int = 0
        self.number_of_meshes: int = 0
        self.unknown2: int = 0
        self.number_of_mesh_subsets: int = 0
        self.string_table_size: int = 0
        self.unknown1: int = 0
        self.unknown3: int = 0
        self.node_mesh_combos: list[NodeMeshCombo] = []
        self.unknown_indices: list[int] = []
        self.material_indices: list[int] = []
        self.node_names: list[str] = []


def _safe_geom_type(value: int) -> IvoGeometryType | int:
    try:
        return IvoGeometryType(value)
    except ValueError:
        return value


@chunk(ChunkType.NodeMeshCombo, 0x900)
class ChunkNodeMeshCombo900(ChunkNodeMeshCombo):
    def read(self, br) -> None:
        super().read(br)
        self.zero_pad = br.read_i32()
        self.number_of_nodes = br.read_i32()
        self.number_of_meshes = br.read_i32()
        self.unknown2 = br.read_i32()
        self.number_of_mesh_subsets = br.read_i32()
        self.string_table_size = br.read_i32()
        self.unknown1 = br.read_i32()
        self.unknown3 = br.read_i32()

        # SC 4.5+ added 32 bytes of zero padding after the header.
        # Older Star Citizen builds (the format CgfConverter v1.7
        # targeted) have no padding — node data starts immediately.
        # The reference C# v2.0.0 unconditionally skips 32 bytes,
        # which silently produces garbage transforms on pre-4.5
        # assets (e.g. ARGO ATLS Mcarog.cga). Detect by peeking:
        # if the next 32 bytes are all zero, treat as padding;
        # otherwise the data starts here.
        peek = br.read_bytes(32)
        if any(b != 0 for b in peek):
            br.seek(-32, 1)
            logger.debug(
                "NodeMeshCombo: no 32-byte zero padding (pre-SC4.5 layout); "
                "first peek bytes=%s",
                peek[:8].hex(),
            )
        else:
            logger.debug(
                "NodeMeshCombo: detected 32-byte zero padding (SC4.5+ layout)"
            )

        for _ in range(self.number_of_nodes):
            n = NodeMeshCombo()
            n.world_to_bone = br.read_matrix3x4()
            n.bone_to_world = br.read_matrix3x4()
            n.scale_component = br.read_vec3()
            n.id = br.read_u32()
            n.unknown2 = br.read_u32()
            n.parent_index = br.read_u16()
            n.geometry_type = _safe_geom_type(br.read_u16())
            n.bounding_box_min = br.read_vec3()
            n.bounding_box_max = br.read_vec3()
            n.unknown3 = (br.read_u32(), br.read_u32(), br.read_u32(), br.read_u32())
            n.number_of_vertices = br.read_u32()
            n.number_of_children = br.read_u16()
            n.mesh_chunk_id = br.read_u16()
            br.skip(40)  # 40 bytes of unknown trailing data per node
            self.node_mesh_combos.append(n)

        self.unknown_indices = [br.read_u16() for _ in range(self.unknown2)]
        self.material_indices = [
            br.read_u16() for _ in range(self.number_of_mesh_subsets)
        ]

        # Null-separated node-name table (bounded by string_table_size
        # per v2.0.0 to prevent buffer overruns on corrupt inputs).
        from .compiled_bones_ivo import _read_null_separated_strings

        self.node_names = _read_null_separated_strings(
            br, self.number_of_nodes, self.string_table_size
        )

        if logger.isEnabledFor(logging.DEBUG):
            for i, n in enumerate(self.node_mesh_combos[:3]):
                name = self.node_names[i] if i < len(self.node_names) else "?"
                logger.debug(
                    "NodeMeshCombo[%d] name=%r id=%d parent=%d geom_type=%s "
                    "mesh_chunk_id=%d num_verts=%d bone_to_world.translation=%s",
                    i,
                    name,
                    n.id,
                    n.parent_index,
                    n.geometry_type,
                    n.mesh_chunk_id,
                    n.number_of_vertices,
                    getattr(n.bone_to_world, "translation", n.bone_to_world),
                )
