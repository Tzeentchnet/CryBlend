"""High-level asset aggregator.

Port of CgfConverter/CryEngine/CryEngine.cs.

A `CryEngine` instance owns one logical asset, which may span multiple
files on disk (a `.cga` and its companion `.cgam`, a `.chr` and its
`.chrm`, etc). It loads each file via the `Model` loader, then walks
the chunk graph to:

- build a flat node hierarchy with parent/children links,
- bind mesh / helper chunks onto their owning nodes,
- collect material library file names referenced by mtl_name chunks,
- consolidate skinning info across companion files (Phase 3),
- discover and load chrparams + CAF/ANIM animation clips (Phase 4).

The Star Citizen IVO branch is handled in Phase 5.
"""

from __future__ import annotations

import logging
import os
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Iterable, Iterator

from ..io.pack_fs import IPackFileSystem
from .chunks.bone_name_list import ChunkBoneNameList
from .chunks.compiled_bones import ChunkCompiledBones
from .chunks.compiled_ext_to_int_map import ChunkCompiledExtToIntMap
from .chunks.compiled_int_faces import ChunkCompiledIntFaces
from .chunks.compiled_int_skin_vertices import ChunkCompiledIntSkinVertices
from .chunks.compiled_physical_bones import ChunkCompiledPhysicalBones
from .chunks.compiled_physical_proxies import ChunkCompiledPhysicalProxies
from .chunks.controller import (
    ChunkController826,
    ChunkController827,
    ChunkController829,
    ChunkController830,
    ChunkController831,
    ChunkController905,
    ChunkMotionParameters925,
)
from .chunks.global_animation_header_caf import ChunkGlobalAnimationHeaderCAF
from .chunks.helper import ChunkHelper
from .chunks.ivo_anim_info import ChunkIvoAnimInfo
from .chunks.ivo_caf import ChunkIvoCAF
from .chunks.ivo_dba_data import ChunkIvoDBAData
from .chunks.ivo_dba_metadata import ChunkIvoDBAMetadata
from .chunks.ivo_skin_mesh import ChunkIvoSkinMesh
from .chunks.mesh import ChunkMesh
from .chunks.mtl_name import ChunkMtlName
from .chunks.node import ChunkNode, VERTEX_SCALE
from .chunks.node_mesh_combo import ChunkNodeMeshCombo
from .chunks.source_info import ChunkSourceInfo
from .chunks.timing_format import ChunkTimingFormat
from .model import Model
from ..enums import CtrlType, MtlNameType
from ..models.animation import (
    AnimationClip,
    BoneAnimationTrack,
    ChrParams,
    ObjectAnimationClip,
    ObjectAnimationTrack,
)
from ..models.skinning import SkinningInfo

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .chunk_registry import Chunk
    from ..materials.material import Material as MaterialT


_VALID_EXTENSIONS = frozenset(
    {
        ".cgf",
        ".cga",
        ".cgam",
        ".cgfm",
        ".chr",
        ".chrm",
        ".skin",
        ".skinm",
        ".anim",
        ".soc",
        ".caf",
        ".dba",
    }
)

_ANIMATION_CLIP_EXTENSIONS = frozenset({".caf", ".anim", ".dba"})

# Companion (geometry-only "m") extensions paired with their primary.
# When the user picks the companion directly we transparently load the
# primary instead so material/skinning metadata is included.
COMPANION_GEOMETRY_PRIMARY: dict[str, str] = {
    ".cgam": ".cga",
    ".cgfm": ".cgf",
    ".chrm": ".chr",
    ".skinm": ".skin",
}
# Backwards-compatible alias used internally by ``CryEngine.process``.
_COMPANION_TO_PRIMARY = COMPANION_GEOMETRY_PRIMARY


class UnsupportedFileError(ValueError):
    """Raised when the input file extension is not a CryEngine asset."""


