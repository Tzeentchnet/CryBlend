"""Tests for the pack file system."""

from __future__ import annotations

from pathlib import Path

import pytest

from cryengine_importer.io.pack_fs import (
    CascadedPackFileSystem,
    InMemoryFileSystem,
    RealFileSystem,
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
