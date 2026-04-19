"""Phase 5 — Star Citizen #ivo chunk reader tests."""

from __future__ import annotations

import io
import struct

from cryengine_importer.core.chunk_registry import make_chunk
from cryengine_importer.core.chunks.binary_xml_data import ChunkBinaryXmlData3
from cryengine_importer.core.chunks.compiled_bones_ivo import (
    ChunkCompiledBones900,
    ChunkCompiledBones901,
)
from cryengine_importer.core.chunks.header import ChunkHeader900
from cryengine_importer.core.chunks.ivo_skin_mesh import (
    ChunkIvoSkinMesh900,
    IvoBoneMap,
)
from cryengine_importer.core.chunks.mesh_900 import ChunkMesh900
from cryengine_importer.core.chunks.mtl_name_900 import ChunkMtlName900
from cryengine_importer.core.chunks.node_mesh_combo import ChunkNodeMeshCombo900
from cryengine_importer.core.cryengine import CryEngine
from cryengine_importer.core.model import Model
from cryengine_importer.enums import (
    ChunkType,
    DatastreamType,
    FileVersion,
    IvoGeometryType,
    VertexFormat,
)
from cryengine_importer.io.binary_reader import BinaryReader
from cryengine_importer.io.pack_fs import IPackFileSystem


# ----------------------------------------------------- helpers ----------


def _drive_ivo(chunk_type: ChunkType, version: int, body: bytes):
    """Instantiate, load + read an IVO chunk against a synthetic body."""
    inst = make_chunk(chunk_type, version)
    hdr = ChunkHeader900()
    hdr.chunk_type = chunk_type
    hdr.version_raw = version
    hdr.id = 1
    hdr.offset = 0
    hdr.size = len(body)

    model = Model()
    model.file_version = FileVersion.x0900
    model.file_signature = "#ivo"

    inst.load(model, hdr)  # type: ignore[arg-type]
    br = BinaryReader(io.BytesIO(body))
    inst.read(br)
    return inst


def _fstring(value: str, length: int) -> bytes:
    raw = value.encode("ascii")
    return raw[:length].ljust(length, b"\x00")


# ----------------------------------------------------- MtlName_900 ------


def test_mtl_name_900_reads_fixed_length_name() -> None:
    body = _fstring("materials/aegs_avenger_body", 128)
    chunk = _drive_ivo(ChunkType.MtlNameIvo, 0x900, body)
    assert isinstance(chunk, ChunkMtlName900)
    assert chunk.name == "materials/aegs_avenger_body"
    assert chunk.num_children == 0


def test_mtl_name_900_routed_for_ivo320_alias() -> None:
    body = _fstring("foo/bar", 128)
    chunk = _drive_ivo(ChunkType.MtlNameIvo320, 0x900, body)
    assert isinstance(chunk, ChunkMtlName900)
    assert chunk.name == "foo/bar"


# ----------------------------------------------------- Mesh_900 ---------


def test_mesh_900_reads_counts_and_assigns_fixed_stream_ids() -> None:
    body = struct.pack(
        "<iiiII",
        0,            # flags2
        4,            # num_vertices
        6,            # num_indices
        1,            # num_vert_subsets
        0,            # 4 bytes pad
    ) + struct.pack("<3f", -1.0, -2.0, -3.0) + struct.pack("<3f", 4.0, 5.0, 6.0)
    chunk = _drive_ivo(ChunkType.MeshIvo, 0x900, body)
    assert isinstance(chunk, ChunkMesh900)
    assert chunk.num_vertices == 4
    assert chunk.num_indices == 6
    assert chunk.num_vert_subsets == 1
    assert chunk.min_bound == (-1.0, -2.0, -3.0)
    assert chunk.max_bound == (4.0, 5.0, 6.0)
    # Fixed IVO datastream IDs.
    assert chunk.id == 2
    assert chunk.indices_data == 4
    assert chunk.verts_uvs_data == 5
    assert chunk.normals_data == 6
    assert chunk.tangents_data == 7
    assert chunk.bone_map_data == 8
    assert chunk.colors_data == 9


# ----------------------------------------------------- BinaryXmlData_3 --


