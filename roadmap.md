# CryEngine Importer for Blender — Roadmap

This document tracks the phased implementation of the Blender add-on
under [`cryengine_importer/`](cryengine_importer/). The authoritative
spec is **CryEngine Converter v2.0.0** (Mar 2026 release — USD Export
and Animation Support), available at
<https://github.com/Markemp/Cryengine-Converter>. New work should
target v2 semantics; the v1.7.1 tree remains useful for diffing
already-ported modules. Each Python module references the C# file it
was ported from.

Status legend: ✅ done · 🚧 in progress · ⏳ planned · ❄️ deferred

---

## Phase 0 — Project scaffolding

- ✅ Package layout (`io/`, `core/`, `core/chunks/`, `blender/`)
- ✅ Decorator-based chunk registry (`@chunk(type, version)`)
- ✅ Parser-only test harness (`tests/parser/`, no `bpy`)
- ✅ `roadmap.md` + `changelog.md`
- ✅ `blender_manifest.toml` (Blender 5.0+ extension format)

## Phase 1 — Crydata geometry import ✅

Goal: open a `.cgf` / `.cga` (+ `.cgam`) in Blender via File → Import,
producing a node hierarchy of meshes with correct transforms and UVs.
Placeholder default material per subset; no skinning, no animation.

- ✅ Binary I/O (`BinaryReader`, endianness, string variants)
- ✅ CryXmlB serializer (pbxml / CryXmlB / plain XML auto-detect)
- ✅ Pack file system (Real / InMemory / Cascaded)
- ✅ File header + chunk table parsing (0x744 / 0x745 / 0x746 / 0x900)
- ✅ Crydata chunk readers: Header, SourceInfo, ExportFlags, Timing,
  SceneProps, Helper_744, MtlName (744/800/802/804), Mesh
  (800/801/802), MeshSubsets_800, DataStream (800/801), Node
  (823/824)
- ✅ `CryEngine` aggregator: companion-file discovery (.cgam/.chrm),
  node hierarchy wiring, mesh resolution across split files,
  material-library file collection
- ✅ `MeshGeometry` dataclass + `mesh_builder` (pure-Python, testable)
- ✅ `ChunkNode.world_matrix` (parent-chain walk)
- ✅ `blender/scene_builder.py`: `bpy.data.meshes` + `from_pydata`
  + UV layer + loop normals + subset-based material slots + parent
  wiring
- ✅ Rewrite `IMPORT_OT_cryengine.execute()` to use `CryEngine` +
  `RealFileSystem` + `scene_builder`
- ✅ Headless smoke test (`tests/headless_smoke.py`, run via
  `blender --background --python …`)

## Phase 2 — Materials ✅

- ✅ `materials/` layer: `.mtl` parser, gen-mask decoding, DDS lookup
- ✅ Load discovered material library files via the pack FS
- ✅ Translate to Blender material nodes (Principled BSDF + image
  texture nodes for diffuse / normal / spec / gloss)
- ✅ Operator option to override material search paths (-objectdir)

## Phase 3 — Skinning ✅

Required for `.chr` and `.skin`.

- ✅ Chunk readers: `CompiledBones` (800/801),
  `CompiledPhysicalBones_800`, `CompiledPhysicalProxies_800`,
  `CompiledIntSkinVertices` (800/801), `CompiledIntFaces_800`,
  `CompiledExtToIntMap_800`, `BoneNameList_745`
- ✅ `SkinningInfo` consolidation in `CryEngine` aggregator
- ✅ Build `bpy.types.Armature` + bones with rest pose
- ✅ Vertex groups + Armature modifier on the mesh
- ⏳ `CompiledBones_900/901` (deferred to Phase 5 — Star Citizen IVO)

## Phase 4 — Animation ✅

- ✅ Chunk readers: `Controller` (826/829/905), `BoneAnim_290`,
  `GlobalAnimationHeaderCAF_971`. Timing 918/919 already covered in
  Phase 1.
- ✅ Compressed quaternion / vec3 decoders (`ShortInt3Quat`,
  `SmallTreeDWORDQuat`, `SmallTree48BitQuat`, `SmallTree64BitQuat`,
  `SmallTree64BitExtQuat`) on `BinaryReader`.
- ✅ `.caf` / `.anim` companion-file discovery via the chrparams
  `AnimationList` (paths resolved against pack-fs / object-dir).
- ✅ Blender actions + fcurves on the armature
  (`blender/action_builder.py`).
- ✅ chrparams.xml character definition loading
  (`core/chrparams_loader.py`).

## Phase 5 — Star Citizen IVO format ✅

