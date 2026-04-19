"""Build Blender Actions + fcurves from `AnimationClip`s.

Phase 4 counterpart of `armature_builder.attach_skin`. For each
`AnimationClip` in `cryengine.animation_clips` we create a
`bpy.types.Action`, group fcurves per bone, and key
``pose.bones["…"].location`` (vec3) and ``…rotation_quaternion``
(quat) at the times listed in the track. The first clip is assigned
to the armature's animation_data so it auto-plays; the rest live in
``bpy.data.actions`` for the user to switch to.

We translate raw seconds into Blender frames using the scene's FPS
(default 24) — that means timeline scrubbing matches what an artist
would expect from a baked import. The clip's `duration_secs` extends
the scene's frame_end so the timeline reflects all loaded clips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]

from ..models.animation import AnimationClip, BoneAnimationTrack

if TYPE_CHECKING:
    from ..core.cryengine import CryEngine


def build_actions(
    cryengine: "CryEngine",
    arm_obj: "bpy.types.Object",
) -> list["bpy.types.Action"]:
    """Create one Action per `AnimationClip`. Returns the list of
    actions. The first action is assigned to ``arm_obj.animation_data``
    so the user sees animation immediately on import."""
    if not cryengine.animation_clips:
        return []

    fps = float(bpy.context.scene.render.fps) or 24.0

    if arm_obj.animation_data is None:
        arm_obj.animation_data_create()

    actions: list[bpy.types.Action] = []
    last_frame = 1
    for clip in cryengine.animation_clips:
        action = bpy.data.actions.new(name=clip.name or "anim")
        _populate_action(action, clip, fps)
        actions.append(action)
        # Track the latest frame for scene end clamp.
        end_frame = int(round(max(clip.duration_secs, 0.0) * fps)) + 1
        if end_frame > last_frame:
            last_frame = end_frame

    arm_obj.animation_data.action = actions[0]
    if last_frame > bpy.context.scene.frame_end:
        bpy.context.scene.frame_end = last_frame

    return actions


def _populate_action(
    action: "bpy.types.Action",
    clip: AnimationClip,
    fps: float,
) -> None:
    for track in clip.tracks:
        bone = track.bone_name
        if not bone:
            continue
        group = action.groups.get(bone) or action.groups.new(name=bone)

        if track.positions:
            data_path = f'pose.bones["{bone}"].location'
            for axis in range(3):
                fc = action.fcurves.new(
                    data_path=data_path, index=axis, action_group=bone
                )
                _ = group  # silence linter; group is read by Blender
                _set_keyframes(
                    fc,
                    [
                        (t * fps + 1.0, p[axis])
                        for t, p in zip(track.pos_times, track.positions)
                    ],
                )

        if track.rotations:
            data_path = f'pose.bones["{bone}"].rotation_quaternion'
            # mathutils.Quaternion order is (w, x, y, z); on-disk is
            # (x, y, z, w). Re-order on the fly.
            order = (3, 0, 1, 2)
            for axis_blender, axis_src in enumerate(order):
                fc = action.fcurves.new(
                    data_path=data_path, index=axis_blender, action_group=bone
                )
                _set_keyframes(
                    fc,
                    [
                        (t * fps + 1.0, _safe_component(q, axis_src))
                        for t, q in zip(track.rot_times, track.rotations)
                    ],
                )


def _set_keyframes(
    fc: "bpy.types.FCurve", samples: list[tuple[float, float]]
) -> None:
    if not samples:
        return
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


__all__ = ["build_actions"]
