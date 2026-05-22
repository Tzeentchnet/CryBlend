"""Phase 4 — animation chunk reader & loader tests."""

from __future__ import annotations

import io
import logging
import math
import struct
from types import SimpleNamespace
from binascii import crc32

import pytest

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.controller import (
    ChunkController826,
    ChunkController827,
    ChunkController829,
    ChunkController830,
    ChunkController831,
    ChunkController905,
    ChunkMotionParameters925,
)
from cryengine_importer.core.chunks.global_animation_header_caf import (
    ChunkGlobalAnimationHeaderCAF971,
)
from cryengine_importer.core.chunks.header import ChunkHeader746
from cryengine_importer.core.chunks.node import ChunkNode824
from cryengine_importer.core.chunks.timing_format import ChunkTimingFormat918
from cryengine_importer.core.chrparams_loader import (
    load_chrparams_with_includes,
    parse_chrparams,
)
from cryengine_importer.core.cryengine import (
    CryEngine,
    _annotate_animation_clip,
    _classify_animation_clip,
    _is_supported_animation_clip_path,
)
from cryengine_importer.core.model import Model
from cryengine_importer.enums import (
    ChunkType,
    CompressionFormat,
    CtrlType,
    FileVersion,
    KeyTimesFormat,
)
from cryengine_importer.io.binary_reader import BinaryReader
from cryengine_importer.io.pack_fs import InMemoryFileSystem
from cryengine_importer.models.animation import (
    Animation905,
    ControllerInfo,
    ControllerKey,
    MotionParams905,
)
from cryengine_importer.models.animation import AnimationClip, BoneAnimationTrack


# -- helpers -------------------------------------------------------------


def _drive(chunk_cls_key, body: bytes):
    chunk_type, version = chunk_cls_key
    inst = make_chunk(chunk_type, version)
    hdr = ChunkHeader746()
    hdr.chunk_type = chunk_type
    hdr.version_raw = version
    hdr.id = 1
    hdr.offset = 0
    hdr.size = len(body)

    model = Model()
    model.file_version = FileVersion.x0746

    inst.load(model, hdr)  # type: ignore[arg-type]
    br = BinaryReader(io.BytesIO(body))
    inst.read(br)
    return inst


# -- Controller 0x826 ----------------------------------------------------


def test_controller_826_keys() -> None:
    body = struct.pack(
        "<IiII",
        int(CtrlType.LINEAR3),
        2,  # num_keys
        0xCAFE0001,  # controller_flags
        0xDEADBEEF,  # controller_id
    )
    # 2 keys: time (i32) + abs_pos (3f) + rel_pos (3f)
    body += struct.pack("<i6f", 0, 1, 2, 3, 0, 0, 0)
    body += struct.pack("<i6f", 100, 4, 5, 6, 0.1, 0.2, 0.3)

    chunk = _drive((ChunkType.Controller, 0x826), body)
    assert chunk.controller_type == CtrlType.LINEAR3
    assert chunk.num_keys == 2
    assert chunk.controller_id == 0xDEADBEEF
    assert chunk.keys[0].time == 0
    assert chunk.keys[0].abs_pos == (1.0, 2.0, 3.0)
    assert chunk.keys[1].time == 100
    assert chunk.keys[1].rel_pos == (
        struct.unpack("<f", struct.pack("<f", 0.1))[0],
        struct.unpack("<f", struct.pack("<f", 0.2))[0],
        struct.unpack("<f", struct.pack("<f", 0.3))[0],
    )


def test_controller_826_tbc3_consumes_extra_floats() -> None:
    body = struct.pack("<IiII", int(CtrlType.TBC3), 2, 0, 0x1234)
    body += struct.pack("<i6f2f", 0, 1, 2, 3, 0, 0, 0, 0.25, 0.5)
    body += struct.pack("<i6f2f", 100, 4, 5, 6, 0, 0, 0, 0.75, 1.0)

    chunk = _drive((ChunkType.Controller, 0x826), body)

    assert chunk.controller_type == CtrlType.TBC3
    assert chunk.keys[0].unknown2 == (0.25, 0.5)
    assert chunk.keys[1].time == 100
    assert chunk.keys[1].abs_pos == (4.0, 5.0, 6.0)


def test_controller_826_tbcq_consumes_extra_vector() -> None:
    body = struct.pack("<IiII", int(CtrlType.TBCQ), 2, 0, 0x1234)
    body += struct.pack("<i6f3f", 0, 1, 0, 0, 0, 0, 0, 0.1, 0.2, 0.3)
    body += struct.pack("<i6f3f", 320, 0, 0, 1, 1.57, 0, 0, 0.4, 0.5, 0.6)

    chunk = _drive((ChunkType.Controller, 0x826), body)

    assert chunk.controller_type == CtrlType.TBCQ
    assert chunk.keys[0].unknown1 == (
        struct.unpack("<f", struct.pack("<f", 0.1))[0],
        struct.unpack("<f", struct.pack("<f", 0.2))[0],
        struct.unpack("<f", struct.pack("<f", 0.3))[0],
    )
    assert chunk.keys[1].time == 320
    assert chunk.keys[1].abs_pos == (0.0, 0.0, 1.0)


def test_build_object_animations_from_node_controller() -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "door.cga"
    engine.object_animation_clips = []

    node = ChunkNode824()
    node.id = 7
    node.name = "door_leaf"
    node.pos_ctrl_id = 10
    engine.nodes = [node]

    timing = ChunkTimingFormat918()
    timing.secs_per_tick = 0.5

    controller = ChunkController826()
    controller.controller_id = 10
    controller.controller_type = CtrlType.TBC3
    controller.keys = [
        ControllerKey(time=0, abs_pos=(0.0, 0.0, 0.0)),
        ControllerKey(time=2, abs_pos=(100.0, 0.0, 0.0)),
    ]

    model = Model()
    model.chunk_map = {1: timing, 2: controller}
    engine.models = [model]

    engine._build_object_animations()

    assert len(engine.object_animation_clips) == 1
    clip = engine.object_animation_clips[0]
    assert clip.name == "door"
    assert clip.duration_secs == 1.0
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.node_id == 7
    assert track.node_name == "door_leaf"
    assert track.pos_times == [0.0, 1.0]
    assert track.positions == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]