class CryEngine:
    """Aggregates the Models that make up one logical CryEngine asset."""

    def __init__(
        self,
        input_file: str,
        pack_fs: IPackFileSystem,
        *,
        material_files: Iterable[str] | None = None,
        object_dir: str | None = None,
        load_related: bool = True,
        load_animations: bool = True,
    ) -> None:
        self.input_file = input_file
        self.pack_fs = pack_fs
        self.material_files: list[str] = (
            list(material_files) if material_files else []
        )
        self.object_dir = object_dir
        # When False, skip auto-discovery of sibling companion geometry
        # (.cgam/.chrm) and chrparams/CAF animation clips. Material
        # libraries are still resolved because they are required to
        # render the imported meshes.
        self.load_related = load_related
        self.load_animations = load_animations

        self.models: list[Model] = []
        self.animations: list[Model] = []
        self.nodes: list[ChunkNode] = []
        self.root_node: ChunkNode | None = None
        # Material library file names discovered in the chunk graph.
        self.material_library_files: list[str] = []
        # Loaded material libraries keyed by the lowercased file stem.
        # Populated by `process()` via `materials.load_material_libraries`.
        self.materials: dict[str, "MaterialT"] = {}

        # Consolidated bones / skin verts / etc. across every loaded
        # model. Populated by `_build_skinning()` (Phase 3).
        self.skinning_info: SkinningInfo = SkinningInfo()

        # Phase 4 — animation. ``chrparams`` is loaded from a sibling
        # ``<stem>.chrparams`` file when present; ``animation_clips``
        # is built from every CAF/ANIM file referenced by the chrparams
        # AnimationList (or auto-discovered alongside the input file).
        self.chrparams: ChrParams | None = None
        self.animation_models: list[Model] = []
        self.animation_clips: list[AnimationClip] = []
        self.object_animation_clips: list[ObjectAnimationClip] = []

        self._chunks_cache: list["Chunk"] | None = None

    # --- public API ----------------------------------------------------

    @staticmethod
    def supports_file(name: str) -> bool:
        return PurePosixPath(name).suffix.lower() in _VALID_EXTENSIONS

    @property
    def name(self) -> str:
        return PurePosixPath(self.input_file).stem.lower()

    @property
    def is_ivo(self) -> bool:
        return bool(self.models) and self.models[0].file_signature == "#ivo"

    @property
    def chunks(self) -> list["Chunk"]:
        """Flat list of every chunk across all loaded models."""
        if self._chunks_cache is None:
            self._chunks_cache = [
                c for m in self.models for c in m.chunk_map.values()
            ]
        return self._chunks_cache

    def process(self) -> None:
        """Load every file that belongs to this asset and build the
        node hierarchy. Equivalent to C# ``ProcessCryengineFiles()``."""
        ext = PurePosixPath(self.input_file).suffix.lower()
        if ext not in _VALID_EXTENSIONS:
            raise UnsupportedFileError(
                f"Unsupported file extension {ext!r}: expected one of "
                f"{sorted(_VALID_EXTENSIONS)}"
            )

        # If the user picked a companion geometry-only file
        # (.cgam/.cgfm/.chrm/.skinm), transparently swap to the primary
        # when it exists so material/skinning metadata is loaded too.
        primary_ext = _COMPANION_TO_PRIMARY.get(ext)
        if primary_ext is not None:
            primary_path = str(
                PurePosixPath(self.input_file).with_suffix(primary_ext)
            )
            if self.pack_fs.exists(primary_path):
                logger.info(
                    "input %s is a companion file; loading primary %s instead",
                    self.input_file,
                    primary_path,
                )
                self.input_file = primary_path

        input_files = [self.input_file]
        if self.load_related:
            self._auto_detect_companion(self.input_file, input_files)

        for path in input_files:
            with self.pack_fs.open(path) as stream:
                self.models.append(Model.from_stream(path, stream))

        self._chunks_cache = None
        sig = self.models[0].file_signature if self.models else "?"
        logger.info(
            "loaded %d file(s) for %s (signature %r): %s",
            len(self.models),
            self.name,
            sig,
            input_files,
        )
        logger.info(
            "%d total chunks across loaded files", len(self.chunks)
        )

        self._build_nodes()
        logger.info(
            "built %d nodes (%s path)",
            len(self.nodes),
            "IVO" if self.is_ivo else "legacy",
        )
        self._build_skinning()
        if self.skinning_info.has_skinning_info:
            logger.info(
                "skinning: %d compiled bones, %d physical bones, %d int verts",
                len(self.skinning_info.compiled_bones),
                len(self.skinning_info.physical_bones),
                len(self.skinning_info.int_vertices),
            )
        self._collect_material_library_files()
        self._load_materials()
        logger.info(
            "materials: %d/%d libraries resolved",
            len(self.materials),
            len(self.material_library_files),
        )
        if self.load_related and self.load_animations:
            self._load_animations()
            logger.info(
                "animations: %d clip(s) loaded", len(self.animation_clips)
            )
        self._build_object_animations()
        if self.object_animation_clips:
            logger.info(
                "object animations: %d clip(s), %d animated node(s)",
                len(self.object_animation_clips),
                sum(len(c.tracks) for c in self.object_animation_clips),
            )

    # --- companion file discovery -------------------------------------

    def _auto_detect_companion(self, path: str, input_files: list[str]) -> None:
        """Look for the geometry-only companion of a `.cga` / `.chr`
        (i.e. `.cgam` / `.chrm` / `.skinm`).

        Delegates to :func:`io.asset_resolver.resolve_companions` so
        the same logic is reusable from a future "browse pack file" UI.
        """
        from ..io.asset_resolver import resolve_companions

        companions = resolve_companions(path, self.pack_fs)
        if companions.companion is not None:
            input_files.append(companions.companion)
        else:
            logger.debug("no companion geometry file found for %s", path)

    # --- node hierarchy -----------------------------------------------

    def _build_nodes(self) -> None:
        if self.is_ivo:
            self._build_nodes_ivo()
            return

        if not self.models:
            return

        model0 = self.models[0]
        all_nodes = [
            c for c in model0.chunk_map.values() if isinstance(c, ChunkNode)
        ]
        node_by_id: dict[int, ChunkNode] = {n.id: n for n in all_nodes}

        # Reset (defensive — `process` may be called only once but the
        # ChunkNode defaults could have been mutated by a prior pass).
        for n in all_nodes:
            n.children = []
            n.parent_node = None
            n.mesh_data = None
            n.chunk_helper = None

        for node in all_nodes:
            obj = model0.chunk_map.get(node.object_node_id)

            if isinstance(obj, ChunkHelper):
                node.chunk_helper = obj
            elif isinstance(obj, ChunkMesh):
                node.mesh_data = self._resolve_mesh(node, obj)

            self.nodes.append(node)

        # Wire up parent / children links.
        for node in self.nodes:
            if node.parent_node_id != -1 and node.parent_node_id in node_by_id:
                parent = node_by_id[node.parent_node_id]
                node.parent_node = parent
                parent.children.append(node)
            else:
                if self.root_node is None:
                    self.root_node = node

    def _resolve_mesh(
        self, node: ChunkNode, mesh: ChunkMesh
    ) -> ChunkMesh:
        """When the asset is split across two files (e.g. .cga + .cgam),
        the first file's mesh chunk has MESH_IS_EMPTY set and the real
        geometry lives in the second file. Look up the matching mesh
        chunk by node name in models[1]."""
        if len(self.models) <= 1:
            return mesh

        m1 = self.models[1]
        # Find the node in model[1] with the same name.
        twin = next(
            (
                c
                for c in m1.chunk_map.values()
                if isinstance(c, ChunkNode) and c.name == node.name
            ),
            None,
        )
        if twin is None:
            # Physics-only node — keep the empty mesh from model[0].
            return mesh

        twin_obj = m1.chunk_map.get(twin.object_node_id)
        if isinstance(twin_obj, ChunkMesh):
            return twin_obj
        return mesh

    # --- IVO node hierarchy (Phase 5) ---------------------------------

    def _find_ivo_skin_mesh(self) -> ChunkIvoSkinMesh | None:
        """The IvoSkinMesh chunk lives in either the input file (rare)
        or its companion ``.skinm`` / ``.chrm`` (the typical case)."""
        for m in self.models:
            for c in m.chunk_map.values():
                if isinstance(c, ChunkIvoSkinMesh):
                    return c
        return None

    def _build_nodes_ivo(self) -> None:
        """Mirror C# CryEngine.BuildNodeStructure for ``#ivo`` assets.

        Two flavours:

        - ``.cgf`` / ``.cga``: the input file contains a
          :class:`ChunkNodeMeshCombo`; we synthesize one
          :class:`ChunkNode` per row, link parents via
          ``parent_index``, and bind the (sole) :class:`ChunkIvoSkinMesh`
          from the companion file as ``mesh_data``.
        - ``.chr`` / ``.skin``: no NodeMeshCombo; create a single root
          node carrying the IvoSkinMesh.
        """
        if not self.models:
            return

        skin_mesh = self._find_ivo_skin_mesh()

        combo: ChunkNodeMeshCombo | None = None
        for c in self.models[0].chunk_map.values():
            if isinstance(c, ChunkNodeMeshCombo) and c.number_of_nodes > 0:
                combo = c
                break

        if combo is None:
            self._build_ivo_skin_root(skin_mesh)
            return

        # NodeMeshCombo path: one synthetic ChunkNode per entry.
        nodes: list[ChunkNode] = []
        for i, entry in enumerate(combo.node_mesh_combos):
            node = ChunkNode()
            node.name = (
                combo.node_names[i]
                if i < len(combo.node_names)
                else f"node_{i}"
            )
            node.id = int(entry.id)
            node.object_node_id = -1
            node.parent_node_id = (
                -1 if entry.parent_index == 0xFFFF else int(entry.parent_index)
            )
            node.parent_node_index = int(entry.parent_index)
            node.num_children = int(entry.number_of_children)
            node.material_id = (
                int(combo.material_indices[i])
                if (
                    i < len(combo.material_indices)
                    and entry.geometry_type == 0  # IvoGeometryType.Geometry
                )
                else 0
            )
            node.transform = _matrix3x4_to_4x4(entry.bone_to_world)
            node.ivo_node_index = i
            # Bind mesh data on every "Geometry" node — all geometry
            # nodes share the single IvoSkinMesh in C#.
            if entry.geometry_type == 0 and skin_mesh is not None:
                node.mesh_data = skin_mesh  # type: ignore[assignment]
            nodes.append(node)

        # Wire parent / children by index (NodeMeshCombo uses index, not id).
        for i, node in enumerate(nodes):
            pi = node.parent_node_index
            if pi != 0xFFFF and 0 <= pi < len(nodes) and pi != i:
                node.parent_node = nodes[pi]
                nodes[pi].children.append(node)
            elif self.root_node is None:
                self.root_node = node

        self.nodes.extend(nodes)

    def _build_ivo_skin_root(self, skin_mesh: ChunkIvoSkinMesh | None) -> None:
        """Skin / chr IVO files: synthesize a single root node from the
        input file's stem and bind the IvoSkinMesh as its mesh_data."""
        node = ChunkNode()
        node.name = PurePosixPath(self.input_file).stem
        node.id = 1
        node.object_node_id = 2
        node.parent_node_id = -1
        node.parent_node_index = 0xFFFF
        node.num_children = 0
        node.material_id = 11
        if skin_mesh is not None:
            node.mesh_data = skin_mesh  # type: ignore[assignment]
        self.nodes.append(node)
        self.root_node = node

    # --- skinning ------------------------------------------------------

    def _build_skinning(self) -> None:
        """Consolidate every skinning-related chunk across all loaded
        models into ``self.skinning_info``. Mirrors how the C# Collada
        renderer pulls bones / int-skin verts / ext->int map from
        whichever Model owns them (typically the .chr's `.chrm`)."""
        if not self.models:
            return

        info = SkinningInfo()
        for m in self.models:
            for c in m.chunk_map.values():
                if isinstance(c, ChunkCompiledBones) and not info.compiled_bones:
                    info.compiled_bones = list(c.bone_list)
                elif isinstance(c, ChunkCompiledPhysicalBones) and not info.physical_bones:
                    info.physical_bones = list(c.physical_bone_list)
                elif isinstance(c, ChunkCompiledPhysicalProxies) and not info.physical_proxies:
                    info.physical_proxies = list(c.physical_proxies)
                elif isinstance(c, ChunkCompiledIntSkinVertices) and not info.int_vertices:
                    info.int_vertices = list(c.int_skin_vertices)
                elif isinstance(c, ChunkCompiledIntFaces) and not info.int_faces:
                    info.int_faces = list(c.faces)
                elif isinstance(c, ChunkCompiledExtToIntMap) and not info.ext_to_int_map:
                    info.ext_to_int_map = list(c.source)
                elif isinstance(c, ChunkBoneNameList) and not info.bone_names:
                    info.bone_names = list(c.bone_names)

        self.skinning_info = info

    # --- materials -----------------------------------------------------

    def _collect_material_library_files(self) -> None:
        if not self.models:
            return

        seen: set[str] = set()
        out: list[str] = []

        def key_for(name: str) -> str:
            return PurePosixPath(name).stem.lower() or name.lower()

        def resolve_name(name: str) -> str:
            return self._resolve_material_library_name(name)

        def add(name: str | None, *, require_existing: bool = False) -> None:
            if not name:
                return
            resolved_name = resolve_name(name)
            if require_existing and not self._material_library_exists(resolved_name):
                return
            key = key_for(resolved_name)
            if key in seen:
                return
            seen.add(key)
            out.append(resolved_name)

        explicit_keys: set[str] = set()
        for name in self.material_files:
            add(name)
            explicit_keys.add(key_for(name))

        material_chunks = [
            c
            for model in self.models
            for c in model.chunk_map.values()
            if isinstance(c, ChunkMtlName)
        ]
        referenced_material_ids = {
            int(node.material_id)
            for node in self.nodes
            if getattr(node, "material_id", 0)
        }
        referenced_library_ids = {
            c.id
            for c in material_chunks
            if c.id in referenced_material_ids and _is_material_library_chunk(c)
        }
        chunks_to_scan = (
            [c for c in material_chunks if c.id in referenced_library_ids]
            if referenced_library_ids
            else material_chunks
        )

        for c in chunks_to_scan:
            if _is_material_library_chunk(c):
                add(c.name, require_existing=bool(explicit_keys))

        sidecar = str(PurePosixPath(self.input_file).with_suffix(".mtl"))
        sidecar_key = key_for(sidecar)
        if self.pack_fs.exists(sidecar):
            has_sidecar_stem = any(key_for(name) == sidecar_key for name in out)
            if not has_sidecar_stem:
                add(sidecar)
            elif sidecar_key not in explicit_keys and _is_pathful_sidecar(sidecar):
                for index, name in enumerate(out):
                    if key_for(name) == sidecar_key and _is_bare_material_name(name):
                        out[index] = sidecar
                        break

        self.material_library_files = out

    def _resolve_material_library_name(self, name: str) -> str:
        """Resolve bare material library names relative to this asset.

        Crysis 2 chunks often store only ``marine_body`` or ``eye`` even
        though the matching library lives beside the current model as
        ``objects/.../marine_body.mtl``. When importing from a game-root
        pack FS, resolving that local path up-front lets the normal material
        loader and material-key lookup do the right thing.
        """
        cleaned = name.replace("\\", "/").strip()
        if not cleaned or not _is_bare_material_name(cleaned):
            return cleaned

        input_dir = str(PurePosixPath(self.input_file).parent)
        if input_dir not in ("", "."):
            local = str(PurePosixPath(input_dir) / cleaned)
            if self._material_library_exists(local):
                return local

        for local in self._source_info_material_library_candidates(cleaned):
            if self._material_library_exists(local):
                return local

        pattern = f"**/{cleaned}.mtl"
        matches = sorted(
            p.replace("\\", "/")
            for p in self.pack_fs.glob(pattern)
            if PurePosixPath(p).name.lower() == f"{cleaned.lower()}.mtl"
        )
        if len(matches) == 1:
            return str(PurePosixPath(matches[0]).with_suffix(""))
        return cleaned

    def _source_info_material_library_candidates(self, name: str) -> Iterator[str]:
        seen: set[str] = set()
        for model in self.models:
            for chunk in model.chunk_map.values():
                if not isinstance(chunk, ChunkSourceInfo):
                    continue
                for source_path in _source_info_pack_path_candidates(chunk.source_file):
                    source_dir = str(PurePosixPath(source_path).parent)
                    if source_dir in ("", "."):
                        continue
                    candidate = str(PurePosixPath(source_dir) / name)
                    key = candidate.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    yield candidate

    def _material_library_exists(self, path: str) -> bool:
        if self.pack_fs.exists(path):
            return True
        lower = path.lower()
        if lower.endswith((".mtl", ".xml")):
            return False
        return self.pack_fs.exists(path + ".mtl") or self.pack_fs.exists(path + ".xml")

    def _load_materials(self) -> None:
        """Resolve `material_library_files` against the pack FS into
        parsed `Material` objects (Phase 2)."""
        if not self.material_library_files:
            return
        # Local import to keep `core/` import-cycle-free.
        from ..materials import load_material_libraries

        self.materials = load_material_libraries(
            self.material_library_files,
            self.pack_fs,
            object_dir=self.object_dir,
        )

    # --- animation -----------------------------------------------------

    def _load_animations(self) -> None:
        """Phase 4 entry point. Looks for a sibling ``.chrparams`` file
        (``<stem>.chrparams`` next to the input), parses it, then loads
        every CAF/ANIM the AnimationList references and builds one
        `AnimationClip` per file. When no chrparams is present we fall
        back to a sibling ``.cal`` file (ArcheAge animation list); if
        that's also absent we still scan the input file's directory for
        CAF siblings sharing the stem so animation-only re-imports
        work."""
        from .cal_loader import load_cal_with_includes
        from .chrparams_loader import load_chrparams_with_includes

        input_path = PurePosixPath(self.input_file)
        chrparams_path = str(input_path.with_suffix(".chrparams"))
        if not self.pack_fs.exists(chrparams_path):
            cdf_chrparams_path = self._find_cdf_attachment_chrparams(input_path)
            if cdf_chrparams_path is not None:
                chrparams_path = cdf_chrparams_path
        try:
            self.chrparams = load_chrparams_with_includes(
                chrparams_path, self.pack_fs
            )
        except Exception:
            logger.warning(
                "failed to load chrparams %s", chrparams_path, exc_info=True
            )
            self.chrparams = None

        anim_paths: list[tuple[str, str]] = []  # (clip_name, file_path)
        seen_anim_paths: set[str] = set()

        def append_anim_path(clip_name: str, path: str) -> None:
            norm = path.replace("\\", "/").lower()
            if norm in seen_anim_paths:
                return
            seen_anim_paths.add(norm)
            anim_paths.append((clip_name, path))
        if self.chrparams is not None:
            if self.chrparams.missing_includes:
                logger.warning(
                    "missing chrparams include(s): %s",
                    ", ".join(self.chrparams.missing_includes),
                )
            base_dir = str(input_path.parent)
            for entry in self.chrparams.animations:
                if not entry.path:
                    continue
                if _is_non_playable_animation_reference(entry.name, entry.path):
                    logger.debug(
                        "skipping non-playable chrparams animation entry %s=%s",
                        entry.name,
                        entry.path,
                    )
                    continue
                if not _is_supported_animation_clip_path(entry.path):
                    logger.debug(
                        "skipping non-clip chrparams animation entry %s",
                        entry.path,
                    )
                    continue
                entry_base_dir = base_dir
                if entry.base_path:
                    entry_base_dir = entry.base_path
                elif entry.source_file_name:
                    entry_base_dir = str(
                        PurePosixPath(entry.source_file_name.replace("\\", "/")).parent
                    )
                    if entry_base_dir == ".":
                        entry_base_dir = base_dir
                for resolved in self._resolve_anim_paths(entry.path, entry_base_dir):
                    clip_name = _animation_clip_name(entry.name, resolved)
                    append_anim_path(clip_name, resolved)
        else:
            # ArcheAge fallback: <stem>.cal alongside the input file.
            cal_path = str(input_path.with_suffix(".cal"))
            if self.pack_fs.exists(cal_path):
                try:
                    cal = load_cal_with_includes(cal_path, self.pack_fs)
                except Exception:
                    logger.warning(
                        "failed to load cal %s", cal_path, exc_info=True
                    )
                    cal = None
                if cal is not None:
                    base_dir = (cal.file_path or "").replace("\\", "/").strip("/")
                    if not base_dir:
                        base_dir = str(input_path.parent)
                    for clip_name, rel in cal.animations.items():
                        if _is_non_playable_animation_reference(clip_name, rel):
                            logger.debug(
                                "skipping non-playable cal animation entry %s=%s",
                                clip_name,
                                rel,
                            )
                            continue
                        if not _is_supported_animation_clip_path(rel):
                            logger.debug(
                                "skipping non-clip cal animation entry %s",
                                rel,
                            )
                            continue
                        for resolved in self._resolve_anim_paths(rel, base_dir):
                            append_anim_path(_animation_clip_name(clip_name, resolved), resolved)

        # Load each animation file and aggregate clips.
        for clip_name, path in anim_paths:
            try:
                with self.pack_fs.open(path) as stream:
                    model = Model.from_stream(path, stream)
            except Exception:
                if _is_metadata_animation_database_reference(clip_name, path):
                    logger.debug(
                        "skipping unreadable animation database %s", path, exc_info=True
                    )
                else:
                    logger.warning(
                        "failed to load animation file %s", path, exc_info=True
                    )
                continue
            self.animation_models.append(model)
            if _is_animation_database_path(path):
                database_clips = self._build_clips_from_controller905_model(model)
                database_clips.extend(self._build_clips_from_ivo_dba(model))
                for clip in database_clips:
                    _annotate_animation_clip(clip, clip.source_file_name or path)
                    self.animation_clips.append(clip)
                continue
            clip = self._build_clip_from_caf(clip_name, model)
            if clip is not None:
                _annotate_animation_clip(clip, path)
                self.animation_clips.append(clip)
                continue
            # Fall back to the Star Citizen IVO CAF format.
            clip = self._build_clip_from_ivo_caf(clip_name, model)
            if clip is not None:
                _annotate_animation_clip(clip, path)
                self.animation_clips.append(clip)
                continue
            # IVO DBA libraries: one input file -> N clips.
            for clip in self._build_clips_from_ivo_dba(model):
                if not clip.source_file_name:
                    _annotate_animation_clip(clip, path)
                self.animation_clips.append(clip)

        # Also pull clips from any Controller_905 chunks already loaded
        # in ``self.models`` (some assets ship inline animations).
        for m in self.models:
            for c in m.chunk_map.values():
                if isinstance(c, ChunkController905):
                    for clip in self._build_clips_from_controller905(c):
                        _annotate_animation_clip(clip, m.file_name or self.input_file)
                        self.animation_clips.append(clip)

        # IVO inline animations: any IvoCAF / IvoDBAData chunks already
        # present in self.models (rare for geometry files, but possible
        # for ``.cga`` files that bundle their animation).
        for m in self.models:
            for c in m.chunk_map.values():
                if isinstance(c, ChunkIvoCAF):
                    info = next(
                        (
                            x
                            for x in m.chunk_map.values()
                            if isinstance(x, ChunkIvoAnimInfo)
                        ),
                        None,
                    )
                    name = PurePosixPath(self.input_file).stem
                    clip = self._ivo_caf_to_clip(name, c, info)
                    if clip is not None:
                        _annotate_animation_clip(clip, m.file_name or self.input_file)
                        self.animation_clips.append(clip)
                elif isinstance(c, ChunkIvoDBAData):
                    for clip in self._build_clips_from_ivo_dba(m):
                        if not clip.source_file_name:
                            _annotate_animation_clip(clip, m.file_name or self.input_file)
                        self.animation_clips.append(clip)

    def _find_cdf_attachment_chrparams(
        self,
        input_path: PurePosixPath,
    ) -> str | None:
        from .cdf_assembly import find_cdf_models_for_attachment

        model_paths = find_cdf_models_for_attachment(str(input_path), self.pack_fs)
        chrparams_paths: list[str] = []
        seen: set[str] = set()
        for model_path in model_paths:
            candidate = str(PurePosixPath(model_path).with_suffix(".chrparams"))
            if not self.pack_fs.exists(candidate):
                continue
            key = candidate.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            chrparams_paths.append(candidate)

        if len(chrparams_paths) == 1:
            logger.info(
                "using chrparams %s discovered from CDF attachment %s",
                chrparams_paths[0],
                self.input_file,
            )
            return chrparams_paths[0]
        if len(chrparams_paths) > 1:
            logger.warning(
                "multiple CDF base chrparams files reference %s: %s",
                self.input_file,
                ", ".join(chrparams_paths),
            )
        return None

    def _resolve_anim_path(self, path: str, base_dir: str) -> str | None:
        """ChrParams paths are typically game-relative (e.g.
        ``Animations/Foo/idle.caf``). Try the verbatim path first, then
        ``<base_dir>/<path>``, then ``<object_dir>/<path>``."""
        paths = self._resolve_anim_paths(path, base_dir)
        return paths[0] if paths else None

    def _resolve_anim_paths(self, path: str, base_dir: str) -> list[str]:
        """Resolve a chrparams/cal animation path, expanding wildcards."""
        ref_path = _normalize_animation_reference(path)
        candidates: list[str] = []
        relative_to_base = _is_relative_animation_reference(ref_path)
        if base_dir and relative_to_base and not ref_path.startswith(base_dir):
            candidates.append(str(PurePosixPath(base_dir) / ref_path))
        if not (_has_glob(ref_path) and base_dir and relative_to_base):
            candidates.append(ref_path)
        for candidate in list(candidates):
            stripped = _without_animations_prefix(candidate)
            if stripped != candidate:
                candidates.append(stripped)
            nested = _with_nested_animations_prefix(candidate)
            if nested != candidate:
                candidates.append(nested)
        if self.object_dir and not _has_glob(ref_path):
            candidates.append(
                str(PurePosixPath(self.object_dir) / ref_path)
            )
        matches: list[str] = []
        seen: set[str] = set()
        for cand in candidates:
            if _has_glob(cand):
                found = sorted(
                    p
                    for p in self.pack_fs.glob(cand.replace("\\", "/"))
                    if _is_supported_animation_clip_path(p)
                )
            elif self.pack_fs.exists(cand):
                found = [cand]
            else:
                found = []
            for item in found:
                norm = item.replace("\\", "/").lower()
                if norm in seen:
                    continue
                seen.add(norm)
                matches.append(item)
            if matches:
                return matches
        return matches

    def _build_clip_from_caf(
        self, name: str, model: Model
    ) -> AnimationClip | None:
        """Combine a CAF file's GlobalAnimationHeaderCAF + Controller_905
        into a single playable `AnimationClip`."""
        header: ChunkGlobalAnimationHeaderCAF | None = None
        controller: ChunkController905 | None = None
        speed_info: ChunkMotionParameters925 | None = None
        classic_controllers: list[
            ChunkController827 | ChunkController829 | ChunkController830 | ChunkController831
        ] = []
        for c in model.chunk_map.values():
            if isinstance(c, ChunkGlobalAnimationHeaderCAF) and header is None:
                header = c
            elif isinstance(c, ChunkController905) and controller is None:
                controller = c
            elif isinstance(c, ChunkMotionParameters925) and speed_info is None:
                speed_info = c
            elif isinstance(
                c,
                (
                    ChunkController827,
                    ChunkController829,
                    ChunkController830,
                    ChunkController831,
                ),
            ):
                classic_controllers.append(c)

        clip = AnimationClip(name=name)
        if header is not None:
            clip.duration_secs = header.total_duration
        if speed_info is not None and speed_info.secs_per_tick > 0:
            if speed_info.end > speed_info.start:
                clip.duration_secs = (
                    speed_info.end - speed_info.start
                ) * speed_info.secs_per_tick

        diagnostics = {
            "skipped_root_tracks": 0,
            "skipped_position_tracks": 0,
        }
        if controller is not None:
            clip.tracks.extend(
                self._tracks_from_controller905(
                    controller,
                    diagnostics=diagnostics,
                )
            )
        for classic_controller in classic_controllers:
            track = self._track_from_classic_controller(
                classic_controller,
                secs_per_tick=(speed_info.secs_per_tick if speed_info else 0.0),
                diagnostics=diagnostics,
            )
            if track is not None:
                clip.tracks.append(track)
        clip.skipped_root_tracks = diagnostics["skipped_root_tracks"]
        clip.skipped_position_tracks = diagnostics["skipped_position_tracks"]
        if not clip.tracks:
            return None
        # If duration wasn't set by the header, derive from the longest
        # observed key time across all tracks.
        if clip.duration_secs <= 0.0 and clip.tracks:
            max_time = 0.0
            for t in clip.tracks:
                if t.pos_times:
                    max_time = max(max_time, t.pos_times[-1])
                if t.rot_times:
                    max_time = max(max_time, t.rot_times[-1])
            clip.duration_secs = max_time
        _update_animation_clip_diagnostics(clip)
        if clip.skipped_root_tracks or clip.skipped_position_tracks:
            logger.debug(
                "animation clip %s: %d rotation track(s), %d position track(s), "
                "%d root track(s) skipped, %d classic position track(s) skipped",
                clip.name,
                clip.rotation_track_count,
                clip.position_track_count,
                clip.skipped_root_tracks,
                clip.skipped_position_tracks,
            )
        return clip

    def _track_from_classic_controller(
        self,
        controller: ChunkController827 | ChunkController829 | ChunkController830 | ChunkController831,
        *,
        secs_per_tick: float,
        diagnostics: dict[str, int] | None = None,
    ) -> BoneAnimationTrack | None:
        if isinstance(controller, (ChunkController827, ChunkController830)):
            return self._track_from_controller_streams(
                controller.controller_id,
                rotation_key_times=controller.key_times,
                key_rotations=controller.key_rotations,
                position_key_times=controller.key_times,
                key_positions=controller.key_positions,
                secs_per_tick=secs_per_tick,
                diagnostics=diagnostics,
                diagnostic_name=type(controller).__name__,
            )
        return self._track_from_controller_streams(
            controller.controller_id,
            rotation_key_times=controller.rotation_key_times,
            key_rotations=controller.key_rotations,
            position_key_times=controller.position_key_times,
            key_positions=controller.key_positions,
            secs_per_tick=secs_per_tick,
            diagnostics=diagnostics,
            diagnostic_name=type(controller).__name__,
        )

    def _track_from_controller829(
        self,
        controller: ChunkController829,
        *,
        secs_per_tick: float,
        diagnostics: dict[str, int] | None = None,
    ) -> BoneAnimationTrack | None:
        return self._track_from_controller_streams(
            controller.controller_id,
            rotation_key_times=controller.rotation_key_times,
            key_rotations=controller.key_rotations,
            position_key_times=controller.position_key_times,
            key_positions=controller.key_positions,
            secs_per_tick=secs_per_tick,
            diagnostics=diagnostics,
            diagnostic_name="ChunkController829",
        )

    def _track_from_controller_streams(
        self,
        controller_id: int,
        *,
        rotation_key_times: Iterable[float],
        key_rotations: list[tuple[float, float, float, float]],
        position_key_times: Iterable[float],
        key_positions: list[tuple[float, float, float]],
        secs_per_tick: float,
        diagnostics: dict[str, int] | None = None,
        diagnostic_name: str = "Controller",
    ) -> BoneAnimationTrack | None:
        bone = self._bone_for_controller(controller_id)
        if bone is not None and bone.parent_bone is None:
            if diagnostics is not None:
                diagnostics["skipped_root_tracks"] = (
                    diagnostics.get("skipped_root_tracks", 0) + 1
                )
            return None
        track = BoneAnimationTrack(
            bone_name=(
                bone.bone_name
                if bone is not None
                else self._bone_name_for_controller(controller_id)
            ),
            controller_id=controller_id,
        )
        rotation_times = list(rotation_key_times)
        position_times = list(position_key_times)
        if key_rotations and rotation_times:
            track.rot_times = _scale_key_times(
                rotation_times,
                secs_per_tick,
            )
            rest_rotation = (
                _bone_bind_local_rotation(bone)
                if bone is not None
                else (0.0, 0.0, 0.0, 1.0)
            )
            track.rotations = _continuous_quaternions(
                [
                    _to_pose_basis_rotation(q, rest_rotation)
                    for q in key_rotations
                ]
            )
        if key_positions:
            if _positions_look_valid(key_positions):
                track.pos_times = _scale_key_times(
                    position_times or rotation_times,
                    secs_per_tick,
                )
                rest_translation = (
                    _bone_bind_local_translation(bone)
                    if bone is not None
                    else (0.0, 0.0, 0.0)
                )
                rest_rotation = (
                    _bone_bind_local_rotation(bone)
                    if bone is not None
                    else (0.0, 0.0, 0.0, 1.0)
                )
                track.positions = [
                    _to_pose_basis_translation(
                        position,
                        rest_translation,
                        rest_rotation,
                    )
                    for position in key_positions
                ]
            else:
                if diagnostics is not None:
                    diagnostics["skipped_position_tracks"] = (
                        diagnostics.get("skipped_position_tracks", 0) + 1
                    )
                logger.debug(
                    "skipping invalid %s position track for %s",
                    diagnostic_name,
                    track.bone_name,
                )
        if not track.pos_times and not track.rot_times:
            return None
        return track

    def _build_clips_from_controller905(
        self, controller: ChunkController905
    ) -> list[AnimationClip]:
        """When a Controller_905 carries embedded ``Animation905``
        records, each becomes its own clip referencing the same shared
        track pool."""
        out: list[AnimationClip] = []
        for anim in controller.animations:
            clip = AnimationClip(name=_animation_clip_name(None, anim.name))
            diagnostics = {
                "skipped_root_tracks": 0,
                "skipped_position_tracks": 0,
            }
            if _is_supported_animation_clip_path(anim.name):
                clip.source_file_name = _normalize_animation_reference(anim.name)
            mp = anim.motion_params
            if mp.secs_per_tick > 0 and mp.end > mp.start:
                clip.duration_secs = (mp.end - mp.start) * mp.secs_per_tick
            for ci in anim.controllers:
                track = self._track_from_controller_info(
                    controller,
                    ci,
                    secs_per_tick=mp.secs_per_tick,
                    tick_offset=float(mp.start),
                    diagnostics=diagnostics,
                )
                if track is not None:
                    clip.tracks.append(track)
            clip.skipped_root_tracks = diagnostics["skipped_root_tracks"]
            clip.skipped_position_tracks = diagnostics["skipped_position_tracks"]
            if clip.tracks:
                _update_animation_clip_diagnostics(clip)
                out.append(clip)
        return out

    def _build_clips_from_controller905_model(self, model: Model) -> list[AnimationClip]:
        out: list[AnimationClip] = []
        for chunk in model.chunk_map.values():
            if isinstance(chunk, ChunkController905):
                out.extend(self._build_clips_from_controller905(chunk))
        return out

    def _tracks_from_controller905(
        self,
        controller: ChunkController905,
        *,
        diagnostics: dict[str, int] | None = None,
    ) -> list[BoneAnimationTrack]:
        """Flatten every Animation905's per-bone controller refs into
        a single track list. Used when no separate Animation905 records
        exist (e.g. CAF-style files where the GlobalAnimationHeaderCAF
        already names the clip and we just need the per-bone tracks)."""
        tracks: list[BoneAnimationTrack] = []
        if controller.animations:
            for anim in controller.animations:
                for ci in anim.controllers:
                    t = self._track_from_controller_info(
                        controller,
                        ci,
                        diagnostics=diagnostics,
                    )
                    if t is not None:
                        tracks.append(t)
        return tracks

    def _track_from_controller_info(
        self,
        controller: ChunkController905,
        ci,
        *,
        secs_per_tick: float = 0.0,
        tick_offset: float = 0.0,
        diagnostics: dict[str, int] | None = None,
    ) -> BoneAnimationTrack | None:
        bone = self._bone_for_controller(ci.controller_id)
        if bone is not None and bone.parent_bone is None:
            if diagnostics is not None:
                diagnostics["skipped_root_tracks"] = (
                    diagnostics.get("skipped_root_tracks", 0) + 1
                )
            return None
        bone_name = (
            bone.bone_name
            if bone is not None
            else self._bone_name_for_controller(ci.controller_id)
        )
        track = BoneAnimationTrack(
            bone_name=bone_name, controller_id=ci.controller_id
        )
        if ci.has_pos_track:
            t_idx = ci.pos_key_time_track
            v_idx = ci.pos_track
            if 0 <= t_idx < len(controller.key_times) and 0 <= v_idx < len(
                controller.key_positions
            ):
                key_positions = list(controller.key_positions[v_idx])
                if _positions_look_valid(key_positions):
                    track.pos_times = _scale_key_times(
                        list(controller.key_times[t_idx]),
                        secs_per_tick,
                        tick_offset=tick_offset,
                    )
                    rest_translation = (
                        _bone_bind_local_translation(bone)
                        if bone is not None
                        else (0.0, 0.0, 0.0)
                    )
                    rest_rotation = (
                        _bone_bind_local_rotation(bone)
                        if bone is not None
                        else (0.0, 0.0, 0.0, 1.0)
                    )
                    track.positions = [
                        _to_pose_basis_translation(
                            position,
                            rest_translation,
                            rest_rotation,
                        )
                        for position in key_positions
                    ]
                elif diagnostics is not None:
                    diagnostics["skipped_position_tracks"] = (
                        diagnostics.get("skipped_position_tracks", 0) + 1
                    )
        if ci.has_rot_track:
            t_idx = ci.rot_key_time_track
            v_idx = ci.rot_track
            if 0 <= t_idx < len(controller.key_times) and 0 <= v_idx < len(
                controller.key_rotations
            ):
                track.rot_times = _scale_key_times(
                    list(controller.key_times[t_idx]),
                    secs_per_tick,
                    tick_offset=tick_offset,
                )
                rest_rotation = (
                    _bone_bind_local_rotation(bone)
                    if bone is not None
                    else (0.0, 0.0, 0.0, 1.0)
                )
                track.rotations = _continuous_quaternions(
                    [
                        _to_pose_basis_rotation(rotation, rest_rotation)
                        for rotation in controller.key_rotations[v_idx]
                    ]
                )
        if not track.pos_times and not track.rot_times:
            return None
        return track

    def _bone_name_for_controller(self, controller_id: int) -> str:
        """Resolve a controller_id back to a bone name via
        `skinning_info.compiled_bones` (the controller_id is a CRC32 of
        the bone name in modern Cry assets)."""
        bone = self._bone_for_controller(controller_id)
        if bone is not None:
            return bone.bone_name
        return f"controller_{controller_id:08X}"

    def _bone_for_controller(self, controller_id: int):
        for bone in self.skinning_info.compiled_bones:
            if bone.controller_id == controller_id:
                return bone
        return None

    # --- IVO #caf / #dba clip building (Phase 5c-E) -------------------

    def _build_clip_from_ivo_caf(
        self, name: str, model: Model
    ) -> AnimationClip | None:
        """Combine an IVO #caf file's :class:`ChunkIvoCAF` (+ optional
        :class:`ChunkIvoAnimInfo`) into an :class:`AnimationClip`."""
        caf: ChunkIvoCAF | None = None
        info: ChunkIvoAnimInfo | None = None
        for c in model.chunk_map.values():
            if isinstance(c, ChunkIvoCAF) and caf is None:
                caf = c
            elif isinstance(c, ChunkIvoAnimInfo) and info is None:
                info = c
        if caf is None:
            return None
        return self._ivo_caf_to_clip(name, caf, info)

    def _ivo_caf_to_clip(
        self,
        name: str,
        caf: ChunkIvoCAF,
        info: ChunkIvoAnimInfo | None,
    ) -> AnimationClip | None:
        """Build an :class:`AnimationClip` from a :class:`ChunkIvoCAF`.

        Bone hashes are resolved against ``skinning_info.compiled_bones``
        (which uses the same CRC32-of-bone-name controller IDs). When
        :class:`ChunkIvoAnimInfo` is present, ``duration_secs`` is set
        from ``end_frame / FPS``; otherwise we fall back to the longest
        observed key time.
        """
        clip = AnimationClip(name=name)
        for bone_hash in set(caf.rotations) | set(caf.positions):
            track = self._track_from_ivo_bone(
                bone_hash,
                caf.rotation_times.get(bone_hash, []),
                caf.rotations.get(bone_hash, []),
                caf.position_times.get(bone_hash, []),
                caf.positions.get(bone_hash, []),
            )
            if track is not None:
                clip.tracks.append(track)
        if not clip.tracks:
            return None

        if info is not None and info.frames_per_second > 0:
            clip.duration_secs = info.end_frame / float(info.frames_per_second)
        else:
            clip.duration_secs = _longest_track_time(clip.tracks)
        return clip

    def _build_clips_from_ivo_dba(
        self, model: Model
    ) -> list[AnimationClip]:
        """Materialize one :class:`AnimationClip` per
        :class:`IvoAnimationBlock` in a DBA library, naming each via
        the matching :class:`ChunkIvoDBAMetadata` entry when available.
        """
        out: list[AnimationClip] = []

        dba: ChunkIvoDBAData | None = None
        meta: ChunkIvoDBAMetadata | None = None
        for c in model.chunk_map.values():
            if isinstance(c, ChunkIvoDBAData) and dba is None:
                dba = c
            elif isinstance(c, ChunkIvoDBAMetadata) and meta is None:
                meta = c
        if dba is None:
            return out

        for i, block in enumerate(dba.animation_blocks):
            if meta is not None and i < len(meta.anim_paths):
                name = PurePosixPath(meta.anim_paths[i]).stem or f"anim_{i}"
                source_file_name = meta.anim_paths[i]
                fps = (
                    meta.entries[i].frames_per_second
                    if i < len(meta.entries)
                    else 0
                )
            else:
                name = f"anim_{i}"
                source_file_name = model.file_name or ""
                fps = 0

            clip = AnimationClip(name=name)
            _annotate_animation_clip(clip, source_file_name)
            for bone_hash in set(block.rotations) | set(block.positions):
                track = self._track_from_ivo_bone(
                    bone_hash,
                    block.rotation_times.get(bone_hash, []),
                    block.rotations.get(bone_hash, []),
                    block.position_times.get(bone_hash, []),
                    block.positions.get(bone_hash, []),
                )
                if track is not None:
                    clip.tracks.append(track)
            if not clip.tracks:
                continue

            if fps > 0:
                clip.duration_secs = (
                    _longest_track_time(clip.tracks) / float(fps)
                )
            else:
                clip.duration_secs = _longest_track_time(clip.tracks)
            out.append(clip)

        return out

    def _track_from_ivo_bone(
        self,
        bone_hash: int,
        rot_times: list[float],
        rotations: list[tuple[float, float, float, float]],
        pos_times: list[float],
        positions: list[tuple[float, float, float]],
    ) -> BoneAnimationTrack | None:
        if not rotations and not positions:
            return None
        return BoneAnimationTrack(
            bone_name=self._bone_name_for_controller(bone_hash),
            controller_id=bone_hash,
            pos_times=list(pos_times),
            positions=list(positions),
            rot_times=list(rot_times),
            rotations=_continuous_quaternions(rotations),
        )

    def _build_object_animations(self) -> None:
        self.object_animation_clips = []
        inline_clip = self._build_object_animation_clip(
            self.name,
            self.nodes,
            self.models,
        )
        if inline_clip is not None:
            self.object_animation_clips.append(inline_clip)

        if (
            getattr(self, "load_related", True)
            and getattr(self, "load_animations", True)
            and hasattr(self, "pack_fs")
        ):
            self._load_external_object_animation_clips()

    def _load_external_object_animation_clips(self) -> None:
        if not self.nodes:
            return
        target_node_by_name = {
            node.name.lower(): node for node in self.nodes if node.name
        }
        for path in self._external_object_animation_paths():
            try:
                with self.pack_fs.open(path) as stream:
                    model = Model.from_stream(path, stream)
            except Exception:
                logger.warning(
                    "failed to load object animation file %s", path, exc_info=True
                )
                continue
            nodes = [
                chunk
                for chunk in model.chunk_map.values()
                if isinstance(chunk, ChunkNode)
            ]
            clip = self._build_object_animation_clip(
                PurePosixPath(path).stem,
                nodes,
                [model],
                target_node_by_name=target_node_by_name,
            )
            if clip is not None:
                self.object_animation_clips.append(clip)

    def _build_object_animation_clip(
        self,
        clip_name: str,
        source_nodes: Iterable[ChunkNode],
        models: Iterable[Model],
        *,
        target_node_by_name: dict[str, ChunkNode] | None = None,
    ) -> ObjectAnimationClip | None:
        source_nodes = list(source_nodes)
        controllers = self._controller826_by_id(models)
        if not controllers or not source_nodes:
            return None

        secs_per_tick = self._secs_per_tick(models)
        clip = ObjectAnimationClip(name=clip_name)
        for node in source_nodes:
            target_node = node
            if target_node_by_name is not None:
                resolved = target_node_by_name.get(node.name.lower())
                if resolved is None:
                    continue
                target_node = resolved
            track = ObjectAnimationTrack(node_id=node.id, node_name=node.name)
            track.node_id = target_node.id
            track.node_name = target_node.name

            pos = controllers.get(node.pos_ctrl_id)
            if pos is not None:
                times, values = _vec3_track(pos, secs_per_tick, scale=VERTEX_SCALE)
                if _has_distinct_vec3(values):
                    track.pos_times = times
                    track.positions = values

            rot = controllers.get(node.rot_ctrl_id)
            if rot is not None:
                times, values = _rotation_track(rot, secs_per_tick)
                if _has_distinct_quat(values):
                    track.rot_times = times
                    track.rotations = _continuous_quaternions(values)

            scl = controllers.get(node.scl_ctrl_id)
            if scl is not None:
                times, values = _vec3_track(scl, secs_per_tick, scale=1.0)
                if _has_distinct_vec3(values):
                    track.scale_times = times
                    track.scales = values

            if track.positions or track.rotations or track.scales:
                clip.tracks.append(track)

        if not clip.tracks:
            return

        clip.duration_secs = max(
            [0.0]
            + [t for track in clip.tracks for t in track.pos_times]
            + [t for track in clip.tracks for t in track.rot_times]
            + [t for track in clip.tracks for t in track.scale_times]
        )
        return clip

    def _external_object_animation_paths(self) -> list[str]:
        input_path = PurePosixPath(self.input_file.replace("\\", "/"))
        if input_path.suffix.lower() not in {".cga", ".cgf"}:
            return []

        out: list[str] = []
        seen: set[str] = set()
        for directory in _object_animation_directories(input_path):
            pattern = str(directory / f"{input_path.stem}*.anm")
            for path in sorted(p.replace("\\", "/") for p in self.pack_fs.glob(pattern)):
                key = path.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(path)
        return out

    def _controller826_by_id(
        self,
        models: Iterable[Model] | None = None,
    ) -> dict[int, ChunkController826]:
        controllers: dict[int, ChunkController826] = {}
        iter_models = self.models if models is None else models
        for model in iter_models:
            for chunk in model.chunk_map.values():
                if not isinstance(chunk, ChunkController826):
                    continue
                if chunk.controller_id in (0, -1):
                    continue
                controllers[int(chunk.controller_id)] = chunk
        return controllers

    def _secs_per_tick(self, models: Iterable[Model] | None = None) -> float:
        iter_models = self.models if models is None else models
        for model in iter_models:
            for chunk in model.chunk_map.values():
                if isinstance(chunk, ChunkTimingFormat) and chunk.secs_per_tick > 0:
                    return float(chunk.secs_per_tick)
        return 1.0 / 30.0

    # --- helpers -------------------------------------------------------

    def iter_nodes(self) -> Iterator[ChunkNode]:
        """Depth-first walk of the assembled node tree."""
        if self.root_node is None:
            return
        stack: list[ChunkNode] = [self.root_node]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))


