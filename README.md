# CryEngine Importer for Blender 5+

A pure-Python Blender add-on that imports CryEngine model files
(`.cgf`, `.cga`, `.cgam`, `.chr`, `.skin`, `.caf`, `.dba`, plus the
Star Citizen `#ivo` variants) directly into Blender.

This add-on is a port of the C# [Cryengine-Converter](https://github.com/Markemp/Cryengine-Converter)
project (v2.0.0 is the authoritative spec). Each Python module
references the C# file it was ported from.

Status: **work in progress** — see [roadmap.md](roadmap.md) for the
phased implementation plan and [changelog.md](changelog.md) for what
has shipped.

## Installation

### From a release zip

1. Download `cryengine_importer-<version>.zip` from the
   [Releases](https://github.com/Markemp/CryBlend/releases) page.
2. In Blender 4.2+: **Edit → Preferences → Get Extensions → ⌄ → Install
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

## Repository layout

```
cryengine_importer/        # the Blender add-on (zipped for distribution)
    blender_manifest.toml  # Blender 4.2+ extension manifest
    __init__.py            # register / unregister entry points
    enums.py
    io/                    # binary readers, pack file system, CryXmlB
    core/                  # Model loader, chunk registry
        chunks/            # one module per chunk family
    models/                # plain dataclasses (no bpy)
    materials/             # .mtl parsing, gen-mask, DDS lookup
    blender/               # the only modules that import bpy
tests/
    parser/                # pytest, runs WITHOUT Blender
    fixtures/              # small committable test files
    headless_smoke.py      # run via `blender --background --python ...`
scripts/
    build_extension.py     # builds dist/cryengine_importer-<version>.zip
    build.ps1              # Windows wrapper
```

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

## License

MIT — see [LICENSE](LICENSE). Original C# project © Geoff Gerber
(Markemp) and contributors.