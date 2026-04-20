"""Companion-file auto-resolution for CryEngine assets.

Given a primary geometry path (e.g. ``objects/atlas.cga``), surface
the sibling files a typical CryEngine asset references:

- ``.cgam`` / ``.chrm`` / ``.skinm`` — geometry-only companion split
  off from a ``.cga`` / ``.chr`` / ``.skin``.
- ``.chrparams`` — character animation list referencing CAF files.
- ``.cal`` — ArcheAge animation list (legacy fallback for chrparams).
- ``.mtl`` — material library next to the geometry.
- ``.meshsetup`` — per-LOD / physics setup metadata.
- ``.cdf`` — character definition (composite skin attachments).

All four geometry-companion extensions and the metadata sidecars
(``.chrparams``, ``.cal``, ``.mtl``, ``.meshsetup``, ``.cdf``) are
*stock* CryEngine — works for MWO / Aion / ArcheAge / Crysis / Star
Citizen alike. Lookups go through an :class:`IPackFileSystem`, so
callers can mix-and-match real folders, ZIP-format ``.pak`` archives,
and in-memory test fixtures.

This module only *discovers* paths — parsing of `.chrparams` / `.cal`
/ `.mtl` continues to live in ``core/chrparams_loader.py``,
``core/cal_loader.py`` and ``materials/loader.py`` respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pack_fs import IPackFileSystem


# Geometry companion extensions: the second-file half of a split asset.
# Mapping is exhaustive — every primary CryEngine geometry extension
# pairs to one (and only one) companion extension. The C# tree
# (`Cryengine.cs::AutoDetectMFile`) computes this by appending ``"m"``
# to the original suffix; we hard-code it for clarity and so we can
# also resolve in reverse (companion → primary) for diagnostics.
_GEOMETRY_COMPANIONS: dict[str, str] = {
    ".cga": ".cgam",
    ".cgf": ".cgfm",  # rare in the wild but the suffix is consistent
    ".chr": ".chrm",
    ".skin": ".skinm",
}

# Metadata sidecars: same-stem files alongside the geometry that
# downstream loaders consume.
_METADATA_EXTS: tuple[str, ...] = (
    ".chrparams",
    ".cal",
    ".mtl",
    ".meshsetup",
    ".cdf",
)


@dataclass
class AssetCompanions:
    """Result of :func:`resolve_companions`.

    ``geometry`` is the path actually probed (the input). Companion
    paths are pack-FS-relative (forward slashes, original casing as
    stored on disk); paths that didn't resolve are simply absent from
    the dataclass — callers can use ``hasattr``-style attribute
    access plus an ``is None`` check.
    """

    geometry: str
    companion: str | None = None
    chrparams: str | None = None
    cal: str | None = None
    mtl: str | None = None
    meshsetup: str | None = None
    cdf: str | None = None
    extras: list[str] = field(default_factory=list)

    def found(self) -> list[str]:
        """All non-None resolved companion paths (excluding geometry)."""
        out: list[str] = []
        for attr in ("companion", "chrparams", "cal", "mtl", "meshsetup", "cdf"):
            v = getattr(self, attr)
            if v is not None:
                out.append(v)
        out.extend(self.extras)
        return out


def resolve_companions(
    geometry_path: str,
    pack_fs: "IPackFileSystem",
    *,
    extra_exts: tuple[str, ...] = (),
) -> AssetCompanions:
    """Resolve the standard sibling-file set for ``geometry_path``.

    ``extra_exts`` lets callers probe additional same-stem extensions
    (e.g. ``(".lod0",)``) without modifying this module. Returned
    paths are whatever the pack-FS uses internally — typically
    forward-slash, possibly mixed-case, since CryEngine PAKs are
    case-insensitive.
    """
    p = PurePosixPath(geometry_path.replace("\\", "/"))
    suffix_lower = p.suffix.lower()
    stem_path = p.with_suffix("")

    result = AssetCompanions(geometry=geometry_path)

    # Geometry companion (.cgam / .chrm / .skinm).
    companion_ext = _GEOMETRY_COMPANIONS.get(suffix_lower)
    if companion_ext is not None:
        cand = str(stem_path) + companion_ext
        if pack_fs.exists(cand):
            result.companion = cand

    # Metadata sidecars share the bare stem.
    for ext in _METADATA_EXTS:
        cand = str(stem_path) + ext
        if pack_fs.exists(cand):
            setattr(result, ext.lstrip("."), cand)

    for ext in extra_exts:
        if not ext.startswith("."):
            ext = "." + ext
        cand = str(stem_path) + ext
        if pack_fs.exists(cand) and cand not in result.extras:
            result.extras.append(cand)

    return result


def find_geometry_files(
    pack_fs: "IPackFileSystem",
    *,
    pattern: str = "*",
    extensions: tuple[str, ...] = (".cgf", ".cga", ".chr", ".skin"),
) -> list[str]:
    """Return all primary geometry files matching ``pattern``.

    Companion files (``.cgam`` / ``.chrm`` / ``.skinm`` / ``.cgfm``)
    are intentionally excluded — they are loaded automatically
    alongside their primary by :func:`resolve_companions`. Useful for
    building a "browse pack file" UI without showing duplicates.

    ``pattern`` is passed verbatim to ``pack_fs.glob``; backends differ
    in how much glob syntax they support, so callers wanting a
    recursive walk should use a backend that supports ``**`` (e.g.
    :class:`RealFileSystem`).
    """
    extensions_lower = tuple(e.lower() for e in extensions)
    companions_lower = set(_GEOMETRY_COMPANIONS.values())

    out: list[str] = []
    seen: set[str] = set()
    for path in pack_fs.glob(pattern):
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in extensions_lower:
            continue
        if suffix in companions_lower:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)

    out.sort(key=str.lower)
    return out


__all__ = [
    "AssetCompanions",
    "resolve_companions",
    "find_geometry_files",
]