def _matrix3x4_to_4x4(
    m: tuple[tuple[float, ...], ...],
) -> tuple[tuple[float, ...], ...]:
    """Convert a CryEngine ``Matrix3x4`` (translation in column 4 —
    ``M14, M24, M34``) into the row-major 4x4 with translation in row 4
    used by :class:`ChunkNode` and consumed by the Blender bridge.

    Mirrors C# ``Matrix3x4.ConvertToLocalTransformMatrix``: transposes
    the 3x3 rotation and moves the column-4 translation into row 4.
    Without this swap the IVO ``NodeMeshCombo`` branch produces
    transforms that look like the identity (translation lands in
    column 3 where downstream code never reads it), which leaves every
    multi-node IVO ``.cga`` mesh stacked at the world origin instead
    of parented to its bone.
    """
    return (
        (m[0][0], m[1][0], m[2][0], 0.0),
        (m[0][1], m[1][1], m[2][1], 0.0),
        (m[0][2], m[1][2], m[2][2], 0.0),
        (m[0][3], m[1][3], m[2][3], 1.0),
    )


def _longest_track_time(tracks: list[BoneAnimationTrack]) -> float:
    """Return the largest time value across every track's pos / rot
    time arrays (used as a duration fallback when no header is present)."""
    max_time = 0.0
    for t in tracks:
        if t.pos_times:
            max_time = max(max_time, t.pos_times[-1])
        if t.rot_times:
            max_time = max(max_time, t.rot_times[-1])
    return max_time


