# CryEngine Importer for Blender 5+

A pure-Python Blender add-on that imports CryEngine and Star Citizen
assets directly into Blender — geometry, skinned characters, animation,
materials, and morph targets — with no external converter step.

Status: **work in progress** — see [roadmap.md](roadmap.md) for the
phased implementation plan and [changelog.md](changelog.md) for what
has shipped.

## Installation

### From a release zip

1. Download `cryengine_importer-<version>.zip` from the
   [Releases](https://github.com/Markemp/CryBlend/releases) page.
2. In Blender 5.0+: **Edit → Preferences → Get Extensions → ⌄ → Install
   from Disk…** and pick the zip. Or simply drag the zip into the
   Blender window.
3. Use **File → Import → CryEngine (.cgf/.chr/.skin)**.

### From source

```pwsh
git clone https://github.com/Markemp/CryBlend.git
cd CryBlend
python scripts/build_extension.py
# Install the resulting dist/cryengine_importer-<version>.zip as above.
```

## Supported formats

### File formats ingested

- **Geometry** — `.cgf`, `.cga` (+ `.cgam` companion files auto-resolved)
- **Skinned characters** — `.chr`, `.skin` (+ `.chrm`, `.skinm`
  companions)
- **Animation** — `.caf`, `.dba`, `.anim`; `.chrparams` and `.cal`
  animation-list files drive companion-file discovery
- **Star Citizen `#ivo` variants** of all of the above, including
  `#caf` animation blocks and `#dba` libraries
- **Materials** — `.mtl` in plain XML, CryXmlB, and pbxml encodings,
  with DDS texture lookup (diffuse / normal / spec / gloss)
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
- Chunk-format coverage up to CryEngine Converter v2.0.0, including
  SC 4.5+ chunk-type IDs and ArcheAge controller variants
  (`Controller_827/828/830/831`)

## Post-import sidebar panel

Every imported asset gets stamped with metadata on its Blender
Collection so a dedicated **CryBlend** tab in the 3D Viewport
sidebar (press `N`) can offer post-import inspection and tweaks
without going back through File → Import.

The panel is context-sensitive: it activates whenever the active
collection (or one of its ancestors) was produced by a CryBlend
import. It contains six sub-panels:

- **General** — source path, axis settings, and a one-click
  **Re-import** that re-runs the importer with the cached settings
  (useful after fixing missing `.cgam` companions or pointing at a
  different object directory).
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
- **Animation** *(only when the collection has an armature)* —
  list every action, **Set Active** / **Push to NLA** per row,
  and **Import Extra Clip…** for adding a `.caf` / `.anim` / `.cal`
  to an already-imported armature.

The metadata payload (`collection["cryblend"]`) is plain JSON-safe
data so it survives Save/Reopen of the `.blend`. The schema is
versioned (`schema=1`) for future migrations.

## Building the extension `.zip`

The build script reads the version from
[`cryengine_importer/blender_manifest.toml`](cryengine_importer/blender_manifest.toml)
and writes a Blender-ready zip into the gitignored `dist/` folder:

```pwsh
# Plain build:
python scripts/build_extension.py

# Clean dist/ first and validate with Blender if it's on PATH:
python scripts/build_extension.py --clean --validate
```

## Development

```pwsh
# Parser-only tests (no Blender required):
python -m pytest tests/parser

# Headless Blender smoke test (requires Blender 5+ on PATH):
blender --background --python tests/headless_smoke.py
```

## Known issues / limitations

- **Star Citizen `.p4k` streaming is not implemented yet.** Extract
  assets to disk first, or repackage as a vanilla ZIP and use
  `ZipFileSystem`.
- **`CompiledPhysicalBonesIvo`** (chunk types `0x90C687DC` and
  `0x90C66666`) are not wired — no test fixture has surfaced.
- **Polyhedron physics primitives (`PrimitiveType 1`) are not
  decoded.** Cube / cylinder / unknown-6 are decoded and surfaced as
  collision proxies; the polyhedron schema is too under-specified in
  pyffi's `cgf.xml` to ship without a real fixture.
- **`ChunkIvoSkinMesh_900` 8-byte tangent-frame smallest-three decode
  is intentionally skipped** — Blender derives tangents from UVs.
- **No loadout / CDF hierarchical assembly with hardpoints.** Import
  component assets individually and assemble in Blender.
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
