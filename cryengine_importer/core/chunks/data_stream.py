"""ChunkDataStream.

Port of CgfConverter/CryEngineCore/Chunks/ChunkDataStream*.cs.
Implements 0x800 and 0x801 for the common datastream types
(VERTICES / INDICES / NORMALS / UVS / TANGENTS / COLORS / VERTSUVS /
BONEMAP / QTANGENTS).

Unlike the C# port, parsed payloads are returned as plain Python
sequences attached to ``self.data``; the type is implied by
``data_stream_type``. Higher-level code (the Blender bridge) consumes
them directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...enums import ChunkType, DatastreamType
from ..chunk_registry import Chunk, chunk


@dataclass
class BoneMap:
    bone_index: tuple[int, int, int, int]
    weight: tuple[float, float, float, float]


@dataclass
class VertUV:
    vertex: tuple[float, float, float]
    color: tuple[float, float, float, float]
    uv: tuple[float, float]
    skipped: bytes | None = None


class ChunkDataStream(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.flags2: int = 0
        self.data_stream_type: DatastreamType | int = DatastreamType.VERTICES
        self.num_elements: int = 0
        self.bytes_per_element: int = 0
        self.star_citizen_flag: int = 0
        self.data: list = []


def _safe_dst(value: int) -> DatastreamType | int:
    try:
        return DatastreamType(value)
    except ValueError:
        return value


def _read_vert_uv(br, bpe: int, is_sc: bool) -> VertUV:
    if bpe == 16:
        if is_sc:
            vertex = br.read_vec3_dymek_half()
        else:
            vertex = br.read_vec3_half()
        skipped = br.read_bytes(2)
        color = br.read_irgba()
        uv = br.read_uv_half()
        return VertUV(vertex=vertex, color=color, uv=uv, skipped=skipped)
    if bpe == 20:
        vertex = br.read_vec3()
        color = br.read_irgba()
        uv = br.read_uv_half()
        return VertUV(vertex=vertex, color=color, uv=uv)
    raise ValueError(f"Unsupported bytesPerElement {bpe} for VertUV")


def _read_bone_map(br, bpe: int) -> BoneMap:
    if bpe == 8:
        idx = (br.read_u8(), br.read_u8(), br.read_u8(), br.read_u8())
        wts = tuple(br.read_u8() / 255.0 for _ in range(4))
    elif bpe == 12:
        idx = (br.read_u16(), br.read_u16(), br.read_u16(), br.read_u16())
        wts = tuple(br.read_u8() / 255.0 for _ in range(4))
    else:
        raise ValueError(f"Unsupported bytesPerElement {bpe} for BoneMap")
    return BoneMap(bone_index=idx, weight=wts)  # type: ignore[arg-type]


def _read_payload(self: ChunkDataStream, br) -> None:
    dst = self.data_stream_type
    n = self.num_elements
    bpe = self.bytes_per_element
    is_sc = self.star_citizen_flag == 257

    if dst == DatastreamType.VERTICES:
        if bpe == 12:
            self.data = [br.read_vec3() for _ in range(n)]
        elif bpe == 8:
            out: list[tuple[float, float, float]] = []
            for _ in range(n):
                out.append(br.read_vec3_half())
                br.read_u16()
            self.data = out
        elif bpe == 16:
            out2: list[tuple[float, float, float]] = []
            for _ in range(n):
                out2.append(br.read_vec3())
                br.skip(4)
            self.data = out2
        elif bpe == 4:
            br.skip(4 * n)
            self.data = []
        else:
            raise ValueError(f"Unsupported bpe {bpe} for VERTICES")

    elif dst == DatastreamType.INDICES:
        if bpe == 2:
            self.data = [br.read_u16() for _ in range(n)]
        elif bpe == 4:
            self.data = [br.read_u32() for _ in range(n)]
        else:
            raise ValueError(f"Unsupported bpe {bpe} for INDICES")

    elif dst == DatastreamType.NORMALS:
        if bpe == 4:
            # Reference C# leaves Z=0 here ("TODO this is wrong"). Match.
            self.data = [
                (br.read_cry_half(), br.read_cry_half(), 0.0) for _ in range(n)
            ]
        elif bpe == 12:
            self.data = [br.read_vec3() for _ in range(n)]
        else:
            raise ValueError(f"Unsupported bpe {bpe} for NORMALS")

    elif dst == DatastreamType.UVS:
        self.data = [br.read_uv() for _ in range(n)]

    elif dst == DatastreamType.TANGENTS:
        # Tangents come as snorm16 quaternions; bpe 8 = tangent only,
        # bpe 16 = tangent + bitangent (we keep only tangent).
        out_q: list[tuple[float, float, float, float]] = []
        if bpe == 0x10:
            # Faithful to C#: tangent + bitangent quats; only the
            # second (bitangent) is retained.
            for _ in range(n):
                _read_quat_snorm(br)
                out_q.append(_read_quat_snorm(br))
        elif bpe == 0x08:
            for _ in range(n):
                out_q.append(_read_quat_snorm(br))
        else:
            raise ValueError(f"Unsupported bpe {bpe} for TANGENTS")
        self.data = out_q

    elif dst == DatastreamType.COLORS:
        if bpe == 3:
            self.data = [br.read_irgba(alpha=1.0) for _ in range(n)]
        elif bpe == 4:
            self.data = [br.read_irgba() for _ in range(n)]
        else:
            raise ValueError(f"Unsupported bpe {bpe} for COLORS")

    elif dst == DatastreamType.VERTSUVS:
        self.data = [_read_vert_uv(br, bpe, is_sc) for _ in range(n)]

    elif dst == DatastreamType.BONEMAP:
        self.data = [_read_bone_map(br, bpe) for _ in range(n)]

    elif dst == DatastreamType.QTANGENTS:
        self.data = [_read_quat_snorm(br) for _ in range(n)]

    else:
        # Unknown stream type — leave data empty; skip_to_end advances.
        self.data = []


def _read_quat_snorm(br) -> tuple[float, float, float, float]:
    return (
        br.read_i16() / 32767.0,
        br.read_i16() / 32767.0,
        br.read_i16() / 32767.0,
        br.read_i16() / 32767.0,
    )


@chunk(ChunkType.DataStream, 0x800)
class ChunkDataStream800(ChunkDataStream):
    def read(self, br) -> None:
        super().read(br)
        self.flags2 = br.read_u32()
        self.data_stream_type = _safe_dst(br.read_u32())
        self.num_elements = br.read_u32()
        self.bytes_per_element = br.read_u16()
        self.star_citizen_flag = br.read_u16()
        br.skip(8)  # reserved1 + reserved2
        _read_payload(self, br)


@chunk(ChunkType.DataStream, 0x801)
class ChunkDataStream801(ChunkDataStream):
    def read(self, br) -> None:
        super().read(br)
        self.flags2 = br.read_u32()
        self.data_stream_type = _safe_dst(br.read_u32())
        br.skip(4)  # data stream index, unused
        self.num_elements = br.read_u32()
        self.bytes_per_element = br.read_u16()
        self.star_citizen_flag = br.read_i16()
        br.skip(8)
        _read_payload(self, br)
