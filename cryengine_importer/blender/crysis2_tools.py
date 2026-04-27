"""Crysis 2 validation helpers adapted from legacy CryTools workflows.

The original XSI, Max, and Maya tools mixed UI, exporter state, and scene
validation.  This module keeps the portable pieces small and free of ``bpy``
so Blender operators can call into deterministic, unit-testable helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Literal, Mapping, Sequence


CRYSIS2_EXPORT_OPTIONS_KEY = "cryblend_c2_export_options"
CRYSIS2_OBJECT_PROPERTIES_KEY = "cryblend_c2_properties"
CRYSIS2_PHYSICALIZE_KEY = "cryblend_c2_physicalize"

CRYEXPORT_NODE_PREFIX = "CryExportNode_"
CRYEXPORT_NODE_SUFFIX = "_CryExportNode"
PHYSICALIZE_LABELS = ("Default", "ProxyNoDraw", "NoCollide", "Obstruct")

CryToolsProfileKey = Literal["CRYSIS1", "CRYSIS2", "CRYSIS3"]

CRYSIS1 = "CRYSIS1"
CRYSIS2 = "CRYSIS2"
CRYSIS3 = "CRYSIS3"

_MATERIAL_ID_RE = re.compile(r"^_(\d+)_(.+)$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_C1_LOD_RE = re.compile(r"-LOD([1-4])-", re.IGNORECASE)


@dataclass(frozen=True)
class CryToolsProfile:
    key: CryToolsProfileKey
    display_label: str
    export_node_style: Literal["suffix", "prefix", "c3_prefix"]
    export_root_prefixes: tuple[str, ...]
    max_skin_influences: int
    export_filetype_labels: tuple[str, ...]
    rc_note: str
    lod_note: str
    piece_note: str


CRYTOOLS_PROFILES: dict[CryToolsProfileKey, CryToolsProfile] = {
    CRYSIS1: CryToolsProfile(
        key=CRYSIS1,
        display_label="Crysis 1 / CE2",
        export_node_style="suffix",
        export_root_prefixes=(CRYEXPORT_NODE_SUFFIX,),
        max_skin_influences=5,
        export_filetype_labels=("CGF", "CGA", "CHR", "CAF"),
        rc_note="Legacy RC profiles commonly use /skipmateriallibrarycreation for CE2 assets.",
        lod_note="Use _LOD1_ through _LOD4_; legacy -LOD#- markers are detected for cleanup.",
        piece_note="Breakable child pieces commonly use -piece names and pieces= object properties.",
    ),
    CRYSIS2: CryToolsProfile(
        key=CRYSIS2,
        display_label="Crysis 2",
        export_node_style="prefix",
        export_root_prefixes=(CRYEXPORT_NODE_PREFIX,),
        max_skin_influences=5,
        export_filetype_labels=("CGF", "CGA", "CHR", "CAF"),
        rc_note="Use the project's Crysis 2 Resource Compiler profile when exporting.",
        lod_note="Keep LOD pieces explicitly named and grouped under the export node.",
        piece_note="Validate pieces= references against objects in the export set.",
    ),
    CRYSIS3: CryToolsProfile(
        key=CRYSIS3,
        display_label="Crysis 3",
        export_node_style="c3_prefix",
        export_root_prefixes=("CryExport_", CRYEXPORT_NODE_PREFIX),
        max_skin_influences=8,
        export_filetype_labels=("CGF", "CGA", "CHR", "SKIN", "CAF"),
        rc_note="Use the Crysis 3 Resource Compiler profile and game-specific export type metadata.",
        lod_note="Crysis 3 audit accepts CryExport_ and CryExportNode_ roots.",
        piece_note="Destroyable metadata lives on object UDP tags such as entity, rotaxes, and sizevar.",
    ),
}


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


def get_crytools_profile(profile: str | CryToolsProfile | None = None) -> CryToolsProfile:
    """Return a target profile, defaulting to the existing Crysis 2 behavior."""
    if isinstance(profile, CryToolsProfile):
        return profile
    key = (profile or CRYSIS2).upper()
    try:
        return CRYTOOLS_PROFILES[key]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"Unknown CryTools profile: {profile!r}") from exc


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


def is_cryexport_node_name(name: str, *, profile: str | CryToolsProfile | None = None) -> bool:
    """Return whether ``name`` matches the target CryExport node convention."""
    return bool(extract_cryexport_node_suffix(name, profile=profile))


def extract_cryexport_node_suffix(name: str, *, profile: str | CryToolsProfile | None = None) -> str:
    """Return the export stem from a CryExport node name or an empty string."""
    target = get_crytools_profile(profile)
    lower = name.lower()
    if target.export_node_style == "suffix":
        suffix = CRYEXPORT_NODE_SUFFIX.lower()
        if not lower.endswith(suffix):
            return ""
        return name[: -len(CRYEXPORT_NODE_SUFFIX)]
    for prefix in target.export_root_prefixes:
        if lower.startswith(prefix.lower()):
            return name[len(prefix) :]
    return ""


def cryexport_node_name_from_filename(path_or_stem: str, *, profile: str | CryToolsProfile | None = None) -> str:
    """Format a CryExportNode name from an export filename or stem."""
    stem = export_filename_stem(path_or_stem)
    target = get_crytools_profile(profile)
    if target.export_node_style == "suffix":
        return f"{stem}{CRYEXPORT_NODE_SUFFIX}"
    if target.export_node_style == "c3_prefix":
        return f"CryExport_{stem}"
    return f"{CRYEXPORT_NODE_PREFIX}{stem}"


def detect_crysis1_lod_level(name: str) -> int | None:
    """Return a CE2 legacy ``-LOD#-`` level, if present."""
    match = _C1_LOD_RE.search(name)
    return int(match.group(1)) if match else None