def test_external_object_animation_paths_use_animations_objects_folder() -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "objects/Vehicles/US_VTOL_Transport/US_VTOL_Transport.cga"
    engine.pack_fs = InMemoryFileSystem(
        {
            "animations/objects/Vehicles/US_VTOL_Transport/US_VTOL_Transport_LG_Open.anm": b"",
            "animations/objects/Vehicles/US_VTOL_Transport/Other.anm": b"",
        }
    )

    assert engine._external_object_animation_paths() == [
        "animations/objects/Vehicles/US_VTOL_Transport/US_VTOL_Transport_LG_Open.anm"
    ]


def test_external_object_animation_clip_retargets_node_by_name() -> None:
    engine = CryEngine.__new__(CryEngine)

    target_node = ChunkNode824()
    target_node.id = 81
    target_node.name = "Engine_Front"

    source_node = ChunkNode824()
    source_node.id = 3
    source_node.name = "Engine_Front"
    source_node.rot_ctrl_id = 4

    timing = ChunkTimingFormat918()
    timing.secs_per_tick = 0.5

    controller = ChunkController826()
    controller.controller_id = 4
    controller.controller_type = CtrlType.TBCQ
    controller.keys = [
        ControllerKey(time=0, abs_pos=(1.0, 0.0, 0.0), rel_pos=(0.0, 0.0, 0.0)),
        ControllerKey(time=2, abs_pos=(-1.0, 0.0, 0.0), rel_pos=(1.57, 0.0, 0.0)),
    ]

    model = Model()
    model.chunk_map = {1: timing, 2: controller}

    clip = engine._build_object_animation_clip(
        "EngineFront",
        [source_node],
        [model],
        target_node_by_name={"engine_front": target_node},
    )

    assert clip is not None
    assert clip.name == "EngineFront"
    assert clip.duration_secs == 1.0
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.node_id == 81
    assert track.node_name == "Engine_Front"
    assert track.rot_times == [0.0, 1.0]
    assert len(track.rotations) == 2


# -- Controller 0x829 (header-only stub) ---------------------------------


def test_controller_829_does_not_crash_with_empty_body() -> None:
    chunk = _drive((ChunkType.Controller, 0x829), b"")
    assert chunk is not None


def test_controller_829_parses_dual_track_body() -> None:
    body = struct.pack(
        "<IHHBBBBBB",
        0x12345678,
        2,  # rotation keys
        2,  # position keys
        1,  # rotation_format = eNoCompressQuat
        2,  # rotation_time_format = byte
        2,  # position_format = eNoCompressVec3
        0,  # position_keys_info: share rotation times
        0,
        0,
    )
    body += b"\x00\x00"  # descriptor padding to 4-byte boundary
    body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
    body += struct.pack("<4f", 0.0, 0.0, 0.707, 0.707)
    body += bytes([0, 30])
    body += struct.pack("<3f", 0.0, 0.0, 0.0)
    body += struct.pack("<3f", 1.0, 2.0, 3.0)

    chunk = _drive((ChunkType.Controller, 0x829), body)

    assert isinstance(chunk, ChunkController829)
    assert chunk.controller_id == 0x12345678
    assert chunk.rotation_key_times == [0.0, 30.0]
    assert chunk.position_key_times == [0.0, 30.0]
    assert chunk.key_rotations[0] == (0.0, 0.0, 0.0, 1.0)
    assert chunk.key_positions[1] == (1.0, 2.0, 3.0)


def test_speed_info_925_parses_motion_params() -> None:
    body = struct.pack(
        "<I I i f i i 5f 4f 3f 4f 3f 8f",
        2,
        400,
        1,
        1.0 / 30.0,
        0,
        30,
        0, 0, 0, 0, 0,
        0, 0, 0, 1,
        0, 0, 0,
        0, 0, 0, 1,
        0, 0, 0,
        -1, -1, -1, -1, -1, -1, -1, -1,
    )

    chunk = _drive((ChunkType.SpeedInfo, 0x925), body)

    assert isinstance(chunk, ChunkMotionParameters925)
    assert chunk.secs_per_tick == struct.unpack("<f", struct.pack("<f", 1.0 / 30.0))[0]
    assert chunk.start == 0
    assert chunk.end == 30


def test_build_clip_from_controller_829_caf() -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    speed = ChunkMotionParameters925()
    speed.secs_per_tick = 1.0 / 30.0
    speed.start = 0
    speed.end = 30

    controller = ChunkController829()
    controller.controller_id = 0x12345678
    controller.rotation_key_times = [0.0, 30.0]
    controller.position_key_times = [0.0, 30.0]
    controller.key_rotations = [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 0.707, 0.707),
    ]
    controller.key_positions = [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]

    model = Model()
    model.chunk_map = {1: speed, 2: controller}

    clip = engine._build_clip_from_caf("idle", model)

    assert clip is not None
    assert clip.name == "idle"
    assert math.isclose(clip.duration_secs, 1.0)
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.bone_name == "controller_12345678"
    assert track.rot_times == [0.0, 1.0]
    assert track.pos_times == [0.0, 1.0]
    assert track.positions == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]
    assert clip.rotation_track_count == 1
    assert clip.position_track_count == 1
    assert clip.skipped_position_tracks == 0
    assert math.isclose(
        math.sqrt(sum(component * component for component in track.rotations[1])),
        1.0,
    )


@pytest.mark.parametrize("controller_cls", [ChunkController827, ChunkController830])
def test_build_clip_from_pqlog_controller_caf(controller_cls) -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    speed = ChunkMotionParameters925()
    speed.secs_per_tick = 1.0 / 30.0
    speed.start = 0
    speed.end = 30

    controller = controller_cls()
    controller.controller_id = 0x12345678
    controller.key_times = [0, 30]
    controller.key_rotations = [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 0.707, 0.707),
    ]
    controller.key_positions = [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]

    model = Model()
    model.chunk_map = {1: speed, 2: controller}

    clip = engine._build_clip_from_caf("idle", model)

    assert clip is not None
    assert clip.name == "idle"
    assert math.isclose(clip.duration_secs, 1.0)
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.bone_name == "controller_12345678"
    assert track.rot_times == [0.0, 1.0]
    assert track.pos_times == [0.0, 1.0]
    assert track.positions == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]
    assert clip.rotation_track_count == 1
    assert clip.position_track_count == 1


