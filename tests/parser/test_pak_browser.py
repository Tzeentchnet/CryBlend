"""Tests for the `pak_browser` CLI module."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from cryengine_importer.pak_browser import build_arg_parser, list_geometry, main
from cryengine_importer.io.pack_fs import RealFileSystem, ZipFileSystem


def _make_pak(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    pak = tmp_path / "data.pak"
    with zipfile.ZipFile(pak, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return pak


# ----------------------------------------------------------------- list_geometry


def test_list_geometry_zip(tmp_path: Path) -> None:
    pak = _make_pak(
        tmp_path,
        {
            "Objects/atlas.cga": b"",
            "Objects/atlas.cgam": b"",  # companion — excluded
            "Objects/centurion.cgf": b"",
            "Chars/hero.chr": b"",
            "Chars/hero.chrm": b"",     # companion — excluded
            "Textures/diffuse.dds": b"",
        },
    )
    with ZipFileSystem(pak) as fs:
        assert list_geometry(fs) == [
            "Chars/hero.chr",
            "Objects/atlas.cga",
            "Objects/centurion.cgf",
        ]


def test_list_geometry_real_fs(tmp_path: Path) -> None:
    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "atlas.cga").write_bytes(b"")
    (tmp_path / "objects" / "atlas.cgam").write_bytes(b"")
    (tmp_path / "objects" / "centurion.cgf").write_bytes(b"")
    fs = RealFileSystem(tmp_path)
    # RealFileSystem.glob supports `**`.
    found = list_geometry(fs, pattern="**/*")
    assert sorted(found, key=str.lower) == [
        "objects/atlas.cga",
        "objects/centurion.cgf",
    ]


# ------------------------------------------------------------------------- CLI


def test_cli_list_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pak = _make_pak(
        tmp_path, {"objects/atlas.cga": b"", "objects/atlas.cgam": b""}
    )
    rc = main(["list", str(pak)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "objects/atlas.cga" in captured.out
    assert "objects/atlas.cgam" not in captured.out


def test_cli_list_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "objects").mkdir()
    (tmp_path / "objects" / "hero.chr").write_bytes(b"")
    rc = main(["list", str(tmp_path), "--pattern", "**/*"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "objects/hero.chr" in captured.out


def test_cli_companions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pak = _make_pak(
        tmp_path,
        {
            "objects/atlas.cga": b"",
            "objects/atlas.cgam": b"",
            "objects/atlas.mtl": b"",
        },
    )
    rc = main(["companions", str(pak), "objects/atlas.cga"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "geometry: objects/atlas.cga" in out
    assert "objects/atlas.cgam" in out
    assert "objects/atlas.mtl" in out


def test_cli_companions_returns_nonzero_when_no_siblings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pak = _make_pak(tmp_path, {"objects/atlas.cga": b""})
    rc = main(["companions", str(pak), "objects/atlas.cga"])
    assert rc == 1
    assert "no companion files found" in capsys.readouterr().out


def test_cli_missing_source_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.pak"
    with pytest.raises(FileNotFoundError):
        main(["list", str(missing)])


def test_cli_requires_subcommand() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