- ✅ Chunk readers: `IvoSkinMesh_900`, `NodeMeshCombo_900`,
  `MtlName_900`, `Mesh_900`, `CompiledBones_900/901`,
  `BinaryXmlData_3`
- ✅ IVO branch in `CryEngine._build_nodes()` (NodeMeshCombo tree
  + skin/chr dummy-root variants)
- ✅ `#ivo` file signature handling end-to-end (header + chunk
  table + companion `.skinm`/`.chrm` discovery)
- ✅ IVO datastream → `MeshGeometry` translation in `mesh_builder`
  (per-node subset filtering by `node_parent_index`; full-mesh emit
  for the skin/chr single-root case)
- ❌ `MeshSubsets_900` chunk reader — the C# class is parameterised
  on `numVertSubsets` and never actually instantiated; IVO subsets
  live inside `IvoSkinMesh_900`.

## Phase 5c — v2.0.0 parser parity ✅

Reference: CryEngine Converter v2.0.0 release notes and source at
<https://github.com/Markemp/Cryengine-Converter>.

### Parity bug fixes (Phase A) ✅

- ✅ SC 4.5+ 32-byte pad after `ChunkNodeMeshCombo_900` header
- ✅ `ChunkCompiledBones_901` parent wiring uses `ParentControllerIndex`
  (matches v2; replaces the v1.7.1 `OffsetParent` bug)
- ✅ Bounded `_read_null_separated_strings(br, count, byte_count)`
  overload (used by IVO bones 0x901 + NodeMeshCombo)
- ✅ Validated against 13 real Star Citizen 4.5+ `.cga`/`.cgf` files
  (Greycat PTV collection): all parse, GRIN_PTV.cga emits 6 valid
  geometries from 75 nodes

### New SC 4.5+ chunk-type IDs (Phase B) ✅

- ✅ Added to `enums.ChunkType` (safely skipped via "unknown" fallback):
  `MotionParams` 0x3002, `IvoAnimInfo` 0x4733C6ED,
  `IvoCAFData` 0xA9496CB5, `IvoDBAData` 0x194FBC50,
  `IvoDBAMetadata` 0xF7351608, `IvoAssetMetadata` 0xBE5E493E,
  `IvoLodDistances` 0x9351756F, `IvoLodMeshData` 0x58DE1772,
  `IvoBoundingData` 0x2B7ECF9F, `IvoChunkTerminator` 0xE0181074,
  `IvoMtlNameVariant` 0x83353533
- ✅ Verified against PTV chunk-type survey: every chunk in 13 real
  SC 4.5+ files now resolves to a known enum name
- ⏳ `CompiledPhysicalBonesIvo` 0x90C687DC,
  `CompiledPhysicalBonesIvo320` 0x90C66666 (deferred — no test fixture
  in PTV collection)

### ArcheAge / new CryAnim controllers (Phase C, extends Phase 4) ✅

- ✅ `ChunkController_827` — uncompressed CryKeyPQLog, no local header
  (half-angle PQLog→Quat conversion)
- ✅ `ChunkController_828` — empty/no-op skip
- ✅ `ChunkController_830` — PQLog + Flags (full-angle conversion)
- ✅ `ChunkController_831` — compressed dual-track (rotation + position)
  with eF32/eU16/eByte time formats and the full quat-compression set
  (eNoCompressQuat, eShotInt3Quat, eSmallTreeDWORD/48Bit/64Bit/64BitExt);
  honours `tracks_aligned` 4-byte padding and shared/separate position
  time tracks
- ✅ `ChunkMotionParameters_925` — read-only metadata (no Blender consumer yet)

### `.cal` animation list (Phase D, ArcheAge) ✅

- ✅ `core/cal_loader.py` — port of `Cal/CalFile.cs` (key=value entries,
  inline `//` comments, `$Include` recursion with multi-path fallback
  including `game/` prefix and including-file-relative resolution;
  cycle-safe; parent overrides win on duplicate keys)
- ✅ `CryEngine._load_animations` fallback to `<stem>.cal` when no
  `.chrparams` is present

### Star Citizen #ivo animation (Phase E) ✅

- ✅ `models/ivo_animation.py` — port of `IvoAnimationStructs.cs`
  (`IvoAnimBlockHeader`, `IvoAnimControllerEntry`,
  `IvoAnimationBlock`, `IvoDBAMetaEntry`, `IvoPositionFormat`, plus
  helpers for SNORM decompression, time-key reading, position-key
  reading, and the `is_channel_active` FLT_MAX float32-quantized
  comparison)
