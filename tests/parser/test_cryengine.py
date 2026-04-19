"""Phase 1.5 — CryEngine aggregator tests.

The aggregator's responsibilities are independent of the binary parser,
so these tests build `Model` objects manually (`chunk_map` populated
with chunk instances) and exercise the hierarchy / material discovery
logic against them.
"""

from __future__ import annotations

import pytest

from cryengine_importer.core import CryEngine, Model, UnsupportedFileError
from cryengine_importer.core.chunks.helper import ChunkHelper744
from cryengine_importer.core.chunks.mesh import ChunkMesh800
from cryengine_importer.core.chunks.mtl_name import ChunkMtlName744
from cryengine_importer.core.chunks.node import ChunkNode823
from cryengine_importer.enums import HelperType, MtlNameType
from cryengine_importer.io.pack_fs import InMemoryFileSystem


# --------------------------------------------------------------- helpers


def _make_node(node_id: int, name: str, object_id: int, parent_id: int) -> ChunkNode823:
    n = ChunkNode823()
    n.id = node_id
    n.name = name
    n.object_node_id = object_id
    n.parent_node_id = parent_id
    return n


def _make_helper(chunk_id: int, helper_type: HelperType = HelperType.DUMMY) -> ChunkHelper744:
    h = ChunkHelper744()
    h.id = chunk_id
    h.helper_type = helper_type
    return h


def _make_mesh(chunk_id: int, num_vertices: int = 0) -> ChunkMesh800:
    m = ChunkMesh800()
    m.id = chunk_id
    m.num_vertices = num_vertices
    return m


def _make_mtl(chunk_id: int, name: str, mat_type: MtlNameType) -> ChunkMtlName744:
    c = ChunkMtlName744()
    c.id = chunk_id
    c.name = name
    c.mat_type = mat_type
    return c


def _model_from_chunks(name: str, chunks: list, signature: str = "CryTek") -> Model:
    m = Model()
    m.file_name = name
    m.file_signature = signature
    m.chunk_map = {c.id: c for c in chunks}
    return m


# --------------------------------------------------------------- tests


def test_supports_file_extensions() -> None:
    assert CryEngine.supports_file("foo.cgf")
    assert CryEngine.supports_file("dir/Foo.CHR")
    assert CryEngine.supports_file("a.skin")
    assert not CryEngine.supports_file("foo.png")
    assert not CryEngine.supports_file("foo")


def test_process_rejects_unsupported_extension() -> None:
    fs = InMemoryFileSystem({"foo.png": b""})
    eng = CryEngine("foo.png", fs)
    with pytest.raises(UnsupportedFileError):
        eng.process()


def test_name_strips_extension_and_lowercases() -> None:
    fs = InMemoryFileSystem()
    eng = CryEngine("Models/Hero.CGF", fs)
    assert eng.name == "hero"


def test_build_nodes_links_parent_and_children_and_picks_root() -> None:
    """Single-model asset with one helper root + two mesh children."""
    helper_chunk = _make_helper(100, HelperType.DUMMY)
    mesh_a = _make_mesh(200, num_vertices=3)
    mesh_b = _make_mesh(201, num_vertices=6)

    root = _make_node(node_id=1, name="root", object_id=100, parent_id=-1)
    child_a = _make_node(node_id=2, name="meshA", object_id=200, parent_id=1)
    child_b = _make_node(node_id=3, name="meshB", object_id=201, parent_id=1)

    model = _model_from_chunks(
        "asset.cgf", [helper_chunk, mesh_a, mesh_b, root, child_a, child_b]
    )

    eng = CryEngine("asset.cgf", InMemoryFileSystem())
    eng.models = [model]
    eng._build_nodes()

    assert eng.root_node is root
    assert root.chunk_helper is helper_chunk
    assert root.mesh_data is None
    assert child_a.mesh_data is mesh_a
    assert child_b.mesh_data is mesh_b
    assert root.children == [child_a, child_b]
    assert child_a.parent_node is root
    assert child_b.parent_node is root


def test_build_nodes_split_files_pulls_geometry_from_second_model() -> None:
    """`.cga` (model[0]) has empty mesh stubs; `.cgam` (model[1]) holds
    the real geometry. The aggregator should swap mesh references."""
    # model[0]: a single mesh node with an empty mesh chunk
    empty_mesh = _make_mesh(50, num_vertices=0)
    node0 = _make_node(node_id=1, name="body", object_id=50, parent_id=-1)
    model_a = _model_from_chunks("asset.cga", [empty_mesh, node0])

    # model[1]: same node name, but mesh has real vertex count
    real_mesh = _make_mesh(60, num_vertices=42)
    node1 = _make_node(node_id=11, name="body", object_id=60, parent_id=-1)
    model_b = _model_from_chunks("asset.cgam", [real_mesh, node1])

    eng = CryEngine("asset.cga", InMemoryFileSystem())
    eng.models = [model_a, model_b]
    eng._build_nodes()

    assert eng.root_node is node0
    assert node0.mesh_data is real_mesh