def suggest_crysis1_lod_name(name: str) -> str:
    """Suggest ``_LOD#_`` normalization for legacy CE2 ``-LOD#-`` names."""
    return _C1_LOD_RE.sub(lambda match: f"_LOD{match.group(1)}_", name)


def is_crysis1_piece_child(name: str) -> bool:
    """Return whether ``name`` looks like a CE2 breakable ``-piece`` child."""
    return "-piece" in name.lower()


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
    *,
    profile: str | CryToolsProfile | None = None,
) -> PiecesValidation:
    """Validate that every ``pieces=`` reference exists in the export set."""
    rows = parse_property_rows(properties)
    pieces = rows.get("pieces") or rows.get("Pieces") or ""
    references = tuple(part for part in re.split(r"[,\s]+", pieces.strip()) if part)
    target = get_crytools_profile(profile)
    valid = set(valid_object_names)
    missing = tuple(
        ref
        for ref in references
        if ref not in valid and not (target.key == CRYSIS1 and detect_crysis1_lod_level(ref))
    )
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
    "CRYSIS1",
    "CRYSIS2",
    "CRYSIS3",
    "CRYTOOLS_PROFILES",
    "CRYEXPORT_NODE_PREFIX",
    "CRYEXPORT_NODE_SUFFIX",
    "CRYSIS2_EXPORT_OPTIONS_KEY",
    "CRYSIS2_OBJECT_PROPERTIES_KEY",
    "CRYSIS2_PHYSICALIZE_KEY",
    "CryToolsProfile",
    "MaterialIdInfo",
    "MaterialIdSummary",
    "PHYSICALIZE_LABELS",
    "PiecesValidation",
    "cryexport_node_name_from_filename",
    "detect_crysis1_lod_level",
    "export_filename_stem",
    "extract_cryexport_node_suffix",
    "format_export_options",
    "get_crytools_profile",
    "is_crysis1_piece_child",
    "is_cryexport_node_name",
    "is_excluded_node_name",
    "is_valid_export_filename",
    "normalize_physicalize_label",
    "parse_export_options",
    "parse_material_id_name",
    "parse_property_rows",
    "shape_key_summary",
    "skin_validation_summary",
    "suggest_crysis1_lod_name",
    "summarize_material_ids",
    "validate_pieces_references",
]