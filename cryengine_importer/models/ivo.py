"""IVO (Star Citizen) data classes.

Port of the structs / records under
``CgfConverter/Models/Structs/Structs.cs`` that are exclusive to the
``#ivo`` file format (Phase 5):

- :class:`IvoGeometryMeshDetails` — header inside ChunkIvoSkinMesh_900.
- :class:`IvoMeshSubset` — submesh entry inside ChunkIvoSkinMesh_900.
- :class:`NodeMeshCombo` — single per-node row in ChunkNodeMeshCombo_900.

The chunk readers store these as plain dataclass instances on the
chunk; higher-level code (the CryEngine aggregator) walks them to
build a Blender-friendly node hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..enums import IvoGeometryType, VertexFormat


_BBOX = tuple[tuple[float, float, float], tuple[float, float, float]]
_VEC3 = tuple[float, float, float]
_MAT34 = tuple[tuple[float, ...], ...]


@dataclass
class IvoGeometryMeshDetails:
    """Port of Models/Structs/Structs.cs#IvoGeometryMeshDetails."""

    flags2: int = 0
    number_of_vertices: int = 0
    number_of_indices: int = 0
    number_of_submeshes: int = 0
    unknown: int = 0
    bounding_box: _BBOX = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    scaling_bounding_box: _BBOX = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    vertex_format: VertexFormat | int = VertexFormat.eVF_Unknown


@dataclass
class IvoMeshSubset:
    """Port of Models/Structs/Structs.cs#IvoMeshSubset (the per-submesh
    record stored by ChunkIvoSkinMesh_900). Distinct from the
    traditional :class:`MeshSubset` because IVO files include a
    ``node_parent_index`` (submesh-to-node binding) and a couple of
    extra unknown ints."""

    mat_id: int = 0
    node_parent_index: int = 0
    first_index: int = 0
    num_indices: int = 0
    first_vertex: int = 0
    unknown: int = 0
    num_vertices: int = 0
    radius: float = 0.0
    center: _VEC3 = (0.0, 0.0, 0.0)
    unknown1: int = 0
    unknown2: int = 0


@dataclass
class NodeMeshCombo:
    """Port of CryEngineCore/Chunks/ChunkNodeMeshCombo.cs#NodeMeshCombo.
    One entry per node in ChunkNodeMeshCombo_900."""

    world_to_bone: _MAT34 = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    bone_to_world: _MAT34 = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    scale_component: _VEC3 = (1.0, 1.0, 1.0)
    id: int = 0
    unknown2: int = 0
    parent_index: int = 0xFFFF
    geometry_type: IvoGeometryType | int = IvoGeometryType.Geometry
    bounding_box_min: _VEC3 = (0.0, 0.0, 0.0)
    bounding_box_max: _VEC3 = (0.0, 0.0, 0.0)
    unknown3: tuple[int, int, int, int] = (0, 0, 0, 0)
    number_of_vertices: int = 0
    number_of_children: int = 0
    mesh_chunk_id: int = 0


__all__ = [
    "IvoGeometryMeshDetails",
    "IvoMeshSubset",
    "NodeMeshCombo",
]
