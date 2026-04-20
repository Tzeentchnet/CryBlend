"""Tests for `io/asset_resolver.py` — companion-file discovery."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from cryengine_importer.io.asset_resolver import (
    AssetCompanions,
    find_geometry_files,
    resolve_companions,
)
from cryengine_importer.io.pack_fs import (
    InMemoryFileSystem,
    RealFileSystem,
    ZipFileSystem,
)


# --------------------------------------------------------------- resolve_companions


def test_resolve_companions_full_set() -> None:
    fs = InMemoryFileSystem(
        {
            "objects/atlas.cga": b"",
            "objects/atlas.cgam": b"",
            "objects/atlas.chrparams": b"",
            "objects/atlas.cal": b"",
            "objects/atlas.mtl": b"",
            "objects/atlas.meshsetup": b"",
            "objects/atlas.cdf": b"",
            # Unrelated noise.
            "objects/centurion.cga": b"",
            "objects/atlas.unrelated": b"",
        }
    )
    result = resolve_companions("objects/atlas.cga", fs)
    assert isinstance(result, AssetCompanions)
    assert result.geometry == "objects/atlas.cga"
    assert result.companion == "objects/atlas.cgam"
    assert result.chrparams == "objects/atlas.chrparams"
    assert result.cal == "objects/atlas.cal"
    assert result.mtl == "objects/atlas.mtl"
    assert result.meshsetup == "objects/atlas.meshsetup"
    assert result.cdf == "objects/atlas.cdf"
    assert "objects/atlas.cgam" in result.found()
    assert len(result.found()) == 6


def test_resolve_companions_only_geometry_present() -> None:
    fs = InMemoryFileSystem({"objects/atlas.cga": b""})
    result = resolve_companions("objects/atlas.cga", fs)
    assert result.companion is None
    assert result.chrparams is None
    assert result.found() == []


def test_resolve_companions_skin_to_skinm() -> None:
    fs = InMemoryFileSystem(
        {"chars/hero.skin": b"", "chars/hero.skinm": b""}
    )
    result = resolve_companions("chars/hero.skin", fs)
    assert result.companion == "chars/hero.skinm"


def test_resolve_companions_chr_to_chrm() -> None:
    fs = InMemoryFileSystem({"chars/hero.chr": b"", "chars/hero.chrm": b""})
    result = resolve_companions("chars/hero.chr", fs)
    assert result.companion == "chars/hero.chrm"


def test_resolve_companions_no_companion_for_unknown_ext() -> None:
    fs = InMemoryFileSystem({"foo/bar.dds": b""})
    result = resolve_companions("foo/bar.dds", fs)
    assert result.companion is None  # .dds has no companion mapping


def test_resolve_companions_extra_exts() -> None:
    fs = InMemoryFileSystem(
        {"objects/atlas.cga": b"", "objects/atlas.lod0": b""}
    )
    result = resolve_companions(
        "objects/atlas.cga", fs, extra_exts=(".lod0", ".lod1")
    )
    assert result.extras == ["objects/atlas.lod0"]
    assert "objects/atlas.lod0" in result.found()


def test_resolve_companions_extra_exts_normalize_leading_dot() -> None:
    fs = InMemoryFileSystem(
        {"objects/atlas.cga": b"", "objects/atlas.lod0": b""}
    )
    result = resolve_companions(
        "objects/atlas.cga", fs, extra_exts=("lod0",)  # no leading dot
    )
    assert result.extras == ["objects/atlas.lod0"]


def test_resolve_companions_real_fs_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "Objects").mkdir()
    (tmp_path / "Objects" / "Atlas.CGA").write_bytes(b"")
    (tmp_path / "Objects" / "Atlas.CGAM").write_bytes(b"")
    (tmp_path / "Objects" / "Atlas.MTL").write_bytes(b"")
    fs = RealFileSystem(tmp_path)
    result = resolve_companions("objects/atlas.cga", fs)
    # Probed paths use the lowercase form we constructed; case-insensitive
    # FS just confirms they exist.
    assert result.companion == "objects/atlas.cgam"
    assert result.mtl == "objects/atlas.mtl"


def test_resolve_companions_works_inside_zip(tmp_path: Path) -> None:
    pak = tmp_path / "data.pak"
    with zipfile.ZipFile(pak, "w") as zf:
        zf.writestr("Objects/Atlas.cga", b"")
        zf.writestr("Objects/Atlas.cgam", b"")
        zf.writestr("Objects/Atlas.mtl", b"")
    with ZipFileSystem(pak) as fs:
        result = resolve_companions("objects/atlas.cga", fs)
        assert result.companion == "objects/atlas.cgam"
        assert result.mtl == "objects/atlas.mtl"


# --------------------------------------------------------------- find_geometry_files


def test_find_geometry_files_excludes_companions(tmp_path: Path) -> None:
    pak = tmp_path / "data.pak"
    with zipfile.ZipFile(pak, "w") as zf:
        zf.writestr("Objects/atlas.cga", b"")
        zf.writestr("Objects/atlas.cgam", b"")  # companion — excluded
        zf.writestr("Objects/centurion.cgf", b"")
        zf.writestr("Chars/hero.chr", b"")
        zf.writestr("Chars/hero.chrm", b"")     # companion — excluded
        zf.writestr("Textures/diffuse.dds", b"")
    with ZipFileSystem(pak) as fs:
        # ZipFileSystem.glob with `*` matches every entry's lowercased key.
        # asset_resolver filters by extension.
        found = find_geometry_files(fs, pattern="*")
        assert sorted(found, key=str.lower) == [
            "Chars/hero.chr",
            "Objects/atlas.cga",
            "Objects/centurion.cgf",
        ]


def test_find_geometry_files_dedupes() -> None:
    fs = InMemoryFileSystem(
        {"objects/a.cga": b"", "objects/b.cga": b"", "objects/c.cgam": b""}
    )
    # InMemoryFileSystem.glob supports trailing `*` only.
    found = find_geometry_files(fs, pattern="objects/*")
    assert found == ["objects/a.cga", "objects/b.cga"]


def test_find_geometry_files_respects_custom_extensions() -> None:
    fs = InMemoryFileSystem(
        {"objects/a.cga": b"", "objects/b.skin": b"", "objects/c.cgf": b""}
    )
    found = find_geometry_files(
        fs, pattern="objects/*", extensions=(".skin",)
    )
    assert found == ["objects/b.skin"]
