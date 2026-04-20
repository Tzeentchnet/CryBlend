# Changelog

All notable changes to the CryEngine Importer for Blender addon are
documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The upstream C# converter is tracked separately at
<https://github.com/Markemp/Cryengine-Converter>.

## [Unreleased]

### Added

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