- ✅ `ChunkIvoAnimInfo_901` — 48-byte animation metadata (FPS, bone
  count, end frame, reference pose)
- ✅ `ChunkIvoCAF_900` — `#caf` block with bone-hash + 24-byte
  controller table; per-controller relative offsets resolve rotation
  + position keyframe data
- ✅ `ChunkIvoDBAData_900` — multiple `#dba` blocks; each materialises
  into an `IvoAnimationBlock`; next block resumes after controller
  headers (not after keyframe payload, per v2 source)
- ✅ `ChunkIvoDBAMetadata_900` / `_901` — 44-byte per-animation
  metadata + null-terminated path string table
- ✅ Aggregator: `_build_clip_from_ivo_caf` synthesises
  `AnimationClip`s from `IvoCAF` + `IvoAnimInfo`, matching CRC32 bone
  hashes against `skinning_info.compiled_bones`. DBA libraries fan out
  to one clip per `IvoAnimationBlock`, named via the matching DBA
  metadata path stem.
- ✅ 17 unit tests covering helpers, all four chunk readers, and the
  SNorm-packed inactive-channel skip path

### Deferred (Phase F)

- ❄️ `ChunkIvoSkinMesh_900` 8-byte tangent-frame smallest-three
  decode (Blender derives tangents from UVs anyway)

## Phase 6 — Morph targets / blend shapes ✅

