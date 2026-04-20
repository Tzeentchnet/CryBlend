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
from .chunks.controller import ChunkController905
from .chunks.global_animation_header_caf import ChunkGlobalAnimationHeaderCAF
from .chunks.helper import ChunkHelper
from .chunks.ivo_anim_info import ChunkIvoAnimInfo
from .chunks.ivo_caf import ChunkIvoCAF
from .chunks.ivo_dba_data import ChunkIvoDBAData
from .chunks.ivo_dba_metadata import ChunkIvoDBAMetadata
from .chunks.ivo_skin_mesh import ChunkIvoSkinMesh
from .chunks.mesh import ChunkMesh
from .chunks.mtl_name import ChunkMtlName
from .chunks.node import ChunkNode
from .chunks.node_mesh_combo import ChunkNodeMeshCombo
from .model import Model
from ..enums import MtlNameType
from ..models.animation import AnimationClip, BoneAnimationTrack, ChrParams
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
        self._load_materials()
        self._collect_material_library_files()
        logger.info(
            "materials: %d/%d libraries resolved",
            len(self.materials),
            len(self.material_library_files),
        )
        if self.load_related:
            self._load_animations()
            logger.info(
                "animations: %d clip(s) loaded", len(self.animation_clips)
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
        for c in self.models[0].chunk_map.values():
            if not isinstance(c, ChunkMtlName):
                continue
            mat_type = c.mat_type
            # MtlNameType is an IntFlag — accept Library / Basic / Single.
            if isinstance(mat_type, MtlNameType):
                is_lib = mat_type in (
                    MtlNameType.Library,
                    MtlNameType.Basic,
                    MtlNameType.Single,
                )
            else:
                is_lib = int(mat_type) in (
                    int(MtlNameType.Library),
                    int(MtlNameType.Basic),
                    int(MtlNameType.Single),
                )
            if not is_lib:
                continue
            name = c.name
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        self.material_library_files = out

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
        from .chrparams_loader import load_chrparams

        input_path = PurePosixPath(self.input_file)
        chrparams_path = str(input_path.with_suffix(".chrparams"))
        try:
            self.chrparams = load_chrparams(chrparams_path, self.pack_fs)
        except Exception:
            logger.warning(
                "failed to load chrparams %s", chrparams_path, exc_info=True
            )
            self.chrparams = None

        anim_paths: list[tuple[str, str]] = []  # (clip_name, file_path)
        if self.chrparams is not None:
            base_dir = str(input_path.parent)
            for entry in self.chrparams.animations:
                if not entry.path:
                    continue
                resolved = self._resolve_anim_path(entry.path, base_dir)
                if resolved is None:
                    continue
                clip_name = entry.name or PurePosixPath(resolved).stem
                anim_paths.append((clip_name, resolved))
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
                        resolved = self._resolve_anim_path(rel, base_dir)
                        if resolved is None:
                            continue
                        anim_paths.append((clip_name, resolved))

        # Load each animation file and aggregate clips.
        for clip_name, path in anim_paths:
            try:
                with self.pack_fs.open(path) as stream:
                    model = Model.from_stream(path, stream)
            except Exception:
                logger.warning(
                    "failed to load animation file %s", path, exc_info=True
                )
                continue
            self.animation_models.append(model)
            clip = self._build_clip_from_caf(clip_name, model)
            if clip is not None:
                self.animation_clips.append(clip)
                continue
            # Fall back to the Star Citizen IVO CAF format.
            clip = self._build_clip_from_ivo_caf(clip_name, model)
            if clip is not None:
                self.animation_clips.append(clip)
                continue
            # IVO DBA libraries: one input file -> N clips.
            self.animation_clips.extend(
                self._build_clips_from_ivo_dba(model)
            )

        # Also pull clips from any Controller_905 chunks already loaded
        # in ``self.models`` (some assets ship inline animations).
        for m in self.models:
            for c in m.chunk_map.values():
                if isinstance(c, ChunkController905):
                    self.animation_clips.extend(
                        self._build_clips_from_controller905(c)
                    )

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
                        self.animation_clips.append(clip)
                elif isinstance(c, ChunkIvoDBAData):
                    self.animation_clips.extend(
                        self._build_clips_from_ivo_dba(m)
                    )

    def _resolve_anim_path(self, path: str, base_dir: str) -> str | None:
        """ChrParams paths are typically game-relative (e.g.
        ``Animations/Foo/idle.caf``). Try the verbatim path first, then
        ``<base_dir>/<path>``, then ``<object_dir>/<path>``."""
        candidates = [path]
        if base_dir and not path.startswith(base_dir):
            candidates.append(str(PurePosixPath(base_dir) / path))
        if self.object_dir:
            candidates.append(
                str(PurePosixPath(self.object_dir) / path)
            )
        for cand in candidates:
            if self.pack_fs.exists(cand):
                return cand
        return None

    def _build_clip_from_caf(
        self, name: str, model: Model
    ) -> AnimationClip | None:
        """Combine a CAF file's GlobalAnimationHeaderCAF + Controller_905
        into a single playable `AnimationClip`."""
        header: ChunkGlobalAnimationHeaderCAF | None = None
        controller: ChunkController905 | None = None
        for c in model.chunk_map.values():
            if isinstance(c, ChunkGlobalAnimationHeaderCAF) and header is None:
                header = c
            elif isinstance(c, ChunkController905) and controller is None:
                controller = c
        if controller is None:
            return None

        clip = AnimationClip(name=name)
        if header is not None:
            clip.duration_secs = header.total_duration

        clip.tracks.extend(self._tracks_from_controller905(controller))
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
        return clip

    def _build_clips_from_controller905(
        self, controller: ChunkController905
    ) -> list[AnimationClip]:
        """When a Controller_905 carries embedded ``Animation905``
        records, each becomes its own clip referencing the same shared
        track pool."""
        out: list[AnimationClip] = []
        for anim in controller.animations:
            clip = AnimationClip(name=anim.name)
            mp = anim.motion_params
            if mp.secs_per_tick > 0 and mp.end > mp.start:
                clip.duration_secs = (mp.end - mp.start) * mp.secs_per_tick
            for ci in anim.controllers:
                track = self._track_from_controller_info(controller, ci)
                if track is not None:
                    clip.tracks.append(track)
            out.append(clip)
        return out

    def _tracks_from_controller905(
        self, controller: ChunkController905
    ) -> list[BoneAnimationTrack]:
        """Flatten every Animation905's per-bone controller refs into
        a single track list. Used when no separate Animation905 records
        exist (e.g. CAF-style files where the GlobalAnimationHeaderCAF
        already names the clip and we just need the per-bone tracks)."""
        tracks: list[BoneAnimationTrack] = []
        if controller.animations:
            for anim in controller.animations:
                for ci in anim.controllers:
                    t = self._track_from_controller_info(controller, ci)
                    if t is not None:
                        tracks.append(t)
        return tracks

    def _track_from_controller_info(
        self, controller: ChunkController905, ci
    ) -> BoneAnimationTrack | None:
        bone_name = self._bone_name_for_controller(ci.controller_id)
        track = BoneAnimationTrack(
            bone_name=bone_name, controller_id=ci.controller_id
        )
        if ci.has_pos_track:
            t_idx = ci.pos_key_time_track
            v_idx = ci.pos_track
            if 0 <= t_idx < len(controller.key_times) and 0 <= v_idx < len(
                controller.key_positions
            ):
                track.pos_times = list(controller.key_times[t_idx])
                track.positions = list(controller.key_positions[v_idx])
        if ci.has_rot_track:
            t_idx = ci.rot_key_time_track
            v_idx = ci.rot_track
            if 0 <= t_idx < len(controller.key_times) and 0 <= v_idx < len(
                controller.key_rotations
            ):
                track.rot_times = list(controller.key_times[t_idx])
                track.rotations = list(controller.key_rotations[v_idx])
        if not track.pos_times and not track.rot_times:
            return None
        return track

    def _bone_name_for_controller(self, controller_id: int) -> str:
        """Resolve a controller_id back to a bone name via
        `skinning_info.compiled_bones` (the controller_id is a CRC32 of
        the bone name in modern Cry assets)."""
        for b in self.skinning_info.compiled_bones:
            if b.controller_id == controller_id:
                return b.bone_name
        return f"controller_{controller_id:08X}"

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
                fps = (
                    meta.entries[i].frames_per_second
                    if i < len(meta.entries)
                    else 0
                )
            else:
                name = f"anim_{i}"
                fps = 0

            clip = AnimationClip(name=name)
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
            rotations=list(rotations),
        )

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


__all__ = ["CryEngine", "UnsupportedFileError", "COMPANION_GEOMETRY_PRIMARY"]
