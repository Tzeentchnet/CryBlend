"""CryEngine Character Definition (`.cdf`) data contracts.

CDF files are XML wrappers that describe a skinned character as a base
model plus an attachment list. The data classes here deliberately stay
plain-Python so the parser and path-planning logic can be tested without
Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CdfModel:
    """The top-level ``<Model>`` entry in a CharacterDefinition."""

    file: str = ""
    material: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class CdfAttachment:
    """One ``<Attachment>`` entry from a CDF attachment list."""

    name: str = ""
    type: str = ""
    binding: str = ""
    bone_name: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    flags: int = 0
    material: str | None = None
    phys_prop_type: str | None = None
    rope_lods: dict[int, dict[str, str]] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def has_binding(self) -> bool:
        return bool(self.binding.strip())

    @property
    def is_rope(self) -> bool:
        return (self.phys_prop_type or "").lower() == "rope"


@dataclass
class CdfDefinition:
    """Parsed representation of a CryEngine ``CharacterDefinition``."""

    source_file_name: str | None = None
    model: CdfModel | None = None
    attachments: list[CdfAttachment] = field(default_factory=list)
    shape_deformation: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)


__all__ = ["CdfAttachment", "CdfDefinition", "CdfModel"]