"""Plain-Python geometry/scene dataclasses (no `bpy` imports).

These mirror the C# `CgfConverter/Models/GeometryInfo.cs` and
`CgfConverter/Models/Datastream.cs` data, but reduced to what the
Blender bridge actually consumes. Keeping them here lets the mesh
builder be unit-tested without Blender.
"""

from .geometry import MeshGeometry, SubsetRange

__all__ = ["MeshGeometry", "SubsetRange"]
