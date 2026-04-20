"""Phase 10 — Blender Rigid Body bridge for CryEngine collision data.

Two sources of collision primitives feed this module:

* **Per-bone AABBs** from :class:`BonePhysicsGeometry` on every
  :class:`CompiledBone` and :class:`CompiledPhysicalBone`. Each
  non-empty AABB becomes one BOX-shaped Empty parented under the
  matching armature bone (``parent_type='BONE'``).
* **Standalone ``MeshPhysicsData_800`` cube / cylinder primitives**
  decoded from the model's chunk table. Each becomes one BOX or
  CYLINDER Empty parented under the owning mesh object.

The pure-Python ``plan_*`` functions return :class:`CollisionShape`
descriptors and are unit-tested without ``bpy``. The ``apply_*``
functions consume those plans and create the corresponding Blender
objects, attaching ``rigid_body`` Collision components when the
scene's Rigid Body World is available.

Polyhedron primitives are deliberately not handled here — the
:mod:`cryengine_importer.models.physics` reader marks them
``polyhedron_skipped=True`` and the planner ignores them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Optional

from ..models.physics import PhysicsPrimitiveType
from ..models.skinning import (
    BonePhysicsGeometry,
    CompiledBone,
    SkinningInfo,
)

if TYPE_CHECKING:  # pragma: no cover
    import bpy  # type: ignore[import-not-found]

    from ..core.chunks.mesh_physics_data import ChunkMeshPhysicsData
    from ..core.cryengine import CryEngine


# Below this half-extent (metres) we treat the AABB as degenerate and
# skip the bone — common for the "dead" LOD on rigid attach points.
_MIN_HALF_EXTENT = 1e-5


@dataclass
class CollisionShape:
    """Renderer-agnostic descriptor of one collision primitive.

    Coordinates are in the parent's local space:

    * For bone shapes the parent is the armature bone, so ``location``
      is bone-local (CryEngine's ``BonePhysicsGeometry`` AABB is
      already in bone space).
    * For mesh-physics shapes the parent is the owning mesh object,
      so ``location`` is mesh-local (matches the ``PhysicsData.center``
      field, which is in the model's local frame).

    ``dimensions`` are full extents along x / y / z (twice the
    half-extent) — Blender's ``object.dimensions`` accepts the same
    convention for an Empty with ``empty_display_size=1.0``.
    """

    name: str
    shape: str  # "BOX" | "CYLINDER"
    location: tuple[float, float, float]
    dimensions: tuple[float, float, float]
    parent_bone: Optional[str] = None
    rotation_euler: tuple[float, float, float] = (0.0, 0.0, 0.0)


# ---------------------------------------------------------- planners ------


def plan_bone_collision_shapes(
    skinning_info: SkinningInfo,
    *,
    include_dead: bool = False,
) -> list[CollisionShape]:
    """Return one BOX :class:`CollisionShape` per bone with a non-empty
    ``physics_alive`` AABB.

    ``include_dead`` additionally emits the ``physics_dead`` LOD AABB
    (suffix ``_dead``) — off by default because most pipelines only
    want the alive-pose collision proxy.

    Bones whose AABB collapses to a point (``extent`` smaller than
    ``_MIN_HALF_EXTENT`` on every axis) are skipped silently;
    CryEngine writes those as placeholders for rigid attach points
    that have no collision body of their own.
    """
    shapes: list[CollisionShape] = []
    if not skinning_info.has_skinning_info:
        return shapes
    for bone in skinning_info.compiled_bones:
        _emit_bone_shape(shapes, bone, bone.physics_alive, suffix="")
        if include_dead:
            _emit_bone_shape(shapes, bone, bone.physics_dead, suffix="_dead")

    return shapes


def _emit_bone_shape(
    out: list[CollisionShape],
    bone: CompiledBone,
    pg: Optional[BonePhysicsGeometry],
    *,
    suffix: str,
) -> None:
    if pg is None or pg.is_empty:
        return
    ex = pg.extent
    if max(abs(ex[0]), abs(ex[1]), abs(ex[2])) <= _MIN_HALF_EXTENT:
        return
    out.append(
        CollisionShape(
            name=f"{bone.bone_name}_collision{suffix}",
            shape="BOX",
            location=pg.center,
            dimensions=(abs(ex[0]) * 2.0, abs(ex[1]) * 2.0, abs(ex[2]) * 2.0),
            parent_bone=bone.bone_name,
        )
    )


def plan_mesh_physics_shapes(
    physics_chunks: Iterable["ChunkMeshPhysicsData"],
    *,
    name_prefix: str = "physics",
) -> list[CollisionShape]:
    """Return one shape per ``ChunkMeshPhysicsData_800`` whose payload
    decoded a CUBE / CYLINDER / UNKNOWN6 primitive.

    The physical dimensions on the standalone ``PhysicsCube`` /
    ``PhysicsCylinder`` records aren't documented by pyffi (most
    fields are annotated ``Unknown``), so we use a unit dimension
    centred at :attr:`PhysicsData.center` and expect the artist to
    scale to fit. The point of this branch is to give artists an
    *anchored marker* per physics primitive without losing the
    primitive type — the cube vs. cylinder display-type is preserved
    so the user sees what CryEngine intended.
    """
    shapes: list[CollisionShape] = []
    for i, chunk in enumerate(physics_chunks):
        pd = getattr(chunk, "physics_data", None)
        if pd is None:
            continue
        primitive = pd.primitive
        if primitive == PhysicsPrimitiveType.CUBE:
            shape = "BOX"
        elif primitive in (
            PhysicsPrimitiveType.CYLINDER,
            PhysicsPrimitiveType.UNKNOWN6,
        ):
            shape = "CYLINDER"
        else:
            continue
        shapes.append(
            CollisionShape(
                name=f"{name_prefix}_{i}_{shape.lower()}",
                shape=shape,
                location=pd.center,
                dimensions=(1.0, 1.0, 1.0),
                parent_bone=None,
            )
        )
    return shapes


# ---------------------------------------------------------- bpy bridge ----


# Display sizes match Blender Empty conventions: each axis is scaled
# to the requested full extent via ``empty_display_size`` * scale.
_SHAPE_TO_EMPTY_DISPLAY = {
    "BOX": "CUBE",
    "CYLINDER": "SINGLE_ARROW",  # CYLINDER isn't an Empty type;
                                  # we fall back to a mesh below.
}


def apply_collision_shapes(
    shapes: list[CollisionShape],
    *,
    armature_obj: "bpy.types.Object | None" = None,
    parent_obj: "bpy.types.Object | None" = None,
    collection: "bpy.types.Collection | None" = None,
    add_rigid_body: bool = True,
) -> "list[bpy.types.Object]":
    """Materialise ``shapes`` as Blender objects.

    BOX shapes become Empties (``empty_display_type='CUBE'``) — they
    accept ``rigid_body`` Collision components and stay lightweight.
    CYLINDER shapes become a small Mesh cylinder (Blender Empties
    have no cylinder display type), still parented under the requested
    bone or object.

    ``add_rigid_body`` adds a passive Rigid Body Collision component
    to each new object, but only when ``bpy.context.scene`` already
    has a Rigid Body World — adding one from inside an importer is
    intrusive, so we leave that to the user.
    """
    import bpy  # type: ignore[import-not-found]
    from mathutils import Vector  # type: ignore[import-not-found]

    if not shapes:
        return []
    if collection is None:
        collection = bpy.context.scene.collection

    has_rb_world = bool(getattr(bpy.context.scene, "rigidbody_world", None))
    created: list[bpy.types.Object] = []

    for shape in shapes:
        obj = _make_collision_object(shape)
        collection.objects.link(obj)
        created.append(obj)

        if shape.parent_bone and armature_obj is not None and (
            shape.parent_bone in armature_obj.data.bones
        ):
            obj.parent = armature_obj
            obj.parent_type = "BONE"
            obj.parent_bone = shape.parent_bone
        elif parent_obj is not None:
            obj.parent = parent_obj
            obj.parent_type = "OBJECT"

        obj.location = Vector(shape.location)
        obj.rotation_euler = Vector(shape.rotation_euler)

        if add_rigid_body and has_rb_world:
            try:
                bpy.context.view_layer.objects.active = obj
                bpy.ops.rigidbody.object_add(type="PASSIVE")
                obj.rigid_body.collision_shape = shape.shape
                obj.rigid_body.kinematic = True
            except Exception:  # pragma: no cover - bpy version variance
                pass

    return created


def _make_collision_object(shape: CollisionShape) -> "bpy.types.Object":
    """Create the bpy object that visually represents ``shape``.

    BOX -> Empty (CUBE display); CYLINDER -> low-poly cylinder mesh
    (Empties have no cylinder display type).
    """
    import bpy  # type: ignore[import-not-found]

    if shape.shape == "BOX":
        empty = bpy.data.objects.new(shape.name, None)
        empty.empty_display_type = "CUBE"
        empty.empty_display_size = 1.0
        # ``dimensions`` on an Empty isn't directly settable; scale axes
        # so that the cube display fills the requested AABB. The cube
        # display goes from -1 to +1 along each axis, hence half-extent.
        empty.scale = tuple(d * 0.5 for d in shape.dimensions)
        return empty

    # CYLINDER fallback: small placeholder mesh. We avoid bmesh here
    # because the geometry is just a marker and a primitive cylinder
    # operator pollutes the active selection state.
    mesh = bpy.data.meshes.new(shape.name + "_mesh")
    verts: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    faces: list[list[int]] = []
    import math

    segments = 8
    rx, ry, hz = (
        max(shape.dimensions[0] * 0.5, 1e-5),
        max(shape.dimensions[1] * 0.5, 1e-5),
        max(shape.dimensions[2] * 0.5, 1e-5),
    )
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        cx, sy = math.cos(theta), math.sin(theta)
        verts.append((cx * rx, sy * ry, -hz))
        verts.append((cx * rx, sy * ry, +hz))
    for i in range(segments):
        a = 2 * i
        b = 2 * ((i + 1) % segments)
        faces.append([a, b, b + 1, a + 1])
    faces.append([2 * i for i in range(segments)])
    faces.append([2 * i + 1 for i in range(segments - 1, -1, -1)])
    mesh.from_pydata(verts, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(shape.name, mesh)
    obj.display_type = "WIRE"
    return obj


# ---------------------------------------------------------- entry point ---


def build_rigid_bodies(
    cryengine: "CryEngine",
    *,
    armature_obj: "bpy.types.Object | None" = None,
    node_to_obj: "dict[int, bpy.types.Object] | None" = None,
    collection: "bpy.types.Collection | None" = None,
    include_dead: bool = False,
    add_rigid_body: bool = True,
) -> "list[bpy.types.Object]":
    """One-shot helper called from :mod:`scene_builder`.

    Plans bone + mesh-physics shapes from ``cryengine`` and applies
    them. Safe to call when there's no skinning info or no physics
    chunks — returns an empty list in that case.
    """
    created: list = []

    if armature_obj is not None:
        bone_shapes = plan_bone_collision_shapes(
            cryengine.skinning_info, include_dead=include_dead
        )
        created.extend(
            apply_collision_shapes(
                bone_shapes,
                armature_obj=armature_obj,
                collection=collection,
                add_rigid_body=add_rigid_body,
            )
        )

    if node_to_obj:
        for model in cryengine.models:
            phys_chunks = [
                c
                for c in model.chunk_map.values()
                if type(c).__name__.startswith("ChunkMeshPhysicsData")
            ]
            if not phys_chunks:
                continue
            mesh_shapes = plan_mesh_physics_shapes(phys_chunks)
            # Parent under the first mesh object we have for this model
            # — CryEngine doesn't link MeshPhysicsData chunks back to a
            # specific node, so first-mesh is the best we can do here.
            parent = next(
                (o for o in node_to_obj.values() if getattr(o, "type", None) == "MESH"),
                None,
            )
            created.extend(
                apply_collision_shapes(
                    mesh_shapes,
                    parent_obj=parent,
                    collection=collection,
                    add_rigid_body=add_rigid_body,
                )
            )

    return created
