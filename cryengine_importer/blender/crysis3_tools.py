"""Crysis 3 artist-tool helpers adapted from CryTools.

The original Max/Maya tools stored CGF metadata as user-defined object
properties such as ``mass = 12``, ``box``, ``limit = 30`` and
``rotaxes = xy``.  Blender-side operators keep the payload as a JSON
string on the object so it survives save/reopen while remaining easy to
inspect and test without ``bpy``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from typing import Any, Iterable, Mapping, Sequence


CRYSIS3_METADATA_KEY = "cryblend_c3_metadata"

PRIMITIVE_TAGS = ("box", "cylinder", "sphere", "capsule")
JOINT_TAGS = ("limit", "twist", "bend", "pull", "push", "shift")
DESTROYABLE_TAGS = ("entity", "rotaxes", "sizevar", "generic")
C3_EXPORT_ROOT_PREFIXES = ("CryExport_", "CryExportNode_")
C3_EXPORT_TYPES = (
    "static_geometry",
    "character",
    "skeleton",
    "skin",
    "animation",
)
C3_PHYSICALIZE_SURFACES = (
    "Default",
    "Physical Proxy (NoDraw)",
    "No Collide",
    "Obstruct",
)


@dataclass(frozen=True)
class Crysis3AuditIssue:
    """One Crysis 3 asset audit finding."""

    severity: str
    code: str
    subject: str
    message: str


def parse_metadata_text(raw: str | Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a normalised metadata dict from JSON or legacy UDP text."""
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return {str(k).lower(): v for k, v in raw.items()}
    text = str(raw).strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, Mapping):
        return {str(k).lower(): v for k, v in data.items()}

    out: dict[str, Any] = {}
    for line in text.replace(";", "\n").splitlines():
        item = line.strip()
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            out[key.strip().lower()] = _coerce_value(value.strip())
        else:
            out[item.lower()] = True
    return out


def serialize_metadata(metadata: Mapping[str, Any]) -> str:
    """Serialise metadata for object custom properties."""
    clean = {
        str(k).lower(): v
        for k, v in metadata.items()
        if v not in (None, "", False)
    }
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def metadata_to_udp_lines(metadata: Mapping[str, Any]) -> list[str]:
    """Format metadata in the old CryTools user-defined-property style."""
    lines: list[str] = []
    for tag in PRIMITIVE_TAGS:
        if metadata.get(tag):
            lines.append(tag)
    for key in ("mass", "density", *JOINT_TAGS, *DESTROYABLE_TAGS):
        value = metadata.get(key)
        if value in (None, "", False):
            continue
        if value is True:
            lines.append(key)
        else:
            lines.append(f"{key} = {value}")
    return lines


