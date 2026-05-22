# CryEngine Importer for Blender 5+

A pure-Python Blender add-on that imports CryEngine and Star Citizen
assets directly into Blender — geometry, skinned characters, animation,
materials, and morph targets — with no external converter step.

Status: **work in progress** — this README tracks the current source
tree.

Current manifest version: **0.1.6** (`dist/cryengine_importer-0.1.6.zip`).

## Installation

### From a release zip

1. Download `cryengine_importer-<version>.zip` from the [Releases](https://github.com/Tzeentchnet/CryBlend/releases) page.
2. In Blender 5.0+: **Edit → Preferences → Get Extensions → ⌄ → Install
   from Disk…** and pick the zip. Or simply drag the zip into the
   Blender window.
3. Use **File → Import → CryEngine (.cgf/.chr/.skin/.cdf)**.

### From source

```pwsh
git clone https://github.com/Tzeentchnet/CryBlend.git
cd CryBlend
python scripts/build_extension.py
# Install the resulting dist/cryengine_importer-<version>.zip as above.
```

## Supported formats

### Game support summary

| Game / asset family | Support level | Current coverage |
| --- | --- | --- |
| Crysis 1 / CryEngine 2 | Targeted | Geometry, skinned characters, CDF assembly, classic CAF/DBA animation, materials, vanilla `.pak`/ZIP assets, and the CE2 authoring audit profile. |
| Crysis 2 | Targeted | Core CryEngine import path plus `.chrparams` animation discovery, nested animation-root handling, and the Crysis 2 tool profile. |
| Crysis 3 | Targeted | Core CryEngine import path plus Crysis 3 metadata/audit helpers, profile skin-weight limits, and nested animation-folder discovery. |
| Star Citizen | Partial | IVO geometry, skinned meshes, `#caf` / `#dba` animation blocks, CryXmlB/pbxml materials, and SC 4.5+ chunk IDs; `.p4k` streaming still requires extraction or repackaging first. |
| ArcheAge | Partial | `.cal` animation-list resolution and ArcheAge controller variants (`Controller_827/828/830/831`); broader workflows depend on available sample coverage. |
| Other CryEngine titles | Experimental | Stock CGF/CGA/CHR/SKIN/CDF/MTL and `.pak`-style layouts may import when their chunk versions match the implemented readers. |

### File formats ingested

- **Geometry** — `.cgf`, `.cga` (+ `.cgam` companion files auto-resolved)
- **Skinned characters** — `.chr`, `.skin` (+ `.chrm`, `.skinm`
  companions)
- **Character definitions** — `.cdf` composition files import the base
  model plus bound `CA_SKIN` / `CA_BONE` attachments, and `.chr` /
  `.skin` imports can auto-compose through a uniquely matching nearby
  CDF.
- **Animation** — `.caf`, `.dba`, `.anim`; `.chrparams` and `.cal`
  animation-list files drive companion-file discovery, including
  `$Include` chains and wildcard CAF entries in `.chrparams`. Classic
  CryEngine controllers, including Controller_829 CAFs,
  Controller_905 DBA tracks, and the newer Controller_827 / 830 / 831
  CAF variants, are converted from Cry bind space into Blender
  pose-basis armature actions with continuous quaternion signs and the
  same safe bone names as the imported armature; top-level root-motion
  tracks and invalid position tracks are skipped.
  Additive, aim-pose, look-pose, and metadata clips are labelled as
  pose-layer data and are blocked from standalone playback in the panel;
  switching playable actions resets stale pose transforms first.
  Imported actions are tagged as full-body,
  additive, aim-pose, look-pose, or partial-body clips so CryEngine
  pose-layer assets are distinguishable from standalone actions.
  Non-clip metadata entries such as `.animevents`, `.lmg`,
  `$TracksDatabase`, and `$AnimEventDatabase` are skipped.
- **Star Citizen `#ivo` variants** of all of the above, including
  `#caf` animation blocks and `#dba` libraries
- **Materials** — `.mtl` in plain XML, CryXmlB, and pbxml encodings,
  with DDS texture lookup (diffuse / normal / spec / gloss). Diffuse
  texture alpha is treated as opacity only when the material explicitly
  requests opacity or alpha testing; otherwise it is kept as packed
  shader data so opaque assets stay visible in Material Preview.
- **Pack-file backends** — real filesystem, in-memory, ZIP-archive
  (vanilla CryEngine `.pak`), and cascaded search paths; Star Citizen
  `.p4k` streaming is planned (see Known issues)

### Capabilities produced in Blender

- Node hierarchy with world transforms, UVs, loop normals, and
  subset-based material slots (Principled BSDF + image texture nodes)
- Armatures with rest pose, vertex groups, and Armature modifiers for
  `.chr` / `.skin` / IVO skinned meshes
- Blender Actions with fcurves on the armature for both classic
  CryEngine `.caf` animation and Star Citizen IVO `#caf` / `#dba`
  clips
- Shape keys (Basis + one per morph target) for
  `CompiledMorphTargets` chunks
- Helper empties with per-`HelperType` display styles (POINT / DUMMY /
  GEOMETRY / XREF / CAMERA)
- Rigid Body collision proxies from `BonePhysicsGeometry` AABBs
  (one BOX Empty per bone, parented under the matching armature
  bone) and from `MeshPhysicsData_800` cube / cylinder primitives
  (BOX/CYLINDER markers parented under the owning mesh). Passive
  Rigid Body Collision is attached automatically when the scene
  already has a Rigid Body World.
- CDF attachment assembly: skinned attachments reuse the base armature
  when possible, bone attachments are parented to their named skeleton
  bone with their CDF bind transform preserved, empty binding slots
  become helper empties, raw attachment flags and material overrides
  are stamped in collection metadata, and rope descriptors keep helper
  data for later simulation work.
- Chunk-format coverage up to CryEngine Converter v2.0.0, including
  SC 4.5+ chunk-type IDs and ArcheAge controller variants
  (`Controller_827/828/830/831`)

### Bulk import & companion-file dedup

You can multi-select or drag-and-drop any number of geometry files
into Blender at once. Before the import loop runs, the operator
canonicalises the dropped paths so each asset is imported exactly
once:

- Exact-path duplicates are collapsed; on Windows the comparison is
  case-insensitive (matching NTFS).
- When a geometry companion (`.cgam` / `.cgfm` / `.chrm` / `.skinm`)
  appears in the **same batch** as its primary (`.cga` / `.cgf` /
  `.chr` / `.skin`), the companion is dropped — the primary's
  importer pulls the companion in automatically. A skipped-count
  is surfaced as an `INFO` report.
- A companion dropped on its own (no primary in the batch) is still
  imported; the parser will transparently load the on-disk primary
  beside it when present, so the asset still resolves to a single
  Blender collection.

This means dragging an entire folder of `.cgf` + `.cgfm` pairs is
safe — each asset is built once, not twice.

## Post-import sidebar panel

Every imported asset gets stamped with metadata on its Blender
Collection so a dedicated **CryBlend** tab in the 3D Viewport
sidebar (press `N`) can offer post-import inspection and tweaks
without going back through File → Import.

The panel is context-sensitive: it activates whenever the active
collection (or one of its ancestors) was produced by a CryBlend
import. It contains nine sub-panels:

- **General** — source path, axis settings, and a one-click
  **Re-import** that re-runs the importer with the cached settings
  (useful after fixing missing `.cgam` companions or pointing at a
  different object or animation directory).
- **Materials** — per-library *resolved / missing* status, plus:
  - **Set Object Directory…** — pick the game's data root; CryBlend
    re-runs material-library resolution and swaps any placeholder
    `<mesh>_mat<N>` slots in place.
  - **Retry Placeholder Materials** — sweep the collection and retry
    resolution against the current libraries.
  - **Replace Active Slot from `.mtl`…** — point at any `.mtl` to
    replace the active object's active material slot.
- **Tints** — for the active material, lists every `Tint_*`
  `ShaderNodeRGB` node (created from the `<PublicParams>` colours of
  the source `.mtl`, e.g. SC `LayerBlend` `DiffuseTint1`,
  `DirtColor`). Primary tints (multiplied into Base Color) group
  separately from secondary (wear / dirt) tints. Each row is a live
  colour picker; **Save Preset…** / **Load Preset…** round-trip a
  JSON sidecar (`<material>.tint.json`); **Reset to .mtl Values**
  restores the originals from the cached PublicParams.
- **Textures** — live audit of broken image references with a
  per-image expander. **Relink From Directory…** walks a folder and
  reassigns image filepaths by lowercase basename; **Export Missing
  List…** writes a tab-separated `<material>\t<image>\t<filepath>`
  `.txt` for offline `.pak` extraction.
- **Physics & Helpers** — count of Phase-10 collision proxies,
  visibility toggle, **Add Rigid Body World** one-click (so the
  passive collision shapes activate), and a bulk helper-display
  switcher (PLAIN_AXES / ARROWS / CONE / CUBE / SPHERE) with size
  control for selected empties.
- **CDF Attachments** *(only on CDF-composed imports)* — base CDF
  source, bound / empty / missing attachment counts, type totals,
  hidden variant and rope counts, and import warnings. **Restore Source**
  reapplies source CDF visibility plus default-hidden helper states;
  **Reveal All** shows every imported attachment; hidden-variant preview
  buttons reveal and select source-hidden variants for inspection.
  Empty-slot **Select** / **Bind** rows target sockets directly, and
  **Bind Active Slot…** imports a picked `.cgf` / `.cga` / `.chr` /
  `.skin` model under the selected slot so weapon and eye-style sockets
  follow the rig.
- **Crysis 2 Tools** — validation and metadata helpers adapted from
  the legacy XSI, Max, and Maya CryTools toolchains, not ports of the
  old exporter runtimes. A **Target** selector switches shared checks
  between Crysis 1 / CryEngine 2, Crysis 2, and Crysis 3 profiles so
  export-node names, skin influence limits, LOD/piece wording, and
  report text match the intended game. The panel checks XSI-style material IDs
  (`_<ID>_<Name>`) for duplicates, gaps, and the 0-31 range; stores
  physicalization labels (`Default`, `ProxyNoDraw`, `NoCollide`,
  `Obstruct`) on materials; creates or updates Crysis 1
  `<stem>_CryExportNode` or later `CryExportNode_<stem>` / `CryExport_<stem>`
  empties from export filenames using XSI-safe naming rules; flags
  Max-style `_` excluded objects; validates `pieces=...` references
  in object property rows; detects Crysis 1 `-LOD1-` through `-LOD4-`
  names and suggests `_LOD1_` through `_LOD4_` normalization; stores
  Maya-style animation export option metadata on the collection; and
  reports Blender-native skin and shape-key findings for export
  planning. Crysis 1 / CE2 reports call out the legacy
  `/skipmateriallibrarycreation` Resource Compiler convention but do
  not invoke RC.
- **Crysis 3 Tools** — game-specific artist helpers adapted from
  CryTools-era Max/Maya workflows. Apply CGF metadata tags to the
  selected objects (`mass`, `density`, force primitives, joint
  `limit` / `twist` / `bend` / `pull` / `push` / `shift`, destroyable
  `Main` / `Remain`, `entity`, `rotaxes`, `sizevar`, and `generic`),
  inspect the active object's tags in the legacy UDP text style,
  select objects in the imported collection by numeric metadata
  comparisons, copy CryEngine attachment-helper XML for selected
  helpers to the clipboard, reset selected/all camera pivot offsets,
  and run the target-aware asset audit. The audit mirrors practical
  checks from the CryEngine Max, Maya, and XSI exporters: CryExport
  root presence and naming, export type / filename validity where the
  profile expects it, empty export roots, duplicate export names, mesh
  UV and colour-set counts, degenerate faces, non-uniform scale,
  CHR/SKIN skeleton presence, skin-weight normalization, profile skin
  influence limits (5 for Crysis 1 / CE2 and Crysis 2, 8 for Crysis
  3), material ID duplicates / gaps, and known physicalization surface
  names. These authoring/export metadata tags are not normally present
  in shipped game depot assets; CDF rope physics and attachment data are
  imported into CDF metadata instead. The panel previews the first
  findings and copies the full report to the clipboard.
- **Animation** *(only when the collection has an armature)* —
  list every action, **Play** / **Push to NLA** per row,
  and **Import Extra Clip…** for adding a `.caf` / `.anim` / `.cal`
  to an already-imported armature. **Play** assigns the action, jumps to
  the action start frame, extends the scene range when needed, and starts
  timeline playback in an interactive Blender session. Non-standalone
  pose-layer clips are labelled in the action list, for example additive,
  aim-pose, look-pose, and partial-body actions, and are blocked from
  direct **Play** assignment so they cannot corrupt later actions.
  If a `.chrparams` file points at a missing `$Include`, the importer
  reports the missing include path and no actions are created from that
  absent list.
  The import dialog also has an optional **Animations Directory** field
  for extracted animation folders that live outside the chosen object or
  game root. It adds a search root for `.chrparams` wildcard CAF entries
  and for nested `Animations/Animations/...` extraction layouts commonly
  seen in Crysis 2 and Crysis 3 assets.

The metadata payload (`collection["cryblend"]`) is plain JSON-safe
data so it survives Save/Reopen of the `.blend`. The schema is
versioned (`schema=2`) for future migrations.

## Building the extension `.zip`

The build script reads the version from
[`cryengine_importer/blender_manifest.toml`](cryengine_importer/blender_manifest.toml)
and writes a Blender-ready zip into the gitignored `dist/` folder:

```pwsh
# Plain build:
python scripts/build_extension.py

# Clean dist/ first and validate with Blender if it's on PATH:
python scripts/build_extension.py --clean --validate

# Maintainer distribution check: build, validate, install-enable,
# and verify the installed bl_ext.user_default module loads:
pwsh scripts/distribute.ps1 -Blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
```

Run the distribution check once per Blender version you intend to use;
Blender keeps separate `5.0`, `5.1`, etc. user extension directories.
Close any open Blender windows for that version before the install-enable
step, because Windows can lock the existing extension folder.

For version **0.1.6**, the local build artifact is
`dist/cryengine_importer-0.1.6.zip`.

## Known issues / limitations

- **Star Citizen `.p4k` streaming is not implemented yet.** Extract
  assets to disk first, or repackage as a vanilla ZIP and use
  `ZipFileSystem`.
- **`CompiledPhysicalBonesIvo`** (chunk types `0x90C687DC` and
  `0x90C66666`) are not wired — no test fixture has surfaced.
- **Polyhedron physics primitives (`PrimitiveType 1`) are partially
  decoded.** Embedded polyhedron vertices/triangles are surfaced as
  wire mesh collision proxies; polyhedrons that only reference
  external data streams are still skipped until a fixture proves that
  path.
- **CDF rope physics is a first-pass preservation/import aid, not a
  CryEngine-equivalent simulation.** Rope attachments keep their parsed
  `PhysPropType` / `lod*` metadata and hidden helper curves where a
  matching bone chain is available; full constraint simulation still
  needs more sample-driven validation.
- **`ChunkIvoSkinMesh_900` 8-byte tangent-frame smallest-three decode
  is intentionally skipped** — Blender derives tangents from UVs.
- **No runtime loadout switching for CDF attachment slots.** Static
  CDF composition, bound geometry, empty slots, visibility metadata,
  and rope helpers import, but game-script loadout swaps still need a
  separate data source.
- **Legacy `MeshMorphTarget` `0xCCCC0011`** and multi-target morph
  name tables are not decoded (upstream C# reader also stubs these).
- **Not in scope:** Wii-U Stream pack filesystem, big-endian Rise of
  Lyric files, and terrain export.
- **Not yet published to extensions.blender.org.** The built zip
  passes `blender --command extension validate`; submission via
  <https://extensions.blender.org/submit/> is pending.

## Attributions

- [Cryengine-Converter](https://github.com/Markemp/Cryengine-Converter)
  by Geoff Gerber (Markemp) and contributors — the authoritative C#
  reference for CryEngine chunk layouts. CryBlend began as a port of
  that project; most parser modules cite the specific C# file they
  were ported from, and v2.0.0 is the spec targeted for new work. The
  `blender/` adapters are Blender-specific and have no direct C#
  counterpart (the C# tree targets Wavefront / Collada / USD
  exporters, not Blender).
- [scorg-tools/Blender-Tools](https://github.com/scorg-tools/Blender-Tools)
  (Apache-2.0) — consulted for Star Citizen workflow patterns
  (companion-file resolution, texture-suffix conventions, threaded
  import UX). CryBlend does not include code from this project.

## License

MIT — see [LICENSE](LICENSE).
