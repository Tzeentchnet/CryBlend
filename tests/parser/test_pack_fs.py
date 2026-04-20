"""Tests for the pack file system."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from cryengine_importer.io.pack_fs import (
    CascadedPackFileSystem,
    InMemoryFileSystem,
    RealFileSystem,
    ZipFileSystem,
)


def test_in_memory_basic() -> None:
    fs = InMemoryFileSystem({"a/b.txt": b"hello"})
    assert fs.exists("a/b.txt")
    assert fs.exists("A/B.TXT") is False  # in-memory is case-sensitive
    assert fs.read_all_bytes("a/b.txt") == b"hello"
    assert list(fs.glob("a/*")) == ["a/b.txt"]


def test_real_fs_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Sub" / "Model.CGF").write_bytes(b"data")
    fs = RealFileSystem(tmp_path)
    # Original casing works.
    assert fs.exists("Sub/Model.CGF")
    # CryEngine paths often arrive lowercased; we should still find it.
    assert fs.exists("sub/model.cgf")
    assert fs.read_all_bytes("sub/model.cgf") == b"data"


def test_cascaded_lifo(tmp_path: Path) -> None:
    a = InMemoryFileSystem({"x.txt": b"A"})
    b = InMemoryFileSystem({"x.txt": b"B"})
    cascade = CascadedPackFileSystem([a, b])
    # Last-pushed wins.
    assert cascade.read_all_bytes("x.txt") == b"B"
    cascade.push(InMemoryFileSystem({"x.txt": b"C"}))
    assert cascade.read_all_bytes("x.txt") == b"C"


def test_missing_file_raises() -> None:
    fs = InMemoryFileSystem()
    with pytest.raises(FileNotFoundError):
        fs.open("nope.txt")


# --------------------------------------------------------------- ZipFileSystem


def _make_pak(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    pak = tmp_path / "data.pak"
    with zipfile.ZipFile(pak, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return pak


def test_zip_fs_basic_lookup(tmp_path: Path) -> None:
    pak = _make_pak(
        tmp_path,
        {"Objects/Mech/atlas.cgf": b"CGF!", "objects/mech/atlas.mtl": b"<m/>"},
    )
    with ZipFileSystem(pak) as fs:
        assert fs.exists("Objects/Mech/atlas.cgf")
        # Case-insensitive (CryEngine convention).
        assert fs.exists("objects/MECH/ATLAS.cgf")
        assert fs.read_all_bytes("OBJECTS/mech/atlas.mtl") == b"<m/>"
        # ``open`` returns a seekable stream so chunk readers can use it.
        with fs.open("objects/mech/atlas.cgf") as stream:
            assert stream.read() == b"CGF!"
            stream.seek(0)
            assert stream.read(3) == b"CGF"


def test_zip_fs_missing_raises(tmp_path: Path) -> None:
    pak = _make_pak(tmp_path, {"a.txt": b"x"})
    with ZipFileSystem(pak) as fs:
        with pytest.raises(FileNotFoundError):
            fs.read_all_bytes("missing.txt")


def test_zip_fs_glob_case_insensitive(tmp_path: Path) -> None:
    pak = _make_pak(
        tmp_path,
        {
            "Objects/Mech/atlas.cgf": b"",
            "Objects/Mech/atlas.mtl": b"",
            "Objects/Mech/centurion.cgf": b"",
            "Textures/diffuse.dds": b"",
        },
    )
    with ZipFileSystem(pak) as fs:
        cgfs = sorted(fs.glob("objects/mech/*.cgf"))
        assert cgfs == ["Objects/Mech/atlas.cgf", "Objects/Mech/centurion.cgf"]


def test_zip_fs_skips_directory_entries(tmp_path: Path) -> None:
    pak = tmp_path / "data.pak"
    with zipfile.ZipFile(pak, "w") as zf:
        # Some packers add explicit directory entries; we should ignore them.
        zf.writestr("dir/", b"")
        zf.writestr("dir/file.txt", b"hi")
    with ZipFileSystem(pak) as fs:
        assert fs.exists("dir/file.txt")
        assert not fs.exists("dir/")


def test_zip_fs_in_cascade(tmp_path: Path) -> None:
    base = InMemoryFileSystem({"shared.txt": b"base"})
    pak = _make_pak(tmp_path, {"shared.txt": b"pak", "extra.cgf": b"new"})
    with ZipFileSystem(pak) as zfs:
        cascade = CascadedPackFileSystem([base, zfs])
        # Last-pushed (zip) wins for shared paths.
        assert cascade.read_all_bytes("shared.txt") == b"pak"
        assert cascade.read_all_bytes("extra.cgf") == b"new"
