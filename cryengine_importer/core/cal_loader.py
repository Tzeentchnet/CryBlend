"""ArcheAge ``.cal`` animation list parser.

Port of CgfConverter/Cal/CalFile.cs (v2.0.0).

A ``.cal`` file is a simple text file with key=value lines:

* ``#filepath = path`` — base path for animation files
* ``$Include = path.cal`` — include another cal file (recursive)
* ``animation_name = relative/path.caf`` — animation entries
* lines starting with ``//`` or ``--`` are comments; inline ``//``
  comments after the value are also stripped
* ``_NAME = ...`` locomotion-group entries are ignored
* other ``$``/``#`` directives are ignored

Used as an alternative to ``.chrparams`` for ArcheAge characters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem


@dataclass
class CalFile:
    """Parsed ``.cal`` file contents."""

    file_path: str | None = None
    """Base path for animation files (from ``#filepath`` directive)."""

    animations: dict[str, str] = field(default_factory=dict)
    """Map of animation name → relative ``.caf`` path. Case-insensitive
    key lookups are the caller's responsibility (mirrors C# which uses
    ``StringComparer.OrdinalIgnoreCase``)."""

    includes: list[str] = field(default_factory=list)
    """Include directives (``$Include``) in declaration order."""


def parse_cal(text: str) -> CalFile:
    """Parse the body of a ``.cal`` file into a :class:`CalFile`.

    Mirrors the line-by-line scan in ``CalFile.Parse``."""
    cal = CalFile()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("//") or line.startswith("--"):
            continue

        eq = line.find("=")
        if eq < 0:
            continue

        key = line[:eq].strip()
        value = line[eq + 1 :].strip()

        # Strip inline `//` comments from the value.
        cmt = value.find("//")
        if cmt >= 0:
            value = value[:cmt].strip()

        klow = key.lower()
        if klow == "#filepath":
            cal.file_path = value
        elif klow == "$include":
            cal.includes.append(value)
        elif key.startswith("$") or key.startswith("#"):
            continue
        elif key.startswith("_"):
            # Locomotion-group reference (e.g. ``_NORMAL_WALK``) — skip.
            continue
        else:
            cal.animations[key] = value

    return cal


def load_cal(path: str, pack_fs: "IPackFileSystem") -> CalFile:
    """Load and parse a single ``.cal`` file from the pack FS.

    Use :func:`load_cal_with_includes` to follow ``$Include``
    directives recursively (recommended)."""
    with pack_fs.open(path) as stream:
        text = stream.read().decode("utf-8", errors="replace")
    return parse_cal(text)


def load_cal_with_includes(
    cal_path: str,
    pack_fs: "IPackFileSystem",
    *,
    _seen: set[str] | None = None,
) -> CalFile:
    """Load a ``.cal`` file and recursively resolve every ``$Include``.

    For each include path the loader tries (in order, mirroring v2):

    1. The path as-is, relative to the pack-fs root.
    2. The path prefixed with ``game/`` (ArcheAge stores files under
       ``game/`` in extracted dumps).
    3. The path resolved against the including file's directory.

    The first variant that exists is loaded. Already-visited paths
    are skipped to break include cycles. Animations from included
    files are merged into the main file's table without overriding
    existing entries (parent wins). The main file's ``file_path`` is
    inherited from the first include that defines one if it isn't
    set locally.
    """
    if _seen is None:
        _seen = set()

    norm = _normalize(cal_path)
    if norm in _seen:
        return CalFile()
    _seen.add(norm)

    main = load_cal(cal_path, pack_fs)
    cal_dir = str(PurePosixPath(cal_path).parent).replace("\\", "/")
    if cal_dir == ".":
        cal_dir = ""

    for include in main.includes:
        sub = _try_load_include(include, cal_dir, pack_fs, _seen)
        if sub is None:
            continue
        for name, rel in sub.animations.items():
            main.animations.setdefault(name, rel)
        if not main.file_path and sub.file_path:
            main.file_path = sub.file_path

    return main


def _try_load_include(
    include: str,
    cal_dir: str,
    pack_fs: "IPackFileSystem",
    seen: set[str],
) -> CalFile | None:
    candidates: list[str] = [include]
    candidates.append(_join("game", include))
    if cal_dir:
        candidates.append(_join(cal_dir, include))
    for path in candidates:
        if pack_fs.exists(path):
            return load_cal_with_includes(path, pack_fs, _seen=seen)
    return None


def _join(*parts: str) -> str:
    s = "/".join(p.replace("\\", "/").strip("/") for p in parts if p)
    return s


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lower()


__all__ = ["CalFile", "parse_cal", "load_cal", "load_cal_with_includes"]
