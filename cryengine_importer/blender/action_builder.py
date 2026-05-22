"""Build Blender Actions + fcurves from `AnimationClip`s.

Phase 4 counterpart of `armature_builder.attach_skin`. For each
`AnimationClip` in `cryengine.animation_clips` we create a
`bpy.types.Action`, group fcurves per bone, and key
``pose.bones["…"].location`` (vec3) and ``…rotation_quaternion``
(quat) at the times listed in the track. Imported actions are left in
``bpy.data.actions`` for the user to switch to; the armature remains in
its rest pose immediately after import.

CGA-style object animation is handled by ``build_object_actions``: one
Action is created per animated Blender object because Blender Actions
belong to a single ID block, not to a whole collection.

We translate raw seconds into Blender frames using the scene's FPS
(default 24) — that means timeline scrubbing matches what an artist
would expect from a baked import. The clip's `duration_secs` extends
the scene's frame_end so the timeline reflects all loaded clips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]

from ..models.animation import AnimationClip, BoneAnimationTrack, ObjectAnimationTrack
from .armature_builder import _safe_bone_name

if TYPE_CHECKING:
    from ..core.cryengine import CryEngine


def build_actions(
    cryengine: "CryEngine",
    arm_obj: "bpy.types.Object",
) -> list["bpy.types.Action"]:
    """Create one Action per `AnimationClip`. Returns the list of
    actions. The armature is left without an active action so newly
    imported meshes don't open in an arbitrary animation pose."""
    if not cryengine.animation_clips:
        return []

    fps = float(bpy.context.scene.render.fps) or 24.0

    if arm_obj.animation_data is None:
        arm_obj.animation_data_create()

    actions: list[bpy.types.Action] = []
    last_frame = 1
    for clip in cryengine.animation_clips:
        action = bpy.data.actions.new(name=clip.name or "anim")
        action.use_fake_user = True
        action["cryblend_kind"] = "armature"
        action["cryblend_target"] = arm_obj.name
        action["cryblend_clip"] = clip.name or "anim"
        action["cryblend_clip_kind"] = clip.clip_kind or "full_body"
        action["cryblend_source_file"] = clip.source_file_name or ""
        action["cryblend_is_additive"] = bool(clip.is_additive)
        action["cryblend_track_count"] = len(clip.tracks)
        action["cryblend_rotation_track_count"] = int(clip.rotation_track_count)
        action["cryblend_position_track_count"] = int(clip.position_track_count)
        action["cryblend_skipped_root_tracks"] = int(clip.skipped_root_tracks)
        action["cryblend_skipped_position_tracks"] = int(
            clip.skipped_position_tracks
        )
        arm_obj.animation_data.action = action
        bound_tracks, unresolved_tracks = _populate_action(action, clip, fps, arm_obj)
        action["cryblend_bound_track_count"] = int(bound_tracks)
        action["cryblend_unresolved_track_count"] = int(unresolved_tracks)
        if bound_tracks == 0:
            arm_obj.animation_data.action = None
            bpy.data.actions.remove(action)
            continue
        actions.append(action)
        # Track the latest frame for scene end clamp.
        end_frame = int(round(max(clip.duration_secs, 0.0) * fps)) + 1
        if end_frame > last_frame:
            last_frame = end_frame

    arm_obj.animation_data.action = None
    if last_frame > bpy.context.scene.frame_end:
        bpy.context.scene.frame_end = last_frame

    return actions


def build_object_actions(
    cryengine: "CryEngine",
    node_to_obj: dict[int, "bpy.types.Object"],
) -> list["bpy.types.Action"]:
    """Create object-transform Actions for CGA-style animated nodes."""
    clips = getattr(cryengine, "object_animation_clips", [])
    if not clips:
        return []

    fps = float(bpy.context.scene.render.fps) or 24.0
    actions: list[bpy.types.Action] = []
    last_frame = 1
    first_action_by_target: dict[str, bpy.types.Action] = {}
    rest_transform_by_target: dict[
        str,
        tuple[
            tuple[float, float, float],
            tuple[float, float, float, float],
            tuple[float, float, float],
        ],
    ] = {}

    for clip in clips:
        clip_name = clip.name or "object_anim"
        for track in clip.tracks:
            obj = node_to_obj.get(track.node_id)
            if obj is None:
                continue
            if track.positions or track.rotations or track.scales:
                obj.rotation_mode = "QUATERNION"
            rest_transform = rest_transform_by_target.setdefault(
                obj.name,
                (
                    _object_rest_location(obj),
                    _object_rest_rotation(obj),
                    _object_rest_scale(obj),
                ),
            )
            if obj.animation_data is None:
                obj.animation_data_create()
            action = bpy.data.actions.new(name=f"{clip_name}.{obj.name}")
            action["cryblend_kind"] = "object"
            action["cryblend_target"] = obj.name
            action["cryblend_clip"] = clip_name
            obj.animation_data.action = action
            if not _populate_object_action(
                action,
                track,
                fps,
                obj,
                base_location=rest_transform[0],
                base_rotation=rest_transform[1],
                base_scale=rest_transform[2],
            ):
                bpy.data.actions.remove(action)
                continue
            actions.append(action)
            first_action_by_target.setdefault(obj.name, action)

            end_frame = int(round(max(clip.duration_secs, 0.0) * fps)) + 1
            if end_frame > last_frame:
                last_frame = end_frame

    if actions and last_frame > bpy.context.scene.frame_end:
        bpy.context.scene.frame_end = last_frame
    for obj_name, action in first_action_by_target.items():
        obj = bpy.data.objects.get(obj_name)
        if obj is not None and obj.animation_data is not None:
            obj.animation_data.action = action
    return actions