def _vec3_track(
    controller: ChunkController826,
    secs_per_tick: float,
    *,
    scale: float,
) -> tuple[list[float], list[tuple[float, float, float]]]:
    if controller.controller_type not in (
        CtrlType.LINEAR3,
        CtrlType.BEZIER3,
        CtrlType.TBC3,
        CtrlType.CONST,
    ):
        return [], []
    return (
        [_key_time_seconds(key.time, secs_per_tick) for key in controller.keys],
        [tuple(float(v) * scale for v in key.abs_pos) for key in controller.keys],
    )


def _rotation_track(
    controller: ChunkController826,
    secs_per_tick: float,
) -> tuple[list[float], list[tuple[float, float, float, float]]]:
    if controller.controller_type == CtrlType.TBCQ:
        return _tbcq_rotation_track(controller, secs_per_tick)
    if controller.controller_type not in (CtrlType.LINEARQ, CtrlType.BEZIERQ):
        return [], []
    return (
        [_key_time_seconds(key.time, secs_per_tick) for key in controller.keys],
        [_quat_from_wxyz_fields(key.abs_pos, key.rel_pos) for key in controller.keys],
    )


def _tbcq_rotation_track(
    controller: ChunkController826,
    secs_per_tick: float,
) -> tuple[list[float], list[tuple[float, float, float, float]]]:
    times: list[float] = []
    rotations: list[tuple[float, float, float, float]] = []
    current = (0.0, 0.0, 0.0, 1.0)
    for index, key in enumerate(controller.keys):
        times.append(_key_time_seconds(key.time, secs_per_tick))
        if index == 0:
            current = _quat_from_wxyz_fields(key.abs_pos, key.rel_pos)
        else:
            delta = _axis_angle_to_quat(key.abs_pos, key.rel_pos[0])
            current = _quat_multiply(current, delta)
        rotations.append(_normalise_quat(current))
    return times, rotations


