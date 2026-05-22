"""Plain-Python geometry/scene dataclasses (no `bpy` imports).

These mirror the C# `CgfConverter/Models/GeometryInfo.cs` and
`CgfConverter/Models/Datastream.cs` data, but reduced to what the
Blender bridge actually consumes. Keeping them here lets the mesh
builder be unit-tested without Blender.
"""

from .cdf import CdfAttachment, CdfDefinition, CdfModel
from .geometry import MeshGeometry, SubsetRange

__all__ = [
	"CdfAttachment",
	"CdfDefinition",
	"CdfModel",
	"MeshGeometry",
	"SubsetRange",
]