def _populate_action(
    action: "bpy.types.Action",
    clip: AnimationClip,
    fps: float,
    datablock: "bpy.types.ID",
) -> tuple[int, int]:
    bound_tracks = 0
    unresolved_tracks = 0
    for track in clip.tracks:
        bone = _safe_bone_name(track.bone_name)
        if not bone:
            continue
        if not _has_pose_bone(datablock, bone):
            unresolved_tracks += 1
            continue

        made_track = False

        if track.positions:
            data_path = f'pose.bones["{bone}"].location'
            for axis in range(3):
                samples = [
                    (t * fps + 1.0, p[axis])
                    for t, p in zip(track.pos_times, track.positions)
                ]
                if not samples:
                    continue
                fc = _new_fcurve(action, datablock, data_path, axis, bone)
                _set_keyframes(fc, samples)
                made_track = True

        if track.rotations:
            data_path = f'pose.bones["{bone}"].rotation_quaternion'
            # mathutils.Quaternion order is (w, x, y, z); on-disk is
            # (x, y, z, w). Re-order on the fly.
            order = (3, 0, 1, 2)
            for axis_blender, axis_src in enumerate(order):
                samples = [
                    (t * fps + 1.0, _safe_component(q, axis_src))
                    for t, q in zip(track.rot_times, track.rotations)
                ]
                if not samples:
                    continue
                fc = _new_fcurve(action, datablock, data_path, axis_blender, bone)
                _set_keyframes(fc, samples)
                made_track = True

        if made_track:
            bound_tracks += 1

    return bound_tracks, unresolved_tracks


def _has_pose_bone(datablock: "bpy.types.ID", bone_name: str) -> bool:
    bones = getattr(getattr(datablock, "data", None), "bones", None)
    if bones is None:
        return True
    try:
        return bone_name in bones
    except TypeError:
        getter = getattr(bones, "get", None)
        if getter is None:
            return True
        return getter(bone_name) is not None


def _populate_object_action(
    action: "bpy.types.Action",
    track: ObjectAnimationTrack,
    fps: float,
    datablock: "bpy.types.ID",
    *,
    base_location: tuple[float, float, float] | None = None,
    base_rotation: tuple[float, float, float, float] | None = None,
    base_scale: tuple[float, float, float] | None = None,
) -> bool:
    made_curve = False
    group_name = track.node_name or "Object"
    key_times = _object_track_times(track)

    if track.positions:
        for axis in range(3):
            fc = _new_fcurve(action, datablock, "location", axis, group_name)
            _set_keyframes(
                fc,
                [
                    (time * fps + 1.0, pos[axis])
                    for time, pos in zip(track.pos_times, track.positions)
                ],
            )
            made_curve = True
    elif key_times:
        location = base_location or _object_rest_location(datablock)
        for axis in range(3):
            fc = _new_fcurve(action, datablock, "location", axis, group_name)
            _set_keyframes(
                fc,
                [(time * fps + 1.0, location[axis]) for time in key_times],
            )

    if track.rotations:
        base_rotation = base_rotation or _object_rest_rotation(datablock)
        rotations = [
            _combine_object_rotation(base_rotation, quat)
            for quat in track.rotations
        ]
        for axis_blender in range(4):
            fc = _new_fcurve(
                action, datablock, "rotation_quaternion", axis_blender, group_name
            )
            _set_keyframes(
                fc,
                [
                    (time * fps + 1.0, _safe_component(quat, axis_blender))
                    for time, quat in zip(track.rot_times, rotations)
                ],
            )
            made_curve = True
    elif key_times:
        rotation = base_rotation or _object_rest_rotation(datablock)
        for axis in range(4):
            fc = _new_fcurve(
                action, datablock, "rotation_quaternion", axis, group_name
            )
            _set_keyframes(
                fc,
                [(time * fps + 1.0, rotation[axis]) for time in key_times],
            )

    if track.scales:
        for axis in range(3):
            fc = _new_fcurve(action, datablock, "scale", axis, group_name)
            _set_keyframes(
                fc,
                [
                    (time * fps + 1.0, scale[axis])
                    for time, scale in zip(track.scale_times, track.scales)
                ],
            )
            made_curve = True
    elif key_times:
        scale = base_scale or _object_rest_scale(datablock)
        for axis in range(3):
            fc = _new_fcurve(action, datablock, "scale", axis, group_name)
            _set_keyframes(
                fc,
                [(time * fps + 1.0, scale[axis]) for time in key_times],
            )

    return made_curve