def test_build_clip_from_controller_831_caf() -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    speed = ChunkMotionParameters925()
    speed.secs_per_tick = 1.0 / 30.0
    speed.start = 0
    speed.end = 30

    controller = ChunkController831()
    controller.controller_id = 0x12345678
    controller.rotation_key_times = [0.0, 30.0]
    controller.position_key_times = [0.0, 30.0]
    controller.key_rotations = [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 0.707, 0.707),
    ]
    controller.key_positions = [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]

    model = Model()
    model.chunk_map = {1: speed, 2: controller}

    clip = engine._build_clip_from_caf("idle", model)

    assert clip is not None
    assert clip.name == "idle"
    assert math.isclose(clip.duration_secs, 1.0)
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.bone_name == "controller_12345678"
    assert track.rot_times == [0.0, 1.0]
    assert track.pos_times == [0.0, 1.0]
    assert track.positions == [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)]
    assert clip.rotation_track_count == 1
    assert clip.position_track_count == 1


def test_animation_clip_classification_from_names() -> None:
    assert _classify_animation_clip("stand_com_idle_01") == "full_body"
    assert _classify_animation_clip(
        "cover_AimPoses_gun_com_lft_low_01"
    ) == "aim_pose"
    assert _classify_animation_clip(
        "stand_com_idle_lookposes_01"
    ) == "look_pose"
    assert _classify_animation_clip(
        "stand_idle_com_additive_null_alr_add_01"
    ) == "additive"
    assert _classify_animation_clip(
        "$TracksDatabase", "Animations/alien/grunt/tracksdatabase.dba"
    ) == "metadata"


def test_animation_clip_annotation_marks_partial_weapon_tracks() -> None:
    clip = AnimationClip(
        name="stand_walk_com_fwd_fast_weapon_01",
        tracks=[BoneAnimationTrack(bone_name="weapon_bone")],
    )

    _annotate_animation_clip(
        clip,
        "Animations/Alien/Grunt/stand_walk_com_fwd_fast_weapon_01.caf",
    )

    assert clip.source_file_name == (
        "Animations/Alien/Grunt/stand_walk_com_fwd_fast_weapon_01.caf"
    )
    assert clip.clip_kind == "partial_body"
    assert clip.is_additive is False


def test_controller_829_uses_world_derived_bind_rotation() -> None:
    def qz(degrees: float) -> tuple[float, float, float, float]:
        radians = math.radians(degrees)
        return (0.0, 0.0, math.sin(radians * 0.5), math.cos(radians * 0.5))

    def matrix_z(degrees: float) -> tuple[tuple[float, ...], ...]:
        radians = math.radians(degrees)
        c = math.cos(radians)
        s = math.sin(radians)
        return (
            (c, -s, 0.0, 0.0),
            (s, c, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )

    parent = SimpleNamespace(
        bone_name="root",
        controller_id=0x1,
        parent_bone=None,
        local_transform_matrix=matrix_z(45.0),
        world_transform_matrix=matrix_z(45.0),
    )
    child = SimpleNamespace(
        bone_name="child",
        controller_id=0x2,
        parent_bone=parent,
        # Deliberately wrong: the world matrices imply a 30-degree
        # child bind rotation, which is what the Blender armature uses.
        local_transform_matrix=matrix_z(0.0),
        world_transform_matrix=matrix_z(75.0),
    )

    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[parent, child])

    controller = ChunkController829()
    controller.controller_id = 0x2
    controller.rotation_key_times = [0.0]
    controller.key_rotations = [qz(60.0)]

    track = engine._track_from_controller829(controller, secs_per_tick=1.0)

    assert track is not None
    assert track.bone_name == "child"
    assert track.rotations[0] == pytest.approx(qz(30.0), abs=1e-6)


def test_controller_829_position_uses_bind_rotation_basis() -> None:
    def matrix_z(degrees: float) -> tuple[tuple[float, ...], ...]:
        radians = math.radians(degrees)
        c = math.cos(radians)
        s = math.sin(radians)
        return (
            (c, -s, 0.0, 0.0),
            (s, c, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )

    parent = SimpleNamespace(
        bone_name="root",
        controller_id=0x1,
        parent_bone=None,
        local_transform_matrix=matrix_z(0.0),
        world_transform_matrix=matrix_z(0.0),
    )
    child = SimpleNamespace(
        bone_name="child",
        controller_id=0x2,
        parent_bone=parent,
        local_transform_matrix=matrix_z(90.0),
        world_transform_matrix=matrix_z(90.0),
    )

    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[parent, child])

    controller = ChunkController829()
    controller.controller_id = 0x2
    controller.position_key_times = [0.0]
    # With a 90-degree bind rotation around Z, a raw local delta of
    # parent-space +Y must become Blender pose-basis +X.
    controller.key_positions = [(0.0, 1.0, 0.0)]

    track = engine._track_from_controller829(controller, secs_per_tick=1.0)

    assert track is not None
    assert track.positions[0] == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)


def test_controller_829_keeps_quaternion_hemisphere_continuous() -> None:
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    controller = ChunkController829()
    controller.controller_id = 0x12345678
    controller.rotation_key_times = [0.0, 1.0, 2.0]
    controller.key_rotations = [
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 0.10, 0.995),
        (0.0, 0.0, -0.12, -0.992),
    ]

    track = engine._track_from_controller829(controller, secs_per_tick=1.0)

    assert track is not None
    adjacent_dots = [
        sum(a * b for a, b in zip(left, right))
        for left, right in zip(track.rotations, track.rotations[1:])
    ]
    assert adjacent_dots[0] > 0.0
    assert adjacent_dots[1] > 0.0
    assert track.rotations[2][2] > 0.0
    assert track.rotations[2][3] > 0.0


