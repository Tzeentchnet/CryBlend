# Changelog

All notable changes to the CryEngine Importer for Blender addon are
documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The upstream C# converter is tracked separately at
<https://github.com/Markemp/Cryengine-Converter>.

## [Unreleased]

## [0.1.3] — 2026-04-26

### Added

- Added profile-aware CryTools audit/export helpers for Crysis 1 /
  CryEngine 2, Crysis 2, and Crysis 3, including target-specific
  CryExport node naming, skin influence limits, Crysis 1 LOD/piece
  checks, and profile-aware audit report titles.

## [0.1.2] — 2026-04-19

### Added

- Companion geometry extensions (`.cgam` / `.cgfm` / `.chrm` /
  `.skinm`) are now first-class inputs: visible in the File → Import
  browser filter, accepted by the drag-and-drop FileHandler, and
  recognised by `CryEngine.supports_file`. Picking a companion
  directly transparently redirects to the on-disk primary
  (`.cga` / `.cgf` / `.chr` / `.skin`) when present so material and
  skinning metadata still load. Fixes silent no-op on
  `*.cgfm` drops.
- Bulk-import dedup. New
  `cryengine_importer/blender/import_dedup.py` with
  `canonicalize_import_paths()` runs ahead of the per-file import
  loop in `IMPORT_OT_cryengine.execute`. It collapses exact-path
  duplicates (case-insensitive on Windows via `os.path.normcase`)
  and drops any companion geometry file whose primary is **also in
  the same drop batch** — the primary's importer pulls the companion
  in automatically. A companion dropped on its own is preserved.
  Skipped companions are surfaced as an `INFO` operator report. 11
  new tests in `tests/parser/test_addon_dedup.py`; full suite 296
  passed.

### Added

- **Phase 8 / 11 — Headless verification against Blender 5.1.1.** The
  built `dist/cryengine_importer-0.1.0.zip` extension now passes
  `blender --command extension validate` cleanly (manifest fix:
  shortened `[permissions] files` to fit the 64-char limit and
  stripped the trailing period — Blender rejects permission strings
  ending in punctuation). `tests/headless_smoke.py` extended to
  assert the Phase 11 metadata stamp (`schema`, `source_path`,
  `material_libs` / `_resolved` counts, `axis_forward` / `axis_up`)
  and verify all sub-panel classes (`VIEW3D_PT_cryblend`,
  `_materials`, `_tints`) registered. Verified end-to-end against
  the `ARGO_ATLS_SeatAccess.cgf` IVO fixture: 5 nodes / 6 objects,
  exit 0.

- **Phase 11 — Post-import "CryBlend" sidebar panel.** Adds a new
  N-panel tab in the 3D Viewport with six sub-panels (General /
  Materials / Tints / Textures / Physics & Helpers / Animation) that
  let artists tweak imports without going back through File → Import.

  *Metadata layer.* New `cryengine_importer/blender/asset_metadata.py`
  stamps each imported Collection with a JSON-safe
  `["cryblend"]` payload (schema-versioned at `1`): `source_path`,
  `object_dir`, `material_libs`, `material_libs_resolved`,
  `axis_forward`, `axis_up`, `convert_axes`, `import_related`,
  `addon_version`, plus a `public_params_by_material` cache used by
  the tint reset operator. `IMPORT_OT_cryengine._import_one` writes
  the stamp after `build_scene`. Lookup helpers
  (`find_cryblend_collections` / `find_active_cryblend_collection`)
  walk `context.collection` → ancestors → active object's collection
  → first stamped, all duck-typed for unit-testability without `bpy`.

  *Materials.* Lists material libraries with a per-row
  resolved/missing icon. `CRYBLEND_OT_set_object_dir` re-runs
  `load_material_libraries` against a chosen object directory and
  swaps placeholder `<obj>_mat<N>` slots in place via
  `mesh.materials[idx] = build_material(...)`. Companions:
  `CRYBLEND_OT_replace_placeholders` (sweep current libs),
  `CRYBLEND_OT_reload_material_from_mtl` (replace active slot from a
  user-picked `.mtl`).

  *Tints.* Lists the `Tint_*` `ShaderNodeRGB` nodes Phase-9 wired
  into materials with PublicParams; each row binds to the node's
  `default_value` for live colour editing. Primary tints (multiplied
  into Base Color) group separately from secondary (wear / dirt) ones.
  `CRYBLEND_OT_save_tint_preset` / `CRYBLEND_OT_load_tint_preset`
  round-trip a JSON sidecar via new pure-Python
  `cryengine_importer/materials/tint_presets.py` (`save_preset` /
  `load_preset` / `default_preset_path` / `TintPresetError`, with
  schema versioning + tolerant ingestion of legacy loose-form JSON).
  `CRYBLEND_OT_reset_tints_from_mtl` restores tints from the cached
  PublicParams stamped on the collection metadata.

  *Textures.* Live audit of broken image references via new
  `cryengine_importer/blender/texture_audit.py`
  (`MissingImage` dataclass, `find_missing_images` with injectable
  `abspath`/`exists` for tests, `index_directory` lowercase-basename
  map, `plan_relinks`, `write_missing_files_report`). Skips packed,
  loaded, and placeholder images. `CRYBLEND_OT_relink_textures` walks
  a directory, reassigns `image.filepath` by lowercase basename, and
  calls `image.reload()`. `CRYBLEND_OT_export_missing_files` writes
  a tab-separated `<material>\t<image>\t<filepath>` `.txt` for
  offline `.pak` extraction.

  *Physics & Helpers.* Counts collision Empties produced by the
  Phase-10 `rigid_body_builder` (heuristic: name contains
  `_collision` or starts with `physics_`). One-click "Add Rigid Body
  World" wraps `bpy.ops.rigidbody.world_add`. Bulk helper-display
  switcher (`PLAIN_AXES` / `ARROWS` / `CONE` / `CUBE` / `SPHERE`)
  applies to selected empties via a new `CryBlendPanelProps` scene
  PropertyGroup.

  *Animation.* Shows only when the active CryBlend collection
  contains an armature; lists actions with per-row "Set Active"
  (`CRYBLEND_OT_set_active_action`) and "Push to NLA"
  (`CRYBLEND_OT_push_action_to_nla`) operators.
  `CRYBLEND_OT_import_extra_clip` stages a `.caf` / `.anim` / `.cal`
  next to the source asset, re-runs `CryEngine.process()`, then
  `build_actions` against the existing armature.

  *Re-import.* `CRYBLEND_OT_reimport` reads the metadata, deletes
  the current objects + collection, and re-invokes
  `bpy.ops.import_scene.cryengine` with the same axes / object_dir /
  import_related so artists can iterate after fixing missing
  companions.

  30 new pure-Python tests across
  `tests/parser/test_asset_metadata.py` (11),
  `tests/parser/test_tint_presets.py` (8), and
  `tests/parser/test_texture_audit.py` (11). All exercises avoid
  `bpy` via duck-typed fakes. Full suite: 285 passed.

