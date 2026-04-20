"""Phase 10 — Blender Rigid Body bridge planner tests.

Only covers the pure-Python ``plan_*`` functions; the bpy-side
``apply_*`` / ``build_rigid_bodies`` paths require Blender's ``bpy``
runtime and are exercised via ``tests/headless_smoke.py``.
"""

from __future__ import annotations

from cryengine_importer.blender.rigid_body_builder import (
    CollisionShape,
    plan_bone_collision_shapes,
    plan_mesh_physics_shapes,
)
from cryengine_importer.models.physics import (
    PhysicsCube,
    PhysicsCylinder,
    PhysicsData,
    PhysicsPrimitiveType,
)
from cryengine_importer.models.skinning import (
    BonePhysicsGeometry,
    CompiledBone,
    SkinningInfo,
)


def _bone(name: str, alive=None, dead=None) -> CompiledBone:
    b = CompiledBone()
    b.bone_name = name
    b.physics_alive = alive
    b.physics_dead = dead
    return b


def _aabb(
    min_=(-1.0, -2.0, -3.0),
    max_=(1.0, 2.0, 3.0),
    physics_geom=42,
) -> BonePhysicsGeometry:
    pg = BonePhysicsGeometry()
    pg.physics_geom = physics_geom
    pg.min = min_
    pg.max = max_
    return pg


# ----------------------------------------------- bone planner -------------


def test_plan_bone_collision_shapes_empty_skinning() -> None:
    info = SkinningInfo()
    assert plan_bone_collision_shapes(info) == []


def test_plan_bone_collision_shapes_skips_when_no_physics() -> None:
    info = SkinningInfo()
    info.compiled_bones = [_bone("Bip01"), _bone("Bip01_Spine")]
    assert plan_bone_collision_shapes(info) == []


def test_plan_bone_collision_shapes_skips_empty_aabb() -> None:
    info = SkinningInfo()
    info.compiled_bones = [_bone("Bip01", alive=BonePhysicsGeometry())]
    assert plan_bone_collision_shapes(info) == []


def test_plan_bone_collision_shapes_skips_degenerate_extent() -> None:
    info = SkinningInfo()
    info.compiled_bones = [
        _bone("Bip01", alive=_aabb(min_=(0.0, 0.0, 0.0), max_=(0.0, 0.0, 0.0)))
    ]
    # AABB is collapsed to a point — physics_geom != 0 keeps is_empty=False
    # but extent is below the tolerance, so the planner skips.
    assert plan_bone_collision_shapes(info) == []


def test_plan_bone_collision_shapes_emits_box_per_alive_bone() -> None:
    info = SkinningInfo()
    info.compiled_bones = [
        _bone("Bip01", alive=_aabb()),
        _bone(
            "Bip01_Head",
            alive=_aabb(min_=(-0.1, -0.1, -0.1), max_=(0.1, 0.1, 0.1)),
        ),
    ]
    shapes = plan_bone_collision_shapes(info)
    assert len(shapes) == 2
    assert all(s.shape == "BOX" for s in shapes)
    assert shapes[0] == CollisionShape(
        name="Bip01_collision",
        shape="BOX",
        location=(0.0, 0.0, 0.0),
        dimensions=(2.0, 4.0, 6.0),
        parent_bone="Bip01",
    )
    assert shapes[1].name == "Bip01_Head_collision"
    assert shapes[1].parent_bone == "Bip01_Head"


def test_plan_bone_collision_shapes_include_dead_emits_extra() -> None:
    info = SkinningInfo()
    info.compiled_bones = [_bone("Bip01", alive=_aabb(), dead=_aabb())]
    alive_only = plan_bone_collision_shapes(info, include_dead=False)
    both = plan_bone_collision_shapes(info, include_dead=True)
    assert len(alive_only) == 1
    assert len(both) == 2
    assert {s.name for s in both} == {"Bip01_collision", "Bip01_collision_dead"}


def test_plan_bone_collision_shapes_uses_offset_aabb_center() -> None:
    info = SkinningInfo()
    pg = _aabb(min_=(0.0, 0.0, 0.0), max_=(2.0, 4.0, 6.0))  # not centred on 0
    info.compiled_bones = [_bone("Bip01", alive=pg)]
    [shape] = plan_bone_collision_shapes(info)
    assert shape.location == (1.0, 2.0, 3.0)
    assert shape.dimensions == (2.0, 4.0, 6.0)


# ----------------------------------------------- mesh-physics planner -----


class _StubChunk:
    def __init__(self, physics_data: PhysicsData | None) -> None:
        self.physics_data = physics_data


def _pd(primitive_type: int, *, cube=None, cylinder=None) -> PhysicsData:
    pd = PhysicsData()
    pd.primitive_type = primitive_type
    pd.center = (10.0, 20.0, 30.0)
    pd.cube = cube
    pd.cylinder = cylinder
    return pd


def test_plan_mesh_physics_shapes_no_payload_emits_nothing() -> None:
    chunks = [_StubChunk(None)]
    assert plan_mesh_physics_shapes(chunks) == []


def test_plan_mesh_physics_shapes_polyhedron_skipped() -> None:
    chunks = [_StubChunk(_pd(PhysicsPrimitiveType.POLYHEDRON))]
    assert plan_mesh_physics_shapes(chunks) == []


def test_plan_mesh_physics_shapes_cube_emits_box() -> None:
    chunks = [_StubChunk(_pd(PhysicsPrimitiveType.CUBE, cube=PhysicsCube()))]
    shapes = plan_mesh_physics_shapes(chunks)
    assert len(shapes) == 1
    assert shapes[0].shape == "BOX"
    assert shapes[0].location == (10.0, 20.0, 30.0)
    assert shapes[0].dimensions == (1.0, 1.0, 1.0)
    assert shapes[0].parent_bone is None
    assert shapes[0].name == "physics_0_box"


def test_plan_mesh_physics_shapes_cylinder_emits_cylinder() -> None:
    chunks = [
        _StubChunk(_pd(PhysicsPrimitiveType.CYLINDER, cylinder=PhysicsCylinder())),
        _StubChunk(_pd(PhysicsPrimitiveType.UNKNOWN6, cylinder=PhysicsCylinder())),
    ]
    shapes = plan_mesh_physics_shapes(chunks)
    assert [s.shape for s in shapes] == ["CYLINDER", "CYLINDER"]
    assert [s.name for s in shapes] == ["physics_0_cylinder", "physics_1_cylinder"]


def test_plan_mesh_physics_shapes_custom_prefix() -> None:
    chunks = [_StubChunk(_pd(PhysicsPrimitiveType.CUBE, cube=PhysicsCube()))]
    [shape] = plan_mesh_physics_shapes(chunks, name_prefix="hitbox")
    assert shape.name == "hitbox_0_box"


def test_plan_mesh_physics_shapes_unknown_primitive_skipped() -> None:
    # Raw primitive_type that isn't one of the known IntEnum values.
    chunks = [_StubChunk(_pd(99))]
    assert plan_mesh_physics_shapes(chunks) == []