def test_binary_xml_data_3_parses_inline_xml() -> None:
    xml = b"<Material Name='foo'><Layer Type='base'/></Material>"
    chunk = _drive_ivo(ChunkType.BinaryXmlDataSC, 0x3, xml)
    assert isinstance(chunk, ChunkBinaryXmlData3)
    assert chunk.data is not None
    assert chunk.data.tag == "Material"
    assert chunk.data.get("Name") == "foo"
    assert chunk.data[0].tag == "Layer"


# ----------------------------------------------------- CompiledBones_900


def _bone_900_record(controller_id: int, parent_index: int) -> bytes:
    # u32 controller_id, u32 limb_id, i32 parent_index,
    # quat (4f), vec3 (3f), quat (4f), vec3 (3f) — identity / zero
    return (
        struct.pack("<IIi", controller_id, 0, parent_index)
        + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        + struct.pack("<3f", 0.0, 0.0, 0.0)
        + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        + struct.pack("<3f", 0.0, 0.0, 0.0)
    )


def test_compiled_bones_900_reads_bones_and_wires_parents() -> None:
    body = struct.pack("<i", 3)  # num_bones
    body += _bone_900_record(0xAAAA, -1)  # root
    body += _bone_900_record(0xBBBB, 0)  # child of root
    body += _bone_900_record(0xCCCC, 1)  # child of bone[1]
    body += b"root\x00child1\x00child2\x00"

    chunk = _drive_ivo(ChunkType.CompiledBones_Ivo, 0x900, body)
    assert isinstance(chunk, ChunkCompiledBones900)
    assert chunk.num_bones == 3
    assert [b.bone_name for b in chunk.bone_list] == ["root", "child1", "child2"]
    assert [b.controller_id for b in chunk.bone_list] == [0xAAAA, 0xBBBB, 0xCCCC]
    # Parent wiring.
    assert chunk.bone_list[0].parent_bone is None
    assert chunk.bone_list[1].parent_bone is chunk.bone_list[0]
    assert chunk.bone_list[2].parent_bone is chunk.bone_list[1]
    assert chunk.bone_list[0].child_ids == [1]
    assert chunk.bone_list[1].child_ids == [2]
    # OffsetParent computed per C# (i==0 -> -1, else parent_index - i).
    assert chunk.bone_list[0].offset_parent == -1
    assert chunk.bone_list[1].offset_parent == -1
    assert chunk.bone_list[2].offset_parent == -1


def test_compiled_bones_900_routed_for_ivo2_alias() -> None:
    body = struct.pack("<i", 1) + _bone_900_record(1, -1) + b"only\x00"
    chunk = _drive_ivo(ChunkType.CompiledBones_Ivo2, 0x900, body)
    assert isinstance(chunk, ChunkCompiledBones900)
    assert chunk.bone_list[0].bone_name == "only"


# ----------------------------------------------------- CompiledBones_901


def _bone_901_header(controller_id: int) -> bytes:
    # u32 controller_id, u16 limb_id, u16 num_children,
    # i16 parent_controller_index, i16 unk, i16 unk2, i16 object_node_index
    return struct.pack(
        "<IHHhhhh", controller_id, 0, 0, -1, -1, -1, -1
    )


def _bone_901_transforms() -> bytes:
    # quat + vec3 (relative), quat + vec3 (world)
    return (
        struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        + struct.pack("<3f", 0.0, 0.0, 0.0)
        + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        + struct.pack("<3f", 0.0, 0.0, 0.0)
    )


def test_compiled_bones_901_reads_split_layout() -> None:
    body = struct.pack("<i", 2)  # num_bones
    body += struct.pack("<i", 11)  # string table size ("root\x00child\x00" = 11 bytes)
    body += struct.pack("<ii", 0, 0)  # flags1, flags2
    body += _bone_901_header(0xAAAA)
    body += _bone_901_header(0xBBBB)
    body += b"root\x00child\x00"
    body += _bone_901_transforms()
    body += _bone_901_transforms()

    chunk = _drive_ivo(ChunkType.CompiledBones_Ivo, 0x901, body)
    assert isinstance(chunk, ChunkCompiledBones901)
    assert chunk.num_bones == 2
    assert [b.bone_name for b in chunk.bone_list] == ["root", "child"]
    assert chunk.bone_list[0].controller_id == 0xAAAA
    # Bind pose for an identity quat + zero translation should be I.
    bp = chunk.bone_list[0].bind_pose_matrix
    assert bp[0][0] == 1.0 and bp[1][1] == 1.0 and bp[2][2] == 1.0
    assert bp[3] == (0.0, 0.0, 0.0, 1.0)


