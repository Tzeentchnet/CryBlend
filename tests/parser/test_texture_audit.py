"""Phase 11 — texture_audit tests with fake bpy datablocks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cryengine_importer.blender.texture_audit import (
    MissingImage,
    find_missing_images,
    index_directory,
    plan_relinks,
    write_missing_files_report,
)


def _img(
    name: str,
    filepath: str = "",
    *,
    has_data: bool = False,
    packed: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        filepath=filepath,
        has_data=has_data,
        packed_file=object() if packed else None,
    )


def _mat(name: str, *images: SimpleNamespace) -> SimpleNamespace:
    nodes = [SimpleNamespace(image=i) for i in images]
    return SimpleNamespace(
        name=name,
        node_tree=SimpleNamespace(nodes=nodes),
    )


def test_find_missing_skips_packed_and_loaded_images() -> None:
    materials = [
        _mat("hero", _img("packed.png", "//packed.png", packed=True)),
        _mat("villain", _img("loaded.png", "//loaded.png", has_data=True)),
        _mat("ghost", _img("missing.png", "//missing.png")),
    ]
    missing = find_missing_images(
        materials,
        abspath=lambda p: p,
        exists=lambda p: False,
    )
    assert [m.image_name for m in missing] == ["missing.png"]
    assert missing[0].material_name == "ghost"
    assert missing[0].filepath == "//missing.png"


def test_find_missing_skips_empty_filepaths() -> None:
    materials = [_mat("ghost", _img("placeholder", ""))]
    assert find_missing_images(
        materials, abspath=lambda p: p, exists=lambda p: True
    ) == []


def test_find_missing_uses_abspath_and_exists() -> None:
    materials = [_mat("hero", _img("a.png", "//a.png"))]
    seen: list[str] = []

    def fake_exists(p: str) -> bool:
        seen.append(p)
        return False

    missing = find_missing_images(
        materials, abspath=lambda p: f"/abs/{p[2:]}", exists=fake_exists
    )
    assert seen == ["/abs/a.png"]
    assert missing[0].filepath == "//a.png"


def test_find_missing_ignores_materials_without_node_tree() -> None:
    materials = [SimpleNamespace(name="legacy", node_tree=None)]
    assert find_missing_images(
        materials, abspath=lambda p: p, exists=lambda p: False
    ) == []


def test_find_missing_dedupes_by_material_image_pair() -> None:
    img = _img("a.png", "//a.png")
    materials = [_mat("hero", img, img)]
    missing = find_missing_images(
        materials, abspath=lambda p: p, exists=lambda p: False
    )
    assert len(missing) == 1


def test_index_directory_lower_case_basename(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "Hero_DIFF.dds").write_bytes(b"x")
    (tmp_path / "sub" / "villain_diff.tif").write_bytes(b"y")
    (tmp_path / "sub" / "ignored.txt").write_bytes(b"z")
    idx = index_directory(tmp_path)
    assert "hero_diff.dds" in idx
    assert "villain_diff.tif" in idx
    assert "ignored.txt" not in idx


def test_index_directory_returns_empty_for_missing(tmp_path: Path) -> None:
    assert index_directory(tmp_path / "nope") == {}


def test_plan_relinks_matches_by_basename() -> None:
    missing = [
        MissingImage("hero", "diff", "//some/path/hero_diff.dds"),
        MissingImage("hero", "stranger", "//unknown.dds"),
    ]
    index = {
        "hero_diff.dds": "/abs/hero_diff.dds",
    }
    plan = plan_relinks(missing, index)
    assert plan == {"diff": "/abs/hero_diff.dds"}


def test_plan_relinks_falls_back_to_image_name() -> None:
    missing = [MissingImage("hero", "hero_diff.dds", "")]
    index = {"hero_diff.dds": "/abs/hero_diff.dds"}
    plan = plan_relinks(missing, index)
    assert plan == {"hero_diff.dds": "/abs/hero_diff.dds"}


def test_write_missing_files_report(tmp_path: Path) -> None:
    p = tmp_path / "missing.txt"
    n = write_missing_files_report(
        p,
        [
            MissingImage("hero", "a.png", "//a.png"),
            MissingImage("hero", "b.png", "//b.png"),
        ],
    )
    assert n == 2
    text = p.read_text(encoding="utf-8")
    assert "hero\ta.png\t//a.png" in text
    assert text.endswith("\n")


def test_write_missing_files_report_empty(tmp_path: Path) -> None:
    p = tmp_path / "missing.txt"
    n = write_missing_files_report(p, [])
    assert n == 0
    assert p.read_text(encoding="utf-8") == ""
