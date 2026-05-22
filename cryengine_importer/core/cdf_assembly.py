"""Path planning helpers for CDF imports.

This module resolves a parsed :class:`CdfDefinition` against an
``IPackFileSystem`` and records what should be imported. It does not
create Blender objects; the Blender bridge consumes the plan and reuses
the existing ``CryEngine`` loader for every referenced CHR/CGF asset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ..models.cdf import CdfAttachment, CdfDefinition
from .cdf_loader import load_cdf

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem


_HIDDEN_VARIANT_FLAGS = {458753}
_VISIBLE_VARIANT_FLAGS = {0, 32770}


@dataclass
class CdfAttachmentPlan:
    attachment: CdfAttachment
    resolved_binding: str | None = None
    material: str | None = None
    status: str = "empty"  # "bound" | "missing" | "empty"
    visible: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass
class CdfAssemblyPlan:
    definition: CdfDefinition
    cdf_path: str
    model_path: str | None = None
    model_material: str | None = None
    attachments: list[CdfAttachmentPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def import_paths(self) -> list[str]:
        out: list[str] = []
        if self.model_path:
            out.append(self.model_path)
        out.extend(
            p.resolved_binding
            for p in self.attachments
            if p.resolved_binding is not None
        )
        return out


def build_cdf_assembly_plan(
    definition: CdfDefinition,
    pack_fs: "IPackFileSystem",
    *,
    cdf_path: str | None = None,
    visibility_mode: str = "auto",
) -> CdfAssemblyPlan:
    """Resolve base and attachment asset paths for ``definition``."""
    source = cdf_path or definition.source_file_name or ""
    plan = CdfAssemblyPlan(
        definition=definition,
        cdf_path=source,
        model_material=definition.model.material if definition.model else None,
    )

    if definition.model is None or not definition.model.file:
        plan.warnings.append("CDF has no base Model File")
    else:
        resolved = resolve_cdf_reference(
            definition.model.file, pack_fs, source_file_name=source
        )
        if resolved is None:
            plan.warnings.append(
                f"Base model not found: {definition.model.file}"
            )
        else:
            plan.model_path = resolved

    inherited_material = plan.model_material
    for attachment in definition.attachments:
        material = attachment.material or inherited_material
        visible = infer_attachment_visibility(
            attachment, mode=visibility_mode
        )
        att_plan = CdfAttachmentPlan(
            attachment=attachment,
            material=material,
            visible=visible,
        )

        if not attachment.has_binding:
            att_plan.status = "empty"
        else:
            resolved = resolve_cdf_reference(
                attachment.binding, pack_fs, source_file_name=source
            )
            if resolved is None:
                att_plan.status = "missing"
                att_plan.warnings.append(
                    f"Attachment binding not found: {attachment.binding}"
                )
            else:
                att_plan.status = "bound"
                att_plan.resolved_binding = resolved

        plan.attachments.append(att_plan)

    return plan


def resolve_cdf_reference(
    reference: str,
    pack_fs: "IPackFileSystem",
    *,
    source_file_name: str | None = None,
) -> str | None:
    """Resolve a CDF model/binding path against ``pack_fs``.

    CDFs commonly store game-root-relative paths like
    ``objects/characters/foo.chr``. Some hand-authored files also use
    paths relative to the CDF itself, so this probes both forms.
    """
    ref = _normalise_slashes(reference)
    if not ref:
        return None

    candidates = [ref]
    if source_file_name:
        source_dir = PurePosixPath(_normalise_slashes(source_file_name)).parent
        if str(source_dir) not in ("", "."):
            candidates.append(str(source_dir / ref))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if pack_fs.exists(candidate):
            return candidate
    return None


def find_cdfs_for_model(
    model_path: str,
    pack_fs: "IPackFileSystem",
) -> list[str]:
    """Return nearby CDF files whose ``<Model File>`` references ``model_path``."""
    model_norm = _normalise_compare_path(model_path)
    model_name = PurePosixPath(model_norm).name
    folder = PurePosixPath(_normalise_slashes(model_path)).parent
    root_folder = str(folder) in ("", ".")
    pattern = "*" if root_folder else str(folder / "*")

    matches: list[str] = []
    for cdf_path in pack_fs.glob(pattern):
        if root_folder and "/" in _normalise_slashes(cdf_path):
            continue
        if PurePosixPath(cdf_path).suffix.lower() != ".cdf":
            continue
        definition = load_cdf(cdf_path, pack_fs)
        if definition is None or definition.model is None:
            continue
        ref_norm = _normalise_compare_path(definition.model.file)
        if ref_norm == model_norm or PurePosixPath(ref_norm).name == model_name:
            matches.append(cdf_path)
    matches.sort(key=str.lower)
    return matches


def find_cdf_models_for_attachment(
    attachment_path: str,
    pack_fs: "IPackFileSystem",
) -> list[str]:
    """Return CDF base models whose attachments reference ``attachment_path``.

    Some CryEngine characters are imported by selecting a visible skin
    ``.chr``/``.skin`` even though the animation list belongs to the
    invisible CDF base skeleton. This scans nearby CDFs and returns the
    resolved ``<Model File>`` paths for matching attachment bindings.
    """
    attachment_slash = _normalise_slashes(attachment_path)
    attachment_norm = _normalise_compare_path(attachment_path)
    attachment_name = PurePosixPath(attachment_norm).name
    attachment_has_folder = "/" in attachment_slash
    folder = PurePosixPath(attachment_slash).parent
    root_folder = str(folder) in ("", ".")
    pattern = "*" if root_folder else str(folder / "*")

    matches: list[str] = []
    seen: set[str] = set()
    for cdf_path in pack_fs.glob(pattern):
        if root_folder and "/" in _normalise_slashes(cdf_path):
            continue
        if PurePosixPath(cdf_path).suffix.lower() != ".cdf":
            continue
        definition = load_cdf(cdf_path, pack_fs)
        if definition is None or definition.model is None:
            continue
        if not _cdf_references_attachment(
            definition,
            cdf_path,
            attachment_norm,
            attachment_name,
            attachment_has_folder,
            pack_fs,
        ):
            continue
        model_path = resolve_cdf_reference(
            definition.model.file,
            pack_fs,
            source_file_name=cdf_path,
        )
        if model_path is None:
            continue
        key = _normalise_compare_path(model_path)
        if key in seen:
            continue
        seen.add(key)
        matches.append(model_path)

    matches.sort(key=str.lower)
    return matches


def _cdf_references_attachment(
    definition: CdfDefinition,
    cdf_path: str,
    attachment_norm: str,
    attachment_name: str,
    attachment_has_folder: bool,
    pack_fs: "IPackFileSystem",
) -> bool:
    for attachment in definition.attachments:
        if not attachment.has_binding:
            continue
        binding_norm = _normalise_compare_path(attachment.binding)
        if binding_norm == attachment_norm:
            return True
        resolved = resolve_cdf_reference(
            attachment.binding,
            pack_fs,
            source_file_name=cdf_path,
        )
        if resolved is not None and _normalise_compare_path(resolved) == attachment_norm:
            return True
        if not attachment_has_folder and PurePosixPath(binding_norm).name == attachment_name:
            return True
    return False


def infer_attachment_visibility(
    attachment: CdfAttachment,
    *,
    mode: str = "auto",
) -> bool:
    """Infer initial visibility while preserving the raw CDF flags."""
    if mode == "all":
        return True
    if mode == "none":
        return False
    if attachment.flags in _VISIBLE_VARIANT_FLAGS:
        return True
    if attachment.flags in _HIDDEN_VARIANT_FLAGS:
        return False
    haystack = f"{attachment.name} {attachment.binding}".lower()
    if "destroyed" in haystack or "_dead" in haystack or haystack.endswith("dead"):
        return False
    return True


def _normalise_slashes(path: str) -> str:
    return path.replace("\\", "/").lstrip("/").strip()


def _normalise_compare_path(path: str) -> str:
    return _normalise_slashes(path).lower()


__all__ = [
    "CdfAssemblyPlan",
    "CdfAttachmentPlan",
    "build_cdf_assembly_plan",
    "find_cdf_models_for_attachment",
    "find_cdfs_for_model",
    "infer_attachment_visibility",
    "resolve_cdf_reference",
]