# ----------------------------------------------------- NodeMeshCombo_900


def _identity_3x4() -> bytes:
    return struct.pack(
        "<12f",
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
    )


def _combo_node_record(
    *, node_id: int, parent_index: int, geom_type: int, mesh_chunk_id: int
) -> bytes:
    return (
        _identity_3x4()  # world_to_bone
        + _identity_3x4()  # bone_to_world
        + struct.pack("<3f", 1.0, 1.0, 1.0)  # scale
        + struct.pack("<II", node_id, 0)  # id, unknown2
        + struct.pack("<HH", parent_index & 0xFFFF, geom_type & 0xFFFF)
        + struct.pack("<3f", -1.0, -1.0, -1.0)
        + struct.pack("<3f", 1.0, 1.0, 1.0)
        + struct.pack("<4I", 0, 0, 0, 0)
        + struct.pack("<I", 0)  # number_of_vertices
        + struct.pack("<HH", 0, mesh_chunk_id)
        + b"\x00" * 40  # 40 unknown trailing bytes
    )


def test_node_mesh_combo_900_reads_two_node_tree() -> None:
    body = struct.pack(
        "<iiiiiiii",
        0,    # zero_pad
        2,    # number_of_nodes
        1,    # number_of_meshes
        0,    # unknown2 (count of unknown_indices)
        1,    # number_of_mesh_subsets (count of material_indices)
        10,   # string_table_size ("root\x00geom\x00" = 10 bytes)
        0,    # unknown1
        0,    # unknown3
    )
    body += b"\x00" * 32  # SC 4.5+ post-header pad
    body += _combo_node_record(
        node_id=10, parent_index=0xFFFF, geom_type=int(IvoGeometryType.Helper2),
        mesh_chunk_id=0,
    )
    body += _combo_node_record(
        node_id=11, parent_index=0, geom_type=int(IvoGeometryType.Geometry),
        mesh_chunk_id=2,
    )
    # 0 unknown_indices, 1 material_index
    body += struct.pack("<H", 7)
    body += b"root\x00geom\x00"

    chunk = _drive_ivo(ChunkType.NodeMeshCombo, 0x900, body)
    assert isinstance(chunk, ChunkNodeMeshCombo900)
    assert chunk.number_of_nodes == 2
    assert len(chunk.node_mesh_combos) == 2
    assert chunk.node_mesh_combos[0].parent_index == 0xFFFF
    assert chunk.node_mesh_combos[0].geometry_type == IvoGeometryType.Helper2
    assert chunk.node_mesh_combos[1].geometry_type == IvoGeometryType.Geometry
    assert chunk.node_mesh_combos[1].mesh_chunk_id == 2
    assert chunk.material_indices == [7]
    assert chunk.node_names == ["root", "geom"]


# ----------------------------------------------------- IvoSkinMesh_900 --


def _ivo_mesh_details(num_verts: int, num_indices: int, num_subsets: int) -> bytes:
    return (
        struct.pack("<IIIIi", 4, num_verts, num_indices, num_subsets, 0)
        + struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack("<3f", 1.0, 1.0, 1.0)
        + struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack("<3f", 1.0, 1.0, 1.0)
        + struct.pack("<I", int(VertexFormat.eVF_P3F_C4B_T2F))
    )


def _ivo_subset(mat_id: int, num_indices: int, num_verts: int) -> bytes:
    return (
        struct.pack("<HH", mat_id, 0)
        + struct.pack("<i", 0)              # first_index
        + struct.pack("<i", num_indices)
        + struct.pack("<i", 0)              # first_vertex
        + struct.pack("<i", 0)              # unknown
        + struct.pack("<i", num_verts)
        + struct.pack("<f", 1.0)            # radius
        + struct.pack("<3f", 0.0, 0.0, 0.0) # center
        + struct.pack("<ii", 0, 0)
    )


