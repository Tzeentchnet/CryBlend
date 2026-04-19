"""Headless smoke test for the Blender addon.

Run inside Blender (4.x / 5.x):

    blender --background --python tests/headless_smoke.py -- <path/to/file.cgf>

What it does:
- Adds the parent ``blender_addon/`` folder to ``sys.path`` so the
  ``cryengine_importer`` package resolves without being installed as
  an extension.
- Registers the addon, invokes the importer on the file passed after
  ``--``, then prints a one-line summary of objects/meshes created.
- Exits non-zero on any failure so CI can pick it up.

This script intentionally lives outside ``tests/parser/`` because it
*requires* ``bpy`` and is not part of the pytest suite.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _parse_argv() -> str:
    if "--" not in sys.argv:
        raise SystemExit(
            "Usage: blender --background --python tests/headless_smoke.py "
            "-- <path/to/file.cgf>"
        )
    rest = sys.argv[sys.argv.index("--") + 1 :]
    if not rest:
        raise SystemExit("Missing input file after '--'.")
    return rest[0]


def main() -> int:
    input_file = _parse_argv()
    if not os.path.isfile(input_file):
        print(f"[smoke] input file not found: {input_file}", file=sys.stderr)
        return 2

    addon_root = Path(__file__).resolve().parent.parent
    if str(addon_root) not in sys.path:
        sys.path.insert(0, str(addon_root))

    import bpy  # noqa: E402

    # Start from an empty scene so counts are deterministic.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    from cryengine_importer import register, unregister  # noqa: E402

    register()
    try:
        result = bpy.ops.import_scene.cryengine(filepath=input_file)
        if "FINISHED" not in result:
            print(f"[smoke] operator returned {result}", file=sys.stderr)
            return 3

        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        empties = [o for o in bpy.data.objects if o.type == "EMPTY"]
        total_tris = sum(len(o.data.polygons) for o in meshes)
        print(
            f"[smoke] OK: {len(meshes)} mesh objects, "
            f"{len(empties)} empties, {total_tris} triangles"
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        try:
            unregister()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
