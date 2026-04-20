"""Inspect CryEngine pack files (folders or ``.pak`` ZIP archives).

A small generic CryEngine utility — works against MWO / Aion /
ArcheAge / Crysis / Star Citizen alike. Not a substitute for the
Blender importer; intended as a pre-flight check ("what's in this
pak?", "which mesh references which material?").

Usage::

    python -m cryengine_importer.pak_browser list path/to/data.pak
    python -m cryengine_importer.pak_browser list path/to/extracted/

    python -m cryengine_importer.pak_browser companions \
        path/to/data.pak objects/atlas.cga

The ``list`` subcommand enumerates primary geometry files
(``.cgf``/``.cga``/``.chr``/``.skin``) while excluding their
companions (``.cgam``/``.chrm``/``.skinm``/``.cgfm``). The
``companions`` subcommand prints the resolved sibling files
(geometry companion + chrparams / cal / mtl / meshsetup / cdf) for a
specific geometry path.

Pure-Python (no ``bpy``); the same module powers both stdout output
and a future Blender "Browse Pack" UI panel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .io.asset_resolver import find_geometry_files, resolve_companions
from .io.pack_fs import IPackFileSystem, RealFileSystem, ZipFileSystem


def _open_pack(source: str | Path) -> IPackFileSystem:
    """Pick the right pack-FS backend for ``source``.

    Directories → :class:`RealFileSystem`. Anything else (typically a
    ``.pak`` / ``.zip`` archive) → :class:`ZipFileSystem`.
    """
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(p)
    if p.is_dir():
        return RealFileSystem(p)
    return ZipFileSystem(p)


def list_geometry(pack: IPackFileSystem, *, pattern: str = "*") -> list[str]:
    """Thin wrapper around :func:`find_geometry_files`. Exposed so the
    same listing logic is reusable from a future Blender UI panel."""
    return find_geometry_files(pack, pattern=pattern)


def _cmd_list(args: argparse.Namespace) -> int:
    pack = _open_pack(args.source)
    try:
        for path in list_geometry(pack, pattern=args.pattern):
            print(path)
    finally:
        if isinstance(pack, ZipFileSystem):
            pack.close()
    return 0


def _cmd_companions(args: argparse.Namespace) -> int:
    pack = _open_pack(args.source)
    try:
        result = resolve_companions(args.path, pack)
        print(f"geometry: {result.geometry}")
        for attr in ("companion", "chrparams", "cal", "mtl", "meshsetup", "cdf"):
            value = getattr(result, attr)
            if value is not None:
                print(f"{attr:>10}: {value}")
        for extra in result.extras:
            print(f"     extra: {extra}")
        if not result.found():
            print("(no companion files found)")
            return 1
    finally:
        if isinstance(pack, ZipFileSystem):
            pack.close()
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser. Exposed so tests can drive it
    without spawning a subprocess."""
    parser = argparse.ArgumentParser(
        prog="python -m cryengine_importer.pak_browser",
        description="Inspect CryEngine pack files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List primary geometry files.")
    list_p.add_argument("source", help="Path to a folder or .pak/.zip file.")
    list_p.add_argument(
        "--pattern",
        default="*",
        help=(
            "Glob pattern passed verbatim to the pack-FS (default '*'). "
            "Backends differ: RealFileSystem supports '**', "
            "InMemoryFileSystem only trailing '*'."
        ),
    )
    list_p.set_defaults(func=_cmd_list)

    comp_p = sub.add_parser(
        "companions", help="Resolve companion files for a geometry path."
    )
    comp_p.add_argument("source", help="Path to a folder or .pak/.zip file.")
    comp_p.add_argument(
        "path",
        help="Pack-FS-relative geometry path (e.g. objects/atlas.cga).",
    )
    comp_p.set_defaults(func=_cmd_companions)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - exercised via -m
    sys.exit(main())


__all__ = ["build_arg_parser", "list_geometry", "main"]
