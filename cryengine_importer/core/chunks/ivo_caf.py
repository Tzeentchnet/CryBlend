"""ChunkIvoCAF — Star Citizen #ivo CAF animation data.

Port of CgfConverter/CryEngineCore/Chunks/ChunkIvoCAF.cs +
ChunkIvoCAF_900.cs (v2.0.0).

Owns the single ``#caf`` block in an IVO ``.caf`` file: block header,
bone-hash array, per-bone controller entries, and the parsed rotation
/ position keyframe tables (keyed by bone-name CRC32 hash).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ...models.ivo_animation import (
    IvoAnimBlockHeader,
    IvoAnimControllerEntry,
    read_position_keys,
    read_rotation_keys,
    read_time_keys,
)
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


_VEC3 = tuple[float, float, float]
_QUAT = tuple[float, float, float, float]


class ChunkIvoCAF(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.block_header: IvoAnimBlockHeader = IvoAnimBlockHeader()
        self.bone_hashes: list[int] = []
        self.controllers: list[IvoAnimControllerEntry] = []
        self.controller_offsets: list[int] = []
        self.rotations: dict[int, list[_QUAT]] = {}
        self.positions: dict[int, list[_VEC3]] = {}
        self.rotation_times: dict[int, list[float]] = {}
        self.position_times: dict[int, list[float]] = {}


@chunk(ChunkType.IvoCAFData, 0x900)
class ChunkIvoCAF900(ChunkIvoCAF):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        block_start = br.tell()

        sig = br.read_bytes(4).decode("ascii", errors="replace")
        bone_count = br.read_u16()
        magic = br.read_u16()
        data_size = br.read_u32()
        self.block_header = IvoAnimBlockHeader(
            signature=sig,
            bone_count=bone_count,
            magic=magic,
            data_size=data_size,
        )

        # Sanity check: bail out cleanly on malformed data so the
        # surrounding model load still succeeds.
        if sig != "#caf":
            return

        self.bone_hashes = [br.read_u32() for _ in range(bone_count)]

        for _ in range(bone_count):
            offset = br.tell()
            self.controller_offsets.append(offset)
            ctrl = IvoAnimControllerEntry(
                num_rot_keys=br.read_u16(),
                rot_format_flags=br.read_u16(),
                rot_time_offset=br.read_u32(),
                rot_data_offset=br.read_u32(),
                num_pos_keys=br.read_u16(),
                pos_format_flags=br.read_u16(),
                pos_time_offset=br.read_u32(),
                pos_data_offset=br.read_u32(),
            )
            self.controllers.append(ctrl)

        self._parse_animation_data(br)

        # Seek to declared end of block so the chunk-table walker can
        # continue without surprises.
        br.seek(block_start + data_size)

    def _parse_animation_data(self, br: "BinaryReader") -> None:
        for i, ctrl in enumerate(self.controllers):
            bone_hash = self.bone_hashes[i]
            ctrl_start = self.controller_offsets[i]

            if ctrl.has_rotation and ctrl.num_rot_keys > 0:
                if ctrl.rot_time_offset > 0:
                    br.seek(ctrl_start + ctrl.rot_time_offset)
                    times = read_time_keys(
                        br, ctrl.num_rot_keys, ctrl.rot_format_flags
                    )
                else:
                    times = [float(t) for t in range(ctrl.num_rot_keys)]
                self.rotation_times[bone_hash] = times

                br.seek(ctrl_start + ctrl.rot_data_offset)
                self.rotations[bone_hash] = read_rotation_keys(
                    br, ctrl.num_rot_keys
                )

            if ctrl.has_position and ctrl.num_pos_keys > 0:
                if ctrl.pos_time_offset > 0:
                    br.seek(ctrl_start + ctrl.pos_time_offset)
                    times = read_time_keys(
                        br, ctrl.num_pos_keys, ctrl.pos_format_flags
                    )
                else:
                    times = [float(t) for t in range(ctrl.num_pos_keys)]
                self.position_times[bone_hash] = times

                br.seek(ctrl_start + ctrl.pos_data_offset)
                positions = read_position_keys(
                    br, ctrl.num_pos_keys, ctrl.pos_format_flags
                )
                if positions:
                    self.positions[bone_hash] = positions
