"""Per-import metadata stamped on the Blender Collection.

Phase 11 — keeps every CryBlend-imported asset self-contained so the
sidebar UI can re-run sub-steps (resolve materials, relink textures,
edit tints, re-import) without forcing the user back through
File → Import.

Schema lives at ``collection["cryblend"]`` and is plain JSON-safe data
(``dict[str, Any]``). ``schema`` is bumped when the layout changes; the
reader migrates older versions transparently when possible.

This module is **bpy-light**: the helpers accept any object that
exposes a dict-like ``__getitem__``/``__setitem__`` and an
``id_data``-style ``name`` attribute, so they're unit-testable without
Blender. Real ``bpy.types.Collection`` instances satisfy the protocol
via the Custom Properties API.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol


KEY = "cryblend"
SCHEMA_VERSION = 1


class _CollectionLike(Protocol):
    """Minimal protocol satisfied by ``bpy.types.Collection``."""

    name: str

    def __contains__(self, key: str) -> bool: ...
    def __getitem__(self, key: str) -> Any: ...
    def __setitem__(self, key: str, value: Any) -> None: ...


def stamp_collection(
    collection: _CollectionLike,
    *,
    source_path: str,
    object_dir: str | None = None,
    material_libs: Iterable[str] = (),
    material_libs_resolved: Iterable[str] = (),
    axis_forward: str = "Y",
    axis_up: str = "Z",
    convert_axes: bool = True,
    import_related: bool = True,
    addon_version: str | None = None,
    public_params_by_material: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Stamp the import-time metadata onto ``collection``.

    Returns the stored metadata dict (a fresh copy, suitable for
    asserting in tests). All values are JSON-serialisable so the
    payload survives a Save/Reopen of the .blend file.

    ``public_params_by_material`` caches the original `<PublicParams>`
    attributes per sub-material name so the tint editor can offer a
    "Reset to .mtl values" action.
    """
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "source_path": str(source_path),
        "object_dir": str(object_dir) if object_dir else "",
        "material_libs": [str(p) for p in material_libs],
        "material_libs_resolved": [str(k) for k in material_libs_resolved],
        "axis_forward": str(axis_forward),
        "axis_up": str(axis_up),
        "convert_axes": bool(convert_axes),
        "import_related": bool(import_related),
        "addon_version": str(addon_version) if addon_version else "",
    }
    if public_params_by_material:
        payload["public_params_by_material"] = {
            str(k): {str(pk): str(pv) for pk, pv in v.items()}
            for k, v in public_params_by_material.items()
        }
    collection[KEY] = payload
    # Return a deep-ish copy so callers can mutate freely.
    return dict(payload)


def has_metadata(collection: _CollectionLike) -> bool:
    """True when ``collection`` has been stamped by a CryBlend import."""
    try:
        return KEY in collection
    except Exception:  # pragma: no cover - defensive against bpy quirks
        return False


def read_metadata(collection: _CollectionLike) -> dict[str, Any] | None:
    """Read and normalise the metadata dict, or ``None`` if not stamped.

    Performs schema migration when an older revision is found. Currently
    only ``schema=1`` exists, so the function is a passthrough plus
    defensive defaults for missing keys.
    """
    if not has_metadata(collection):
        return None
    try:
        raw = collection[KEY]
    except Exception:
        return None
    # ``raw`` may be an IDPropertyGroup-like object in bpy; normalise
    # to a plain dict for callers.
    data = dict(raw) if not isinstance(raw, dict) else raw
    schema = int(data.get("schema", 0) or 0)
    if schema < 1:
        # Pre-schema stamp; pad with defaults so downstream code doesn't
        # have to special-case missing keys.
        data.setdefault("source_path", "")
        data.setdefault("object_dir", "")
        data.setdefault("material_libs", [])
        data.setdefault("material_libs_resolved", [])
        data.setdefault("axis_forward", "Y")
        data.setdefault("axis_up", "Z")
        data.setdefault("convert_axes", True)
        data.setdefault("import_related", True)
        data.setdefault("addon_version", "")
        data["schema"] = SCHEMA_VERSION
    # Coerce the list-typed fields back to plain lists for stable
    # comparison in tests (bpy hands back IDPropertyArray).
    for list_key in ("material_libs", "material_libs_resolved"):
        if list_key in data:
            data[list_key] = list(data[list_key])
    return dict(data)


def find_cryblend_collections(scene: Any) -> list[Any]:
    """Return every Collection (recursively) under ``scene`` that has
    been stamped by a CryBlend import.

    ``scene`` is duck-typed: anything with ``collection.children`` and a
    recursive ``children`` tree. Real ``bpy.types.Scene`` satisfies it.
    """
    out: list[Any] = []
    seen: set[int] = set()

    root = getattr(scene, "collection", None)
    if root is None:
        return out

    def _walk(coll: Any) -> None:
        if id(coll) in seen:
            return
        seen.add(id(coll))
        if has_metadata(coll):
            out.append(coll)
        children = getattr(coll, "children", None) or ()
        for child in children:
            _walk(child)

    _walk(root)
    return out


def find_active_cryblend_collection(context: Any) -> Any | None:
    """Best-effort lookup of the user's "current" CryBlend collection.

    Resolution order:

    1. ``context.collection`` if it is itself stamped.
    2. The first stamped ancestor of ``context.collection``.
    3. The first stamped collection containing ``context.active_object``.
    4. The first stamped collection in the scene.
    5. ``None``.
    """
    scene = getattr(context, "scene", None)
    candidates = find_cryblend_collections(scene) if scene else []
    if not candidates:
        return None

    # 1 + 2: walk up from context.collection.
    coll = getattr(context, "collection", None)
    if coll is not None:
        cur = coll
        # ``children_recursive`` doesn't exist on every Collection; we
        # can't easily walk *up* in bpy without scanning all candidates.
        if has_metadata(cur):
            return cur
        for cand in candidates:
            children = getattr(cand, "children_recursive", None) or ()
            if cur in children:
                return cand

    # 3: containing collection of the active object.
    obj = getattr(context, "active_object", None)
    if obj is not None:
        for cand in candidates:
            objs = getattr(cand, "all_objects", None) or getattr(cand, "objects", ())
            if obj in objs:
                return cand

    # 4: fall back to the first stamped collection.
    return candidates[0]


__all__ = [
    "KEY",
    "SCHEMA_VERSION",
    "find_active_cryblend_collection",
    "find_cryblend_collections",
    "has_metadata",
    "read_metadata",
    "stamp_collection",
]
