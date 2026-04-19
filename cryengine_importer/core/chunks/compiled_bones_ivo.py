"""ChunkCompiledBones_900 / _901 — IVO compiled bones.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledBones_900.cs
and ChunkCompiledBones_901.cs.

Both versions are routed against the IVO chunk types
``CompiledBones_Ivo`` (0xC201973C) and ``CompiledBones_Ivo2``
(0xC2011111). The traditional 0x800 / 0x801 records live in
``compiled_bones.py``.

The 0x900 record stores per-bone:
    - controller id (u32) — CRC32 of bone name
    - limb id (u32)
    - parent index (i32) — index into the bone list, -1 for root
    - relative quat + vec3 (local)
    - world quat + vec3
…then a null-separated bone-name table follows.

The 0x901 record is split: a 14-byte per-bone header, then the
name table, then a second per-bone block with relative + world
quat / vec3 from which we derive the bind-pose matrix.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import CompiledBone
from ..chunk_registry import chunk
from .compiled_bones import ChunkCompiledBones


def _read_null_separated_strings(
    br, count: int, byte_count: int | None = None
) -> list[str]:
    """Port of Utilities/Utils.cs#GetNullSeparatedStrings.

    Two modes (matches the v2.0.0 C# overloads):

    - ``byte_count is None`` or ``0`` — legacy unbounded form: read
      ``count`` null-terminated strings sequentially from the stream.
    - ``byte_count > 0`` — v2 bounded form: read exactly ``byte_count``
      bytes from the stream, then split into up to ``count`` null-
      terminated strings. Prevents buffer overruns on corrupt inputs.
      Mirrors
      ``GetNullSeparatedStrings(int numberOfNames, int byteCount, BinaryReader b)``.
    """
    if not byte_count:
        return [br.read_cstring() for _ in range(count)]

    buf = br.read_bytes(byte_count)
    out: list[str] = []
    start = 0
    for i in range(len(buf)):
        if buf[i] == 0:
            out.append(buf[start:i].decode("ascii", errors="replace"))
            start = i + 1
            if len(out) == count:
                break
    while len(out) < count:
        out.append("")
    return out


def _quat_vec3_to_mat34(
    q: tuple[float, float, float, float], v: tuple[float, float, float]
) -> tuple[tuple[float, ...], ...]:
    """Build a row-major 3x4 rotation+translation matrix from a quat
    + translation, matching ``Matrix3x4.CreateFromParts``."""
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), v[0]),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), v[1]),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), v[2]),
    )


def _invert_world_to_bind(
    q: tuple[float, float, float, float], v: tuple[float, float, float]
) -> tuple[tuple[float, ...], ...]:
    """Invert a rigid (rotation + translation) world matrix to produce
    a bind-pose matrix. Matches the C# 0x900 / 0x901 code which builds
    a Matrix4x4 from worldQuat + translation, then ``Matrix4x4.Invert``.
    For a rigid transform the inverse is ``R^T | -R^T * t``."""
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    # Forward rotation rows (= R).
    r00, r01, r02 = 1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)
    r10, r11, r12 = 2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)
    r20, r21, r22 = 2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)
    tx, ty, tz = v
    # Inverse translation = -R^T * t.
    inv_tx = -(r00 * tx + r10 * ty + r20 * tz)
    inv_ty = -(r01 * tx + r11 * ty + r21 * tz)
    inv_tz = -(r02 * tx + r12 * ty + r22 * tz)
    return (
        (r00, r10, r20, inv_tx),
        (r01, r11, r21, inv_ty),
        (r02, r12, r22, inv_tz),
        (0.0, 0.0, 0.0, 1.0),
    )


@chunk(ChunkType.CompiledBones_Ivo, 0x900)
@chunk(ChunkType.CompiledBones_Ivo2, 0x900)
class ChunkCompiledBones900(ChunkCompiledBones):
    def read(self, br) -> None:
        super().read(br)
        self.num_bones = br.read_i32()

        # Per-bone records (controllerId, limbId, parentIndex, then
        # local + world quat/vec3 pairs).
        for i in range(self.num_bones):
            bone = CompiledBone()
            bone.controller_id = br.read_u32()
            bone.limb_id = br.read_u32()
            bone.parent_index = br.read_i32()
            rel_q = br.read_quat()
            rel_v = br.read_vec3()
            world_q = br.read_quat()
            world_v = br.read_vec3()
            bone.local_transform_matrix = _quat_vec3_to_mat34(rel_q, rel_v)
            bone.world_transform_matrix = _quat_vec3_to_mat34(world_q, world_v)
            bone.bind_pose_matrix = _invert_world_to_bind(world_q, world_v)
            # OffsetParent = i == 0 ? -1 : ParentIndex - i.
            bone.offset_parent = -1 if i == 0 else bone.parent_index - i
            self.bone_list.append(bone)

        names = _read_null_separated_strings(br, self.num_bones)
        for i, b in enumerate(self.bone_list):
            b.bone_name = names[i] if i < len(names) else ""
            if b.parent_index != -1 and 0 <= b.parent_index < len(self.bone_list):
                parent = self.bone_list[b.parent_index]
                b.parent_bone = parent
                b.parent_controller_index = b.parent_index
                parent.child_ids.append(i)
                parent.number_of_children += 1


@chunk(ChunkType.CompiledBones_Ivo, 0x901)
@chunk(ChunkType.CompiledBones_Ivo2, 0x901)
class ChunkCompiledBones901(ChunkCompiledBones):
    def read(self, br) -> None:
        super().read(br)
        self.num_bones = br.read_i32()
        string_table_size = br.read_i32()
        self.flags1 = br.read_i32()
        self.flags2 = br.read_i32()

        # First per-bone block: 14-byte header.
        for _ in range(self.num_bones):
            bone = CompiledBone()
            bone.controller_id = br.read_u32()
            bone.limb_id = br.read_u16()
            bone.number_of_children = br.read_u16()
            bone.parent_controller_index = br.read_i16()
            br.read_i16()  # unknown 0xFFFF
            br.read_i16()  # unknown 0xFFFF
            bone.object_node_index = br.read_i16()
            self.bone_list.append(bone)

        names = _read_null_separated_strings(
            br, self.num_bones, string_table_size
        )

        # Second per-bone block: relative + world quat / vec3, plus
        # parent wiring via ParentControllerIndex (matches v2.0.0
        # ChunkCompiledBones_901; v1.7.1 used OffsetParent which the
        # 0x901 reader never actually populates from disk).
        for i, bone in enumerate(self.bone_list):
            rel_q = br.read_quat()
            rel_v = br.read_vec3()
            world_q = br.read_quat()
            world_v = br.read_vec3()

            bone.local_transform_matrix = _quat_vec3_to_mat34(rel_q, rel_v)
            bone.world_transform_matrix = _quat_vec3_to_mat34(world_q, world_v)
            bone.bind_pose_matrix = _invert_world_to_bind(world_q, world_v)

            bone.bone_name = names[i] if i < len(names) else ""
            pci = bone.parent_controller_index
            if pci is not None and 0 <= pci < len(self.bone_list):
                parent = self.bone_list[pci]
                bone.parent_bone = parent
                parent.child_ids.append(i)
                parent.number_of_children += 1