def _object_track_times(track: ObjectAnimationTrack) -> list[float]:
    return sorted(
        {
            *track.pos_times,
            *track.rot_times,
            *track.scale_times,
        }
    )


def _object_rest_location(datablock: "bpy.types.ID") -> tuple[float, float, float]:
    loc = getattr(datablock, "location", None)
    if loc is None:
        return (0.0, 0.0, 0.0)
    try:
        return (float(loc[0]), float(loc[1]), float(loc[2]))
    except (TypeError, ValueError, IndexError):
        return (0.0, 0.0, 0.0)


def _object_rest_scale(datablock: "bpy.types.ID") -> tuple[float, float, float]:
    scale = getattr(datablock, "scale", None)
    if scale is None:
        return (1.0, 1.0, 1.0)
    try:
        return (float(scale[0]), float(scale[1]), float(scale[2]))
    except (TypeError, ValueError, IndexError):
        return (1.0, 1.0, 1.0)


def _object_rest_rotation(datablock: "bpy.types.ID") -> tuple[float, float, float, float]:
    quat = getattr(datablock, "rotation_quaternion", None)
    if quat is None:
        return (1.0, 0.0, 0.0, 0.0)
    try:
        return (
            float(quat[0]),
            float(quat[1]),
            float(quat[2]),
            float(quat[3]),
        )
    except (TypeError, ValueError, IndexError):
        return (1.0, 0.0, 0.0, 0.0)


def _combine_object_rotation(
    base_wxyz: tuple[float, float, float, float],
    delta_xyzw: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    bw, bx, by, bz = base_wxyz
    dx, dy, dz, dw = delta_xyzw
    return _normalise_wxyz(
        (
            bw * dw - bx * dx - by * dy - bz * dz,
            bw * dx + bx * dw + by * dz - bz * dy,
            bw * dy - bx * dz + by * dw + bz * dx,
            bw * dz + bx * dy - by * dx + bz * dw,
        )
    )


def _normalise_wxyz(
    quat: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    length = sum(component * component for component in quat) ** 0.5
    if length <= 1e-8:
        return (1.0, 0.0, 0.0, 0.0)
    return tuple(component / length for component in quat)  # type: ignore[return-value]


def _new_fcurve(
    action: "bpy.types.Action",
    datablock: "bpy.types.ID",
    data_path: str,
    index: int,
    group_name: str,
) -> "bpy.types.FCurve":
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        return fcurves.new(data_path=data_path, index=index, action_group=group_name)
    return action.fcurve_ensure_for_datablock(
        datablock, data_path, index=index, group_name=group_name
    )


def _set_keyframes(
    fc: "bpy.types.FCurve", samples: list[tuple[float, float]]
) -> None:
    if not samples:
        return
    clear = getattr(fc.keyframe_points, "clear", None)
    if callable(clear):
        clear()
    fc.keyframe_points.add(count=len(samples))
    for i, (frame, value) in enumerate(samples):
        kp = fc.keyframe_points[i]
        kp.co = (frame, value)
        kp.interpolation = "LINEAR"


def _safe_component(q: tuple, idx: int) -> float:
    """Compressed quat formats can leave NaN in the W slot when the
    on-disk format was eNoCompressVec3. Substitute 1.0 in that case
    so Blender doesn't reject the keyframe."""
    if idx >= len(q):
        return 0.0
    v = q[idx]
    if v != v:  # NaN check
        return 1.0 if idx == 3 else 0.0
    return float(v)


__all__ = ["build_actions", "build_object_actions"]