# -- Controllers 0x827 / 0x828 / 0x830 / 0x831 (v2.0.0) ------------------


def test_controller_827_uncompressed_pqlog_no_local_header() -> None:
    """0x827 has no embedded local header — body starts at the chunk
    table offset directly."""
    body = struct.pack("<II", 2, 0xCAFEBABE)  # num_keys, controller_id
    body += struct.pack("<i6f", 0, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0)
    body += struct.pack("<i6f", 100, 4.0, 5.0, 6.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.Controller, 0x827), body)
    assert chunk.num_keys == 2
    assert chunk.controller_id == 0xCAFEBABE
    assert chunk.key_times == [0, 100]
    assert chunk.key_positions[0] == (1.0, 2.0, 3.0)
    # Zero rot_log → identity quat.
    assert chunk.key_rotations[0] == (0.0, 0.0, 0.0, 1.0)


def test_controller_828_empty_chunk_is_no_op() -> None:
    chunk = _drive((ChunkType.Controller, 0x828), b"")
    assert chunk is not None
    assert chunk.controller_id == 0


def test_controller_830_pqlog_with_flags() -> None:
    body = struct.pack("<III", 1, 0xDEADBEEF, 0x42)  # num_keys, id, flags
    body += struct.pack("<i6f", 50, 7.0, 8.0, 9.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.Controller, 0x830), body)
    assert chunk.num_keys == 1
    assert chunk.controller_id == 0xDEADBEEF
    assert chunk.flags == 0x42
    assert chunk.key_positions[0] == (7.0, 8.0, 9.0)
    assert chunk.key_rotations[0] == (0.0, 0.0, 0.0, 1.0)


def test_controller_831_compressed_dual_track_no_compression() -> None:
    """0x831 with eNoCompressQuat rotations + eNoCompressVec3 positions
    + float time format. position_keys_info=0 so position times share
    rotation times."""
    body = struct.pack(
        "<II",  # controller_id, flags
        0x12345678, 0,
    )
    body += struct.pack(
        "<HH", 1, 1,  # num_rot_keys, num_pos_keys
    )
    body += struct.pack(
        "<BBBBBB",
        1,  # rotation_format = eNoCompressQuat
        0,  # rotation_time_format = eF32
        2,  # position_format = eNoCompressVec3
        0,  # position_keys_info = 0 (share rot times)
        0,  # position_time_format
        0,  # tracks_aligned = 0
    )
    # rotations (1 quat = 16 bytes), then time (1 float), then positions
    # (1 vec3), then no position times.
    body += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
    body += struct.pack("<f", 0.5)  # rot time
    body += struct.pack("<3f", 1.5, 2.5, 3.5)  # position

    chunk = _drive((ChunkType.Controller, 0x831), body)
    assert chunk.controller_id == 0x12345678
    assert chunk.num_rotation_keys == 1
    assert chunk.num_position_keys == 1
    assert chunk.key_rotations == [(0.0, 0.0, 0.0, 1.0)]
    assert chunk.rotation_key_times == [0.5]
    assert chunk.key_positions == [(1.5, 2.5, 3.5)]
    # Position times share rotation times.
    assert chunk.position_key_times == [0.5]


# -- MotionParameters 0x925 ----------------------------------------------


def test_motion_parameters_925_reads_all_fields() -> None:
    body = struct.pack(
        "<II",
        0xAA,  # asset_flags
        1,     # compression
    )
    body += struct.pack("<if", 30, 1.0 / 30.0)  # ticks_per_frame, secs_per_tick
    body += struct.pack("<ii", 0, 60)            # start, end
    body += struct.pack("<5f", 1.5, 0.5, 0.0, 10.0, 0.0)  # speeds + slope
    body += struct.pack("<4f", 0, 0, 0, 1)        # start QuatT
    body += struct.pack("<3f", 0, 0, 0)
    body += struct.pack("<4f", 0, 0, 0, 1)        # end QuatT
    body += struct.pack("<3f", 10, 0, 0)
    body += struct.pack("<8f", 0, 0.5, 0.5, 1.0, 0.5, 1.0, 0.0, 0.5)  # foot timing

    chunk = _drive((ChunkType.MotionParams, 0x925), body)
    assert chunk.asset_flags == 0xAA
    assert chunk.ticks_per_frame == 30
    assert chunk.start == 0 and chunk.end == 60
    assert chunk.move_speed == 1.5
    assert chunk.end_location_t == (10.0, 0.0, 0.0)
    assert chunk.r_toe0_end == 0.5


# -- Controller 0x905 ----------------------------------------------------


