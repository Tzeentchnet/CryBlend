"""Blender bridge: turn a `CryEngine` asset into bpy data.

This is the *only* parser-side module that imports `bpy`. Everything
upstream (`core/`, `io/`, `models/`) is plain Python and unit-testable
without Blender.

Pipeline (mirrors `WavefrontModelRenderer.WriteRootNode` / the Collada
node walker on the C# side):

    CryEngine.process()
        -> for each ChunkNode:
            build_geometry(node) -> MeshGeometry | None
            create bpy.types.Mesh + Object (or Empty for helpers)
            assign per-subset materials (parsed `.mtl` -> Principled BSDF
            graph; falls back to a placeholder when no library matches)
            wire parent/child via obj.parent + matrix_local

Skinning / armature are deferred to Phase 3.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]
from mathutils import Matrix  # type: ignore[import-not-found]

from ..core.mesh_builder import build_geometry
from ..enums import HelperType
from ..models.geometry import MeshGeometry
from .action_builder import build_actions
from .armature_builder import attach_skin, build_armature
from .material_builder import build_material

if TYPE_CHECKING:
    from ..core.chunks.node import ChunkNode
    from ..core.cryengine import CryEngine
    from ..materials.material import Material


def build_scene(
    cryengine: "CryEngine",
    *,
    collection: "bpy.types.Collection | None" = None,
) -> "bpy.types.Collection":
    """Materialize ``cryengine`` into ``collection`` (or a new one)."""
    if collection is None:
        collection = bpy.data.collections.new(cryengine.name)
        bpy.context.scene.collection.children.link(collection)

    node_to_obj: dict[int, "bpy.types.Object"] = {}

    for node in cryengine.nodes:
        obj = _create_object_for_node(node, collection, cryengine)
        if obj is not None:
            node_to_obj[node.id] = obj

    for node in cryengine.nodes:
        obj = node_to_obj.get(node.id)
        if obj is None:
            continue

        local = _row_major_to_matrix(node.transform)

        if node.parent_node is not None and node.parent_node.id in node_to_obj:
            parent_obj = node_to_obj[node.parent_node.id]
            obj.parent = parent_obj
            obj.matrix_local = local
        else:
            obj.matrix_world = local

    # --- skinning (Phase 3) ------------------------------------------
    if cryengine.skinning_info.has_skinning_info:
        arm_obj = build_armature(cryengine, collection=collection)
        if arm_obj is not None:
            for obj in node_to_obj.values():
                if obj.type == "MESH":
                    attach_skin(arm_obj, obj, cryengine)

            # --- animation (Phase 4) ---------------------------------
            if cryengine.animation_clips:
                build_actions(cryengine, arm_obj)

    return collection


# ---------------------------------------------------------------- helpers


def _create_object_for_node(
    node: "ChunkNode",
    collection: "bpy.types.Collection",
    cryengine: "CryEngine",
) -> "bpy.types.Object | None":
    """Build either a mesh-backed Object or an Empty for ``node``."""
    geom = build_geometry(node)

    if geom is None or geom.num_vertices == 0:
        empty = bpy.data.objects.new(node.name or f"node_{node.id}", None)
        _apply_helper_display(empty, node)
        collection.objects.link(empty)
        return empty

    mesh = _build_bpy_mesh(node.name or f"mesh_{node.id}", geom, node, cryengine)
    obj = bpy.data.objects.new(node.name or f"node_{node.id}", mesh)
    collection.objects.link(obj)
    if geom.morph_targets:
        _apply_shape_keys(obj, geom)
    return obj


# Phase 7 — visualise CryEngine HelperType values via Blender's empty
# display modes. The C# tree never specialises by HelperType (every
# helper renders as a generic Collada/Wavefront <node>), so this is
# purely a Blender-side UX hint that mirrors the semantic distinction:
#
#     POINT / DUMMY / GEOMETRY -> PLAIN_AXES (default look)
#     XREF                     -> ARROWS    (signals "external ref")
#     CAMERA                   -> CONE      (closest to a viewport cam)
#
# Anything not parsed as a known HelperType (e.g. an unknown raw int
# fallback from ``ChunkHelper744.read``) keeps the default display.
_HELPER_DISPLAY: dict[HelperType, str] = {
    HelperType.POINT: "PLAIN_AXES",
    HelperType.DUMMY: "PLAIN_AXES",
    HelperType.GEOMETRY: "PLAIN_AXES",
    HelperType.XREF: "ARROWS",
    HelperType.CAMERA: "CONE",
}


def _apply_helper_display(empty: "bpy.types.Object", node: "ChunkNode") -> None:
    """Set ``empty``'s display mode according to its CryEngine
    :class:`HelperType` (when available)."""
    empty.empty_display_size = 0.1
    helper = getattr(node, "chunk_helper", None)
    if helper is None:
        return
    display = _HELPER_DISPLAY.get(helper.helper_type)
    if display is not None:
        try:
            empty.empty_display_type = display
        except (AttributeError, TypeError):  # pragma: no cover - bpy variance
            pass


def _build_bpy_mesh(
    name: str,
    geom: MeshGeometry,
    node: "ChunkNode",
    cryengine: "CryEngine",
) -> "bpy.types.Mesh":
    mesh = bpy.data.meshes.new(name)

    triangles = geom.triangles
    mesh.from_pydata(geom.positions, [], triangles)
    mesh.update(calc_edges=True)

    if geom.uvs and len(geom.uvs) >= len(geom.positions):
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_data = uv_layer.data
        uvs = geom.uvs
        for loop in mesh.loops:
            u, v = uvs[loop.vertex_index]
            # CryEngine V is top-down; Blender expects bottom-up.
            uv_data[loop.index].uv = (u, 1.0 - v)

    if geom.colors and len(geom.colors) >= len(geom.positions):
        try:
            color_layer = mesh.color_attributes.new(
                name="Color", type="FLOAT_COLOR", domain="CORNER"
            )
            for loop in mesh.loops:
                color_layer.data[loop.index].color = geom.colors[loop.vertex_index]
        except Exception:  # pragma: no cover - bpy version variance
            pass

    if geom.subsets:
        slot_for_mat: dict[int, int] = {}
        for s in geom.subsets:
            if s.mat_id in slot_for_mat:
                continue
            slot_for_mat[s.mat_id] = len(mesh.materials)
            resolved = _resolve_material(cryengine, node, s.mat_id)
            if resolved is not None:
                mesh.materials.append(
                    build_material(resolved, pack_fs=cryengine.pack_fs)
                )
            else:
                mesh.materials.append(_placeholder_material(f"{name}_mat{s.mat_id}"))

        # Subsets store ranges in the index buffer; one triangle = 3 indices.
        for s in geom.subsets:
            slot = slot_for_mat[s.mat_id]
            tri_start = s.first_index // 3
            tri_end = tri_start + s.num_indices // 3
            for poly in mesh.polygons[tri_start:tri_end]:
                poly.material_index = slot

    if geom.normals and len(geom.normals) >= len(geom.positions):
        try:
            mesh.normals_split_custom_set_from_vertices(geom.normals)
        except Exception:  # pragma: no cover - bpy version variance
            pass

    mesh.validate(clean_customdata=False)
    return mesh


def _apply_shape_keys(
    obj_owner: "bpy.types.Object",
    geom: MeshGeometry,
) -> None:
    """Materialise ``geom.morph_targets`` as Blender shape keys on
    ``obj_owner``'s mesh.

    Phase 6. The CryEngine ``CompiledMorphTargets`` chunk stores the
    *absolute deformed position* per affected vertex, which is exactly
    what ``key.data[vertex_id].co`` accepts — Blender derives the
    delta vs. the Basis automatically. Vertices not listed in a morph
    keep their Basis position.

    Shape keys must be added through an :class:`bpy.types.Object` that
    owns the mesh; ``bpy.types.Mesh`` itself has no ``shape_key_add``.
    """
    if not geom.morph_targets:
        return
    mesh = obj_owner.data
    try:
        if mesh.shape_keys is None:
            obj_owner.shape_key_add(name="Basis", from_mix=False)
        for morph in geom.morph_targets:
            key = obj_owner.shape_key_add(name=morph.name, from_mix=False)
            kd = key.data
            n = len(kd)
            for vertex_id, pos in morph.vertices:
                if 0 <= vertex_id < n:
                    kd[vertex_id].co = pos
    except Exception:  # pragma: no cover - bpy version variance
        pass


def _resolve_material(
    cryengine: "CryEngine", node: "ChunkNode", mat_id: int
) -> "Material | None":
    """Look up the parsed `Material` for a subset of ``node``.

    Path: ``node.material_id -> ChunkMtlName.name -> stem -> library
    -> sub_materials[mat_id]``. Returns ``None`` when any link is
    missing so the caller can fall back to a placeholder.
    """
    if not cryengine.materials or node.material_id == 0:
        return None

    if not cryengine.models:
        return None
    mtl_chunk = cryengine.models[0].chunk_map.get(node.material_id)
    if mtl_chunk is None:
        return None
    name = getattr(mtl_chunk, "name", None)
    if not name:
        return None

    key = PurePosixPath(name).stem.lower() or name.lower()
    library = cryengine.materials.get(key)
    if library is None:
        return None
    subs = library.sub_materials or [library]
    if 0 <= mat_id < len(subs):
        return subs[mat_id]
    return subs[0] if subs else None


def _placeholder_material(name: str) -> "bpy.types.Material":
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
    return mat


def _row_major_to_matrix(rows: tuple) -> "Matrix":
    """Convert our row-major 4x4 (translation in last row) into a
    `mathutils.Matrix` (column-major, translation in last column)."""
    return Matrix(
        (
            (rows[0][0], rows[1][0], rows[2][0], rows[3][0]),
            (rows[0][1], rows[1][1], rows[2][1], rows[3][1]),
            (rows[0][2], rows[1][2], rows[2][2], rows[3][2]),
            (rows[0][3], rows[1][3], rows[2][3], rows[3][3]),
        )
    )


__all__ = ["build_scene"]
