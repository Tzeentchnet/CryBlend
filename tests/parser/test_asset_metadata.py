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
    summarize_cdf_attachments,
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


class FakeObject:
    def __init__(self, name: str) -> None:
        self.name = name


class StrictNameCollection:
    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)

    def __iter__(self):
        return iter(self._items)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return any(getattr(item, "name", None) == key for item in self._items)
        if isinstance(key, tuple) and all(isinstance(part, str) for part in key):
            names = {getattr(item, "name", None) for item in self._items}
            return all(part in names for part in key)
        raise TypeError(
            "bpy_prop_collection.__contains__: expected a string or a tuple of strings"
        )


class StrictCollection(FakeCollection):
    @property
    def all_objects(self) -> StrictNameCollection:
        return StrictNameCollection(super().all_objects)

    @property
    def children_recursive(self) -> StrictNameCollection:
        return StrictNameCollection(super().children_recursive)


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
    assert written["animations_dir"] == ""
    assert written["material_libs"] == []
    assert written["axis_forward"] == "Y"
    assert written["axis_up"] == "Z"
    assert written["convert_axes"] is True
    assert written["import_related"] is True
    assert written["import_cdf_composition"] is True
    assert written["cdf_source_path"] == ""
    assert written["cdf_attachments"] == []
    assert written["cdf_warnings"] == []
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
        animations_dir=r"D:\\game\\Animations\\Alien\\grunt",
        material_libs=["materials/hero.mtl", "materials/villain.mtl"],
        material_libs_resolved=["hero"],
        axis_forward="-Y",
        axis_up="Z",
        convert_axes=False,
        import_related=False,
        import_cdf_composition=False,
        addon_version="1.2.3",
        public_params_by_material=pp_cache,
    )
    data = read_metadata(coll)
    assert data is not None
    assert data["object_dir"] == r"D:\\game\\Data"
    assert data["animations_dir"] == r"D:\\game\\Animations\\Alien\\grunt"
    assert data["material_libs"] == ["materials/hero.mtl", "materials/villain.mtl"]
    assert data["material_libs_resolved"] == ["hero"]
    assert data["axis_forward"] == "-Y"
    assert data["convert_axes"] is False
    assert data["import_related"] is False
    assert data["import_cdf_composition"] is False
    assert data["addon_version"] == "1.2.3"
    assert data["public_params_by_material"]["Anodized_01_A"]["DiffuseTint1"] == "0.5,0.5,0.5"


def test_stamp_collection_cdf_payload_round_trips() -> None:
    coll = FakeCollection("Grunt")
    stamp_collection(
        coll,
        source_path="objects/characters/alien/grunt/grunt.cdf",
        cdf_source_path="objects/characters/alien/grunt/grunt.cdf",
        cdf_attachments=[
            {
                "name": "armor_head",
                "type": "CA_BONE",
                "binding": "objects/chars/armor_head.cgf",
                "flags": 32770,
                "visible": True,
            }
        ],
        cdf_warnings=["Attachment bone not found: Missing"],
    )

    data = read_metadata(coll)
    assert data is not None
    assert data["schema"] == SCHEMA_VERSION
    assert data["cdf_source_path"] == "objects/characters/alien/grunt/grunt.cdf"
    assert data["cdf_attachments"] == [
        {
            "name": "armor_head",
            "type": "CA_BONE",
            "binding": "objects/chars/armor_head.cgf",
            "flags": 32770,
            "visible": True,
        }
    ]
    assert data["cdf_warnings"] == ["Attachment bone not found: Missing"]


def test_summarize_cdf_attachments_counts_status_types_and_visibility() -> None:
    summary = summarize_cdf_attachments(
        {
            "cdf_attachments": [
                {"name": "jelly_alive", "type": "CA_SKIN", "status": "bound", "visible": True},
                {"name": "gun", "type": "CA_BONE", "status": "bound", "visible": True},
                {
                    "name": "rope1",
                    "type": "CA_BONE",
                    "status": "empty",
                    "phys_prop_type": "Rope",
                    "bone_name": "rope start",
                },
                {
                    "name": "destroyed",
                    "type": "CA_SKIN",
                    "status": "bound",
                    "visible": False,
                    "binding": "objects/destroyed.skin",
                    "bone_name": "Bip01 Spine",
                    "flags": 458753,
                },
                {"name": "missing", "type": "CA_BONE", "status": "missing", "visible": True},
            ],
            "cdf_warnings": ["Missing attachment"],
        }
    )

    assert summary["total"] == 5
    assert summary["by_type"] == {"CA_SKIN": 2, "CA_BONE": 3}
    assert summary["bound"] == 3
    assert summary["empty"] == 1
    assert summary["empty_details"] == [
        {
            "name": "rope1",
            "type": "CA_BONE",
            "bone_name": "rope start",
            "phys_prop_type": "Rope",
        }
    ]
    assert summary["missing"] == 1
    assert summary["hidden"] == ["destroyed"]
    assert summary["hidden_details"] == [
        {
            "name": "destroyed",
            "type": "CA_SKIN",
            "status": "bound",
            "binding": "objects/destroyed.skin",
            "bone_name": "Bip01 Spine",
            "flags": 458753,
        }
    ]
    assert summary["ropes"] == ["rope1"]
    assert summary["warnings"] == ["Missing attachment"]


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


def test_find_active_walks_up_with_blender5_children_collection() -> None:
    root = FakeCollection("Scene")
    parent = StrictCollection("Parent")
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


def test_find_active_handles_blender5_object_collection_membership() -> None:
    root = FakeCollection("Scene")
    first_candidate = FakeCollection("A")
    target_collection = StrictCollection("B")
    root.children.extend([first_candidate, target_collection])
    obj = FakeObject("active_mesh")
    target_collection.objects.append(obj)
    stamp_collection(first_candidate, source_path="a.cgf")
    stamp_collection(target_collection, source_path="b.cgf")

    ctx = FakeContext(FakeScene(root), collection=None, active_object=obj)
    assert find_active_cryblend_collection(ctx) is target_collection


def test_find_active_final_fallback_first_candidate() -> None:
    root = FakeCollection("Scene")
    a = FakeCollection("A")
    root.children.append(a)
    stamp_collection(a, source_path="a.cgf")

    ctx = FakeContext(FakeScene(root))
    assert find_active_cryblend_collection(ctx) is a
