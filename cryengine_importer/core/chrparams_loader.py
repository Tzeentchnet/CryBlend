"""ChrParams XML loader.

Port of CgfConverter/ChrParams/ChrParams.cs + Animation.cs.

A `.chrparams` XML file lives next to a `.chr` and lists named
animations + the `.caf` / `.anim` files that contain them. Reading it
turns "load every CAF in the AnimationList" into a deterministic
operation, and lets us name Blender actions with their in-game names.

The file format is plain XML in CryEngine 3+, but we route through
`io.cry_xml` so pbxml / CryXmlB variants (rare in chrparams files but
not impossible) are handled transparently.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ..io import cry_xml
from ..models.animation import ChrParams, ChrParamsAnimation

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem


def load_chrparams(path: str, pack_fs: "IPackFileSystem") -> ChrParams | None:
    """Load and parse ``path`` (a `.chrparams` file). Returns ``None``
    when the file isn't present in ``pack_fs``."""
    if not pack_fs.exists(path):
        return None
    with pack_fs.open(path) as stream:
        root = cry_xml.read_stream(stream)
    return parse_chrparams(root, source_file_name=path)


def parse_chrparams(root, *, source_file_name: str | None = None) -> ChrParams:
    """Parse a chrparams `<Params>` root element into a `ChrParams`."""
    out = ChrParams(source_file_name=source_file_name)
    # <Params><AnimationList><Animation name=".." path=".."/>...
    anim_list = root.find("AnimationList")
    if anim_list is not None:
        animation_base_path: str | None = None
        for el in anim_list.findall("Animation"):
            name = el.get("name")
            path = el.get("path")
            lowered_name = (name or "").lower()
            if lowered_name == "$include":
                if path:
                    out.includes.append(path)
                continue
            if lowered_name == "#filepath":
                animation_base_path = _clean_path(path)
                out.animation_base_path = animation_base_path
                continue
            out.animations.append(
                ChrParamsAnimation(
                    name=name,
                    path=path,
                    source_file_name=source_file_name,
                    base_path=animation_base_path,
                )
            )
    return out


def load_chrparams_with_includes(
    path: str,
    pack_fs: "IPackFileSystem",
    *,
    _seen: set[str] | None = None,
) -> ChrParams | None:
    """Load a `.chrparams` file and recursively merge `$Include` lists."""
    if not pack_fs.exists(path):
        return None
    if _seen is None:
        _seen = set()

    norm = _normalize(path)
    if norm in _seen:
        return ChrParams(source_file_name=path)
    _seen.add(norm)

    main = load_chrparams(path, pack_fs)
    if main is None:
        return None

    base_dir = str(PurePosixPath(path.replace("\\", "/")).parent)
    if base_dir == ".":
        base_dir = ""

    known: set[tuple[str, str]] = {
        ((anim.name or "").lower(), (anim.path or "").replace("\\", "/").lower())
        for anim in main.animations
    }
    for include in main.includes:
        sub = _try_load_include(include, base_dir, pack_fs, _seen)
        if sub is None:
            main.missing_includes.append(include)
            continue
        main.missing_includes.extend(sub.missing_includes)
        for anim in sub.animations:
            key = (
                (anim.name or "").lower(),
                (anim.path or "").replace("\\", "/").lower(),
            )
            if key in known:
                continue
            known.add(key)
            main.animations.append(anim)

    return main


def _try_load_include(
    include: str,
    base_dir: str,
    pack_fs: "IPackFileSystem",
    seen: set[str],
) -> ChrParams | None:
    candidates = [include, _join("game", include)]
    if base_dir:
        candidates.append(_join(base_dir, include))
    for path in candidates:
        if pack_fs.exists(path):
            return load_chrparams_with_includes(path, pack_fs, _seen=seen)
    return None


def _join(*parts: str) -> str:
    return "/".join(part.replace("\\", "/").strip("/") for part in parts if part)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lower()


def _clean_path(path: str | None) -> str | None:
    if path is None:
        return None
    cleaned = path.replace("\\", "/").strip().strip("/")
    return cleaned or None


__all__ = ["load_chrparams", "load_chrparams_with_includes", "parse_chrparams"]
