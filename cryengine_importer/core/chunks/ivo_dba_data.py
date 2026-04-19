"""ChunkIvoDBAData — Star Citizen #ivo DBA animation data.

Port of CgfConverter/CryEngineCore/Chunks/ChunkIvoDBAData.cs +
ChunkIvoDBAData_900.cs (v2.0.0).

Holds N back-to-back ``#dba`` animation blocks (each is essentially the
same shape as a single :class:`ChunkIvoCAF`). Per the v2 source: in
DBA the controller-entry headers are sequential and the keyframe data
is at the end accessed via per-controller offsets, so after each
block's headers we restore the stream pointer rather than skipping
over the keyframe payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...enums import ChunkType
from ...models.ivo_animation import (
    IvoAnimBlockHeader,
    IvoAnimControllerEntry,
    IvoAnimationBlock,
    read_position_keys,
    read_rotation_keys,
    read_time_keys,
)
from ..chunk_registry import Chunk, chunk

if TYPE_CHECKING:
    from ...io.binary_reader import BinaryReader


class ChunkIvoDBAData(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.total_data_size: int = 0
        self.animation_blocks: list[IvoAnimationBlock] = []


@chunk(ChunkType.IvoDBAData, 0x900)
class ChunkIvoDBAData900(ChunkIvoDBAData):
    def read(self, br: "BinaryReader") -> None:
        super().read(br)
        self.total_data_size = br.read_u32()
        data_end = br.tell() + self.total_data_size - 4

        while br.tell() < data_end:
            sig = br.read_bytes(4).decode("ascii", errors="replace")
            if sig != "#dba":
                # Either we walked past the last block or the data is
                # malformed; either way stop cleanly.
                break

            bone_count = br.read_u16()
            magic = br.read_u16()
            data_size = br.read_u32()
            header = IvoAnimBlockHeader(
                signature=sig,
                bone_count=bone_count,
                magic=magic,
                data_size=data_size,
            )

            bone_hashes = [br.read_u32() for _ in range(bone_count)]

            controllers: list[IvoAnimControllerEntry] = []
            controller_offsets: list[int] = []
            for _ in range(bone_count):
                controller_offsets.append(br.tell())
                controllers.append(
                    IvoAnimControllerEntry(
                        num_rot_keys=br.read_u16(),
                        rot_format_flags=br.read_u16(),
                        rot_time_offset=br.read_u32(),
                        rot_data_offset=br.read_u32(),
                        num_pos_keys=br.read_u16(),
                        pos_format_flags=br.read_u16(),
                        pos_time_offset=br.read_u32(),
                        pos_data_offset=br.read_u32(),
                    )
                )

            # The next #dba block starts here, immediately after the
            # controller-entry array — *not* after the keyframe payload.
            position_after_headers = br.tell()

            block = IvoAnimationBlock(
                header=header,
                bone_hashes=bone_hashes,
                controllers=controllers,
                controller_offsets=controller_offsets,
            )
            self._parse_block(br, block)
            self.animation_blocks.append(block)

            br.seek(position_after_headers)

    def _parse_block(
        self, br: "BinaryReader", block: IvoAnimationBlock
    ) -> None:
        for i, ctrl in enumerate(block.controllers):
            bone_hash = block.bone_hashes[i]
            ctrl_start = block.controller_offsets[i]

            if ctrl.has_rotation and ctrl.num_rot_keys > 0:
                if ctrl.rot_time_offset > 0:
                    br.seek(ctrl_start + ctrl.rot_time_offset)
                    times = read_time_keys(
                        br, ctrl.num_rot_keys, ctrl.rot_format_flags
                    )
                else:
                    times = [float(t) for t in range(ctrl.num_rot_keys)]
                block.rotation_times[bone_hash] = times

                br.seek(ctrl_start + ctrl.rot_data_offset)
                block.rotations[bone_hash] = read_rotation_keys(
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
                block.position_times[bone_hash] = times

                br.seek(ctrl_start + ctrl.pos_data_offset)
                positions = read_position_keys(
                    br, ctrl.num_pos_keys, ctrl.pos_format_flags
                )
                if positions:
                    block.positions[bone_hash] = positions