- **Phase 9 — MTL tint-palette inputs.** New helpers on
  `cryengine_importer.materials.material`: `parse_color_value` /
  `parse_scalar_value` (single-value parsers),
  `extract_color_params` / `extract_scalar_params` (partition a
  `PublicParams` dict by value shape), `extract_tint_colors` (sugar
  over a `Material`'s public params), and `is_primary_tint_key`
  (classifies `DiffuseTint` / `DiffuseTint1` … as multiplicative
  primary tints; excludes `*Wear*` blend layers and overlay colours
  like `DirtColor` / `DustColor`). The Blender bridge in
  `blender/material_builder.py` now surfaces every RGB-valued
  PublicParam as a labelled `ShaderNodeRGB` node so artists can
  re-tint imported assets without editing the `.mtl`; primary tints
  are additionally chained through MixRGB(MULTIPLY) nodes inserted
  between the diffuse texture (or BSDF default) and the Principled
  BSDF Base Color input. Verified against the verbatim
  `Anodized_01_A` PublicParams from `tests/fixtures/SC_mat.mtl`
  (`DirtColor`, `DiffuseTint1`, `DiffuseTintWear1`, plus 7 scalar
  params). 12 new tests in `tests/parser/test_materials.py`.

- **Phase 10 — Blender Rigid Body bridge.** New
  `cryengine_importer/blender/rigid_body_builder.py` turns the
  per-bone `BonePhysicsGeometry` AABBs (decoded earlier in Phase 10)
  and the standalone `MeshPhysicsData_800` cube / cylinder primitives
  into Blender collision proxies. Pure-Python
  `plan_bone_collision_shapes(skinning_info, *, include_dead=False)`
  emits one BOX `CollisionShape` per bone with a non-empty alive
  AABB (skipping `is_empty` records and degenerate point-sized
  extents); `plan_mesh_physics_shapes(physics_chunks)` emits one
  BOX/CYLINDER per cube / cylinder / unknown-6 payload (polyhedron
  is skipped, matching the parser's `polyhedron_skipped=True` flag).
  bpy-side `apply_collision_shapes` materialises BOX shapes as
  Empties (`empty_display_type='CUBE'`) parented under the matching
  armature bone via `parent_type='BONE'`; CYLINDER shapes become a
  small wireframe cylinder mesh (Empties have no cylinder display
  type). Passive Rigid Body Collision is attached automatically when
  the scene already has a Rigid Body World — adding a world from
  inside the importer is intrusive, so we leave that to the user.
  `scene_builder.build_scene` now calls `build_rigid_bodies` after
  the armature + animation passes. 13 new tests in
  `tests/parser/test_rigid_body_builder.py` cover the planner
  contract: empty skinning, no-physics bones, empty AABB, degenerate
  extent, alive-only emit, `include_dead` extra emit, offset-AABB
  centre derivation, no-payload mesh chunks, polyhedron skip, cube /
  cylinder / unknown-6 emit, custom `name_prefix`, and unknown raw
  primitive types.

- **Phase 10 — `MeshPhysicsData_800` payload decode (pyffi spec).** The
  chunk's 24-byte header (`physics_data_size` / `flags` /
  `tetrahedra_data_size` / `tetrahedra_id` / 2× reserved) plus the
  optional `PhysicsData` payload are now fully decoded. Authoritative
  on-disk layout came from **PyFFI's** `cgf.xml` schema
  (<https://github.com/niftools/pyffi> → `pyffi/formats/cgf/cgf.xml`,
  structs `MeshPhysicsDataChunk`, `PhysicsData`, `PhysicsCube`,
  `PhysicsCylinder`, `PhysicsShape6`) — the upstream C#
  `ChunkMeshPhysicsData_800.Read` is a TODO stub and
  `Models/PhysicsData.cs` only declares the record fields without
  reading them. New `cryengine_importer.models.physics` module ports
  the schema: `PhysicsData` 60-byte prefix (inertia / quat rotation /
  center / mass / primitive type) plus the `PhysicsCube` (132 bytes,
  2× `PhysicsStruct1` + int) and `PhysicsCylinder` / `PhysicsShape6`
  (104 bytes, identical layouts per pyffi: `float[8]` + int +
  `PhysicsDataType2`) primitive shapes. Trailing `tetrahedra_data` is
  read as raw bytes (capped by the chunk's declared size to survive
  corrupt headers). `PrimitiveType.POLYHEDRON` (1) is intentionally
  not decoded — pyffi's schema is variable-size with multiple
  `Unknown` / `Junk?` / `not sure` annotations and `PhysicsDataType{0,1}`
  substructs whose `Num Data 1` field is documented as "usually
  0xffffffff" without a firm rule. The reader records the type and
  flags `polyhedron_skipped = True`; the chunk-table walker advances
  past unread bytes via the chunk header's `size`. 12 tests in
  `tests/parser/test_physics.py` cover registration, empty / undersized
  chunks, header-only, tetrahedra payload, the truncation cap, the
  cube / cylinder / unknown-6 payloads end-to-end through the chunk
  reader, the standalone `read_physics_cube` / `read_physics_cylinder`
  / `read_physics_data` helpers, and the polyhedron skip path.

- **Phase 9 — pack-file inspection CLI.** New
  `cryengine_importer.pak_browser` module (runnable via
  `python -m cryengine_importer.pak_browser`). Auto-detects directory
  vs. ZIP-archive sources (`RealFileSystem` vs. `ZipFileSystem`) and
  exposes two subcommands: `list` enumerates primary geometry files
  (delegates to `find_geometry_files`, so
  `.cgam`/`.chrm`/`.skinm`/`.cgfm` companions are filtered out
  automatically), and `companions` prints the resolved sibling files
  (geometry companion + chrparams / cal / mtl / meshsetup / cdf) for
  a specific geometry path. Pure Python; the same module powers both
  stdout output and a future Blender "Browse Pack" UI panel. 8 new
  tests in `tests/parser/test_pak_browser.py` cover both subcommands
  against ZIP archives and `RealFileSystem` directories,
  missing-source errors, the no-companions-found non-zero exit code,
  and the argparse subcommand requirement.

### Changed

- **Phase 0 cleanup.** `blender_manifest.toml` was already shipping
  for Blender 5.0+ but the roadmap entry still showed ⏳ (4.2+).
  Promoted to ✅ to reflect reality.

- **Phase 10 — `BonePhysicsGeometry` decode.** The per-bone 104-byte
  `PhysicsGeometry` payload (previously `skip()`ped) is now fully
  decoded by `models.skinning.read_bone_physics_geometry` into a new
  `BonePhysicsGeometry` dataclass. Both `ChunkCompiledBones_800` /
  `_801` (alive + dead LODs → `CompiledBone.physics_alive` /
  `physics_dead`) and `ChunkCompiledPhysicalBones_800`
  (`CompiledPhysicalBone.physics_geometry`) consume the new helper.
  The dataclass carries `physics_geom` id, flags, AABB `min`/`max`
  (with derived `center` / `extent` properties), spring angle/tension,
  damping, and the 3x3 frame matrix — foundation for a future Blender
  Rigid Body bridge that turns each bone's AABB into a BOX collision
  shape parented under the armature without leaving the addon.
  4 new tests in `tests/parser/test_skinning.py` cover the standalone
  decoder, empty-record detection, and integration with both
  `CompiledBones_800` and `CompiledPhysicalBones_800` readers
  (verifying alive vs. dead LOD population and AABB
  `center`/`extent` derivation).
- **Phase 9 — IVO CAF → Blender Action wiring confirmed.** The IVO
  `.caf` / `.dba` clip output of `core/cryengine.py`
  (`_build_clip_from_ivo_caf` / `_ivo_caf_to_clip` /
  `_build_clips_from_ivo_dba`) already flows into the same
  `animation_clips` list that `blender/action_builder.build_actions`
  iterates — so SC `.caf` / `.dba` companion files alongside an IVO
  geometry produce Blender Actions on the armature without further
  wiring. Roadmap entry promoted from ⏳ to ✅.

- **Phase 9 — companion-file auto-resolution.** New
  `cryengine_importer.io.asset_resolver` module. `resolve_companions`
  takes a geometry path + pack-FS and returns an `AssetCompanions`
  dataclass with the geometry companion (`.cgam` / `.chrm` /
  `.skinm` / `.cgfm`) plus the standard metadata sidecars
  (`.chrparams`, `.cal`, `.mtl`, `.meshsetup`, `.cdf`). All extensions
  are stock CryEngine — works for MWO / Aion / ArcheAge / Crysis /
  Star Citizen alike. `extra_exts` lets callers probe additional
  same-stem extensions (e.g. `(".lod0",)`) without modifying the
  module. `core/cryengine.py`'s `_auto_detect_companion` now
  delegates here, so the same logic is reusable from a future
  "browse pack file" UI in the addon. A companion
  `find_geometry_files(pack_fs, pattern)` helper enumerates primary
  geometry files while excluding the
  `.cgam`/`.chrm`/`.skinm`/`.cgfm` duplicates. 12 new tests in
  `tests/parser/test_asset_resolver.py` cover full-set discovery,
  partial sets, ZIP-archive lookups, case-insensitive `RealFileSystem`
  resolution, custom extras (with and without leading dot), and
  companion-dedup in `find_geometry_files`.

- **Phase 10 — `ZipFileSystem` pack-FS backend.** New
  `cryengine_importer.io.pack_fs.ZipFileSystem` reads vanilla
  CryEngine ZIP-format `.pak` archives directly via the stdlib
  `zipfile` module. Lookups are case-insensitive (CryEngine
  convention) via a lower-case → real-name index built at construction
  time, so `exists` / `open` / `read_all_bytes` are O(1). `open`
  returns an in-memory `BytesIO` so the chunk readers' `seek` / `tell`
  reliance keeps working. Slots in alongside `RealFileSystem` /
  `InMemoryFileSystem` / `CascadedPackFileSystem` behind the same
  interface — non-SC users (MWO / Aion / ArcheAge / Crysis) can now
  point CryBlend straight at game `.pak` files instead of extracting
  by hand. 6 new tests in `tests/parser/test_pack_fs.py` cover
  case-insensitive lookup, `open`-returns-seekable, glob, missing-file
  errors, ignored directory entries, and use inside a cascade.
- **Phase 9 — MTL texture-suffix conventions.**
  `cryengine_importer.materials.material.classify_texture_suffix`
  recognises the standard CryEngine artist suffixes
  (`_diff` / `_ddna` / `_ddn` / `_spec` / `_displ` / `_disp` /
  `_pom_height` / `_decal` / `_damage` / `_stencil` / `_em` / `_ao`)
  on the texture filename and overrides the `<Texture Map="...">`
  attribute. This is a vanilla Crytek convention used across every
  CryEngine title, not SC-specific. `Texture.slot` now consults the
  suffix table first because Crytek artists frequently leave
  `Map="Diffuse"` even on packed normal/gloss maps. The Blender
  bridge (`blender/material_builder.py`) wires the new slots:
  `normals_gloss` (DDNA — RGB normal + alpha gloss) splits into a
  Normal Map node *and* an Invert → Roughness path so DXT5nm
  packed textures unpack correctly; `height` (`_displ` / `_disp` /
  `_pom_height`) feeds a Displacement node into the Output's
  Displacement input; branch decals (`_damage` / `_stencil` /
  `_decal`) land on a labelled, unconnected Image node so artists
  can wire them into a second material slot or layered shader
  without losing the reference. 16 new tests in
  `tests/parser/test_materials.py` cover the suffix classifier,
  longest-match priority (`_pom_height` over `_disp`,
  `_displ` over `_disp`), and the suffix-beats-`Map=` behaviour.

- **Phase 8 — distribution.** `scripts/build_extension.py` is now
  submission-ready: bumped to `compresslevel=9` (matches
  `blender --command extension build`), still skips `__pycache__/` and
  `.pyc`/`.pyo`, and zips `cryengine_importer/` as a single top-level
  subdir so Blender's `pkg_zipfile_detect_subdir_or_none` picks it up
  cleanly. `blender_manifest.toml` gains a `[permissions] files`
  declaration (the importer reads `.cgf`/`.mtl`/`.dds` from disk) plus
  a real maintainer contact. New `tests/parser/test_build_extension.py`
  (5 tests) round-trips the built zip and asserts the layout Blender's
  installer requires: single top-level `cryengine_importer/` subdir,
  manifest + `__init__.py` next to it, no cache artefacts, and the zip
  filename matches the manifest version. README install steps updated
  to Blender 5.0+ to match `blender_version_min`. The actual
  extensions.blender.org submission is pending a one-shot
  `blender --command extension validate` on a machine that has Blender
  5.0+ on PATH.

- **Phase 7 — physics & misc.** New
  `core/chunks/mesh_physics_data.py` with `ChunkMeshPhysicsData_800`,
  a registered no-op reader that mirrors the C# stub
  (`ChunkMeshPhysicsData_800.Read` is a TODO that just calls
  `base.Read`; nothing downstream consumes the physics payload). The
  chunk now resolves to a typed instance instead of falling through
  the generic unknown-chunk skip path, while the trailing
  `PhysicsData` bytes remain unread — the chunk-table walker
  advances past them via the offset + size in the header. The full
  `PhysicsData` decode (PrimitiveType 0/1/5/6 plus the
  `PhysicsDataType{0,1,2}` / `PhysicsStruct{1,2,50}` substructures)
  is intentionally deferred: the C# tree itself never reads those
  bytes and annotates the on-disk layout as unverified. The Blender
  bridge in `blender/scene_builder.py` now picks an
  `empty_display_type` per `HelperType` (`PLAIN_AXES` for
  POINT/DUMMY/GEOMETRY, `ARROWS` for XREF, `CONE` for CAMERA),
  giving artists a visual cue for the helper kind without diverging
  from the C# tree's renderer-agnostic helper handling. 3 new parser
  tests under `tests/parser/test_physics.py` cover registration, the
  no-op read path, and an empty-chunk edge case.

- **Phase 6 — morph targets / blend shapes.** New
  `core/chunks/morph_targets.py` with `ChunkCompiledMorphTargets_800`
  / `_801` / `_802` plus the Star Citizen `CompiledMorphTargetsSC`
  variant routed to the same factory (matches C# `Chunk.cs`). 0x801 is
  a no-op mirroring the commented-out C# body; 0x800 and 0x802 share
  the `u32 count` + `count × 16` layout (`u32 vertex_id` + `vec3
  absolute_position`). `models/geometry.MeshGeometry` gains a
  `morph_targets: list[MorphTarget]` field populated by
  `mesh_builder._collect_morph_targets` from every
  `ChunkCompiledMorphTargets` in the owning model's chunk map (works
  for both classic and IVO geometry paths; out-of-range vertex ids
  are dropped defensively). `blender/scene_builder._apply_shape_keys`
  adds a Basis key plus one shape key per morph target named
  `Morph_{chunk_id:X}`, feeding the absolute deformed positions
  straight into `key.data[vid].co` so Blender computes deltas vs. the
  Basis. 10 new parser tests under
  `tests/parser/test_morph_targets.py` cover the three reader
  versions, the SC variant, and the four `mesh_builder` integration
  paths (single chunk, empty chunk skipped, out-of-range ids dropped,
  multi-chunk collection). The legacy 0xCCCC0011 `MeshMorphTarget`
  is intentionally not handled — the only concrete C# subclass is
  also a TODO no-op.

- **Phase 5c-E — Star Citizen #ivo animation.** Full parser support
  for the IVO animation chunks introduced in CryEngine Converter v2:
  `ChunkIvoAnimInfo_901`, `ChunkIvoCAF_900`, `ChunkIvoDBAData_900`,
  and `ChunkIvoDBAMetadata_900` / `_901`. Backed by a shared
  `models/ivo_animation.py` with the `IvoAnimBlockHeader` /
  `IvoAnimControllerEntry` / `IvoDBAMetaEntry` / `IvoAnimationBlock`
  data classes plus helpers for the three position-data formats
  (FloatVector3, SNorm-full, SNorm-packed-with-inactive-channel-skip),
  the two time-key formats (ubyte array vs u16 header + linear
  interpolation), and the float32-quantized FLT_MAX inactive-channel
  sentinel. The aggregator's `_load_animations` now feeds each loaded
  IVO `.caf` into `_build_clip_from_ivo_caf` and each `.dba` library
  fans out to one `AnimationClip` per `IvoAnimationBlock`, named via
  the matching DBA-metadata path stem; bone-hash CRC32 lookups go
  through `skinning_info.compiled_bones`.

- **Phase 5c — v2.0.0 parser parity (Phases A–D).** Integration of the
  upstream CryEngine Converter v2.0.0 release as the new authoritative
  spec. Covers parity bug fixes, new chunk-type IDs, ArcheAge / new
  CryAnim controllers, and the `.cal` animation list loader.

  - **Phase A — parity bug fixes.** `ChunkNodeMeshCombo_900` now skips
    the SC 4.5+ 32-byte post-header pad. `ChunkCompiledBones_901` wires
    bone parents from `ParentControllerIndex` (matches v2; replaces
    the v1.7.1 `OffsetParent` bug). New bounded
    `_read_null_separated_strings(br, count, byte_count)` overload
    used by IVO bones 0x901 + NodeMeshCombo. Validated against 13 real
    Star Citizen 4.5+ `.cga`/`.cgf` files (Greycat PTV collection).

  - **Phase B — new SC 4.5+ chunk-type IDs.** Added to `enums.ChunkType`
    so they resolve to known names and skip cleanly: `MotionParams`
    (0x3002) and 10 IVO types (`IvoAnimInfo`, `IvoCAFData`,
    `IvoDBAData`, `IvoDBAMetadata`, `IvoAssetMetadata`,
    `IvoLodDistances`, `IvoLodMeshData`, `IvoBoundingData`,
    `IvoChunkTerminator`, `IvoMtlNameVariant`).

  - **Phase C — new controller versions.** `ChunkController_827`
    (uncompressed CryKeyPQLog, no embedded local header — used by
    legacy 0x744 CAFs), `ChunkController_828` (no-op skip),
    `ChunkController_830` (PQLog + Flags), and `ChunkController_831`
    (compressed dual-track with eF32/eU16/eByte time formats and full
    quat-compression set: eNoCompressQuat, eShotInt3Quat,
    eSmallTreeDWORD/48Bit/64Bit/64BitExt). Honours `tracks_aligned`
    4-byte padding and shared/separate position time tracks. Plus
    `ChunkMotionParameters_925` (132-byte read-only metadata). 5 new
    tests in `tests/parser/test_animation.py`.

  - **Phase D — `.cal` animation list (ArcheAge).** New
    `core/cal_loader.py` ports `Cal/CalFile.cs`: key=value entries,
    `//` and `--` comments (including inline `//`), `$Include`
    recursion with multi-path fallback (`game/` prefix +
    including-file-relative resolution), cycle-safe traversal, and
    parent-wins merging. `CryEngine._load_animations` falls back to
    `<stem>.cal` when no `.chrparams` is present. 6 new tests in
    `tests/parser/test_cal_loader.py`.

  Reference: <https://github.com/Markemp/Cryengine-Converter> v2.0.0
  is now the primary spec. Test suite: 115 passing (up from 99).

- **Phase 5b — IVO mesh translation.** `core/mesh_builder.py` now
  recognises `ChunkIvoSkinMesh` as a valid `node.mesh_data` and
  translates its inline vertex/index/UV/colour/normal streams into a
  `MeshGeometry`. Per-node subsets are filtered by
  `IvoMeshSubset.node_parent_index` against the new
  `ChunkNode.ivo_node_index` (set by
  `CryEngine._build_nodes_ivo`), mirroring C#
  `CryEngine.BuildNodeStructure`'s
  `skinMesh.MeshSubsets.Where(x => x.NodeParentIndex == index)`.
  Skin / chr single-root nodes (no `ivo_node_index`) emit every
  subset. 5 new tests in `tests/parser/test_mesh_builder.py`.

- **Phase 5 — Star Citizen IVO format.** Six new chunk readers under
  `core/chunks/`: `mtl_name_900.py`, `mesh_900.py`,
  `compiled_bones_ivo.py` (versions 0x900 + 0x901),
  `node_mesh_combo.py`, `binary_xml_data.py` (version 0x3), and
  `ivo_skin_mesh.py`. Each is registered against every IVO chunk-type
  alias the C# `Chunk.New` factory routes through (`MtlNameIvo` /
  `MtlNameIvo320`, `MeshIvo` / `MeshInfo`, `IvoSkin` / `IvoSkin2`,
  `CompiledBones_Ivo` / `CompiledBones_Ivo2`, `BinaryXmlDataSC`).
