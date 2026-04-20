"""Pre-import canonicalization for the bulk-import flow.

Lives outside ``addon.py`` so the logic is unit-testable without a
working ``bpy`` install. ``addon.py`` re-exports
:func:`_canonicalize_import_paths` for backwards compatibility.
"""

from __future__ import annotations

import os

from ..core.cryengine import COMPANION_GEOMETRY_PRIMARY


def canonicalize_import_paths(paths):
    """Filter a raw list of dropped/selected file paths down to the
    set of *primary* assets to import.

    Two normalisations are applied:

    1. Case- and separator-insensitive dedup via ``os.path.normcase`` /
       ``os.path.normpath`` (matches NTFS semantics on Windows; a no-op
       casing-wise on POSIX).
    2. When a path is a geometry companion (``.cgam`` / ``.cgfm`` /
       ``.chrm`` / ``.skinm``) and the corresponding primary file is
       *also* in the batch, the companion is dropped — the primary's
       import will pull the companion in automatically via
       ``CryEngine._auto_detect_companion``. A companion whose primary
       isn't in the batch is kept as-is so users can still drop a
       stand-alone ``*m`` file (the import path then transparently
       redirects to the on-disk primary if present, see
       ``CryEngine.process``).

    Returns ``(kept_paths, skipped_companion_count)``. ``kept_paths``
    preserves the original input ordering of the survivors.
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for p in paths:
        key = os.path.normcase(os.path.normpath(p))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    primary_keys = {
        os.path.normcase(os.path.normpath(p))
        for p in deduped
        if os.path.splitext(p)[1].lower() not in COMPANION_GEOMETRY_PRIMARY
    }

    kept: list[str] = []
    skipped = 0
    for p in deduped:
        ext = os.path.splitext(p)[1].lower()
        primary_ext = COMPANION_GEOMETRY_PRIMARY.get(ext)
        if primary_ext is None:
            kept.append(p)
            continue
        primary_path = os.path.splitext(p)[0] + primary_ext
        primary_key = os.path.normcase(os.path.normpath(primary_path))
        if primary_key in primary_keys:
            skipped += 1
            continue
        kept.append(p)
    return kept, skipped


__all__ = ["canonicalize_import_paths"]
