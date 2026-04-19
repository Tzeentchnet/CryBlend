"""Build the CryEngine Importer Blender extension `.zip` into `dist/`.

Blender 4.2+ extensions are plain zip archives whose root contains the
`blender_manifest.toml` file alongside the addon's Python package. This
script zips `cryengine_importer/` so the manifest sits at the zip root,
excluding caches, byte-compiled files, and other dev artefacts.

Usage:
    python scripts/build_extension.py [--validate]

`--validate` invokes `blender --command extension validate <zip>` if
`blender` is on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "cryengine_importer"
DIST_DIR = REPO_ROOT / "dist"
MANIFEST = ADDON_DIR / "blender_manifest.toml"

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def read_version() -> str:
    with MANIFEST.open("rb") as fh:
        data = tomllib.load(fh)
    version = data.get("version")
    if not version:
        raise RuntimeError(f"`version` missing from {MANIFEST}")
    return str(version)


def iter_addon_files() -> list[Path]:
    files: list[Path] = []
    for path in ADDON_DIR.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(ADDON_DIR).parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        files.append(path)
    return files


def build(out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    addon_root_name = ADDON_DIR.name
    files = iter_addon_files()
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            # Blender expects manifest at zip root OR inside a single
            # top-level folder. We use the addon folder name as the
            # top-level entry so the unpacked install matches the
            # source layout.
            arcname = Path(addon_root_name) / file.relative_to(ADDON_DIR)
            zf.write(file, arcname.as_posix())
    print(f"Built {out_zip} ({len(files)} files, {out_zip.stat().st_size:,} bytes)")


def validate(zip_path: Path) -> int:
    blender = shutil.which("blender")
    if not blender:
        print("warning: `blender` not on PATH; skipping validation", file=sys.stderr)
        return 0
    print(f"Validating with {blender} ...")
    result = subprocess.run(
        [blender, "--command", "extension", "validate", str(zip_path)],
        check=False,
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the built zip with `blender --command extension validate`.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove dist/ before building.",
    )
    args = parser.parse_args(argv)

    if args.clean and DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)

    version = read_version()
    out_zip = DIST_DIR / f"cryengine_importer-{version}.zip"
    build(out_zip)

    if args.validate:
        return validate(out_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
