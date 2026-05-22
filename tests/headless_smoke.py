"""Headless smoke test for the Blender addon.

Run inside Blender (4.x / 5.x):

    blender --background --python tests/headless_smoke.py -- [--verbose] [--reimport] <path/to/file.cgf>

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


def _parse_argv() -> tuple[str, bool, bool]:
    if "--" not in sys.argv:
        raise SystemExit(
            "Usage: blender --background --python tests/headless_smoke.py "
            "-- [--verbose] [--reimport] <path/to/file.cgf|file.chr|file.cdf>"
        )
    rest = sys.argv[sys.argv.index("--") + 1 :]
    verbose = False
    reimport = False
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in ("-v", "--verbose"):
            verbose = True
        elif flag == "--reimport":
            reimport = True
        else:
            raise SystemExit(f"Unknown flag {flag!r}")
    if not rest:
        raise SystemExit("Missing input file after '--'.")
    return rest[0], verbose, reimport


def main() -> int:
    input_file, verbose, reimport = _parse_argv()
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
    from cryengine_importer.blender.import_visibility import (  # noqa: E402
        should_hide_imported_object_name,
    )

    register()
    try:
        result = bpy.ops.import_scene.cryengine(
            filepath=input_file, verbose=verbose
        )
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

        # Phase 11 — metadata stamp on the imported collection.
        from cryengine_importer.blender.asset_metadata import (  # noqa: E402
            KEY,
            SCHEMA_VERSION,
            find_cryblend_collections,
        )

        stamped = find_cryblend_collections(bpy.context.scene)
        if not stamped:
            print(
                "[smoke] ERROR: no cryblend-stamped collection found",
                file=sys.stderr,
            )
            return 4
        meta = dict(stamped[0][KEY])
        if int(meta.get("schema", 0)) != SCHEMA_VERSION:
            print(
                f"[smoke] ERROR: bad schema {meta.get('schema')!r}",
                file=sys.stderr,
            )
            return 5
        if not meta.get("source_path"):
            print("[smoke] ERROR: empty source_path in metadata", file=sys.stderr)
            return 6
        print(
            f"[smoke] metadata OK: source={Path(meta['source_path']).name}, "
            f"libs={len(meta.get('material_libs', []))}, "
            f"resolved={len(meta.get('material_libs_resolved', []))}, "
            f"axes={meta.get('axis_forward')}/{meta.get('axis_up')}"
        )

        default_hidden = [
            o for o in bpy.data.objects
            if should_hide_imported_object_name(o.name)
        ]
        visible_default_hidden = [
            o for o in default_hidden
            if not o.hide_viewport or not o.hide_render
        ]
        if visible_default_hidden:
            names = ", ".join(o.name for o in visible_default_hidden[:4])
            print(
                f"[smoke] ERROR: default-hidden object(s) visible: {names}",
                file=sys.stderr,
            )
            return 7
        if default_hidden:
            print(f"[smoke] default-hidden objects OK: {len(default_hidden)}")

        if Path(input_file).suffix.lower() == ".cdf":
            attachments = list(meta.get("cdf_attachments", []))
            if not attachments:
                print("[smoke] ERROR: CDF metadata has no attachments", file=sys.stderr)
                return 8
            cdf_objects = [
                o for o in bpy.data.objects
                if o.get("cryblend_cdf_attachment")
            ]
            if not cdf_objects:
                print("[smoke] ERROR: no CDF attachment objects found", file=sys.stderr)
                return 9
            hidden_meta = [a for a in attachments if not bool(a.get("visible", True))]
            hidden_objects = [o for o in cdf_objects if o.hide_viewport]
            if hidden_meta and not hidden_objects:
                print("[smoke] ERROR: expected hidden CDF variants", file=sys.stderr)
                return 10

            bpy.ops.cryblend.set_cdf_attachment_visibility(
                collection_name=stamped[0].name,
                mode="SHOW_ALL",
            )
            if any(o.hide_viewport for o in cdf_objects):
                print("[smoke] ERROR: Show All did not reveal CDF attachments", file=sys.stderr)
                return 11
            bpy.ops.cryblend.set_cdf_attachment_visibility(
                collection_name=stamped[0].name,
                mode="METADATA",
            )
            restored_hidden = [o for o in cdf_objects if o.hide_viewport]
            if hidden_meta and not restored_hidden:
                print("[smoke] ERROR: CDF metadata visibility was not restored", file=sys.stderr)
                return 12
            if any(not o.hide_viewport for o in default_hidden):
                print(
                    "[smoke] ERROR: default-hidden visibility was not restored",
                    file=sys.stderr,
                )
                return 13
            print(
                f"[smoke] cdf metadata OK: attachments={len(attachments)}, "
                f"objects={len(cdf_objects)}, hidden={len(restored_hidden)}"
            )

        # Phase 11 — panel registration smoke (verify the sidebar
        # classes registered without throwing).
        try:
            file_handler = bpy.types.IO_FH_cryengine
            if ".cdf" not in file_handler.bl_file_extensions.lower().split(";"):
                print(
                    "[smoke] ERROR: .cdf missing from drag-and-drop file handler",
                    file=sys.stderr,
                )
                return 14
            if file_handler.bl_import_operator != "import_scene.cryengine":
                print(
                    f"[smoke] ERROR: bad file handler operator "
                    f"{file_handler.bl_import_operator!r}",
                    file=sys.stderr,
                )
                return 15
            _ = bpy.types.VIEW3D_PT_cryblend
            _ = bpy.types.VIEW3D_PT_cryblend_materials
            _ = bpy.types.VIEW3D_PT_cryblend_tints
            _ = bpy.types.VIEW3D_PT_cryblend_cdf
            print(f"[smoke] file handler OK: {file_handler.bl_file_extensions}")
            print("[smoke] panel classes registered")
        except AttributeError as exc:
            print(f"[smoke] ERROR: panel class missing: {exc}", file=sys.stderr)
            return 16

        if reimport:
            result = bpy.ops.cryblend.reimport(
                collection_name=stamped[0].name,
            )
            if "FINISHED" not in result:
                print(f"[smoke] ERROR: reimport returned {result}", file=sys.stderr)
                return 17
            stamped = find_cryblend_collections(bpy.context.scene)
            if not stamped:
                print("[smoke] ERROR: no collection after reimport", file=sys.stderr)
                return 18
            meta = dict(stamped[0][KEY])
            if int(meta.get("schema", 0)) != SCHEMA_VERSION:
                print(
                    f"[smoke] ERROR: bad schema after reimport {meta.get('schema')!r}",
                    file=sys.stderr,
                )
                return 19
            if Path(input_file).suffix.lower() == ".cdf":
                if not meta.get("cdf_attachments"):
                    print(
                        "[smoke] ERROR: CDF attachments missing after reimport",
                        file=sys.stderr,
                    )
                    return 20
                if not bool(meta.get("import_cdf_composition", False)):
                    print(
                        "[smoke] ERROR: CDF composition setting lost after reimport",
                        file=sys.stderr,
                    )
                    return 21
            print(
                f"[smoke] reimport OK: source={Path(meta.get('source_path', '')).name}, "
                f"schema={meta.get('schema')}"
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
