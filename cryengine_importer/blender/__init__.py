"""Blender-side modules.

The ONLY modules in the package that are allowed to ``import bpy``.
Keeps `cryengine_importer.{io,core,models,materials,enums}` testable
without Blender installed.
"""
