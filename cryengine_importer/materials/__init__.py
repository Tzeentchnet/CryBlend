"""Material parsing layer (Phase 2).

Pure-Python (no `bpy`) — the Blender translation lives in
`blender/material_builder.py`.
"""

from __future__ import annotations

from .loader import load_material, load_material_libraries
from .material import Material, MaterialFlags, Texture

__all__ = [
    "Material",
    "MaterialFlags",
    "Texture",
    "load_material",
    "load_material_libraries",
]
