"""Character Definition (`.cdf`) XML loader.

CDF files assemble a CryEngine character from a base ``<Model>`` and an
``<AttachmentList>``. The files seen in Crysis 2 are plain XML, but this
loader routes through :mod:`io.cry_xml` so CryXmlB/pbxml variants follow
the same code path as materials and chrparams.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..io import cry_xml
from ..models.cdf import CdfAttachment, CdfDefinition, CdfModel

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    from ..io.pack_fs import IPackFileSystem


_ATTACHMENT_KNOWN_ATTRS = {
    "AName",
    "Type",
    "Binding",
    "BoneName",
    "Position",
    "Rotation",
    "Flags",
    "Material",
    "PhysPropType",
}


def load_cdf(path: str, pack_fs: "IPackFileSystem") -> CdfDefinition | None:
    """Load and parse ``path``. Returns ``None`` when absent."""
    if not pack_fs.exists(path):
        return None
    with pack_fs.open(path) as stream:
        root = cry_xml.read_stream(stream)
    return parse_cdf(root, source_file_name=path)


def parse_cdf(
    root: "Element", *, source_file_name: str | None = None
) -> CdfDefinition:
    """Parse a ``<CharacterDefinition>`` root element."""
    definition = CdfDefinition(
        source_file_name=source_file_name,
        attributes={str(k): str(v) for k, v in root.attrib.items()},
    )

    model_el = root.find("Model")
    if model_el is not None:
        definition.model = CdfModel(
            file=(model_el.get("File") or "").strip(),
            material=_clean_optional(model_el.get("Material")),
            attributes={str(k): str(v) for k, v in model_el.attrib.items()},
        )

    att_list = root.find("AttachmentList")
    if att_list is not None:
        for el in att_list.findall("Attachment"):
            definition.attachments.append(_parse_attachment(el))

    shape_el = root.find("ShapeDeformation")
    if shape_el is not None:
        definition.shape_deformation = {
            str(k): str(v) for k, v in shape_el.attrib.items()
        }

    return definition


def _parse_attachment(el: "Element") -> CdfAttachment:
    rope_lods: dict[int, dict[str, str]] = {}
    unknown: dict[str, str] = {}

    for raw_key, raw_value in el.attrib.items():
        key = str(raw_key)
        value = str(raw_value)
        lod = _parse_lod_key(key)
        if lod is not None:
            level, prop = lod
            rope_lods.setdefault(level, {})[prop] = value
        elif key not in _ATTACHMENT_KNOWN_ATTRS:
            unknown[key] = value

    return CdfAttachment(
        name=(el.get("AName") or "").strip(),
        type=(el.get("Type") or "").strip(),
        binding=(el.get("Binding") or "").strip(),
        bone_name=(el.get("BoneName") or "").strip(),
        position=_parse_float_tuple(el.get("Position"), 3, (0.0, 0.0, 0.0)),
        rotation=_parse_float_tuple(el.get("Rotation"), 4, (1.0, 0.0, 0.0, 0.0)),
        flags=_parse_int(el.get("Flags"), 0),
        material=_clean_optional(el.get("Material")),
        phys_prop_type=_clean_optional(el.get("PhysPropType")),
        rope_lods=rope_lods,
        attributes=unknown,
    )


def _parse_lod_key(key: str) -> tuple[int, str] | None:
    if not key.startswith("lod") or "_" not in key:
        return None
    prefix, prop = key.split("_", 1)
    level_text = prefix[3:]
    if not level_text.isdigit() or not prop:
        return None
    return int(level_text), prop


def _parse_float_tuple(
    value: str | None,
    count: int,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    if not value:
        return default
    try:
        parts = tuple(float(p.strip()) for p in value.split(","))
    except ValueError:
        return default
    if len(parts) != count:
        return default
    return parts


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value, 0)
    except ValueError:
        return default


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = ["load_cdf", "parse_cdf"]