- ✅ Chunk readers: `CompiledMorphTargets` 0x800 / 0x801 / 0x802 plus
  the Star Citizen `CompiledMorphTargetsSC` variant (routed to the
  same factory as in C# `Chunk.cs`). 0x801 is a no-op (mirrors the
  commented-out C# body in v1.7.1 / v2.0.0); 0x800 and 0x802 share
  the `u32 count` + `count × 16` layout (`u32 vertex_id` + `vec3
  absolute_position`).
- ✅ `MorphTarget` dataclass on `models/geometry.py`; `MeshGeometry`
  exposes a `morph_targets` list populated by `mesh_builder` from
  every `ChunkCompiledMorphTargets` in the owning model's chunk map.
  Out-of-range vertex ids are dropped defensively.
- ✅ `blender/scene_builder._apply_shape_keys`: adds a Basis key per
  mesh and one shape key per morph target (named `Morph_{chunk_id:X}`
  to match the C# tree's lack of per-target naming), feeding the
  absolute deformed positions straight into `key.data[vid].co` so
  Blender derives the deltas vs. Basis.
- ❌ Legacy `MeshMorphTarget` 0xCCCC0011 — intentionally not handled;
  the only concrete C# subclass (`ChunkMeshMorphTargets_001`) is also
  a TODO no-op and the abstract base is annotated "no longer used".
- ❄️ Per-target naming / multi-target chunk decoding — the C# reader
  truncates after the vertex array, so the on-disk layout of any
  trailing name table is unverified. Deferred until a real `.skin`
  fixture with named morphs surfaces.

## Phase 7 — Physics & misc ✅

- ✅ `MeshPhysicsData_800` — registered no-op chunk reader. Mirrors
  the C# `ChunkMeshPhysicsData_800.Read` stub (a TODO that just calls
  `base.Read` and leaves the trailing physics payload unparsed).
  Routing the chunk through a typed instance instead of the unknown
  fallback keeps the chunk-table walk clean; nothing downstream
  consumes physics data — Blender users wire physics through the
  Rigid Body / Collision modifiers, not via baked CryEngine
  tetrahedra.
- ✅ Helper types beyond POINT/DUMMY (XREF, CAMERA, GEOMETRY) — the
  parser already mapped all five `HelperType` values via
  `enums.HelperType` (Phase 1). The Blender bridge now picks an
  appropriate `empty_display_type` per type (`PLAIN_AXES` for
  POINT/DUMMY/GEOMETRY, `ARROWS` for XREF, `CONE` for CAMERA), giving
  artists a visual cue without diverging from the C# tree, which
  itself never specialises by HelperType.
- ✅ Full `PhysicsData` payload decode — promoted to Phase 10. The
  per-bone slice (`BonePhysicsGeometry`) and the standalone
  `MeshPhysicsData_800` chunk decode (PrimitiveType 0 / 5 / 6 via
  pyffi's `cgf.xml` schema) have both landed. PrimitiveType 1
  (polyhedron) intentionally deferred — pyffi's schema for it is
  variable-size with multiple "Unknown" / "Junk?" annotations.

## Phase 8 — Distribution ✅

- ✅ Bundle as a Blender extension (`.zip` per `blender_manifest.toml`).
  `scripts/build_extension.py` zips `cryengine_importer/` as a single
  top-level subdir (matches Blender's `pkg_zipfile_detect_subdir_or_none`),
  uses `compresslevel=9` to match `blender --command extension build`,
  and skips `__pycache__/` + `.pyc`/`.pyo`. Manifest declares
  `[permissions] files` (importer reads `.cgf`/`.mtl`/`.dds` from disk)
  and a real maintainer contact. 5 parser tests under
  `tests/parser/test_build_extension.py` round-trip the built zip and
  assert the layout Blender's installer requires (single top-level
  subdir, manifest + `__init__.py` present, no cache artefacts,
  filename matches manifest version).
- ✅ Submit-readiness: validated against Blender 5.1.1 via
  `blender --command extension validate dist/cryengine_importer-0.1.0.zip`
  (TOML parses cleanly, no fatal errors). Manifest fix in this pass:
  shortened the `[permissions] files` value to fit the 64-char
  limit and stripped the trailing period (Blender rejects
  permission strings ending in punctuation). Upload pending via
  <https://extensions.blender.org/submit/>.

## Phase 9 — Generalised import polish (scorg-inspired)

**Guiding constraint**: CryBlend is a standalone Blender plugin first.
Every item below must be useful for *generic* CryEngine assets
(MWO, Aion, ArcheAge, Crytek demos, modded Crysis, etc.) without
requiring Star-Citizen-specific external tooling (datacore/DataForge,
`scdatatools`, `cgf-converter.exe`). SC-specific adapters are allowed
*only* when they slot in behind an existing abstraction so non-SC
users pay zero cost.

Reference notes for the Apache-2.0 [scorg-tools/Blender-Tools](https://github.com/scorg-tools/Blender-Tools)
addon are captured in repo memory at `/memories/repo/scorg-tools-notes.md`
(module map, useful constants, license posture, comparison vs CryBlend).
Key finding: scorg-tools delegates **all** binary parsing to the external
`scdatatools` library and converts geometry via `cgf-converter.exe` → DAE
→ Blender's Collada importer, so its value to us is **workflow patterns
and artist conventions**, not chunk-level code. The follow-up items
below are ordered by standalone usefulness × user-visible impact.

- ✅ **MTL → Blender material wiring (texture-suffix conventions)** —
  Suffix classifier landed: `materials.material.classify_texture_suffix`
  recognises `_diff` / `_ddna` / `_ddn` / `_spec` / `_displ` / `_disp` /
  `_pom_height` / `_decal` / `_damage` / `_stencil` / `_em` / `_ao` on
  the texture filename and overrides the `<Texture Map="...">`
  attribute (Crytek artists frequently leave `Map="Diffuse"` on packed
  textures). Blender bridge wires the new slots: DDNA splits into
  Normal Map + Invert→Roughness (RGB normal, A gloss); `height` feeds
  a Displacement node into the Output's Displacement input; branch
  decals land on a labelled unconnected Image node for artist wiring.
  Tint-palette inputs landed via
  `materials.material.extract_color_params` /
  `extract_scalar_params` / `extract_tint_colors` /
  `is_primary_tint_key` (parses Star Citizen `LayerBlend`
  PublicParams like `DiffuseTint1`, `DirtColor`, `GlossMult1`).
  Blender bridge surfaces every RGB-valued PublicParam as a labelled
  `ShaderNodeRGB` node; primary tints (`DiffuseTint`, `DiffuseTint1`,
  …; excludes `*Wear*` / `Dirt*` / `Dust*`) chain through MixRGB
  MULTIPLY nodes inserted between the diffuse texture and the BSDF
  Base Color input. 12 new tests in
  `tests/parser/test_materials.py` cover colour/scalar parsing,
  partition behaviour against verbatim `Anodized_01_A` PublicParams
  from `SC_mat.mtl`, primary-tint key classification, and end-to-end
  extraction off a real SC `.mtl`.
- ✅ **Companion-file auto-resolution** —
  `cryengine_importer/io/asset_resolver.py` landed:
  `resolve_companions(geometry_path, pack_fs)` returns an
  `AssetCompanions` dataclass with the geometry companion
  (`.cgam` / `.chrm` / `.skinm` / `.cgfm`) and the standard metadata
  sidecars (`.chrparams`, `.cal`, `.mtl`, `.meshsetup`, `.cdf`),
  plus an `extra_exts` parameter for caller-supplied extensions.
  All extensions are stock CryEngine. `core/cryengine.py`'s
  `_auto_detect_companion` now delegates here. A companion
  `find_geometry_files(pack_fs, pattern)` helper enumerates primary
  geometry while excluding the `.cgam`/`.chrm`/`.skinm`/`.cgfm`
  duplicates — directly usable for a future "browse pack file" UI.
  12 tests in `tests/parser/test_asset_resolver.py` cover the full
  set, partial sets, ZIP-archive lookups, case-insensitivity,
  custom extras, and companion-dedup.
- ⏳ **Background/threaded import + progress UI** — refactor
  `blender/addon.py` to run import on a worker thread with a modal
  progress reporter. Pure addon-UX work, format-agnostic; benefits
  every large import (mech, zone, ship). Borrow scorg's
  `concurrent.futures` worker-pool + main-thread task pre-calc pattern
  (clean reimplementation).
- ✅ **CAF → Blender Action for IVO clips** — already wired:
  `core/cryengine.py::_load_animations` appends IVO clips (built by
  `_build_clip_from_ivo_caf` / `_ivo_caf_to_clip` /
  `_build_clips_from_ivo_dba`) to the same `animation_clips` list
  that `blender/action_builder.build_actions` iterates. SC `.caf` /
  `.dba` companion files alongside an IVO geometry now produce
  Blender Actions on the armature without further wiring.
- ⏳ **P4K streaming reader (optional pack-FS adapter)** — extend
  `io/pack_fs.py` with an optional Star Citizen `.p4k` adapter
  (lazy entry table, ZStd decompression, case-insensitive name cache,
  multi-part `.dds.N` reassembly). SC-specific archive format, so it
  slots in *behind* the existing `PackFileSystem` interface — non-SC
  users never load the module. ZStd dependency stays optional.
- ⏳ **`scdatatools` review (research, generic-CryEngine focus)** —
  mine `scdatatools` for *generic* CryEngine insights we may still be
  missing: undocumented chunk layouts, additional controller variants,
  compression decoders. Skip the SC-specific datacore/DataForge bits.
  Output is a follow-up roadmap entry, not a dependency.
- ✅ **Pack-file inspection CLI** —
  `cryengine_importer/pak_browser.py` is a small `python -m`
  entry point that auto-detects directory vs. ZIP-archive sources
  (`RealFileSystem` vs. `ZipFileSystem`) and exposes two subcommands:
  `list` enumerates primary geometry files (delegating to
  `find_geometry_files`, so `.cgam`/`.chrm`/`.skinm`/`.cgfm`
  companions are filtered out automatically), and `companions`
  prints the resolved sibling files (geometry companion + chrparams /
  cal / mtl / meshsetup / cdf) for a specific geometry path. Pure
  Python; the same module powers both stdout output and a future
  Blender "Browse Pack" UI panel. 8 tests in
  `tests/parser/test_pak_browser.py` cover both subcommands against
  ZIP archives and `RealFileSystem` directories, missing-source
  errors, and the no-companions-found exit code.
- ❄️ **Loadout / CDF hierarchical assembly with hardpoints** —
  deferred indefinitely. Requires parsing Star Citizen DataForge
  (`*.dcb`) blueprints, which violates the standalone-Blender-plugin
  posture (would need either an `scdatatools` runtime dependency or a
  hand-rolled DataForge parser of comparable scope to the entire rest
  of CryBlend). The C# tree itself never reads these bytes either.

## Phase 11 — Post-import UI panel & tweak tools

Adds a "CryBlend" sidebar tab (N-panel) in the 3D Viewport that
exposes post-import inspection and tweaks. Per-import metadata is
stamped on the imported Collection's custom properties so the panel
can re-run sub-steps (resolve materials, relink textures, edit tints,
re-import) without forcing the user back through File → Import. UI
work is the priority for this phase; all parser-side logic stays
pure-Python and unit-testable (no `bpy` in the helpers).

Cross-cutting decisions:
- Metadata lives on the imported **Collection**
  (`coll["cryblend"] = {...}`), not on addon preferences — survives
  Save/Reopen and keeps each import self-contained. Schema versioned
  via `["cryblend"]["schema"] = 1` from day one.
- Panels are read-only on parsed structures; mutating operators
  preserve manual user edits where possible (e.g., placeholder swap
  leaves user-edited slots alone).
- Tint preset format is plain JSON
  (`{"DiffuseTint1": [r, g, b], ...}`); auto-save on Blender save is
  *off by default* — implicit disk writes surprise artists.
- Out of scope here: background/threaded import (still tracked under
  Phase 9), P4K-specific UI (panel stays pack-FS-agnostic), and NLA
  sequencer features beyond a "Push to NLA" button.

### Phase A — Import metadata + scaffolding

- ✅ Stamp `coll["cryblend"]` after `build_scene` in
  `blender/addon.py::IMPORT_OT_cryengine._import_one`:
  `source_path`, `object_dir`, `material_libs`,
  `material_libs_resolved`, `axis_forward`, `axis_up`, `convert_axes`,
  `import_related`, `addon_version`, `schema=1`, plus a
  `public_params_by_material` cache used by the tint reset.
- ✅ New `cryengine_importer/blender/asset_metadata.py` —
  `stamp_collection`, `read_metadata`, `has_metadata`,
  `find_cryblend_collections`, `find_active_cryblend_collection`.
  11 unit tests in `tests/parser/test_asset_metadata.py` against
  fake collections (no `bpy`).
- ✅ New `cryengine_importer/blender/panel.py` registers
  `VIEW3D_PT_cryblend` (`bl_category='CryBlend'`) plus the six
  sub-panels in a single module.
- ✅ Wire registration into `blender/addon.py`'s `register()` /
  `unregister()`.

### Phase B — Materials sub-panel *(depends on A)*

- ✅ `VIEW3D_PT_cryblend_materials` lists material libraries with a
  green/red dot for resolved vs missing.
- ✅ `CRYBLEND_OT_set_object_dir` — pure-Python helper
  `_reresolve_materials` re-runs `load_material_libraries` with the
  new directory and swaps placeholder `<obj>_mat<N>` slots in place
  via `mesh.materials[idx] = build_material(...)`.
- ✅ `CRYBLEND_OT_reload_material_from_mtl` — `ImportHelper`-based
  picker, replaces the active object's active material slot.
- ✅ `CRYBLEND_OT_replace_placeholders` — sweeps the collection,
  retries resolution per placeholder name pattern.

### Phase C — Tint palette editor *(depends on A; parallel with B)*

- ✅ `VIEW3D_PT_cryblend_tints` finds `ShaderNodeRGB` nodes whose
  `name` starts with `Tint_` (already wired by Phase 9 in
  `blender/material_builder.py::_wire_tint_palette`); each row is a
  live colour picker bound to `node.outputs[0].default_value`.
  Primary tints group separately from secondary (wear / dirt) ones.
- ✅ `CRYBLEND_OT_save_tint_preset` / `CRYBLEND_OT_load_tint_preset`
  — JSON sidecar `<material>.tint.json`. Pure helpers
  (`save_preset`, `load_preset`, `default_preset_path`,
  `TintPresetError`) in new `materials/tint_presets.py`. 8 unit
  tests in `tests/parser/test_tint_presets.py` cover round-trip,
  overwrite, loose-form ingestion, and 4 malformed-input rejections.
- ✅ `CRYBLEND_OT_reset_tints_from_mtl` — restores tints from the
  cached PublicParams stamped on collection metadata.

### Phase D — Texture relink + missing-files report *(depends on A)*

- ✅ New `cryengine_importer/blender/texture_audit.py` — pure-Python
  `MissingImage`, `find_missing_images` (datablock injected for
  tests; skips packed / loaded / placeholder images),
  `index_directory` (lowercase-basename map), `plan_relinks` (matches
  by basename then image name fallback), and
  `write_missing_files_report`. 11 unit tests in
  `tests/parser/test_texture_audit.py`.
- ✅ `VIEW3D_PT_cryblend_textures` shows broken count + per-image
  expander (capped at 8 entries with overflow line).
- ✅ `CRYBLEND_OT_relink_textures` — pick directory, walk recursively,
  reassign `image.filepath` by lowercase basename, `image.reload()`.
- ✅ `CRYBLEND_OT_export_missing_files` — write a tab-separated
  `<material>\t<image>\t<filepath>` `.txt` for offline `.pak`
  extraction.

### Phase E — Physics & helper tools *(depends on A; parallel with B/C/D)*

- ✅ `VIEW3D_PT_cryblend_physics` — collision-shape count
  (heuristic: name contains `_collision` or starts with `physics_`,
  matching `rigid_body_builder`'s naming), visibility toggle,
  "Add Rigid Body World" one-click via `bpy.ops.rigidbody.world_add`.
- ✅ Helper-display switcher — bulk-set `empty_display_type` /
  `empty_display_size` for selected empties via a scene
  `PropertyGroup` (`PLAIN_AXES` / `ARROWS` / `CONE` / `CUBE` /
  `SPHERE`).

### Phase F — Animation tools *(depends on A; parallel with B–E)*

- ✅ `VIEW3D_PT_cryblend_animation` (poll requires the collection to
  contain an armature) — list `bpy.data.actions` filtered to actions
  whose user is the armature, with per-row "Set Active"
  (`CRYBLEND_OT_set_active_action`) and "Push to NLA"
  (`CRYBLEND_OT_push_action_to_nla`) operators. Capped at 24 entries
  with overflow line.
- ✅ `CRYBLEND_OT_import_extra_clip` — pick `.caf` / `.anim` /
  `.cal`, stage next to the source asset (so chrparams
  auto-discovery picks it up), re-run `CryEngine.process()`, then
  call `build_actions` on the existing armature. New action count
  reported.

### Phase G — Re-import / sticky settings *(depends on A)*

- ✅ `CRYBLEND_OT_reimport` — read metadata off the active cryblend
  collection, delete its objects + collection, re-run
  `bpy.ops.import_scene.cryengine` with the same axes / object_dir /
  import_related.
- ✅ `VIEW3D_PT_cryblend_general` shows source path, object_dir,
  axis settings (read-only labels) plus the Re-import button.

### Phase H — Wire-up + verification

- ✅ All new classes registered in `blender/panel.py::register`,
  invoked from `blender/addon.py::register`.
- ✅ Headless smoke-test extended (`tests/headless_smoke.py`) to
  also assert that the imported collection carries the
  `["cryblend"]` metadata stamp (schema, source path, library
  counts, axes) and that the Phase 11 panel classes registered.
  Verified end-to-end against Blender 5.1.1 on the
  `ARGO_ATLS_SeatAccess.cgf` fixture (5 nodes / 6 objects, exit 0).
- ⏳ Manual GUI verification — pending one-shot interactive run on
  a Blender-equipped machine.

## Phase 10 — CryEngine Converter parser parity

**Parity bar**: the upstream C# tree
([`Markemp/Cryengine-Converter`](https://github.com/Markemp/Cryengine-Converter))
is split into *parsers* (`CgfConverter/Models/`,
`CgfConverter/Models/Chunks/`, `CgfConverter/FileHandlers/`,
`CgfConverter/Cryengine.cs`) and *renderers*
(`CgfConverter/Renderers/{Wavefront,Collada,Gltf,USD}/`). CryBlend
imports CryEngine assets directly into Blender, so **Blender itself
is our renderer** — `Renderers/` is intentionally out of scope; users
re-export via Blender's stock USD/glTF/Collada/Wavefront exporters.
Parser parity, however, is in scope: anything the C# tree can read
off disk, CryBlend should also read.

The items below are gaps against parser parity that were previously
filed under "Deferred". Promoted because they all have working C# code
in v2.0.0 and are useful for *generic* CryEngine assets (not SC-only).

- 🚧 **`PhysicsData` payload decode** — Phase 7 originally registered
  `MeshPhysicsData_800` as a no-op because the C# `Read` is a TODO
  stub and `Models/PhysicsData.cs` only declares the record fields
  (it never actually reads them). The authoritative on-disk layout
  lives in **PyFFI's** `cgf.xml` schema
  (<https://github.com/niftools/pyffi> →
  `pyffi/formats/cgf/cgf.xml`, structs `MeshPhysicsDataChunk` /
  `PhysicsData` / `PhysicsCube` / `PhysicsCylinder` /
  `PhysicsShape6`). File-format layouts aren't copyrightable and
  PyFFI itself ships under BSD-3, so we use that schema as the spec.
  Decoding these unlocks a Blender-first feature: emit collision
  primitives as Empty-with-Rigid-Body-collision (BOX/CYLINDER) and
  proxy meshes as Mesh collision shapes — directly usable in
  Blender's Rigid Body / Collision modifier stack without leaving
  the addon.
  ✅ Per-bone slice (Phase 10 first landing): the 104-byte
  `PhysicsGeometry` payload (previously skipped) is decoded into a
  `BonePhysicsGeometry` dataclass on every `CompiledBone`
  (`physics_alive` / `physics_dead`) and `CompiledPhysicalBone`
  (`physics_geometry`). Carries `physics_geom` id, flags, AABB
  `min`/`max` (with derived `center` / `extent` properties), spring
  angle/tension, damping, and the 3x3 frame matrix.
  ✅ Standalone `MeshPhysicsData_800` payload now decoded too:
  `models/physics.py` ports the pyffi schema for `PhysicsData`
  (60-byte prefix: inertia / quat rotation / center / mass /
  primitive type) plus the `PhysicsCube` (132 bytes) and
  `PhysicsCylinder` / `PhysicsShape6` (104 bytes — identical layouts
  per pyffi) primitive types. `core/chunks/mesh_physics_data.py`
  reads the 24-byte chunk header (physics_data_size / flags /
  tetrahedra_data_size / tetrahedra_id / 2× reserved), the optional
  `PhysicsData` body, and any trailing tetrahedra bytes (capped by
  the chunk's declared size to survive corrupt headers). 12 tests
  in `tests/parser/test_physics.py` cover header-only, tetrahedra
  payload, cube payload, cylinder payload, the unknown-6 alias,
  unknown raw primitive types, and the polyhedron skip path.
  ⏳ Polyhedron primitive (PrimitiveType 1) intentionally deferred:
  pyffi's schema is variable-size with multiple `Unknown` /
  `Junk?` / `not sure` annotations and `PhysicsDataType{0,1}`
  substructs whose `Num Data 1` field is documented as "usually
  0xffffffff" without a firm rule. The reader records the type and
  flags `polyhedron_skipped = True`; the chunk-table walker
  advances past the unread bytes via the chunk header's `size`.
  ✅ Blender Rigid Body bridge: new
  `cryengine_importer/blender/rigid_body_builder.py` plans collision
  shapes from `BonePhysicsGeometry` (one BOX Empty per bone with a
  non-empty AABB, parented under the armature bone via
  `parent_type='BONE'`) and from `MeshPhysicsData_800` cube /
  cylinder payloads (BOX/CYLINDER markers parented under the owning
  mesh). Pure-Python `plan_bone_collision_shapes` /
  `plan_mesh_physics_shapes` are unit-tested; bpy-side
  `apply_collision_shapes` attaches passive Rigid Body Collision when
  the scene already has a Rigid Body World. Wired into
  `scene_builder.build_scene`.
- ⏳ **`CompiledPhysicalBonesIvo` 0x90C687DC** — IVO ragdoll bone
  table; C# implementation exists in v2.0.0. Blocked on a real SC
  character `.chr` fixture; promote to in-progress when one surfaces.
- ⏳ **`CompiledPhysicalBonesIvo320` 0x90C66666** — SC 3.20 variant
  of the above; same blocker.
- ✅ **ZIP archive backend for `pack_fs`** — `ZipFileSystem` landed
  in `cryengine_importer/io/pack_fs.py`. Lazy lower-case → real-name
  index built at construction time (O(1) lookups, case-insensitive per
  CryEngine convention); `open` returns an in-memory `BytesIO` so the
  chunk readers' `seek`/`tell` reliance keeps working. Slots in
  alongside `RealFileSystem` / `InMemoryFileSystem` /
  `CascadedPackFileSystem` behind the same interface. No new
  dependencies (stdlib `zipfile`). Users of MWO / Aion / ArcheAge /
  Crysis can now point CryBlend straight at game `.pak` files.

### Parity gaps with standing rationale to defer

- ❄️ **`ChunkIvoSkinMesh_900` 8-byte tangent-frame smallest-three
  decode** (also listed under Phase 5c F). Blender derives tangents
  from UVs at mesh-eval time, so the decoded data would be discarded.
  Skip-with-rationale, not a true gap.
- ❄️ **Wii-U Stream pack file system** (`WiiuStreamPackFileSystem.cs`).
  Niche console target; no test fixtures available; no user demand.
- ❄️ **Big-endian Rise of Lyric files**. Same rationale as Wii-U
  Stream — niche, no fixtures, no demand. The C# tree carries it for
  historical reasons.
- ❄️ **Terrain** (`CgfConverter/Terrain/`). Judgement call rather
  than parser limitation: CryEngine terrain in Blender is rarely
  what users want — heightmap / splatmap workflows via Blender's
  native displacement modifiers and image-based texture nodes are
  almost always preferable to importing baked terrain tetrahedra.
  Promote if a concrete user request appears.

---

## Deferred / not in scope ❄️

- Direct USD / glTF / Collada / Wavefront export from inside Blender —
  Blender already ships those exporters; the C# tree's `Renderers/`
  layer handles batch conversion *outside* Blender, which CryBlend
  intentionally does not replicate. Users re-export via Blender after
  import.
- See "Parity gaps with standing rationale to defer" under Phase 10
  for parser-side items deferred with rationale.

---

## Cross-references

- C# source of truth: <https://github.com/Markemp/Cryengine-Converter>
  (specifically `CgfConverter/Renderers/Wavefront/` and
  `CgfConverter/Renderers/Collada/` for traversal conventions).
- See [changelog.md](changelog.md) for release history.