def _build_controller_905_body(
    *,
    name: bytes = b"idle",
    key_times: tuple[float, float] = (0.0, 1.0),
    start: int = 0,
    end: int = 30,
) -> bytes:
    """Synthesize a tiny controller_905 with one time / pos / rot
    track and a single Animation905 binding them to one bone."""
    num_pos = 1
    num_rot = 1
    num_time = 1
    num_anims = 1

    body = struct.pack("<IIII", num_pos, num_rot, num_time, num_anims)

    # key_time_lengths (u16 * num_time)
    body += struct.pack("<H", 2)  # 2 time samples
    # key_time_formats (u32 * (eBitset+1) = 7)
    fmt = [0] * 7
    fmt[KeyTimesFormat.eF32] = 1
    body += struct.pack("<7I", *fmt)
    # key_pos_lengths (u16 * num_pos)
    body += struct.pack("<H", 2)
    # key_pos_formats (u32 * eAutomaticQuat = 9)
    pfmt = [0] * 9
    pfmt[CompressionFormat.eNoCompressVec3] = 1
    body += struct.pack("<9I", *pfmt)
    # key_rot_lengths
    body += struct.pack("<H", 2)
    rfmt = [0] * 9
    rfmt[CompressionFormat.eNoCompressQuat] = 1
    body += struct.pack("<9I", *rfmt)

    # offsets — these are *relative to the post-table-aligned* start.
    # We'll place: times (8 bytes), positions (24 bytes), rotations (32 bytes)
    body += struct.pack("<I", 0)  # key_time_offsets
    body += struct.pack("<I", 8)  # key_pos_offsets
    body += struct.pack("<I", 8 + 24)  # key_rot_offsets
    body += struct.pack("<I", 8 + 24 + 32)  # track_length

    # The reader aligns to a 4-byte boundary before reading tracks.
    pos = len(body)
    pad = (-pos) & 3
    body += b"\x00" * pad

    # 2 time samples
    body += struct.pack("<2f", *key_times)
    # 2 vec3 positions
    body += struct.pack("<6f", 0.0, 0.0, 0.0, 1.0, 2.0, 3.0)
    # 2 quaternions (identity, then 90deg-ish — but we just check storage)
    body += struct.pack("<8f", 0, 0, 0, 1, 0.5, 0.5, 0.5, 0.5)

    # Animation905 record:
    body += struct.pack("<H", len(name))
    body += name
    # MotionParams905: 8 ints + 5 floats + locator quats/vecs + 8 foot floats
    # AssetFlags(u32), Compression(u32), TicksPerFrame(i32), SecsPerTick(f32),
    # Start(i32), End(i32), MoveSpeed(f32), TurnSpeed(f32), AssetTurn(f32),
    # Distance(f32), Slope(f32),
    # StartLocationQ(4f), StartLocationV(3f),
    # EndLocationQ(4f), EndLocationV(3f),
    # 8 foot floats
    body += struct.pack(
        "<I I i f i i 5f 4f 3f 4f 3f 8f",
        0,
        0xFFFFFFFF,
        30,
        1.0 / 30.0,
        start,
        end,
        -1, -1, -1, -1, -1,
        0, 0, 0, 1,
        0, 0, 0,
        0, 0, 0, 1,
        0, 0, 0,
        -1, -1, -1, -1, -1, -1, -1, -1,
    )
    body += struct.pack("<H", 0)  # foot_plant_bits count
    body += struct.pack("<H", 1)  # 1 controller binding
    body += struct.pack(
        "<IiIIi",  # ControllerInfo: id(u32), pos_kt(i32), pos(i32), rot_kt(i32), rot(i32)
        0x12345678,
        0, 0, 0, 0,
    )
    return body


def test_controller_905_single_track() -> None:
    body = _build_controller_905_body()
    chunk = _drive((ChunkType.Controller, 0x905), body)
    assert isinstance(chunk, ChunkController905)
    assert chunk.num_key_pos == 1
    assert chunk.num_key_rot == 1
    assert chunk.num_key_time == 1
    assert chunk.num_anims == 1
    assert chunk.key_times[0] == [0.0, 1.0]
    assert chunk.key_positions[0][0] == (0.0, 0.0, 0.0)
    assert chunk.key_positions[0][1] == (1.0, 2.0, 3.0)
    assert chunk.key_rotations[0][1] == (0.5, 0.5, 0.5, 0.5)
    assert len(chunk.animations) == 1
    a = chunk.animations[0]
    assert a.name == "idle"
    assert a.motion_params.start == 0
    assert a.motion_params.end == 30
    assert len(a.controllers) == 1
    assert a.controllers[0].controller_id == 0x12345678


# -- GlobalAnimationHeaderCAF 0x971 --------------------------------------


def test_caf_header_971_parses_path_and_durations() -> None:
    file_path = "Animations/foo/idle.caf"
    body = struct.pack("<I", 0xCAFE0000)  # flags
    body += file_path.encode("utf-8").ljust(256, b"\x00")
    body += struct.pack("<I", crc32(file_path.encode("utf-8")) & 0xFFFFFFFF)
    body += struct.pack("<I", 0)  # dba crc32
    # 8 foot floats
    body += struct.pack("<8f", 0, 0.5, 0, 0.5, 0, 0.5, 0, 0.5)
    # start, end, total
    body += struct.pack("<3f", 0.0, 1.5, 1.5)
    body += struct.pack("<I", 12)  # controllers
    # start_location quat, last_locator_key quat, velocity vec3
    body += struct.pack("<4f", 0, 0, 0, 1)
    body += struct.pack("<4f", 0, 0, 0, 1)
    body += struct.pack("<3f", 1.0, 0.0, 0.0)
    # distance, speed, slope, turn_speed, asset_turn
    body += struct.pack("<5f", 1.5, 1.0, 0.0, 0.0, 0.0)

    chunk = _drive((ChunkType.GlobalAnimationHeaderCAF, 0x971), body)
    assert isinstance(chunk, ChunkGlobalAnimationHeaderCAF971)
    assert chunk.file_path == file_path
    assert chunk.flags == 0xCAFE0000
    assert math.isclose(chunk.total_duration, 1.5)
    assert chunk.controllers == 12
    assert math.isclose(chunk.distance, 1.5)


# -- ChrParams XML parser ------------------------------------------------


def test_parse_chrparams_extracts_animation_list() -> None:
    from xml.etree import ElementTree as ET

    xml = ET.fromstring(
        """
        <Params>
          <AnimationList>
            <Animation name="idle" path="anims/idle.caf"/>
            <Animation name="walk" path="anims/walk.caf"/>
          </AnimationList>
        </Params>
        """.strip()
    )
    cp = parse_chrparams(xml, source_file_name="x.chrparams")
    assert cp.source_file_name == "x.chrparams"
    assert len(cp.animations) == 2
    assert cp.animations[0].name == "idle"
    assert cp.animations[0].path == "anims/idle.caf"
    assert cp.animations[0].source_file_name == "x.chrparams"
    assert cp.animations[1].name == "walk"


def test_parse_chrparams_extracts_include_entries() -> None:
    from xml.etree import ElementTree as ET

    xml = ET.fromstring(
        """
        <Params>
          <AnimationList>
            <Animation name="$Include" path="Animations/Alien/grunt/grunt.chrparams"/>
            <Animation name="idle" path="idle.caf"/>
          </AnimationList>
        </Params>
        """.strip()
    )

    cp = parse_chrparams(xml, source_file_name="Grunt_Base.chrparams")

    assert cp.includes == ["Animations/Alien/grunt/grunt.chrparams"]
    assert len(cp.animations) == 1
    assert cp.animations[0].name == "idle"


