"""ChunkIvoSkinMesh_900 — IVO skin mesh payload.

Port of CgfConverter/CryEngineCore/Chunks/ChunkIvoSkinMesh_900.cs.

Layout::

    u32 flags                      (skipped)
    IvoGeometryMeshDetails details (44 bytes)
    92 bytes of unknown / pad
    IvoMeshSubset[NumberOfSubmeshes]
    while not EOF:
        u32 datastreamType
        u32 bytesPerElement
        payload aligned to 8 bytes

Each datastream type uses its own decoder; the supported variants
match the C# reference:

- IVOINDICES — u16 / u32 indices
- IVOVERTSUVS / IVOVERTSUVS2 — packed pos + colour + uv (16 / 20 bpe)
- IVONORMALS / IVONORMALS2 — CryHalf2 (4 bpe) or float3 (12 bpe)
- IVOTANGENTS — snorm-quat tangents (8 bpe) or tangent + bitangent
  pair (16 bpe)
- IVOQTANGENTS — snorm-quat (8 bpe) or float-quat (16 bpe)
- IVOBONEMAP / IVOBONEMAP32 — 4-influence (8 / 12 bpe) or 8-influence
  (24 bpe)
- IVOCOLORS2 — IRGBA (4 bpe)
- IVOUNKNOWN — payload skipped

Registered against ``IvoSkin`` (0xB875B2D9) and ``IvoSkin2``
(0xB8757777), matching the C# Chunk.New routing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...enums import ChunkType, DatastreamType
from ...models.ivo import IvoGeometryMeshDetails, IvoMeshSubset
from ..chunk_registry import Chunk, chunk
from .data_stream import VertUV


@dataclass
class IvoBoneMap:
    """Per-vertex bone influences. Variable count (4 or 8)."""

    bone_index: list[int]
    weight: list[float]


class ChunkIvoSkinMesh(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.mesh_details: IvoGeometryMeshDetails = IvoGeometryMeshDetails()
        self.mesh_subsets: list[IvoMeshSubset] = []
        # Datastream payloads — populated as encountered in the body.
        self.indices: list[int] = []
        self.indices_bpe: int = 0
        self.verts_uvs: list[VertUV] = []
        self.verts_uvs_bpe: int = 0
        self.normals: list[tuple[float, float, float]] = []
        self.normals_bpe: int = 0
        self.tangents: list[tuple[float, float, float, float]] = []
        self.bitangents: list[tuple[float, float, float, float]] = []
        self.tangents_bpe: int = 0
        self.qtangents: list[tuple[float, float, float, float]] = []
        self.colors: list[tuple[float, float, float, float]] = []
        self.colors_bpe: int = 0
        self.bone_mappings: list[IvoBoneMap] = []
        self.bone_map_bpe: int = 0


def _read_indices(br, n: int, bpe: int) -> list[int]:
    if bpe == 2:
        return [br.read_u16() for _ in range(n)]
    if bpe == 4:
        return [br.read_u32() for _ in range(n)]
    raise ValueError(f"Unsupported IVO indices bpe {bpe}")


def _read_verts_uvs(br, n: int, bpe: int) -> list[VertUV]:
    out: list[VertUV] = []
    if bpe == 16:
        for _ in range(n):
            vertex = br.read_vec3_snorm16()
            skipped = br.read_bytes(2)
            color = br.read_irgba()
            uv = br.read_uv_half()
            out.append(VertUV(vertex=vertex, color=color, uv=uv, skipped=skipped))
    elif bpe == 20:
        for _ in range(n):
            vertex = br.read_vec3()
            color = br.read_irgba()
            uv = br.read_uv_half()
            out.append(VertUV(vertex=vertex, color=color, uv=uv))
    else:
        raise ValueError(f"Unsupported IVO verts/uvs bpe {bpe}")
    return out


def _read_normals(br, n: int, bpe: int) -> list[tuple[float, float, float]]:
    if bpe == 4:
        # CryHalf2 + implicit Z=0 (matches C# reference).
        return [
            (br.read_cry_half(), br.read_cry_half(), 0.0) for _ in range(n)
        ]
    if bpe == 12:
        return [br.read_vec3() for _ in range(n)]
    raise ValueError(f"Unsupported IVO normals bpe {bpe}")


def _read_tangents(
    br, n: int, bpe: int
) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float, float, float]]]:
    tan: list[tuple[float, float, float, float]] = []
    bitan: list[tuple[float, float, float, float]] = []
    if bpe == 8:
        for _ in range(n):
            tan.append(br.read_quat_snorm16())
    elif bpe == 16:
        for _ in range(n):
            tan.append(br.read_quat_snorm16())
            bitan.append(br.read_quat_snorm16())
    else:
        raise ValueError(f"Unsupported IVO tangents bpe {bpe}")
    return tan, bitan


def _read_qtangents(
    br, n: int, bpe: int
) -> list[tuple[float, float, float, float]]:
    if bpe == 8:
        return [br.read_quat_snorm16() for _ in range(n)]
    if bpe == 16:
        return [br.read_quat() for _ in range(n)]
    raise ValueError(f"Unsupported IVO qtangents bpe {bpe}")


def _read_bone_maps(br, n: int, bpe: int) -> list[IvoBoneMap]:
    out: list[IvoBoneMap] = []
    if bpe == 12:  # 4 ushort + 4 ubyte
        for _ in range(n):
            idx = [br.read_u16() for _ in range(4)]
            wts = [br.read_u8() / 255.0 for _ in range(4)]
            out.append(IvoBoneMap(bone_index=idx, weight=wts))
    elif bpe == 24:  # 8 ushort + 8 ubyte
        for _ in range(n):
            idx = [br.read_u16() for _ in range(8)]
            wts = [br.read_u8() / 255.0 for _ in range(8)]
            out.append(IvoBoneMap(bone_index=idx, weight=wts))
    elif bpe == 8:  # 4 ubyte + 4 ubyte (older / rare)
        for _ in range(n):
            idx = [br.read_u8() for _ in range(4)]
            wts = [br.read_u8() / 255.0 for _ in range(4)]
            out.append(IvoBoneMap(bone_index=idx, weight=wts))
    else:
        raise ValueError(f"Unsupported IVO bonemap bpe {bpe}")
    return out


def _read_colors(br, n: int, bpe: int) -> list[tuple[float, float, float, float]]:
    if bpe == 4:
        return [br.read_irgba() for _ in range(n)]
    # Unknown size — skip the payload.
    br.skip(bpe * n)
    return []


def _safe_dst(value: int) -> DatastreamType | int:
    try:
        return DatastreamType(value)
    except ValueError:
        return value


@chunk(ChunkType.IvoSkin, 0x900)
@chunk(ChunkType.IvoSkin2, 0x900)
class ChunkIvoSkinMesh900(ChunkIvoSkinMesh):
    def read(self, br) -> None:
        super().read(br)
        br.skip(4)  # flags
        self.mesh_details = br.read_ivo_mesh_details()
        br.skip(92)  # 92 bytes of pad / unknown

        for _ in range(self.mesh_details.number_of_submeshes):
            self.mesh_subsets.append(br.read_ivo_mesh_subset())

        # End of the chunk body lives at offset + size; for IVO files
        # ``size`` is computed by the model loader from the next entry's
        # offset (0x900 chunk headers don't carry per-entry sizes).
        end = self.offset + self.size if self.size else br.length
        n_verts = self.mesh_details.number_of_vertices
        n_indices = self.mesh_details.number_of_indices
        has_indices = False

        while br.tell() < end:
            try:
                ds_raw = br.read_u32()
            except EOFError:
                break
            ds = _safe_dst(ds_raw)
            try:
                bpe = br.read_u32()
            except EOFError:
                break

            if ds == DatastreamType.IVOINDICES:
                if has_indices:
                    return
                has_indices = True
                self.indices_bpe = bpe
                self.indices = _read_indices(br, n_indices, bpe)
                br.align_to(8)
            elif ds in (DatastreamType.IVOVERTSUVS, DatastreamType.IVOVERTSUVS2):
                self.verts_uvs_bpe = bpe
                self.verts_uvs = _read_verts_uvs(br, n_verts, bpe)
                br.align_to(8)
            elif ds in (DatastreamType.IVONORMALS, DatastreamType.IVONORMALS2):
                self.normals_bpe = bpe
                self.normals = _read_normals(br, n_verts, bpe)
                br.align_to(8)
            elif ds == DatastreamType.IVOTANGENTS:
                self.tangents_bpe = bpe
                self.tangents, self.bitangents = _read_tangents(br, n_verts, bpe)
                br.align_to(8)
            elif ds == DatastreamType.IVOQTANGENTS:
                self.qtangents = _read_qtangents(br, n_verts, bpe)
                br.align_to(8)
            elif ds in (DatastreamType.IVOBONEMAP, DatastreamType.IVOBONEMAP32):
                self.bone_map_bpe = bpe
                self.bone_mappings = _read_bone_maps(br, n_verts, bpe)
                br.align_to(8)
            elif ds == DatastreamType.IVOCOLORS2:
                self.colors_bpe = bpe
                self.colors = _read_colors(br, n_verts, bpe)
                br.align_to(8)
            elif ds == DatastreamType.IVOUNKNOWN:
                br.skip(bpe * n_verts)
                br.align_to(8)
            else:
                # Unknown stream — match C#: nudge forward by 4 and try
                # again on the next iteration.
                br.skip(4)