- **`models/ivo.py`** — `IvoGeometryMeshDetails`, `IvoMeshSubset`,
  and `NodeMeshCombo` dataclasses (port of the IVO-only records in
  `Models/Structs/Structs.cs`).
- **`enums.py`** — `IvoGeometryType` and `VertexFormat` (full port).
- **`io/binary_reader.py`** — `read_ivo_mesh_details`,
  `read_ivo_mesh_subset`, `read_quat_snorm16`,
  `read_quat_dymek_half`, and `read_vec3_snorm16` helpers, porting
  the IVO-relevant `BinaryReaderExtensions.cs` extension methods.
- **`models/skinning.py#CompiledBone`** — added `parent_index`,
  `object_node_index`, and `bind_pose_matrix` fields (only populated
  by the new 0x900 / 0x901 IVO bone readers).
- **`CryEngine._build_nodes_ivo`** — routed automatically for any
  asset whose first model carries the `#ivo` file signature. Two
  flavours: NodeMeshCombo-driven (`.cgf` / `.cga`) builds one
  synthetic `ChunkNode` per `NodeMeshCombo_900` row with parents
  wired by index; skin / chr files synthesize a single root node
  bound to the IvoSkinMesh from the companion `.skinm` / `.chrm`.
- **`ChunkIvoSkinMesh_900`** decodes IVO datastreams in-place: u16/u32
  indices, snorm-packed verts/uvs (16/20 bpe), CryHalf2 / float3
  normals, snorm tangents ± bitangents, snorm + float qtangents,
  4- and 8-influence bone maps, IRGBA colour streams; unknown stream
  types are skipped while preserving the 8-byte stream alignment.
