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
- **Pack-file backends** — real filesystem, in-memory, and cascaded
  search paths; `.p4k` streaming is planned (see Known issues)

### Capabilities produced in Blender

- Node hierarchy with world transforms, UVs, loop normals, and
  subset-based material slots (Principled BSDF + image texture nodes)
- Armatures with rest pose, vertex groups, and Armature modifiers for
  `.chr` / `.skin` / IVO skinned meshes
- Blender Actions with fcurves on the armature for classic CryEngine
  `.caf` animation (IVO CAF → Action bridge is pending — see Known
  issues)
- Shape keys (Basis + one per morph target) for
  `CompiledMorphTargets` chunks
- Helper empties with per-`HelperType` display styles (POINT / DUMMY /
  GEOMETRY / XREF / CAMERA)
- Chunk-format coverage up to CryEngine Converter v2.0.0, including
  SC 4.5+ chunk-type IDs and ArcheAge controller variants
  (`Controller_827/828/830/831`)

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
  assets to disk first and point the importer at the extracted tree.
- **IVO animation → Blender Action bridge is pending.** `#caf` and
  `#dba` blocks parse into `AnimationClip`s but are not yet wired
  through `blender/action_builder.py` the way classic `.caf` is.
- **`CompiledPhysicalBonesIvo`** (chunk types `0x90C687DC` and
  `0x90C66666`) are not wired — no test fixture has surfaced.
- **`PhysicsData` payload is skipped.** `MeshPhysicsData_800` is a
  registered no-op; wire physics via Blender's own Rigid Body /
  Collision modifiers.
- **`ChunkIvoSkinMesh_900` 8-byte tangent-frame smallest-three decode
  is intentionally skipped** — Blender derives tangents from UVs.
- **No loadout / CDF hierarchical assembly with hardpoints.** Import
  component assets individually and assemble in Blender.
- **Legacy `MeshMorphTarget` `0xCCCC0011`** and multi-target morph
  name tables are not decoded (upstream C# reader also stubs these).
- **Not in scope:** Wii-U Stream pack filesystem, big-endian Rise of
  Lyric files, and terrain export.
- **Not yet published to extensions.blender.org.** Submission is
  pending a one-shot `blender --command extension validate` run.

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