def apply_crysis3_settings(
    existing: Mapping[str, Any] | str | None,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply sidebar settings to existing Crysis 3 metadata."""
    metadata = parse_metadata_text(existing)

    _set_numeric(metadata, "mass", settings.get("mass"), settings.get("use_mass"))
    _set_numeric(
        metadata,
        "density",
        settings.get("density"),
        settings.get("use_density"),
    )
    if metadata.get("mass") is not None:
        metadata.pop("density", None)
    if metadata.get("density") is not None:
        metadata.pop("mass", None)

    primitive = str(settings.get("primitive", "NONE")).lower()
    for tag in PRIMITIVE_TAGS:
        metadata.pop(tag, None)
    if primitive in PRIMITIVE_TAGS:
        metadata[primitive] = True

    if settings.get("use_joint"):
        for key in JOINT_TAGS:
            _set_numeric(metadata, key, settings.get(key), True)
    else:
        for key in JOINT_TAGS:
            metadata.pop(key, None)

    if settings.get("entity"):
        metadata["entity"] = True
    else:
        metadata.pop("entity", None)

    rotaxes = str(settings.get("rotaxes", "NONE")).lower()
    if rotaxes == "none":
        metadata.pop("rotaxes", None)
    else:
        metadata["rotaxes"] = rotaxes
    _set_numeric(metadata, "sizevar", settings.get("sizevar"), settings.get("sizevar"))
    _set_numeric(metadata, "generic", settings.get("generic"), settings.get("generic"))

    return metadata


def metadata_value_matches(
    metadata: Mapping[str, Any] | str | None,
    key: str,
    comparator: str,
    value: float,
) -> bool:
    """Return whether ``metadata[key]`` satisfies a numeric comparison."""
    data = parse_metadata_text(metadata)
    raw = data.get(key.lower())
    if raw in (None, "", False, True):
        return False
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return False
    if comparator == ">":
        return number > value
    if comparator == "<":
        return number < value
    return number == value


def format_attachment_xml(
    name: str,
    position: tuple[float, float, float],
    quaternion_wxyz: tuple[float, float, float, float],
) -> str:
    """Format a CryEngine attachment helper line.

    CryTools emitted quaternion values as ``w,x,y,z`` inside the
    ``Rotation`` attribute; Blender's quaternion order is also
    ``w,x,y,z``.
    """
    safe_name = escape(name, quote=True)
    w, x, y, z = quaternion_wxyz
    px, py, pz = position
    return (
        f'    <Attachment AName="{safe_name}" Type="CA_BONE" '
        f'Rotation="{w:.6g},{x:.6g},{y:.6g},{z:.6g}" '
        f'Position="{px:.6g},{py:.6g},{pz:.6g}" '
        f'BoneName="bone_{safe_name}" Binding="" Flags="0"/>'
    )


def audit_crysis3_asset(
    objects: Iterable[Mapping[str, Any]],
    materials: Iterable[Mapping[str, Any]] | None = None,
    *,
    fps: float | None = None,
    unit_system: str | None = None,
) -> list[Crysis3AuditIssue]:
    """Return Max/Maya/XSI-inspired Crysis 3 scene audit findings.

    The records are intentionally plain mappings so Blender-bound code can
    collect scene facts while tests can exercise the rules without ``bpy``.
    """
    object_rows = list(objects)
    material_rows = list(materials or [])
    issues: list[Crysis3AuditIssue] = []

    if fps is not None and abs(float(fps) - 30.0) > 0.001:
        issues.append(
            Crysis3AuditIssue(
                "warning",
                "time-units",
                "Scene",
                "CryTools validators expect animation time to be 30 FPS.",
            )
        )
    if unit_system and unit_system.upper() not in {"METRIC", "NONE"}:
        issues.append(
            Crysis3AuditIssue(
                "warning",
                "unit-system",
                "Scene",
                "Use metric units for CryEngine-authored assets.",
            )
        )

    export_roots = [row for row in object_rows if _is_c3_export_root(row)]
    if not export_roots:
        issues.append(
            Crysis3AuditIssue(
                "warning",
                "no-export-roots",
                "Scene",
                "No CryExport root found. Original Crysis 3 tools export from CryExport_* nodes.",
            )
        )

    _audit_export_roots(export_roots, issues)
    _audit_duplicate_export_names(object_rows, issues)
    for row in object_rows:
        _audit_object(row, issues)
    _audit_materials(material_rows, issues)
    return issues


def format_crysis3_audit_report(issues: Sequence[Crysis3AuditIssue]) -> str:
    """Format audit findings as a clipboard/report-friendly text block."""
    if not issues:
        return "Crysis 3 Asset Audit\nNo issues found."
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    lines = [
        "Crysis 3 Asset Audit",
        f"Errors: {counts.get('error', 0)}  Warnings: {counts.get('warning', 0)}  Info: {counts.get('info', 0)}",
        "",
    ]
    severity_order = {"error": 0, "warning": 1, "info": 2}
    for issue in sorted(
        issues,
        key=lambda item: (severity_order.get(item.severity, 99), item.subject, item.code),
    ):
        lines.append(
            f"[{issue.severity.upper()}] {issue.subject}: {issue.message} ({issue.code})"
        )
    return "\n".join(lines)


def _is_c3_export_root(row: Mapping[str, Any]) -> bool:
    name = str(row.get("name", ""))
    export_type = str(row.get("export_type", "")).strip()
    return name.startswith(C3_EXPORT_ROOT_PREFIXES) or bool(export_type)


def _audit_export_roots(
    export_roots: Sequence[Mapping[str, Any]],
    issues: list[Crysis3AuditIssue],
) -> None:
    seen_filenames: dict[str, str] = {}
    for row in export_roots:
        name = str(row.get("name", "")) or "<unnamed>"
        export_type = str(row.get("export_type", "")).strip().lower()
        if not name.startswith(C3_EXPORT_ROOT_PREFIXES):
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "export-root-prefix",
                    name,
                    "Export roots should use the CryExport_ or CryExportNode_ prefix.",
                )
            )
        if not export_type:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "export-root-type-missing",
                    name,
                    "Export root has no Crysis 3 export type metadata.",
                )
            )
        elif export_type not in C3_EXPORT_TYPES:
            issues.append(
                Crysis3AuditIssue(
                    "error",
                    "export-root-type-invalid",
                    name,
                    f"Unknown export type '{export_type}'.",
                )
            )
        if int(row.get("child_count", 0) or 0) <= 0:
            issues.append(
                Crysis3AuditIssue(
                    "error",
                    "export-root-empty",
                    name,
                    "Export root has no children.",
                )
            )
        filename = str(row.get("filename", "")).strip() or _export_filename_from_name(name)
        if filename:
            if not _is_valid_cry_filename(filename):
                issues.append(
                    Crysis3AuditIssue(
                        "error",
                        "export-filename-invalid",
                        name,
                        "Export filenames should use only letters, numbers, and underscores.",
                    )
                )
            previous = seen_filenames.get(filename.lower())
            if previous is not None:
                issues.append(
                    Crysis3AuditIssue(
                        "error",
                        "export-filename-duplicate",
                        name,
                        f"Export filename duplicates {previous}.",
                    )
                )
            else:
                seen_filenames[filename.lower()] = name


def _audit_duplicate_export_names(
    rows: Sequence[Mapping[str, Any]],
    issues: list[Crysis3AuditIssue],
) -> None:
    seen: dict[str, str] = {}
    for row in rows:
        name = str(row.get("name", ""))
        if not name:
            continue
        clean = _clean_export_name(name)
        previous = seen.get(clean.lower())
        if previous is None:
            seen[clean.lower()] = name
        elif previous != name:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "duplicate-export-name",
                    name,
                    f"Name resolves to the same CryEngine export name as {previous}.",
                )
            )


def _audit_object(row: Mapping[str, Any], issues: list[Crysis3AuditIssue]) -> None:
    name = str(row.get("name", "")) or "<unnamed>"
    obj_type = str(row.get("type", "")).upper()
    if obj_type == "MESH":
        vertices = int(row.get("vertices", 0) or 0)
        faces = int(row.get("faces", 0) or 0)
        if vertices <= 0 or faces <= 0:
            issues.append(
                Crysis3AuditIssue(
                    "error",
                    "mesh-empty",
                    name,
                    "Mesh has no vertices or faces.",
                )
            )
        uv_layers = int(row.get("uv_layers", 0) or 0)
        if uv_layers <= 0:
            issues.append(
                Crysis3AuditIssue("warning", "mesh-no-uv", name, "Mesh has no UV set.")
            )
        elif uv_layers > 1:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "mesh-many-uvs",
                    name,
                    "Mesh has more than one UV set; old CryTools validators expected one.",
                )
            )
        color_sets = int(row.get("color_sets", 0) or 0)
        if color_sets > 1:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "mesh-many-color-sets",
                    name,
                    "Mesh has more than one color set.",
                )
            )
        degenerate_faces = int(row.get("degenerate_faces", 0) or 0)
        if degenerate_faces > 0:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "mesh-degenerate-faces",
                    name,
                    f"Mesh has {degenerate_faces} degenerate face(s).",
                )
            )
        vertices_without_uv = int(row.get("vertices_without_uv", 0) or 0)
        if vertices_without_uv > 0:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "mesh-verts-without-uv",
                    name,
                    f"Mesh has {vertices_without_uv} vertex/vertices without UVs.",
                )
            )
        if _has_non_uniform_scale(row.get("scale")):
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "object-non-uniform-scale",
                    name,
                    "Object has non-uniform scale; apply transforms before export.",
                )
            )
        _audit_skinning(row, issues)

    if _is_c3_export_root(row):
        export_type = str(row.get("export_type", "")).strip().lower()
        if export_type in {"character", "skin"} and not row.get("has_skeleton"):
            issues.append(
                Crysis3AuditIssue(
                    "error",
                    "character-no-skeleton",
                    name,
                    "CHR/SKIN export root has no skeleton or armature descendant.",
                )
            )


def _audit_skinning(row: Mapping[str, Any], issues: list[Crysis3AuditIssue]) -> None:
    if not row.get("is_skinned"):
        return
    name = str(row.get("name", "")) or "<unnamed>"
    if not row.get("has_armature"):
        issues.append(
            Crysis3AuditIssue(
                "warning",
                "skin-no-armature-modifier",
                name,
                "Skinned mesh has vertex weights but no armature modifier.",
            )
        )
    bad_weight_totals = int(row.get("bad_weight_totals", 0) or 0)
    if bad_weight_totals > 0:
        issues.append(
            Crysis3AuditIssue(
                "error",
                "skin-weights-not-normalized",
                name,
                f"{bad_weight_totals} weighted vertex/vertices do not sum to 1.",
            )
        )
    too_many_influences = int(row.get("too_many_influences", 0) or 0)
    if too_many_influences > 0:
        issues.append(
            Crysis3AuditIssue(
                "error",
                "skin-too-many-influences",
                name,
                f"{too_many_influences} vertex/vertices exceed the 8-influence CryEngine limit.",
            )
        )


def _audit_materials(
    rows: Sequence[Mapping[str, Any]],
    issues: list[Crysis3AuditIssue],
) -> None:
    material_ids: dict[int, str] = {}
    for row in rows:
        name = str(row.get("name", "")) or "<unnamed material>"
        if name.lower() == "defaultlib":
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "material-default-library-name",
                    name,
                    "Rename DefaultLib to the intended .mtl library name.",
                )
            )
        material_id = row.get("material_id")
        if material_id not in (None, ""):
            try:
                number = int(material_id)
            except (TypeError, ValueError):
                issues.append(
                    Crysis3AuditIssue(
                        "error",
                        "material-id-invalid",
                        name,
                        "Material ID is not an integer.",
                    )
                )
            else:
                previous = material_ids.get(number)
                if previous is None:
                    material_ids[number] = name
                else:
                    issues.append(
                        Crysis3AuditIssue(
                            "error",
                            "material-id-duplicate",
                            name,
                            f"Material ID {number} duplicates {previous}.",
                        )
                    )
        physicalize = str(row.get("physicalize", "")).strip()
        if physicalize and physicalize not in C3_PHYSICALIZE_SURFACES:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "material-physicalize-unknown",
                    name,
                    f"Unknown physicalize surface '{physicalize}'.",
                )
            )
    if material_ids:
        ids = sorted(material_ids)
        expected = set(range(0, ids[-1] + 1))
        missing = sorted(expected.difference(ids))
        if missing:
            issues.append(
                Crysis3AuditIssue(
                    "warning",
                    "material-id-hole",
                    "Materials",
                    "Material IDs have holes: " + ", ".join(str(v) for v in missing[:8]),
                )
            )


def _export_filename_from_name(name: str) -> str:
    for prefix in C3_EXPORT_ROOT_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def _is_valid_cry_filename(name: str) -> bool:
    stem = name.rsplit(".", 1)[0]
    return bool(stem) and re.fullmatch(r"[A-Za-z0-9_]+", stem) is not None


def _clean_export_name(name: str) -> str:
    clean = name.split("|", 1)[-1]
    clean = re.sub(r"\.\d+$", "", clean)
    clean = re.sub(r"_lod[0-5]$", "", clean, flags=re.IGNORECASE)
    return clean


def _has_non_uniform_scale(value: Any) -> bool:
    if value is None:
        return False
    try:
        scale = [abs(float(v)) for v in value]
    except (TypeError, ValueError):
        return False
    if len(scale) < 3:
        return False
    return max(scale[:3]) - min(scale[:3]) > 0.001


def _coerce_value(value: str) -> Any:
    try:
        return float(value)
    except ValueError:
        return value


def _set_numeric(
    metadata: dict[str, Any],
    key: str,
    value: Any,
    enabled: Any,
) -> None:
    if not enabled:
        metadata.pop(key, None)
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        metadata.pop(key, None)
        return
    if number == 0.0:
        metadata.pop(key, None)
    else:
        metadata[key] = number


__all__ = [
    "CRYSIS3_METADATA_KEY",
    "DESTROYABLE_TAGS",
    "JOINT_TAGS",
    "PRIMITIVE_TAGS",
    "C3_EXPORT_ROOT_PREFIXES",
    "C3_EXPORT_TYPES",
    "C3_PHYSICALIZE_SURFACES",
    "Crysis3AuditIssue",
    "audit_crysis3_asset",
    "apply_crysis3_settings",
    "format_attachment_xml",
    "format_crysis3_audit_report",
    "metadata_to_udp_lines",
    "metadata_value_matches",
    "parse_metadata_text",
    "serialize_metadata",
]