def _key_time_seconds(ticks: int, secs_per_tick: float) -> float:
    return max(float(ticks), 0.0) * secs_per_tick


def _quat_from_wxyz_fields(
    abs_pos: tuple[float, float, float],
    rel_pos: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    return _normalise_quat((abs_pos[1], abs_pos[2], rel_pos[0], abs_pos[0]))


def _axis_angle_to_quat(
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float, float]:
    import math

    x, y, z = axis
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-8 or abs(angle) <= 1e-8:
        return (0.0, 0.0, 0.0, 1.0)
    half = angle * 0.5
    scale = math.sin(half) / length
    return _normalise_quat((x * scale, y * scale, z * scale, math.cos(half)))


def _quat_multiply(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return _normalise_quat(
        (
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        )
    )


def _normalise_quat(
    quat: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    import math

    x, y, z, w = quat
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1e-8:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / length, y / length, z / length, w / length)


def _has_distinct_vec3(values: list[tuple[float, float, float]]) -> bool:
    if len(values) < 2:
        return False
    first = values[0]
    return any(
        any(abs(value[i] - first[i]) > 1e-6 for i in range(3))
        for value in values[1:]
    )


def _has_distinct_quat(values: list[tuple[float, float, float, float]]) -> bool:
    if len(values) < 2:
        return False
    first = values[0]
    return any(
        any(abs(value[i] - first[i]) > 1e-6 for i in range(4))
        for value in values[1:]
    )


def _is_supported_animation_clip_path(path: str) -> bool:
    suffix = PurePosixPath(_normalize_animation_reference(path)).suffix.lower()
    return suffix in _ANIMATION_CLIP_EXTENSIONS


def _object_animation_directories(input_path: PurePosixPath) -> tuple[PurePosixPath, ...]:
    parts = input_path.parts
    if not parts:
        return ()
    parent_parts = parts[:-1]
    candidates: list[PurePosixPath] = []

    if parent_parts and parent_parts[0].lower() == "objects":
        collapsed = parent_parts
        if len(parent_parts) >= 2 and parent_parts[1].lower() == "objects":
            collapsed = (parent_parts[0], *parent_parts[2:])
        candidates.append(PurePosixPath("animations", *collapsed))

    candidates.append(PurePosixPath("animations", *parent_parts))

    out: list[PurePosixPath] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return tuple(out)


def _has_glob(path: str) -> bool:
    return any(ch in path for ch in "*?[")


def _is_relative_animation_reference(path: str) -> bool:
    cleaned = path.replace("\\", "/").lstrip("/")
    if not cleaned:
        return False
    first = cleaned.split("/", 1)[0].lower()
    return first not in {"animations", "game"}


def _is_bare_material_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return str(path.parent) in ("", ".") and path.suffix == ""


def _is_pathful_sidecar(path: str) -> bool:
    parent = PurePosixPath(path.replace("\\", "/")).parent
    return str(parent) not in ("", ".")


def _is_material_library_chunk(chunk: ChunkMtlName) -> bool:
    mat_type = chunk.mat_type
    library_types = (
        MtlNameType.Library,
        MtlNameType.Basic,
        MtlNameType.Single,
    )
    if isinstance(mat_type, MtlNameType):
        return mat_type in library_types
    return int(mat_type) in {int(t) for t in library_types}


def _source_info_pack_path_candidates(source_file: str) -> tuple[str, ...]:
    cleaned = source_file.replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        return ()

    candidates: list[str] = []

    def add(path: str) -> None:
        normalized = path.strip().lstrip("/")
        if normalized and normalized.lower() not in {
            candidate_path.lower() for candidate_path in candidates
        }:
            candidates.append(normalized)

    add(cleaned)
    lower = cleaned.lower()
    if lower.startswith("bjects/"):
        add("o" + cleaned)

    parts = cleaned.split("/")
    for index, part in enumerate(parts):
        if part.lower() in {"objects", "textures"}:
            add("/".join(parts[index:]))
            break

    return tuple(candidates)


def _animation_clip_name(name: str | None, path: str) -> str:
    if name and name != "*":
        return name
    return PurePosixPath(path.replace("\\", "/")).stem or "anim"


def _annotate_animation_clip(clip: AnimationClip, source_file_name: str | None) -> None:
    _update_animation_clip_diagnostics(clip)
    clip.source_file_name = (source_file_name or "").replace("\\", "/")
    clip.clip_kind = _classify_animation_clip(
        clip.name,
        clip.source_file_name,
        track_bone_names=[track.bone_name for track in clip.tracks],
    )
    clip.is_additive = clip.clip_kind in {"additive", "aim_pose", "look_pose"}


def _update_animation_clip_diagnostics(clip: AnimationClip) -> None:
    clip.rotation_track_count = sum(1 for track in clip.tracks if track.rotations)
    clip.position_track_count = sum(1 for track in clip.tracks if track.positions)


def _classify_animation_clip(
    name: str | None,
    source_file_name: str | None = None,
    *,
    track_bone_names: Iterable[str] | None = None,
) -> str:
    text = f"{name or ''} {source_file_name or ''}".replace("\\", "/").lower()
    if "$tracksdatabase" in text or "$animeventdatabase" in text:
        return "metadata"
    if "aimposes" in text or "aimpose" in text:
        return "aim_pose"
    if "lookposes" in text or "lookpose" in text:
        return "look_pose"
    tokens = text.replace("-", "_").replace("/", "_").split("_")
    if "additive" in tokens or "add" in tokens:
        return "additive"
    if track_bone_names is not None:
        bones = [bone.lower() for bone in track_bone_names if bone]
        if bones and len(bones) <= 3 and any("weapon" in bone for bone in bones):
            return "partial_body"
    return "full_body"


def _normalize_animation_reference(path: str) -> str:
    ref = path.replace("\\", "/").strip()
    lowered = ref.lower()
    endings: list[int] = []
    for ext in sorted(_ANIMATION_CLIP_EXTENSIONS, key=len, reverse=True):
        idx = lowered.rfind(ext)
        if idx < 0:
            continue
        end = idx + len(ext)
        if end == len(lowered) or lowered[end].isspace() or lowered[end] == "(":
            endings.append(end)
    if endings:
        ref = ref[: min(endings)]
    return ref


def _is_non_playable_animation_reference(name: str | None, path: str) -> bool:
    lowered_name = (name or "").lower()
    if lowered_name == "$tracksdatabase":
        return not _is_animation_database_path(path)
    if lowered_name == "$animeventdatabase":
        return True
    suffix = PurePosixPath(_normalize_animation_reference(path)).suffix.lower()
    return suffix in {".animevents", ".lmg"}


def _is_animation_database_path(path: str) -> bool:
    suffix = PurePosixPath(_normalize_animation_reference(path)).suffix.lower()
    return suffix == ".dba"


def _is_metadata_animation_database_reference(name: str | None, path: str) -> bool:
    return (name or "").lower() == "$tracksdatabase" and _is_animation_database_path(path)


def _scale_key_times(
    times: list[float],
    secs_per_tick: float,
    *,
    tick_offset: float = 0.0,
) -> list[float]:
    if secs_per_tick > 0.0:
        return [max(float(t) - tick_offset, 0.0) * secs_per_tick for t in times]
    return [max(float(t) - tick_offset, 0.0) for t in times]


def _to_pose_basis_rotation(
    rotation: tuple[float, float, float, float],
    rest_rotation: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    anim = _normalize_quat(rotation)
    rest = _normalize_quat(rest_rotation)
    return _normalize_quat(_quat_multiply(_quat_conjugate(rest), anim))


def _continuous_quaternions(
    rotations: Iterable[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    previous: tuple[float, float, float, float] | None = None
    for rotation in rotations:
        quat = _normalize_quat(rotation)
        if previous is not None:
            dot = _quat_dot(previous, quat)
            if dot == dot and dot < 0.0:
                quat = (-quat[0], -quat[1], -quat[2], -quat[3])
        out.append(quat)
        previous = quat
    return out


def _to_pose_basis_translation(
    translation: tuple[float, float, float],
    rest_translation: tuple[float, float, float],
    rest_rotation: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    delta = _vec3_subtract(translation, rest_translation)
    rest = _normalize_quat(rest_rotation)
    return _quat_rotate_vector(_quat_conjugate(rest), delta)


def _normalize_quat(
    quat: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    x, y, z, w = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    norm = (x * x + y * y + z * z + w * w) ** 0.5
    if norm <= 1e-8:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / norm, y / norm, z / norm, w / norm)


def _quat_conjugate(
    quat: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    x, y, z, w = quat
    return (-x, -y, -z, w)


def _quat_dot(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def _quat_multiply(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_rotate_vector(
    quat: tuple[float, float, float, float],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    q = _normalize_quat(quat)
    vx, vy, vz = (float(vector[0]), float(vector[1]), float(vector[2]))
    rotated = _quat_multiply(
        _quat_multiply(q, (vx, vy, vz, 0.0)),
        _quat_conjugate(q),
    )
    return (rotated[0], rotated[1], rotated[2])


def _quat_from_matrix3x4(rows: tuple) -> tuple[float, float, float, float]:
    m00, m01, m02 = rows[0][0], rows[0][1], rows[0][2]
    m10, m11, m12 = rows[1][0], rows[1][1], rows[1][2]
    m20, m21, m22 = rows[2][0], rows[2][1], rows[2][2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = (trace + 1.0) ** 0.5 * 2.0
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = (1.0 + m00 - m11 - m22) ** 0.5 * 2.0
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = (1.0 + m11 - m00 - m22) ** 0.5 * 2.0
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = (1.0 + m22 - m00 - m11) ** 0.5 * 2.0
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


def _bone_bind_local_rotation(bone) -> tuple[float, float, float, float]:
    """Return the local bind rotation in the same basis used to build
    Blender edit bones.

    Legacy 0x800 compiled bones carry both local and world matrices,
    but the Blender armature is placed from the world matrices. Some
    Crysis 2 assets have local matrices that do not match the
    parent-inverse world basis, so animation pose deltas must use the
    world-derived local bind rotation.
    """
    world = getattr(bone, "world_transform_matrix", None)
    if not world or _is_identity_3x4(world):
        return _quat_from_matrix3x4(bone.local_transform_matrix)

    rotation = _rotation3_from_matrix3x4(world)
    parent = getattr(bone, "parent_bone", None)
    if parent is not None:
        parent_world = getattr(parent, "world_transform_matrix", None)
        if parent_world and not _is_identity_3x4(parent_world):
            parent_rotation = _rotation3_from_matrix3x4(parent_world)
            rotation = _matrix3_multiply(
                _matrix3_transpose(parent_rotation),
                rotation,
            )
    return _quat_from_matrix3x4(_matrix3_to_matrix3x4(rotation))


def _bone_bind_local_translation(bone) -> tuple[float, float, float]:
    """Return the local bind translation in the same parent-inverse
    world basis used for Blender edit bones."""
    world = getattr(bone, "world_transform_matrix", None)
    if not world or _is_identity_3x4(world):
        return _translation_from_matrix3x4(bone.local_transform_matrix)

    translation = _translation_from_matrix3x4(world)
    parent = getattr(bone, "parent_bone", None)
    if parent is not None:
        parent_world = getattr(parent, "world_transform_matrix", None)
        if parent_world and not _is_identity_3x4(parent_world):
            parent_rotation = _rotation3_from_matrix3x4(parent_world)
            parent_translation = _translation_from_matrix3x4(parent_world)
            translation = _matrix3_vector_multiply(
                _matrix3_transpose(parent_rotation),
                _vec3_subtract(translation, parent_translation),
            )
    return translation


def _positions_look_valid(values: list[tuple[float, float, float]]) -> bool:
    for position in values:
        for value in position:
            if value != value or abs(float(value)) > 10000.0:
                return False
    return True


def _translation_from_matrix3x4(rows: tuple) -> tuple[float, float, float]:
    return (float(rows[0][3]), float(rows[1][3]), float(rows[2][3]))


def _rotation3_from_matrix3x4(rows: tuple) -> tuple[tuple[float, float, float], ...]:
    return (
        (float(rows[0][0]), float(rows[0][1]), float(rows[0][2])),
        (float(rows[1][0]), float(rows[1][1]), float(rows[1][2])),
        (float(rows[2][0]), float(rows[2][1]), float(rows[2][2])),
    )


def _matrix3_to_matrix3x4(rows: tuple[tuple[float, float, float], ...]) -> tuple:
    return (
        (rows[0][0], rows[0][1], rows[0][2], 0.0),
        (rows[1][0], rows[1][1], rows[1][2], 0.0),
        (rows[2][0], rows[2][1], rows[2][2], 0.0),
    )


def _matrix3_transpose(rows: tuple[tuple[float, float, float], ...]) -> tuple:
    return (
        (rows[0][0], rows[1][0], rows[2][0]),
        (rows[0][1], rows[1][1], rows[2][1]),
        (rows[0][2], rows[1][2], rows[2][2]),
    )


def _matrix3_multiply(
    a: tuple[tuple[float, float, float], ...],
    b: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(sum(a[row][k] * b[k][col] for k in range(3)) for col in range(3))
        for row in range(3)
    )


def _matrix3_vector_multiply(
    matrix: tuple[tuple[float, float, float], ...],
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(
        sum(matrix[row][col] * vector[col] for col in range(3))
        for row in range(3)
    )


def _vec3_subtract(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (float(a[0]) - float(b[0]), float(a[1]) - float(b[1]), float(a[2]) - float(b[2]))


def _is_identity_3x4(rows: tuple) -> bool:
    expected = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
    )
    for r in range(3):
        for c in range(4):
            if abs(float(rows[r][c]) - expected[r][c]) > 1e-6:
                return False
    return True


def _without_animations_prefix(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    parts = normalized.split("/", 1)
    if len(parts) == 2 and parts[0].lower() == "animations":
        return parts[1]
    return normalized


def _with_nested_animations_prefix(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    parts = normalized.split("/", 2)
    if len(parts) >= 2 and parts[0].lower() == "animations":
        if parts[1].lower() != "animations":
            return f"animations/{normalized}"
    return normalized


__all__ = ["CryEngine", "UnsupportedFileError", "COMPANION_GEOMETRY_PRIMARY"]
