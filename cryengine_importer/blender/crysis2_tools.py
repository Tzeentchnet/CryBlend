"""Crysis 2 validation helpers adapted from legacy CryTools workflows.

The original XSI, Max, and Maya tools mixed UI, exporter state, and scene
validation.  This module keeps the portable pieces small and free of ``bpy``
so Blender operators can call into deterministic, unit-testable helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Mapping, Sequence


CRYSIS2_EXPORT_OPTIONS_KEY = "cryblend_c2_export_options"
CRYSIS2_OBJECT_PROPERTIES_KEY = "cryblend_c2_properties"
CRYSIS2_PHYSICALIZE_KEY = "cryblend_c2_physicalize"

CRYEXPORT_NODE_PREFIX = "CryExportNode_"
PHYSICALIZE_LABELS = ("Default", "ProxyNoDraw", "NoCollide", "Obstruct")

_MATERIAL_ID_RE = re.compile(r"^_(\d+)_(.+)$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class MaterialIdInfo:
    name: str
    material_id: int | None
    label: str
    valid_name: bool
    in_range: bool


@dataclass(frozen=True)
class MaterialIdSummary:
    materials: tuple[MaterialIdInfo, ...]
    duplicate_ids: tuple[int, ...]
    holes: tuple[int, ...]
    out_of_range: tuple[MaterialIdInfo, ...]
    missing_ids: tuple[MaterialIdInfo, ...]


@dataclass(frozen=True)
class PiecesValidation:
    references: tuple[str, ...]
    missing: tuple[str, ...]


def parse_material_id_name(name: str, *, max_id: int = 31) -> MaterialIdInfo:
    """Parse an XSI-style material name such as ``_3_metal``."""
    match = _MATERIAL_ID_RE.match(name.strip())
    if match is None:
        return MaterialIdInfo(name=name, material_id=None, label=name, valid_name=False, in_range=False)
    material_id = int(match.group(1))
    label = match.group(2)
    return MaterialIdInfo(
        name=name,
        material_id=material_id,
        label=label,
        valid_name=True,
        in_range=0 <= material_id <= max_id,
    )


def summarize_material_ids(
    material_names: Sequence[str], *, max_id: int = 31
) -> MaterialIdSummary:
    """Return duplicate, range, and hole findings for material IDs."""
    materials = tuple(parse_material_id_name(name, max_id=max_id) for name in material_names)
    ids = [info.material_id for info in materials if info.material_id is not None and info.in_range]
    duplicate_ids = tuple(sorted({material_id for material_id in ids if ids.count(material_id) > 1}))
    holes: tuple[int, ...] = ()
    if ids:
        present = set(ids)
        holes = tuple(i for i in range(min(present), max(present) + 1) if i not in present)
    return MaterialIdSummary(
        materials=materials,
        duplicate_ids=duplicate_ids,
        holes=holes,
        out_of_range=tuple(info for info in materials if info.valid_name and not info.in_range),
        missing_ids=tuple(info for info in materials if not info.valid_name),
    )


def is_valid_export_filename(stem: str) -> bool:
    """Return whether a Crysis 2 export filename stem uses XSI-safe chars."""
    return bool(_FILENAME_RE.fullmatch(stem.strip()))


def export_filename_stem(path_or_stem: str) -> str:
    """Return a filename stem without directories or extension."""
    trimmed = path_or_stem.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if "." in trimmed:
        return trimmed.rsplit(".", 1)[0]
    return trimmed


def is_cryexport_node_name(name: str) -> bool:
    """Return whether ``name`` starts with CryExportNode_, case-insensitive."""
    return name.lower().startswith(CRYEXPORT_NODE_PREFIX.lower()) and bool(
        extract_cryexport_node_suffix(name)
    )


def extract_cryexport_node_suffix(name: str) -> str:
    """Return the part after CryExportNode_ or an empty string."""
    if not name.lower().startswith(CRYEXPORT_NODE_PREFIX.lower()):
        return ""
    return name[len(CRYEXPORT_NODE_PREFIX) :]


def cryexport_node_name_from_filename(path_or_stem: str) -> str:
    """Format a CryExportNode name from an export filename or stem."""
    return f"{CRYEXPORT_NODE_PREFIX}{export_filename_stem(path_or_stem)}"


def is_excluded_node_name(name: str) -> bool:
    """Max CryTools skipped scene nodes whose names start with underscore."""
    return name.startswith("_")


def parse_export_options(text: str | Mapping[str, object] | None) -> dict[str, str]:
    """Parse Maya-style export options into string values.

    Accepts ``-key value`` tokens and also ``key=value`` / ``key:value`` rows so
    metadata edited by hand in Blender remains readable.
    """
    if text is None:
        return {}
    if isinstance(text, Mapping):
        return {str(key): _format_option_value(value) for key, value in text.items()}
    tokens = shlex.split(str(text).replace(";", " "))
    out: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "=" in token and not token.startswith("-"):
            key, value = token.split("=", 1)
            out[key] = value
            index += 1
            continue
        if ":" in token and not token.startswith("-"):
            key, value = token.split(":", 1)
            out[key] = value
            index += 1
            continue
        key = token[1:] if token.startswith("-") else token
        value = "true"
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            value = tokens[index + 1]
            index += 1
        out[key] = value
        index += 1
    return out


def format_export_options(options: Mapping[str, object]) -> str:
    """Format export options as deterministic Maya-style ``-key value`` tokens."""
    parts: list[str] = []
    for key in sorted(options):
        value = _format_option_value(options[key])
        if not key or value == "":
            continue
        parts.extend((f"-{key}", shlex.quote(value)))
    return " ".join(parts)


def parse_property_rows(text: str | Mapping[str, object] | None) -> dict[str, str]:
    """Parse legacy object-property rows from newline/semicolon text."""
    if text is None:
        return {}
    if isinstance(text, Mapping):
        return {str(key): _format_option_value(value) for key, value in text.items()}
    out: dict[str, str] = {}
    for row in str(text).replace(";", "\n").splitlines():
        item = row.strip()
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            out[key.strip()] = value.strip()
        else:
            out[item] = "true"
    return out


def validate_pieces_references(
    properties: str | Mapping[str, object] | None,
    valid_object_names: Sequence[str],
) -> PiecesValidation:
    """Validate that every ``pieces=`` reference exists in the export set."""
    rows = parse_property_rows(properties)
    pieces = rows.get("pieces") or rows.get("Pieces") or ""
    references = tuple(part for part in re.split(r"[,\s]+", pieces.strip()) if part)
    valid = set(valid_object_names)
    missing = tuple(ref for ref in references if ref not in valid)
    return PiecesValidation(references=references, missing=missing)


def normalize_physicalize_label(label: str | None) -> str:
    """Return a canonical physicalization label or ``Default``."""
    if not label:
        return PHYSICALIZE_LABELS[0]
    for known in PHYSICALIZE_LABELS:
        if known.lower() == str(label).lower():
            return known
    return PHYSICALIZE_LABELS[0]


def skin_validation_summary(
    *,
    mesh_count: int,
    meshes_without_armature: int,
    missing_armature_objects: int,
    unweighted_vertices: int,
    non_normalized_vertices: int,
    skeleton_roots: Sequence[str],
) -> list[str]:
    """Format Blender-collected skin findings for display/reporting."""
    lines = [f"Meshes checked: {mesh_count}"]
    if meshes_without_armature:
        lines.append(f"Meshes without armature: {meshes_without_armature}")
    if missing_armature_objects:
        lines.append(f"Missing armature objects: {missing_armature_objects}")
    if unweighted_vertices:
        lines.append(f"Unweighted vertices: {unweighted_vertices}")
    if non_normalized_vertices:
        lines.append(f"Non-normalized vertices: {non_normalized_vertices}")
    if skeleton_roots:
        lines.append("Skeleton roots: " + ", ".join(skeleton_roots))
    if len(lines) == 1:
        lines.append("No skin issues found.")
    return lines


def shape_key_summary(object_name: str, key_names: Sequence[str], muted_or_zero: Sequence[str]) -> list[str]:
    """Format shape-key findings for display/reporting."""
    if not key_names:
        return [f"{object_name}: no shape keys"]
    lines = [f"{object_name}: {len(key_names)} shape key(s)"]
    if muted_or_zero:
        lines.append("Muted/zero keys: " + ", ".join(muted_or_zero))
    return lines


def _format_option_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = [
    "CRYEXPORT_NODE_PREFIX",
    "CRYSIS2_EXPORT_OPTIONS_KEY",
    "CRYSIS2_OBJECT_PROPERTIES_KEY",
    "CRYSIS2_PHYSICALIZE_KEY",
    "MaterialIdInfo",
    "MaterialIdSummary",
    "PHYSICALIZE_LABELS",
    "PiecesValidation",
    "cryexport_node_name_from_filename",
    "export_filename_stem",
    "extract_cryexport_node_suffix",
    "format_export_options",
    "is_cryexport_node_name",
    "is_excluded_node_name",
    "is_valid_export_filename",
    "normalize_physicalize_label",
    "parse_export_options",
    "parse_material_id_name",
    "parse_property_rows",
    "shape_key_summary",
    "skin_validation_summary",
    "summarize_material_ids",
    "validate_pieces_references",
]