- 12 new tests in `tests/parser/test_ivo.py` covering each chunk
  reader plus two `CryEngine.process()` end-to-end tests using a
  trivial in-memory pack FS (one skin + companion file, one
  NodeMeshCombo-driven cgf + cgam).

- **Phase 4 — Animation.** Three new chunk readers under
  `core/chunks/`: `controller.py` (versions 0x826 keyed,
  0x829 header-only stub, 0x905 compressed Star Citizen / new
  CryAnimation tracks), `bone_anim.py` (0x290 stub matching the C#
  reference), and `global_animation_header_caf.py` (0x971 — the CAF
  file's anchor with FilePath / total duration / locator keys, plus
  CRC32-based endianness probe).
- **`models/animation.py`** — `ControllerKey`, `MotionParams905`,
  `ControllerInfo`, `Animation905`, `ChrParamsAnimation`, `ChrParams`,
  plus the consumer-facing `BoneAnimationTrack` / `AnimationClip`
  aggregates that the Blender layer keys into.
- **`enums.py`** — `KeyTimesFormat`, `CompressionFormat`, and
  `AnimAssetFlags` (port of ChunkController_905's nested enums).
- **`io/binary_reader.py`** — five compressed-quaternion decoders
  (`read_short_int3_quat`, `read_small_tree_dword_quat`,
  `read_small_tree_48bit_quat`, `read_small_tree_64bit_quat`,
  `read_small_tree_64bit_ext_quat`), porting
  `Models/Structs/Structs.cs#SmallTree*Quat`.
- **`core/chrparams_loader.py`** — `load_chrparams(path, pack_fs)`
  and `parse_chrparams(root)` for the `<Params><AnimationList>...`
  XML schema. Routes through `cry_xml.read_stream` so pbxml /
  CryXmlB variants are handled transparently.
- **`CryEngine._load_animations`** — auto-discovers a sibling
  `<stem>.chrparams`, then for every `<Animation path="..."/>` entry
  loads the referenced CAF/ANIM file via the pack FS, parses its
  `GlobalAnimationHeaderCAF` + `Controller_905`, and emits one
  `AnimationClip` per file. Inline Controller_905 chunks already in
  `self.models` also contribute clips. Per-bone tracks are matched
  back to bones by `controller_id` (CRC32 of bone name) against
  `skinning_info.compiled_bones`.
- **`blender/action_builder.py`** — `build_actions(cryengine, arm_obj)`
  creates one `bpy.types.Action` per clip with per-bone fcurve groups,
  keys `pose.bones["…"].location` (vec3) and `…rotation_quaternion`
  (re-ordered from on-disk `(x,y,z,w)` to mathutils `(w,x,y,z)`) at
  `time_secs * scene.fps + 1`. The first clip is auto-assigned to the
  armature's `animation_data.action` so playback works on import,
  and `scene.frame_end` is extended to cover the longest clip.
- **`scene_builder.build_scene`** — when an armature was built and
  `cryengine.animation_clips` is non-empty, calls `build_actions`.
- **`IMPORT_OT_cryengine`** — operator report now also includes the
  number of imported animation clips.
- 8 new tests in `tests/parser/test_animation.py` covering Controller
  0x826 / 0x829 / 0x905 (synthesized single-track + Animation905
  binding), GlobalAnimationHeaderCAF 0x971 (CRC32 path round-trip,
  durations), chrparams XML parsing (with + without AnimationList),
  and the `ShortInt3Quat` / `SmallTreeDWORDQuat` decoder helpers.

- **Phase 3 — Skinning.** Seven new chunk readers under
  `core/chunks/`: `compiled_bones.py` (versions 0x800/0x801),
  `compiled_physical_bones.py` (0x800), `compiled_physical_proxies.py`
  (0x800), `compiled_int_skin_vertices.py` (0x800/0x801),
  `compiled_int_faces.py` (0x800), `compiled_ext_to_int_map.py`
  (0x800) and `bone_name_list.py` (0x745). PhysicsGeometry payload
  bytes are skipped (the importer doesn't visualise CryEngine's
  collision primitives) but bone hierarchy, transforms, weights, and
  ext→int vertex mapping are fully parsed.
- **`models/skinning.py`** — `CompiledBone`, `CompiledPhysicalBone`,
  `PhysicalProxy`, `MeshBoneMapping`, `IntSkinVertex`, `TFace`, and
  the `SkinningInfo` aggregate (port of `Models/SkinningInfo.cs`).
- **`CryEngine._build_skinning`** — consolidates every skinning chunk
  across all loaded models (so a `.chr` and its `.chrm` companion
  produce one `SkinningInfo`) into `cryengine.skinning_info`.
- **`blender/armature_builder.py`** — `build_armature(cryengine)`
  creates `bpy.data.armatures` + EditBones placed by world transform
  (with a parent-chain fallback for 0x801 records that lack a world
  matrix), parents each bone to its `parent_bone`, and points single-
  child bones' tails at the child for cleaner viewport visualisation.
  `attach_skin(arm_obj, mesh_obj, cryengine)` adds the Armature
  modifier and creates one vertex group per bone, weighted via
  `ext_to_int_map -> int_skin_vertices[i].bone_mapping`.
- **`scene_builder.build_scene`** — when `skinning_info.has_skinning_info`,
  builds the armature, parents every mesh Object to it, and attaches
  the skin (vertex groups + modifier).
- 10 new tests in `tests/parser/test_skinning.py` covering all seven
  chunks (root-only / parent-link bone trees, 0x801 record sizing,
  4-influence skin verts, ext-to-int map, physical proxy verts +
  indices, physical bone parent_id resolution, NUL-terminated
  bone-name list).

### Fixed

- Repaired a botched merge in `blender/scene_builder.py` that left
  the material-slot loop and `_resolve_material` mangled.

### Added (earlier in Unreleased)

- Project roadmap (`roadmap.md`) and this changelog (Phase 0).
- **`materials/material.py`** — `Material`, `Texture`, `MaterialFlags`
  IntFlag (port of `Models/Materials/MaterialFlags.cs`), and
  `Material.from_xml_root` / `from_xml`. Decodes the
  `MtlFlags` / `GenMask` / `StringGenMask` / `Diffuse` / `Specular`
  / `Emissive` / `Opacity` / `Shininess` / `Glossiness` /
  `GlowAmount` / `AlphaTest` attributes, the nested `<Textures>`,
  `<PublicParams>`, and `<SubMaterials>` elements, and the
  ``%FOO%BAR`` shader gen-mask string. Maps the 28 raw
  ``<Texture Map="...">`` strings (Diffuse / Bumpmap / Normal /
  Specular / Heightmap / Decal / SubSurface / Custom / Opacity /
  Smoothness / Emittance / Occlusion / TexSlot1–13, etc.) to a
  normalized `Texture.slot` matching `Texture.MapTypeEnum` in the
  C# tree.
- **`materials/loader.py`** — `load_material(path, pack_fs)` reads
  through the existing `cry_xml` decoder so pbxml / CryXmlB / plain
  XML are all handled transparently; appends `.mtl` when the
  caller passes a stem. `load_material_libraries(names, fs,
  object_dir=)` mirrors the C# `MaterialUtilities.FromStream`
  behaviour, falling back to ``object_dir/<name>`` when the direct
  lookup misses, and keys results by lowercased file stem.
- **`CryEngine.materials`** — the aggregator now calls
  `load_material_libraries` after `_collect_material_library_files`,
  populating a `{stem: Material}` map for downstream consumers.
  `CryEngine` accepts an `object_dir=` kwarg that's forwarded to the
  loader.
- **`blender/material_builder.py`** — `build_material(material,
  pack_fs)` creates a Blender material with a Principled BSDF +
  per-texture `ShaderNodeTexImage` graph. Slot routing: diffuse →
  Base Color (and Alpha when present), normals → Normal Map node
  → Normal, specular → Specular IOR Level, opacity → Alpha,
  emittance → Emission Color. Non-color slots are tagged
  `Non-Color`; backface culling is disabled for two-sided materials.
  Texture lookup tries the verbatim `.tif` path then the same path
  with the extension swapped to `.dds`, both via the pack FS, and
  falls back to a 4×4 placeholder image so the user can relink it
  in the UI.
- **`scene_builder._resolve_material`** — walks `node.material_id`
  → `ChunkMtlName.name` → lowercased stem → `cryengine.materials`
  → `sub_materials[mat_id]` to pick the Blender material per
  subset, falling back to the previous placeholder when any link is
  missing.
- **`IMPORT_OT_cryengine.object_dir`** — new operator property /
  file-picker `DIR_PATH` field. When set, a second `RealFileSystem`
  rooted at the directory is layered on top of the file's directory
  via `CascadedPackFileSystem`, mirroring the C# `-objectdir`
  argument. The same path is forwarded to `CryEngine` for relative
  material library resolution.
- 8 new tests in `tests/parser/test_materials.py` covering the XML
  parser (single material, library w/ submaterials, pbxml round
  trip, gen-mask decoding, two-sided flag) and the loader (missing
  file → None, stem-only retry, lowercased-stem keying, object_dir
  fallback).
- **`blender/scene_builder.py`** — `build_scene(cryengine)` walks
  `cryengine.nodes`, calls `build_geometry` on each, and creates
  `bpy.data.meshes` via `from_pydata` (verts + triangles), a UV layer
  (V-flipped for Blender's bottom-up convention), per-corner vertex
  colours, placeholder materials per subset with polygon
  `material_index` assignments, and custom split normals when
  available. Helper / empty nodes become Blender Empties so child
  parenting still works. Parent / child wiring is done in a second
  pass via `obj.parent` + `matrix_local`; row-major node transforms
  are transposed to `mathutils.Matrix` (column-major) (Phase 1B).
- **`blender/addon.py`** — `IMPORT_OT_cryengine.execute()` now wires
  the file picker through `RealFileSystem` (rooted at the file's
  directory so `.cgam` / `.chrm` companions resolve), `CryEngine`,
  and `build_scene`, reporting node / object / material-lib counts
  on success (Phase 1C).
- **`tests/headless_smoke.py`** — `blender --background --python`
  driver: registers the addon in an empty scene, runs the importer
  on a file passed after `--`, and prints / exit-codes a one-line
  mesh / empty / triangle summary for CI.
- **`models/geometry.py`** — `MeshGeometry` and `SubsetRange`
  dataclasses, the bpy-free contract between the chunk graph and the
  upcoming Blender bridge. Exposes `positions`, `indices`, `normals`,
  `uvs`, `colors`, `subsets`, plus `triangles` / `num_triangles`
  conveniences (Phase 1A).
- **`core/mesh_builder.py`** — `build_geometry(node)` dereferences a
  `ChunkNode`'s `mesh_data` to its accompanying `ChunkDataStream`s
  and `ChunkMeshSubsets`, returning a `MeshGeometry`. Falls back to
  the combined `VERTSUVS` stream when separate position/uv/colour
  streams are absent, and synthesises a single material-slot subset
  when no `MeshSubsets` chunk is present. Silently drops streams
  whose `DatastreamType` does not match the expected slot
  (Phase 1A).
- **`ChunkNode.world_matrix`** — local-to-world 4×4 (row-major,
  translation in last row) computed by walking the
  `parent_node` chain. Mirrors C#
  `WavefrontModelRenderer.GetNestedTransformations` (Phase 1A).
- 9 new tests in `tests/parser/test_mesh_builder.py` covering the
  builder's empty-mesh / split-file / wrong-stream-type paths and
  the world-matrix composition order.

## [0.1.0-dev] — initial parser spike

### Added

- Package skeleton: `cryengine_importer/{io,core,blender,enums.py}`
  with parser-only modules kept free of `bpy` for headless testing.
- **`io/binary_reader.py`** — endianness-toggleable reader port of
  `Services/EndiannessChangeableBinaryReader.cs` and
  `Utilities/BinaryReaderExtensions.cs`. Scalar (i8–u64, f16/f32/f64),
  string (`fstring` / `cstring` / `pstring`), and alignment helpers.
- **`io/cry_xml.py`** — port of `CryXmlB/CryXmlSerializer.cs`. Auto-
  detects pbxml, CryXmlB, and plain XML; returns `ElementTree`.
- **`io/pack_fs.py`** — `IPackFileSystem` interface plus
  `RealFileSystem` (case-insensitive resolve), `InMemoryFileSystem`,
  and `CascadedPackFileSystem` (LIFO stacking). Ports
  `PackFileSystem/RealFileSystem.cs` and `CascadedPackFileSystem.cs`.
- **`core/model.py`** — file-header + chunk-table parsing for file
  versions 0x744, 0x745, 0x746, and 0x900.
- **`core/chunk_registry.py`** — `@chunk(type, version)` decorator
  factory replacing the C# reflection-based dispatcher; falls back to
  `ChunkUnknown` for unregistered combinations.
- **`core/chunks/`** — readers for 12 Crydata chunk families
  (20 `(type, version)` registrations): Header (0x744 / 0x745 /
  0x746 / 0x900), SourceInfo (0x0 / 0x1), ExportFlags (0x1), Timing
  (0x918 / 0x919), SceneProps (0x744), Helper (0x744), MtlName
  (0x744 / 0x800 / 0x802 / 0x804), Mesh (0x800 / 0x801 / 0x802),
  MeshSubsets (0x800), DataStream (0x800 / 0x801), Node (0x823 /
  0x824), Unknown.
- **`core/cryengine.py`** — Crydata aggregator: companion-file
  discovery (`.cgam` / `.chrm`), node hierarchy wiring, mesh
  resolution across split files, and material-library file
  collection.
- **`enums.py`** — initial port: `FileVersion`, `FileType`,
  `ChunkType` (~73 entries), `MtlNameType`, `MtlNamePhysicsType`,
  `HelperType`, `DatastreamType`.
- **`blender/addon.py`** — Phase-0 stub `IMPORT_OT_cryengine`
  operator: file picker → parse → INFO report (no mesh creation).
- **`tests/parser/`** — six pytest modules covering binary reader,
  CryXmlB, pack FS, chunk registry + readers, and the `CryEngine`
  aggregator. All tests run without Blender installed.
- **`tests/fixtures/`** — sample material XML (`SimpleMat.xml`,
  `MultipleMats.xml`, `pbxml.mtl`, `SC_mat.mtl`).

### Deferred

- IVO (`#ivo`) file branch and all IVO-specific chunks.
- Skinning chunks (`CompiledBones`, `CompiledIntSkinVertices`,
  `CompiledIntFaces`, `CompiledExtToIntMap`, `CompiledMorphTargets`,
  `CompiledPhysicalBones`, `CompiledPhysicalProxies`).
- Animation chunks (`Controller`, `BoneAnim`, `BoneNameList`,
  `GlobalAnimationHeaderCAF`).
- Material file (`.mtl`) loading and Blender material translation.
- chrparams / character XML loading.
- Mesh creation in Blender (Phase 1).
- `blender_manifest.toml` for the Blender 4.2+ extension format.

[Unreleased]: https://github.com/Markemp/CryBlend/compare/HEAD...HEAD
[0.1.0-dev]: https://github.com/Markemp/CryBlend
