"""Tint-palette presets (Phase 11).

Plain JSON sidecars — ``{"DiffuseTint1": [r, g, b], ...}`` — with a
``schema`` field so future format changes can migrate cleanly. Lives
under ``materials/`` so the loaders are unit-testable without `bpy`.

The Blender bridge in `blender/panel.py` reads the dict and writes
each entry into the matching ``Tint_<key>`` ``ShaderNodeRGB`` node
created by `blender/material_builder.py::_wire_tint_palette`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1


class TintPresetError(ValueError):
    """Raised when a preset file is malformed."""


def save_preset(
    path: str | Path,
    tints: Mapping[str, tuple[float, float, float]],
    *,
    material_name: str | None = None,
) -> None:
    """Write ``tints`` to ``path`` as JSON.

    ``tints`` keys are PublicParam names (e.g. ``"DiffuseTint1"``);
    values are RGB triples in [0, 1]. Existing files are overwritten.
    """
    payload = {
        "schema": SCHEMA_VERSION,
        "material": str(material_name) if material_name else "",
        "tints": {
            str(k): [float(v[0]), float(v[1]), float(v[2])]
            for k, v in tints.items()
        },
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def load_preset(path: str | Path) -> dict[str, tuple[float, float, float]]:
    """Load a preset and return ``{key: (r, g, b)}``.

    Migrates older schema versions transparently. Raises
    :class:`TintPresetError` when the file is structurally invalid
    (missing ``tints`` mapping or non-triple values).
    """
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TintPresetError(f"invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise TintPresetError(f"{path}: top-level must be an object")

    tints = data.get("tints")
    if tints is None:
        # Legacy/loose form: the entire dict *is* the tint mapping
        # (no ``schema`` / ``tints`` envelope). Tolerate it.
        tints = {k: v for k, v in data.items() if k not in ("schema", "material")}

    if not isinstance(tints, dict):
        raise TintPresetError(f"{path}: 'tints' must be an object")

    out: dict[str, tuple[float, float, float]] = {}
    for key, value in tints.items():
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 3
            or not all(isinstance(c, (int, float)) for c in value)
        ):
            raise TintPresetError(
                f"{path}: tint {key!r} must be a 3-element numeric list"
            )
        out[str(key)] = (float(value[0]), float(value[1]), float(value[2]))
    return out


def default_preset_path(mtl_path: str | Path, material_name: str) -> Path:
    """Sibling JSON path for ``material_name`` next to ``mtl_path``.

    Used as the default path picker target for save/load operators.
    """
    p = Path(mtl_path)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in material_name)
    return p.with_name(f"{p.stem}.{safe}.tint.json")


__all__ = [
    "SCHEMA_VERSION",
    "TintPresetError",
    "default_preset_path",
    "load_preset",
    "save_preset",
]
