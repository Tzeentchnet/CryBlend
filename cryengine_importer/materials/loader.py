"""Load `.mtl` files from a pack file system.

Mirrors `Utilities/MaterialUtilities.cs` (the FromStream / FromFile
helpers) but adapted to our `IPackFileSystem` + `cry_xml` decoder so
pbxml / CryXmlB / plain XML are all handled transparently.

Texture path resolution (DDS lookup) is *not* done here — that's
`blender/material_builder.py`'s job, because it needs the pack FS at
load time anyway.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable

from ..io.cry_xml import read_stream
from ..io.pack_fs import IPackFileSystem
from .material import Material


_MTL_EXTENSIONS = (".mtl", ".xml")


def load_material(
    path: str, pack_fs: IPackFileSystem
) -> Material | None:
    """Load and parse a single material library file. Returns ``None``
    if the file cannot be found or does not parse."""
    if not pack_fs.exists(path):
        # Try the .mtl extension explicitly (the chunk name often omits it).
        if not path.lower().endswith(_MTL_EXTENSIONS):
            return load_material(path + ".mtl", pack_fs)
        return None

    try:
        with pack_fs.open(path) as stream:
            root = read_stream(stream)
    except Exception:
        return None

    mat = Material.from_xml_root(root)
    mat.source_file = path
    return mat


def load_material_libraries(
    names: Iterable[str], pack_fs: IPackFileSystem, *, object_dir: str | None = None
) -> dict[str, Material]:
    """Load all named libraries; returns a ``{stem: Material}`` map.

    ``names`` is the list collected by `CryEngine.material_library_files`.
    ``object_dir``, when set, is prepended for relative names whose
    direct lookup misses (mirrors the C# ``-objectdir`` argument).
    """
    out: dict[str, Material] = {}
    for raw in names:
        candidates: list[str] = []
        candidates.append(raw)
        if object_dir and not raw.lower().startswith(object_dir.lower()):
            joined = str(PurePosixPath(object_dir) / raw)
            candidates.append(joined)

        loaded: Material | None = None
        for cand in candidates:
            loaded = load_material(cand, pack_fs)
            if loaded is not None:
                break

        if loaded is None:
            continue

        key = PurePosixPath(raw).stem.lower() or raw.lower()
        out[key] = loaded
    return out


__all__ = ["load_material", "load_material_libraries"]