def test_ivo_skin_mesh_900_reads_indices_stream() -> None:
    n_verts = 4
    n_indices = 6
    body = b"\x00" * 4  # flags
    body += _ivo_mesh_details(n_verts, n_indices, 1)
    body += b"\x00" * 92
    body += _ivo_subset(mat_id=3, num_indices=n_indices, num_verts=n_verts)

    # Indices stream: u32 type, u32 bpe, then n_indices u16s, then 8-aligned pad.
    payload = struct.pack("<II", int(DatastreamType.IVOINDICES), 2)
    payload += struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    body += payload
    # Pad to next 8-byte boundary from the start of the body (so the
    # in-stream cursor is 8-aligned after this point).
    pad = (-len(body)) & 7
    body += b"\x00" * pad

    chunk = _drive_ivo(ChunkType.IvoSkin, 0x900, body)
    assert isinstance(chunk, ChunkIvoSkinMesh900)
    assert chunk.mesh_details.number_of_vertices == n_verts
    assert chunk.mesh_details.number_of_indices == n_indices
    assert chunk.mesh_details.vertex_format == VertexFormat.eVF_P3F_C4B_T2F
    assert len(chunk.mesh_subsets) == 1
    assert chunk.mesh_subsets[0].mat_id == 3
    assert chunk.mesh_subsets[0].num_indices == n_indices
    assert chunk.indices == [0, 1, 2, 0, 2, 3]
    assert chunk.indices_bpe == 2


def test_ivo_skin_mesh_900_reads_bone_map_8_influences() -> None:
    n_verts = 1
    body = b"\x00" * 4
    body += _ivo_mesh_details(n_verts, 0, 0)
    body += b"\x00" * 92

    # 24-bpe bone map: 8 ushort indices + 8 ubyte weights.
    body += struct.pack("<II", int(DatastreamType.IVOBONEMAP32), 24)
    body += struct.pack("<8H", 1, 2, 3, 4, 5, 6, 7, 8)
    body += struct.pack("<8B", 255, 0, 128, 0, 0, 0, 0, 0)

    chunk = _drive_ivo(ChunkType.IvoSkin, 0x900, body)
    assert isinstance(chunk, ChunkIvoSkinMesh900)
    assert len(chunk.bone_mappings) == 1
    bm: IvoBoneMap = chunk.bone_mappings[0]
    assert bm.bone_index == [1, 2, 3, 4, 5, 6, 7, 8]
    assert bm.weight[0] == 1.0
    assert bm.weight[2] == 128 / 255.0


# ----------------------------------------------------- CryEngine wiring -