def test_build_nodes_split_files_keeps_physics_only_node() -> None:
    """A node present in model[0] but missing from model[1] (typically
    a physics proxy) should keep its original empty mesh, not crash."""
    empty_mesh = _make_mesh(50, num_vertices=0)
    phys_node = _make_node(node_id=1, name="phys_proxy", object_id=50, parent_id=-1)
    model_a = _model_from_chunks("asset.cga", [empty_mesh, phys_node])

    other_mesh = _make_mesh(60, num_vertices=99)
    other_node = _make_node(node_id=11, name="something_else", object_id=60, parent_id=-1)
    model_b = _model_from_chunks("asset.cgam", [other_mesh, other_node])

    eng = CryEngine("asset.cga", InMemoryFileSystem())
    eng.models = [model_a, model_b]
    eng._build_nodes()

    assert phys_node in eng.nodes
    # Falls back to the empty mesh from model[0].
    assert phys_node.mesh_data is empty_mesh


def test_collect_material_library_files_dedupes_and_filters() -> None:
    lib = _make_mtl(10, "shared/lib", MtlNameType.Library)
    single = _make_mtl(11, "single_mat", MtlNameType.Single)
    child = _make_mtl(12, "child_mat", MtlNameType.Child)  # excluded
    dup = _make_mtl(13, "shared/lib", MtlNameType.Library)  # duplicate
    empty = _make_mtl(14, "", MtlNameType.Library)  # empty name skipped

    model = _model_from_chunks("asset.cgf", [lib, single, child, dup, empty])

    eng = CryEngine("asset.cgf", InMemoryFileSystem())
    eng.models = [model]
    eng._collect_material_library_files()

    assert eng.material_library_files == ["shared/lib", "single_mat"]


def test_chunks_property_flattens_across_models() -> None:
    a = _make_helper(1)
    b = _make_helper(2)
    c = _make_helper(3)
    eng = CryEngine("asset.cga", InMemoryFileSystem())
    eng.models = [
        _model_from_chunks("asset.cga", [a, b]),
        _model_from_chunks("asset.cgam", [c]),
    ]
    assert {ch.id for ch in eng.chunks} == {1, 2, 3}


def test_iter_nodes_depth_first() -> None:
    helper = _make_helper(100)
    root = _make_node(1, "root", 100, -1)
    a = _make_node(2, "a", 100, 1)
    b = _make_node(3, "b", 100, 1)
    aa = _make_node(4, "aa", 100, 2)

    model = _model_from_chunks("asset.cgf", [helper, root, a, b, aa])
    eng = CryEngine("asset.cgf", InMemoryFileSystem())
    eng.models = [model]
    eng._build_nodes()

    order = [n.name for n in eng.iter_nodes()]
    assert order == ["root", "a", "aa", "b"]


def test_process_loads_companion_cgam(tmp_path) -> None:
    """End-to-end: write a synthetic 0x745 file pair, point a
    `RealFileSystem` at the directory, and confirm `.cga` + `.cgam`
    are both parsed."""
    import struct
    from cryengine_importer.io.pack_fs import RealFileSystem

    def _build_empty_745(file_type: int = 0xFFFF0000) -> bytes:
        # 24-byte header, 0 chunks.
        out = bytearray()
        out.extend(b"CryTek\x00\x00")
        out.extend(struct.pack("<I", file_type))
        out.extend(struct.pack("<I", 0x745))
        out.extend(struct.pack("<i", 24 - 4))  # loader adds +4
        out.extend(struct.pack("<I", 0))  # num chunks
        return bytes(out)

    (tmp_path / "hero.cga").write_bytes(_build_empty_745())
    (tmp_path / "hero.cgam").write_bytes(_build_empty_745())

    fs = RealFileSystem(tmp_path)
    eng = CryEngine("hero.cga", fs)
    eng.process()

    assert len(eng.models) == 2
    assert eng.models[0].file_name == "hero.cga"
    assert eng.models[1].file_name == "hero.cgam"
    assert not eng.is_ivo
    assert eng.root_node is None  # no node chunks
