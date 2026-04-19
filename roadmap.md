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
- ⏳ `blender_manifest.toml` (Blender 4.2+ extension format)

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
- ❄️ Full `PhysicsData` payload decode (PrimitiveType 0/1/5/6 + the
  `PhysicsDataType{0,1,2}` / `PhysicsStruct{1,2,50}` substructures
  in `Models/PhysicsData.cs` + `Models/Structs/Structs.cs`).
  Intentionally deferred — the C# tree itself never reads these bytes
  and annotates the on-disk layout as unverified.

## Phase 8 — Distribution ⏳

- ⏳ Bundle as a Blender extension (`.zip` per `blender_manifest.toml`)
- ⏳ Submit to extensions.blender.org

---

## Deferred / not in scope ❄️

- Wii-U Stream pack file system (`WiiuStreamPackFileSystem.cs`)
- ZIP archive backend for the pack FS
- Terrain export (`CgfConverter/Terrain/` in the upstream C# tree)
- Direct USD / glTF / Collada / Wavefront export from inside Blender —
  Blender already ships those exporters; the C# tree handles batch
  conversion outside Blender
- Big-endian Rise of Lyric files (covered by C# tree; not currently
  prioritized for the addon)

---

## Cross-references

- C# source of truth: <https://github.com/Markemp/Cryengine-Converter>
  (specifically `CgfConverter/Renderers/Wavefront/` and
  `CgfConverter/Renderers/Collada/` for traversal conventions).
- See [changelog.md](changelog.md) for release history.