class _DictPackFs(IPackFileSystem):
    """Trivial in-memory pack FS for end-to-end IVO file tests."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = {k.lower(): v for k, v in files.items()}

    def exists(self, path: str) -> bool:
        return path.lower() in self._files

    def open(self, path: str):
        return io.BytesIO(self._files[path.lower()])

    def read_all_bytes(self, path: str) -> bytes:
        return self._files[path.lower()]

    def glob(self, pattern: str):
        # Tests don't exercise globbing — return matches by suffix only.
        for f in self._files:
            if f.endswith(pattern.lstrip("*").lower()):
                yield f


def _build_ivo_file(chunks: list[tuple[int, int, bytes]]) -> bytes:
    """Assemble a minimal #ivo container around (chunk_type, version, body)
    triples. Returns the file bytes."""
    # Layout: 16-byte header (signature + version + count + chunk-table-offset),
    # then bodies, then the chunk table at the tail.
    header_len = 16
    header_size_per_entry = 20  # ChunkHeader_900: type(4) + ver(4) + offset(8) + 4 trailing? actually 20.

    # Actually ChunkHeader_900 reads: u32 type + u32 ver + u64 offset = 16 bytes.
    # The file header counts that. But the loader uses entry size derived
    # from struct reads, not a constant — so we just have to write 16 bytes
    # per entry.

    bodies = b""
    offsets: list[int] = []
    for _ct, _ver, body in chunks:
        offsets.append(header_len + len(bodies))
        bodies += body

    table = b""
    for (ct, ver, _body), off in zip(chunks, offsets):
        table += struct.pack("<II", ct, ver) + struct.pack("<Q", off)

    file_header = (
        b"#ivo"
        + struct.pack("<I", 0x900)
        + struct.pack("<I", len(chunks))
        + struct.pack("<i", header_len + len(bodies))
    )
    return file_header + bodies + table


def test_cryengine_loads_ivo_skin_file_with_dummy_root_node() -> None:
    """Skin / chr IVO file: no NodeMeshCombo → single root node bound
    to the IvoSkinMesh from the companion .skinm."""
    # `.skin` (input): just declares it's an IVO file with a placeholder
    # binary-xml chunk so the file isn't empty.
    skin_bytes = _build_ivo_file([
        (int(ChunkType.BinaryXmlDataSC), 0x3, b"<Root/>"),
    ])
    # `.skinm` (companion): the IvoSkinMesh.
    skin_mesh_body = b"\x00" * 4
    skin_mesh_body += _ivo_mesh_details(3, 3, 1)
    skin_mesh_body += b"\x00" * 92
    skin_mesh_body += _ivo_subset(mat_id=0, num_indices=3, num_verts=3)
    skin_mesh_body += struct.pack("<II", int(DatastreamType.IVOINDICES), 2)
    skin_mesh_body += struct.pack("<3H", 0, 1, 2)
    pad = (-len(skin_mesh_body)) & 7
    skin_mesh_body += b"\x00" * pad
    skinm_bytes = _build_ivo_file([
        (int(ChunkType.IvoSkin), 0x900, skin_mesh_body),
    ])

    fs = _DictPackFs({
        "Objects/test.skin": skin_bytes,
        "Objects/test.skinm": skinm_bytes,
    })
    cry = CryEngine("Objects/test.skin", fs)
    cry.process()

    assert cry.is_ivo
    assert cry.root_node is not None
    assert cry.root_node.name == "test"
    # The root node is bound to the IvoSkinMesh from the companion.
    assert isinstance(cry.root_node.mesh_data, ChunkIvoSkinMesh900)
    assert len(cry.nodes) == 1


def test_cryengine_loads_ivo_cgf_with_node_mesh_combo() -> None:
    """CGF IVO file: NodeMeshCombo drives a 2-node tree."""
    # `.cgf` (input): NodeMeshCombo + material chunk.
    combo_body = struct.pack(
        "<iiiiiiii", 0, 2, 1, 0, 1, 10, 0, 0
    )
    combo_body += b"\x00" * 32  # SC 4.5+ post-header pad
    combo_body += _combo_node_record(
        node_id=10, parent_index=0xFFFF,
        geom_type=int(IvoGeometryType.Helper2), mesh_chunk_id=0,
    )
    combo_body += _combo_node_record(
        node_id=11, parent_index=0,
        geom_type=int(IvoGeometryType.Geometry), mesh_chunk_id=2,
    )
    combo_body += struct.pack("<H", 0)  # 1 material index
    combo_body += b"root\x00mesh\x00"

    cgf_bytes = _build_ivo_file([
        (int(ChunkType.NodeMeshCombo), 0x900, combo_body),
        (int(ChunkType.MtlNameIvo), 0x900, _fstring("test_material", 128)),
    ])

    skin_mesh_body = b"\x00" * 4
    skin_mesh_body += _ivo_mesh_details(3, 3, 1)
    skin_mesh_body += b"\x00" * 92
    skin_mesh_body += _ivo_subset(mat_id=0, num_indices=3, num_verts=3)
    skin_mesh_body += struct.pack("<II", int(DatastreamType.IVOINDICES), 2)
    skin_mesh_body += struct.pack("<3H", 0, 1, 2)
    pad = (-len(skin_mesh_body)) & 7
    skin_mesh_body += b"\x00" * pad
    cgam_bytes = _build_ivo_file([
        (int(ChunkType.IvoSkin), 0x900, skin_mesh_body),
    ])

    fs = _DictPackFs({
        "Objects/box.cgf": cgf_bytes,
        "Objects/box.cgfm": cgam_bytes,
    })
    cry = CryEngine("Objects/box.cgf", fs)
    cry.process()

    assert cry.is_ivo
    assert len(cry.nodes) == 2
    # Root is the helper; child is the geometry node.
    root = cry.root_node
    assert root is not None
    assert root.name == "root"
    assert root.children and root.children[0].name == "mesh"
    geom = root.children[0]
    assert isinstance(geom.mesh_data, ChunkIvoSkinMesh900)
    assert geom.material_id == 0  # only one material index in the table
