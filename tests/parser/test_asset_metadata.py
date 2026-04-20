"""Phase 11 — `blender/asset_metadata.py` round-trip + lookup tests.

These tests deliberately avoid importing `bpy`. They use lightweight
fakes that satisfy the duck-typed protocol the helpers expect.
"""

from __future__ import annotations

from typing import Any

import pytest

from cryengine_importer.blender.asset_metadata import (
    KEY,
    SCHEMA_VERSION,
    find_active_cryblend_collection,
    find_cryblend_collections,
    has_metadata,
    read_metadata,
    stamp_collection,
)


class FakeCollection:
    """Minimal stand-in for `bpy.types.Collection`."""

    def __init__(self, name: str = "coll") -> None:
        self.name = name
        self._props: dict[str, Any] = {}
        self.children: list["FakeCollection"] = []
        self.objects: list[Any] = []

    @property
    def all_objects(self) -> list[Any]:
        out = list(self.objects)
        for child in self.children:
            out.extend(child.all_objects)
        return out

    @property
    def children_recursive(self) -> list["FakeCollection"]:
        out: list[FakeCollection] = []
        for c in self.children:
            out.append(c)
            out.extend(c.children_recursive)
        return out

    def __contains__(self, key: str) -> bool:
        return key in self._props

    def __getitem__(self, key: str) -> Any:
        return self._props[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._props[key] = value


class FakeScene:
    def __init__(self, root: FakeCollection) -> None:
        self.collection = root


class FakeContext:
    def __init__(
        self,
        scene: FakeScene,
        collection: FakeCollection | None = None,
        active_object: Any = None,
    ) -> None:
        self.scene = scene
        self.collection = collection
        self.active_object = active_object


# --------------------------------------------------------------- stamp


def test_stamp_collection_round_trips_minimal() -> None:
    coll = FakeCollection("MyAsset")
    written = stamp_collection(coll, source_path=r"C:\\assets\\hero.cgf")
    assert written["schema"] == SCHEMA_VERSION
    assert written["source_path"] == r"C:\\assets\\hero.cgf"
    assert written["object_dir"] == ""
    assert written["material_libs"] == []
    assert written["axis_forward"] == "Y"
    assert written["axis_up"] == "Z"
    assert written["convert_axes"] is True
    assert written["import_related"] is True
    # And it actually landed on the collection under KEY.
    assert KEY in coll
    assert has_metadata(coll)


def test_stamp_collection_full_payload_including_public_params() -> None:
    coll = FakeCollection("Anodized")
    pp_cache = {
        "Anodized_01_A": {
            "DiffuseTint1": "0.5,0.5,0.5",
            "GlossMult1": "0.8",
        }
    }
    stamp_collection(
        coll,
        source_path="objects/hero.cgf",
        object_dir=r"D:\\game\\Data",
        material_libs=["materials/hero.mtl", "materials/villain.mtl"],
        material_libs_resolved=["hero"],
        axis_forward="-Y",
        axis_up="Z",
        convert_axes=False,
        import_related=False,
        addon_version="1.2.3",
        public_params_by_material=pp_cache,
    )
    data = read_metadata(coll)
    assert data is not None
    assert data["object_dir"] == r"D:\\game\\Data"
    assert data["material_libs"] == ["materials/hero.mtl", "materials/villain.mtl"]
    assert data["material_libs_resolved"] == ["hero"]
    assert data["axis_forward"] == "-Y"
    assert data["convert_axes"] is False
    assert data["import_related"] is False
    assert data["addon_version"] == "1.2.3"
    assert data["public_params_by_material"]["Anodized_01_A"]["DiffuseTint1"] == "0.5,0.5,0.5"


def test_read_metadata_returns_none_when_not_stamped() -> None:
    assert read_metadata(FakeCollection()) is None
    assert has_metadata(FakeCollection()) is False


def test_read_metadata_migrates_pre_schema_payload() -> None:
    """A stamp written before `schema` was added should still parse."""
    coll = FakeCollection()
    coll[KEY] = {"source_path": "x.cgf"}  # no schema, no other fields
    data = read_metadata(coll)
    assert data is not None
    assert data["schema"] == SCHEMA_VERSION
    assert data["source_path"] == "x.cgf"
    assert data["material_libs"] == []
    assert data["convert_axes"] is True


# ---------------------------------------------------------- discovery


def test_find_cryblend_collections_walks_recursively() -> None:
    root = FakeCollection("Scene")
    a = FakeCollection("A")
    b = FakeCollection("B")
    a_child = FakeCollection("A.child")
    a.children.append(a_child)
    root.children.extend([a, b])

    stamp_collection(a, source_path="a.cgf")
    stamp_collection(a_child, source_path="a.child.cgf")
    # b is *not* stamped.

    found = find_cryblend_collections(FakeScene(root))
    found_names = sorted(c.name for c in found)
    assert found_names == ["A", "A.child"]


def test_find_cryblend_collections_handles_no_scene() -> None:
    assert find_cryblend_collections(None) == []
    assert find_cryblend_collections(object()) == []


def test_find_active_returns_none_when_nothing_stamped() -> None:
    root = FakeCollection("Scene")
    ctx = FakeContext(FakeScene(root))
    assert find_active_cryblend_collection(ctx) is None


def test_find_active_prefers_context_collection_when_stamped() -> None:
    root = FakeCollection("Scene")
    a = FakeCollection("A")
    b = FakeCollection("B")
    root.children.extend([a, b])
    stamp_collection(a, source_path="a.cgf")
    stamp_collection(b, source_path="b.cgf")

    ctx = FakeContext(FakeScene(root), collection=b)
    assert find_active_cryblend_collection(ctx) is b


def test_find_active_walks_up_when_context_collection_unstamped() -> None:
    root = FakeCollection("Scene")
    parent = FakeCollection("Parent")
    child = FakeCollection("Child")
    parent.children.append(child)
    root.children.append(parent)
    stamp_collection(parent, source_path="parent.cgf")

    ctx = FakeContext(FakeScene(root), collection=child)
    assert find_active_cryblend_collection(ctx) is parent


def test_find_active_falls_back_to_object_collection() -> None:
    root = FakeCollection("Scene")
    a = FakeCollection("A")
    b = FakeCollection("B")
    root.children.extend([a, b])
    obj = object()
    b.objects.append(obj)
    stamp_collection(a, source_path="a.cgf")
    stamp_collection(b, source_path="b.cgf")

    ctx = FakeContext(FakeScene(root), collection=None, active_object=obj)
    assert find_active_cryblend_collection(ctx) is b


def test_find_active_final_fallback_first_candidate() -> None:
    root = FakeCollection("Scene")
    a = FakeCollection("A")
    root.children.append(a)
    stamp_collection(a, source_path="a.cgf")

    ctx = FakeContext(FakeScene(root))
    assert find_active_cryblend_collection(ctx) is a
