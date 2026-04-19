"""CryEngine model importer for Blender 5+.

Pure-Python port of the C# CgfConverter project. The package is split
so that the `cryengine_importer.blender` subpackage is the *only* part
that imports `bpy`; everything else (parsing, materials, models) is
plain Python and can be unit-tested without Blender.
"""

from __future__ import annotations

bl_info = {
    "name": "CryEngine Importer",
    "author": "Cryengine-Converter contributors",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "File > Import > CryEngine (.cgf/.chr/.skin)",
    "description": "Import CryEngine model files (.cgf, .cga, .chr, .skin)",
    "category": "Import-Export",
}


def register() -> None:
    # Import lazily so non-bpy environments (pytest) can import the
    # package without Blender being available.
    from .blender import addon

    addon.register()


def unregister() -> None:
    from .blender import addon

    addon.unregister()