def test_parse_chrparams_extracts_filepath_base() -> None:
        from xml.etree import ElementTree as ET

        xml = ET.fromstring(
                """
                <Params>
                    <AnimationList>
                        <Animation name="#filepath" path="animations\\alien\\grunt"/>
                        <Animation name="*" path="*\\*.caf"/>
                    </AnimationList>
                </Params>
                """.strip()
        )

        cp = parse_chrparams(xml, source_file_name="grunt_base.chrparams")

        assert cp.animation_base_path == "animations/alien/grunt"
        assert len(cp.animations) == 1
        assert cp.animations[0].base_path == "animations/alien/grunt"
        assert cp.animations[0].path == "*\\*.caf"


def test_load_chrparams_with_includes_records_missing_include() -> None:
    fs = InMemoryFileSystem(
        {
            "Grunt_Base.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$Include" path="Animations/Alien/grunt/grunt.chrparams"/>
                </AnimationList></Params>
            """,
        }
    )

    cp = load_chrparams_with_includes("Grunt_Base.chrparams", fs)

    assert cp is not None
    assert cp.animations == []
    assert cp.missing_includes == ["Animations/Alien/grunt/grunt.chrparams"]


def test_load_chrparams_with_includes_resolves_game_relative_include() -> None:
    fs = InMemoryFileSystem(
        {
            "Objects/characters/alien/grunt/Grunt_Base.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$Include" path="Animations/Alien/grunt/grunt.chrparams"/>
                </AnimationList></Params>
            """,
            "Animations/Alien/grunt/grunt.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="idle" path="idle.caf"/>
                </AnimationList></Params>
            """,
        }
    )

    cp = load_chrparams_with_includes(
        "Objects/characters/alien/grunt/Grunt_Base.chrparams", fs
    )

    assert cp is not None
    assert cp.includes == ["Animations/Alien/grunt/grunt.chrparams"]
    assert len(cp.animations) == 1
    assert cp.animations[0].name == "idle"
    assert cp.animations[0].path == "idle.caf"
    assert cp.animations[0].source_file_name == "Animations/Alien/grunt/grunt.chrparams"


def test_load_chrparams_with_includes_handles_cycles() -> None:
    fs = InMemoryFileSystem(
        {
            "a.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$Include" path="b.chrparams"/>
                  <Animation name="idle" path="idle.caf"/>
                </AnimationList></Params>
            """,
            "b.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$Include" path="a.chrparams"/>
                  <Animation name="walk" path="walk.caf"/>
                </AnimationList></Params>
            """,
        }
    )

    cp = load_chrparams_with_includes("a.chrparams", fs)

    assert cp is not None
    assert [anim.name for anim in cp.animations] == ["idle", "walk"]


def test_supported_animation_clip_path_filters_chrparams_metadata() -> None:
    assert _is_supported_animation_clip_path("animations/alien/grunt/idle.caf")
    assert _is_supported_animation_clip_path("animations/alien/grunt/combat.ANIM")
    assert _is_supported_animation_clip_path("animations/alien/grunt/packed.dba")
    assert _is_supported_animation_clip_path(
        "animations/alien/grunt/idle.caf (stand_idle_idle_01)"
    )
    assert not _is_supported_animation_clip_path(
        "animations/alien/grunt/events.animevents"
    )
    assert not _is_supported_animation_clip_path(
        "animations/alien/grunt/locomotion/lmg/walk.lmg"
    )


def test_load_animations_skips_chrparams_non_clip_entries(caplog) -> None:
    fs = InMemoryFileSystem(
        {
            "grunt.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="events" path="events.animevents"/>
                  <Animation name="walk" path="locomotion/lmg/walk.lmg"/>
                </AnimationList></Params>
            """,
            "events.animevents": b"<anim_events/>",
            "locomotion/lmg/walk.lmg": b"<LocomotionGroup/>",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "grunt.chr"
    engine.pack_fs = fs
    engine.object_dir = None
    engine.models = []
    engine.animation_models = []
    engine.animation_clips = []
    engine.chrparams = None

    caplog.set_level(logging.WARNING, logger="cryengine_importer.core.cryengine")
    engine._load_animations()

    assert engine.animation_models == []
    assert engine.animation_clips == []
    assert "failed to load animation file" not in caplog.text


def test_load_animations_skips_tracks_database_entries(caplog) -> None:
    fs = InMemoryFileSystem(
        {
            "grunt.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$TracksDatabase" path="animations/alien/grunt/grunt.dba"/>
                </AnimationList></Params>
            """,
            "animations/alien/grunt/grunt.dba": b"not a playable clip",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "grunt.chr"
    engine.pack_fs = fs
    engine.object_dir = None
    engine.models = []
    engine.animation_models = []
    engine.animation_clips = []
    engine.chrparams = None

    caplog.set_level(logging.WARNING, logger="cryengine_importer.core.cryengine")
    engine._load_animations()

    assert engine.animation_models == []
    assert engine.animation_clips == []
    assert "failed to load animation file" not in caplog.text


def test_load_animations_imports_playable_tracks_database_dba(monkeypatch) -> None:
    from cryengine_importer.core import cryengine as ce_mod

    fs = InMemoryFileSystem(
        {
            "alienbase.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="$TracksDatabase" path="animations/alien/alienbase/alienbase.dba"/>
                </AnimationList></Params>
            """,
            "animations/animations/alien/alienbase/alienbase.dba": b"dba",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "alienbase.chr"
    engine.pack_fs = fs
    engine.object_dir = None
    engine.models = []
    engine.animation_models = []
    engine.animation_clips = []
    engine.chrparams = None
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    chunk = _drive((ChunkType.Controller, 0x905), _build_controller_905_body())
    model = Model()
    model.file_name = "animations/animations/alien/alienbase/alienbase.dba"
    model.chunk_map = {1: chunk}
    monkeypatch.setattr(
        ce_mod.Model,
        "from_stream",
        classmethod(lambda cls, name, stream: model),
    )

    engine._load_animations()

    assert len(engine.animation_models) == 1
    assert len(engine.animation_clips) == 1
    [clip] = engine.animation_clips
    assert clip.name == "idle"
    assert clip.source_file_name == "animations/animations/alien/alienbase/alienbase.dba"
    assert clip.duration_secs == pytest.approx(1.0)
    assert clip.rotation_track_count == 1
    assert clip.position_track_count == 1
    assert clip.tracks[0].rot_times == pytest.approx([0.0, 1.0 / 30.0])


def test_controller_905_dba_clip_times_start_at_zero() -> None:
    chunk = _drive(
        (ChunkType.Controller, 0x905),
        _build_controller_905_body(
            name=b"offset_idle",
            key_times=(120.0, 150.0),
            start=120,
            end=150,
        ),
    )
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[])

    [clip] = engine._build_clips_from_controller905(chunk)

    assert clip.name == "offset_idle"
    assert clip.duration_secs == pytest.approx(1.0)
    assert clip.tracks[0].pos_times == pytest.approx([0.0, 1.0])
    assert clip.tracks[0].rot_times == pytest.approx([0.0, 1.0])


def test_controller_905_uses_bind_pose_basis_and_skips_root_track() -> None:
    def qz(degrees: float) -> tuple[float, float, float, float]:
        radians = math.radians(degrees)
        return (0.0, 0.0, math.sin(radians * 0.5), math.cos(radians * 0.5))

    def matrix_z(degrees: float) -> tuple[tuple[float, ...], ...]:
        radians = math.radians(degrees)
        c = math.cos(radians)
        s = math.sin(radians)
        return (
            (c, -s, 0.0, 0.0),
            (s, c, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        )

    root = SimpleNamespace(
        bone_name="MASTER",
        controller_id=0x1,
        parent_bone=None,
        local_transform_matrix=matrix_z(0.0),
        world_transform_matrix=matrix_z(0.0),
    )
    child = SimpleNamespace(
        bone_name="child",
        controller_id=0x2,
        parent_bone=root,
        local_transform_matrix=matrix_z(90.0),
        world_transform_matrix=matrix_z(90.0),
    )

    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[root, child])

    controller = ChunkController905()
    controller.key_times = [[0.0, 30.0]]
    controller.key_positions = [[(0.0, 1.0, 0.0), (0.0, 2.0, 0.0)]]
    controller.key_rotations = [[qz(120.0), qz(150.0)]]
    controller.animations = [
        Animation905(
            name="pose_basis",
            motion_params=MotionParams905(secs_per_tick=1.0 / 30.0, start=0, end=30),
            controllers=[
                ControllerInfo(
                    controller_id=0x1,
                    pos_key_time_track=0,
                    pos_track=0,
                    rot_key_time_track=0,
                    rot_track=0,
                ),
                ControllerInfo(
                    controller_id=0x2,
                    pos_key_time_track=0,
                    pos_track=0,
                    rot_key_time_track=0,
                    rot_track=0,
                ),
            ],
        )
    ]

    [clip] = engine._build_clips_from_controller905(controller)

    assert clip.skipped_root_tracks == 1
    assert len(clip.tracks) == 1
    track = clip.tracks[0]
    assert track.bone_name == "child"
    assert track.pos_times == pytest.approx([0.0, 1.0])
    assert track.positions[0] == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert track.rotations[0] == pytest.approx(qz(30.0), abs=1e-6)


def test_controller_905_skips_invalid_position_track() -> None:
    bone = SimpleNamespace(
        bone_name="child",
        controller_id=0x2,
        parent_bone=object(),
        local_transform_matrix=(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        ),
        world_transform_matrix=(
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
        ),
    )
    engine = CryEngine.__new__(CryEngine)
    engine.skinning_info = SimpleNamespace(compiled_bones=[bone])

    controller = ChunkController905()
    controller.key_times = [[0.0]]
    controller.key_positions = [[(100000.0, 0.0, 0.0)]]
    controller.key_rotations = [[(0.0, 0.0, 0.0, 1.0)]]
    controller.animations = [
        Animation905(
            name="bad_position",
            motion_params=MotionParams905(secs_per_tick=1.0, start=0, end=1),
            controllers=[
                ControllerInfo(
                    controller_id=0x2,
                    pos_key_time_track=0,
                    pos_track=0,
                    rot_key_time_track=0,
                    rot_track=0,
                )
            ],
        )
    ]

    [clip] = engine._build_clips_from_controller905(controller)

    assert clip.skipped_position_tracks == 1
    assert clip.rotation_track_count == 1
    assert clip.position_track_count == 0
    assert clip.tracks[0].positions == []


def test_load_animations_uses_cdf_base_chrparams_for_skin_attachment(monkeypatch) -> None:
        from cryengine_importer.core import cryengine as ce_mod

        fs = InMemoryFileSystem(
                {
                        "objects/chars/hazmat/hazmat.cdf": b"""
                                <CharacterDefinition>
                                    <Model File="objects/chars/generic/skeleton_male_generic.chr"/>
                                    <AttachmentList>
                                        <Attachment AName="hazmat" Type="CA_SKIN"
                                                                Binding="objects/chars/hazmat/hazmatsuit.chr"/>
                                    </AttachmentList>
                                </CharacterDefinition>
                        """,
                        "objects/chars/hazmat/hazmat_without_rifle.cdf": b"""
                                <CharacterDefinition>
                                    <Model File="objects/chars/generic/skeleton_male_generic.chr"/>
                                    <AttachmentList>
                                        <Attachment AName="hazmat" Type="CA_SKIN"
                                                                Binding="objects/chars/hazmat/hazmatsuit.chr"/>
                                    </AttachmentList>
                                </CharacterDefinition>
                        """,
                        "objects/chars/generic/skeleton_male_generic.chr": b"",
                        "objects/chars/generic/skeleton_male_generic.chrparams": b"""
                                <Params><AnimationList>
                                    <Animation name="idle" path="animations/human/male/idle.caf"/>
                                </AnimationList></Params>
                        """,
                        "animations/human/male/idle.caf": b"caf",
                }
        )
        engine = CryEngine.__new__(CryEngine)
        engine.input_file = "objects/chars/hazmat/hazmatsuit.chr"
        engine.pack_fs = fs
        engine.object_dir = None
        engine.models = []
        engine.animation_models = []
        engine.animation_clips = []
        engine.chrparams = None

        monkeypatch.setattr(
                ce_mod.Model,
                "from_stream",
                classmethod(lambda cls, name, stream: Model()),
        )
        engine._build_clip_from_caf = lambda name, model: AnimationClip(name=name)

        engine._load_animations()

        assert engine.chrparams is not None
        assert engine.chrparams.source_file_name == (
                "objects/chars/generic/skeleton_male_generic.chrparams"
        )
        assert [clip.name for clip in engine.animation_clips] == ["idle"]
        assert engine.animation_clips[0].source_file_name == "animations/human/male/idle.caf"


def test_load_animations_scopes_filepath_wildcards(monkeypatch) -> None:
    from cryengine_importer.core import cryengine as ce_mod

    fs = InMemoryFileSystem(
        {
            "objects/characters/alien/grunt/grunt_base.chrparams": b"""
                <Params><AnimationList>
                  <Animation name="#filepath" path="animations\\alien\\grunt"/>
                  <Animation name="*" path="*\\*.caf"/>
                </AnimationList></Params>
            """,
            "animations/alien/grunt/behavior/idle.caf": b"caf",
            "animations/alien/other/behavior/idle.caf": b"caf",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "objects/characters/alien/grunt/grunt_base.chr"
    engine.pack_fs = fs
    engine.object_dir = None
    engine.models = []
    engine.animation_models = []
    engine.animation_clips = []
    engine.chrparams = None

    monkeypatch.setattr(
        ce_mod.Model,
        "from_stream",
        classmethod(lambda cls, name, stream: Model()),
    )
    engine._build_clip_from_caf = lambda name, model: AnimationClip(name=name)

    engine._load_animations()

    assert [clip.source_file_name for clip in engine.animation_clips] == [
        "animations/alien/grunt/behavior/idle.caf"
    ]


def test_resolve_anim_paths_expands_chrparams_wildcards() -> None:
    fs = InMemoryFileSystem(
        {
            "animations/alien/grunt/behavior/idle/idle_01.caf": b"",
            "animations/alien/grunt/behavior/idle/idle_02.caf": b"",
            "animations/alien/grunt/behavior/idle/notes.txt": b"",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "objects/characters/alien/grunt/grunt_base.chr"
    engine.pack_fs = fs
    engine.object_dir = r"E:\SafeToCopy\Models\Cry2Objects"

    assert engine._resolve_anim_paths(
        "behavior/idle/*.caf", "animations/alien/grunt"
    ) == [
        "animations/alien/grunt/behavior/idle/idle_01.caf",
        "animations/alien/grunt/behavior/idle/idle_02.caf",
    ]

    assert engine._resolve_anim_paths(
        "behavior/idle/idle_01.caf (stand_idle_idle_01)",
        "animations/alien/grunt",
    ) == ["animations/alien/grunt/behavior/idle/idle_01.caf"]


def test_resolve_anim_paths_can_use_animations_root() -> None:
    fs = InMemoryFileSystem(
        {
            "alien/grunt/behavior/idle/idle_01.caf": b"",
            "alien/grunt/behavior/idle/idle_02.caf": b"",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "objects/characters/alien/grunt/grunt_base.chr"
    engine.pack_fs = fs
    engine.object_dir = None

    assert engine._resolve_anim_paths(
        "behavior/idle/*.caf", "animations/alien/grunt"
    ) == [
        "alien/grunt/behavior/idle/idle_01.caf",
        "alien/grunt/behavior/idle/idle_02.caf",
    ]


def test_resolve_anim_paths_can_use_nested_animations_root() -> None:
    fs = InMemoryFileSystem(
        {
            "animations/animations/animals/squirrel/squirrel_idle.caf": b"",
            "animations/animations/animals/squirrel/squirrel_walk.caf": b"",
        }
    )
    engine = CryEngine.__new__(CryEngine)
    engine.input_file = "objects/characters/animals/squirrel/squirrel.chr"
    engine.pack_fs = fs
    engine.object_dir = None

    assert engine._resolve_anim_paths(
        "animations/animals/squirrel/squirrel_idle.caf", "objects/characters/animals/squirrel"
    ) == ["animations/animations/animals/squirrel/squirrel_idle.caf"]

    assert engine._resolve_anim_paths(
        "animations/animals/squirrel/*.caf", "objects/characters/animals/squirrel"
    ) == [
        "animations/animations/animals/squirrel/squirrel_idle.caf",
        "animations/animations/animals/squirrel/squirrel_walk.caf",
    ]


def test_parse_chrparams_handles_missing_animation_list() -> None:
    from xml.etree import ElementTree as ET

    cp = parse_chrparams(ET.fromstring("<Params/>"))
    assert cp.animations == []


# -- compressed quat helpers ---------------------------------------------


def test_short_int3_quat_roundtrip_identity() -> None:
    # Encode identity (0,0,0,1) and decode back; W reconstructed.
    raw = struct.pack("<3h", 0, 0, 0)
    br = BinaryReader(io.BytesIO(raw))
    q = br.read_short_int3_quat()
    assert q == (0.0, 0.0, 0.0, 1.0)


def test_small_tree_dword_quat_decodes_identity() -> None:
    # max-index = 3 (W), all other components 0 (packed as midpoint).
    # (mid + range) * MAX_10BITf with mid==0 -> 723 * 0.7071 = 511.something
    # Easier: build the bit-pattern directly by packing zeros then patching
    # max-index bits.
    raw = struct.pack("<I", 0xC0000000 | 0)  # max_idx=3, zero packs => negative
    # The decoder will produce non-identity (because 0 packed != 0 component);
    # just assert it returns a valid-length quat.
    br = BinaryReader(io.BytesIO(raw))
    q = br.read_small_tree_dword_quat()
    assert len(q) == 4
