"""Phase 11 — texture audit & relink helpers.

Pure-Python so the missing-image detector + the directory walker can
be unit-tested without `bpy`. The Blender bridge in
`blender/panel.py` wraps these around the `bpy.data.images` /
`bpy.data.materials` collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol


class _ImageLike(Protocol):
    """Minimal duck type satisfied by ``bpy.types.Image``."""

    name: str
    filepath: str

    @property
    def has_data(self) -> bool: ...
    @property
    def packed_file(self) -> object | None: ...


@dataclass(frozen=True)
class MissingImage:
    """A texture image whose backing file can't be found on disk."""

    material_name: str
    image_name: str
    filepath: str


def find_missing_images(
    materials: Iterable[object],
    *,
    abspath: "callable[[str], str] | None" = None,
    exists: "callable[[str], bool] | None" = None,
) -> list[MissingImage]:
    """Walk ``materials``' node trees and report images with no file.

    ``abspath`` resolves a possibly-relative bpy filepath (``//tex.png``)
    to an absolute disk path; defaults to a stdlib resolver against
    cwd. ``exists`` defaults to :func:`os.path.exists`. Both are
    injectable so tests don't need a real filesystem.

    Skips images that:
      * are packed into the .blend (``packed_file`` is set), or
      * report ``has_data=True`` (already loaded in memory), or
      * have no filepath at all (placeholder / generated).
    """
    if abspath is None:
        abspath = lambda p: str(Path(p).resolve()) if p else ""
    if exists is None:
        from os.path import exists as _exists

        exists = _exists

    out: list[MissingImage] = []
    seen: set[tuple[str, str]] = set()

    for mat in materials:
        mat_name = getattr(mat, "name", "?")
        node_tree = getattr(mat, "node_tree", None)
        if node_tree is None:
            continue
        for node in getattr(node_tree, "nodes", ()):
            img = getattr(node, "image", None)
            if img is None:
                continue
            if getattr(img, "packed_file", None) is not None:
                continue
            if getattr(img, "has_data", False):
                continue
            filepath = getattr(img, "filepath", "") or ""
            if not filepath:
                continue
            key = (mat_name, img.name)
            if key in seen:
                continue
            seen.add(key)
            resolved = abspath(filepath) if filepath else ""
            if not resolved or not exists(resolved):
                out.append(MissingImage(mat_name, img.name, filepath))
    return out


def index_directory(
    root: str | Path,
    *,
    extensions: Iterable[str] = (".dds", ".tif", ".tiff", ".png", ".tga", ".jpg", ".jpeg"),
) -> dict[str, str]:
    """Recursively index ``root`` keyed by lowercased basename.

    Returns ``{lowercase_basename: absolute_path}``. Later matches with
    the same lowercase basename are *kept* (last-wins) — a deliberate
    shallow heuristic, since CryEngine asset trees commonly carry the
    same texture under multiple resolutions and the user typically
    wants the last one indexed (often the high-res variant).
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return {}
    exts = {e.lower() for e in extensions}
    out: dict[str, str] = {}
    for p in root_path.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        out[p.name.lower()] = str(p.resolve())
    return out


def plan_relinks(
    missing: Iterable[MissingImage],
    index: Mapping[str, str],
) -> dict[str, str]:
    """Match each missing image to a candidate path from ``index``.

    Returns ``{image_name: new_filepath}``. Images without a match in
    the index are omitted. The lookup is by lowercase basename of the
    *original* filepath; if no match, the image name itself is tried
    as a fallback (some addons strip the extension when naming images).
    """
    plan: dict[str, str] = {}
    for m in missing:
        candidates = []
        if m.filepath:
            candidates.append(Path(m.filepath).name.lower())
        if m.image_name:
            candidates.append(m.image_name.lower())
        for cand in candidates:
            hit = index.get(cand)
            if hit is not None:
                plan[m.image_name] = hit
                break
    return plan


def write_missing_files_report(
    path: str | Path, missing: Iterable[MissingImage]
) -> int:
    """Write a one-per-line report and return the number of entries."""
    lines = []
    for m in missing:
        lines.append(f"{m.material_name}\t{m.image_name}\t{m.filepath}")
    text = "\n".join(lines)
    if text:
        text += "\n"
    Path(path).write_text(text, encoding="utf-8")
    return len(lines)


__all__ = [
    "MissingImage",
    "find_missing_images",
    "index_directory",
    "plan_relinks",
    "write_missing_files_report",
]
