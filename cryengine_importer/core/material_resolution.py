"""Pure material lookup helpers shared by Blender import paths.

Classic CryEngine assets store ``ChunkNode.material_id`` as a chunk id
pointing at a ``ChunkMtlName``. IVO assets are different: their chunk
ids are synthetic and material references are indices from the IVO
submesh / ``NodeMeshCombo`` tables. Keeping that distinction here makes
the Blender bridge small while leaving the lookup unit-testable without
``bpy``.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .chunks.mtl_name import ChunkMtlName
from .chunks.node_mesh_combo import ChunkNodeMeshCombo

if TYPE_CHECKING:
    from .chunks.node import ChunkNode
    from .cryengine import CryEngine
    from ..materials.material import Material


def resolve_material_for_subset(
    cryengine: "CryEngine", node: "ChunkNode", mat_id: int
) -> "Material | None":
    """Return the parsed material for ``node`` / subset ``mat_id``.

    For classic assets, ``node.material_id`` is a ``ChunkMtlName`` id.
    For IVO CGA/CGF/SKIN assets, ``mat_id`` is an index into the IVO
    material tables, so chunk-id lookup would always miss.
    """
    if not cryengine.materials:
        return None

    if getattr(cryengine, "is_ivo", False):
        return _resolve_ivo_material(cryengine, mat_id)

    return _resolve_legacy_material(cryengine, node, mat_id)


def _resolve_legacy_material(
    cryengine: "CryEngine", node: "ChunkNode", mat_id: int
) -> "Material | None":
    library = None

    if cryengine.models and node.material_id != 0:
        mtl_chunk = cryengine.models[0].chunk_map.get(node.material_id)
        if isinstance(mtl_chunk, ChunkMtlName) and mtl_chunk.name:
            key = _library_key(mtl_chunk.name)
            library = cryengine.materials.get(key)

    if library is not None:
        return _select_sub_material(library, mat_id)

    # Some CGA/CGF files do not carry a usable MtlName chunk but do ship
    # a sibling .mtl. If only one library resolved, use it conservatively.
    ordered = _ordered_libraries(cryengine)
    if len(ordered) == 1:
        return _select_sub_material(ordered[0], mat_id)
    return None


def _resolve_ivo_material(cryengine: "CryEngine", mat_id: int) -> "Material | None":
    ordered = _ordered_libraries(cryengine)
    if not ordered:
        return None

    material_index = _ivo_material_index(cryengine, mat_id)
    if material_index is None:
        material_index = mat_id

    if 0 <= material_index < len(ordered):
        # IVO MtlName chunks commonly name one concrete material file per
        # entry, so selecting the library is the important step. If that
        # file itself is a multi-material library, fall back to the subset
        # id before using the first child.
        library = ordered[material_index]
        selected = _select_sub_material(library, mat_id)
        if selected is not None:
            return selected
        return _select_sub_material(library, 0)

    if len(ordered) == 1:
        return _select_sub_material(ordered[0], mat_id)
    return None


def _ivo_material_index(cryengine: "CryEngine", mat_id: int) -> int | None:
    if not cryengine.models:
        return None
    for chunk in cryengine.models[0].chunk_map.values():
        if not isinstance(chunk, ChunkNodeMeshCombo):
            continue
        if 0 <= mat_id < len(chunk.material_indices):
            return int(chunk.material_indices[mat_id])
    return None


def _ordered_libraries(cryengine: "CryEngine") -> list["Material"]:
    ordered: list["Material"] = []
    seen: set[str] = set()

    for name in getattr(cryengine, "material_library_files", ()):  # preserve file order
        key = _library_key(name)
        material = cryengine.materials.get(key)
        if material is None or key in seen:
            continue
        ordered.append(material)
        seen.add(key)

    for key, material in cryengine.materials.items():
        if key in seen:
            continue
        ordered.append(material)
        seen.add(key)

    return ordered


def _select_sub_material(library: "Material", mat_id: int) -> "Material | None":
    subs = library.sub_materials or [library]
    if 0 <= mat_id < len(subs):
        return subs[mat_id]
    return subs[0] if subs else None


def _library_key(name: str) -> str:
    return PurePosixPath(name).stem.lower() or name.lower()


__all__ = ["resolve_material_for_subset"]