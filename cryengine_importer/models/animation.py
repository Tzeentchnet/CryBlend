"""Animation data classes — port of CgfConverter animation chunk types.

Plain dataclasses shared between the Phase 4 chunk readers
(`core/chunks/controller_*`, `global_animation_header_caf.py`,
`bone_anim.py`) and the Blender action builder. No `bpy` here.

References:
- CgfConverter/CryEngineCore/Chunks/ChunkController_826.cs
- CgfConverter/CryEngineCore/Chunks/ChunkController_905.cs
- CgfConverter/CryEngineCore/Chunks/ChunkGlobalAnimationHeaderCAF.cs
- CgfConverter/ChrParams/ChrParams.cs / Animation.cs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# -- Controller_826 keyframe ---------------------------------------------


@dataclass
class ControllerKey:
    """Port of Models/Structs/Structs.cs#Key."""

    time: int = 0
    abs_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rel_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)


# -- Controller_905 sub-records ------------------------------------------


@dataclass
class MotionParams905:
    """Port of ChunkController_905.MotionParams905."""

    asset_flags: int = 0
    compression: int = 0xFFFFFFFF
    ticks_per_frame: int = 0
    secs_per_tick: float = 0.0
    start: int = 0
    end: int = 0

    move_speed: float = -1.0
    turn_speed: float = -1.0
    asset_turn: float = -1.0
    distance: float = -1.0
    slope: float = -1.0

    start_location_q: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    start_location_v: tuple[float, float, float] = (1.0, 1.0, 1.0)
    end_location_q: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    end_location_v: tuple[float, float, float] = (1.0, 1.0, 1.0)

    l_heel_start: float = -1.0
    l_heel_end: float = -1.0
    l_toe0_start: float = -1.0
    l_toe0_end: float = -1.0
    r_heel_start: float = -1.0
    r_heel_end: float = -1.0
    r_toe0_start: float = -1.0
    r_toe0_end: float = -1.0


@dataclass
class ControllerInfo:
    """Port of ChunkController_905.CControllerInfo (per-bone track refs)."""

    INVALID_TRACK: int = -1

    controller_id: int = 0xFFFFFFFF
    pos_key_time_track: int = -1
    pos_track: int = -1
    rot_key_time_track: int = -1
    rot_track: int = -1

    @property
    def has_pos_track(self) -> bool:
        return self.pos_track != -1 and self.pos_key_time_track != -1

    @property
    def has_rot_track(self) -> bool:
        return self.rot_track != -1 and self.rot_key_time_track != -1


@dataclass
class Animation905:
    """Port of ChunkController_905.Animation (one named animation
    inside a Controller_905 chunk)."""

    name: str = ""
    motion_params: MotionParams905 = field(default_factory=MotionParams905)
    foot_plant_bits: bytes = b""
    controllers: list[ControllerInfo] = field(default_factory=list)


# -- ChrParams ------------------------------------------------------------


@dataclass
class ChrParamsAnimation:
    """Port of ChrParams/Animation.cs."""

    name: Optional[str] = None
    path: Optional[str] = None


@dataclass
class ChrParams:
    """Port of ChrParams/ChrParams.cs."""

    source_file_name: Optional[str] = None
    animations: list[ChrParamsAnimation] = field(default_factory=list)


# -- Per-bone animation track (consumer-facing) --------------------------


@dataclass
class BoneAnimationTrack:
    """One bone's animation track resolved from a Controller_905 +
    bone_names list. Times are in seconds; rotations are (x, y, z, w);
    positions are (x, y, z).

    Either ``positions`` or ``rotations`` may be empty when the track
    only animates one channel.
    """

    bone_name: str = ""
    controller_id: int = 0
    pos_times: list[float] = field(default_factory=list)
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    rot_times: list[float] = field(default_factory=list)
    rotations: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class AnimationClip:
    """One playable animation: a name, a duration, and per-bone tracks.

    Built by the Phase 4 Blender layer from either:
      * a Controller_905's tracks + Animation905 entries, or
      * a CAF file's Controller chunks + GlobalAnimationHeaderCAF_971.
    """

    name: str = ""
    duration_secs: float = 0.0
    tracks: list[BoneAnimationTrack] = field(default_factory=list)


__all__ = [
    "ControllerKey",
    "MotionParams905",
    "ControllerInfo",
    "Animation905",
    "ChrParamsAnimation",
    "ChrParams",
    "BoneAnimationTrack",
    "AnimationClip",
]
