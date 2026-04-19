"""Translate parsed `Material` objects into Blender materials.

Pure-bpy module — only imported when running inside Blender.

The graph we build is a small, opinionated Principled BSDF tree:

    [Diffuse Image] -- Base Color
    [Specular Image]  -- (R) Specular Tint  / (A) Roughness when
                                              SPECULARPOW_GLOSSALPHA
    [Normal Image]   -- Normal Map -- Normal
    [Opacity Image]  -- Alpha (when present)

Texture file resolution: CryEngine .mtl files reference textures with
``.tif`` paths that resolve to ``.dds`` on disk. We try the verbatim
path, then the same path with the extension swapped to ``.dds``, all
through the pack file system (case-insensitive). If neither resolves,
the image node is created with the original path string so the user
can fix it up in Blender.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import bpy  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem
    from ..materials.material import Material, Texture


# Slot -> (input socket name on Principled BSDF, color-space, non-color)
_SLOT_PROFILE: dict[str, tuple[str, bool]] = {
    # slot: (principled_input, is_data_texture)
    "diffuse": ("Base Color", False),
    "normals": ("Normal", True),
    "specular": ("Specular IOR Level", True),
    "opacity": ("Alpha", True),
    "emittance": ("Emission Color", False),
    "occlusion": ("", True),  # not wired yet
}


def build_material(
    material: "Material",
    pack_fs: "IPackFileSystem | None" = None,
    *,
    image_search_root: str | None = None,
) -> "bpy.types.Material":
    """Create (or reuse) a Blender material for ``material``.

    ``pack_fs`` is used to resolve texture file paths; when ``None``,
    image nodes still get created with the raw path so the user can
    relink them later.
    """
    name = material.name or "cryengine_material"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    output = nt.nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    nt.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    # Base PBR scalars from the .mtl attributes.
    if material.diffuse is not None:
        r, g, b = material.diffuse
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
    if material.specular is not None and "Specular IOR Level" in bsdf.inputs:
        # Use luminance as an approximation for the specular scalar.
        sr, sg, sb = material.specular
        bsdf.inputs["Specular IOR Level"].default_value = (sr + sg + sb) / 3.0
    if material.opacity < 1.0 and "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = material.opacity
        mat.blend_method = "BLEND"

    if material.is_two_sided:
        mat.use_backface_culling = False

    # Place texture nodes vertically to the left of the BSDF.
    y = 300
    for tex in material.textures:
        node = _add_texture_node(
            nt, tex, pack_fs=pack_fs, image_search_root=image_search_root, y=y
        )
        y -= 280
        if node is None:
            continue
        _wire_texture(nt, node, tex.slot, bsdf)

    return mat


# ---------------------------------------------------------------- helpers


def _add_texture_node(
    nt: "bpy.types.NodeTree",
    tex: "Texture",
    *,
    pack_fs: "IPackFileSystem | None",
    image_search_root: str | None,
    y: int,
) -> "bpy.types.Node | None":
    if not tex.file:
        return None

    img = _load_image(tex.file, pack_fs=pack_fs, image_search_root=image_search_root)
    node = nt.nodes.new("ShaderNodeTexImage")
    node.location = (-600, y)
    node.label = tex.map
    node.image = img

    is_data = _SLOT_PROFILE.get(tex.slot, ("", False))[1]
    if is_data and node.image is not None:
        try:
            node.image.colorspace_settings.name = "Non-Color"
        except Exception:  # pragma: no cover - bpy version variance
            pass
    return node


def _wire_texture(
    nt: "bpy.types.NodeTree",
    tex_node: "bpy.types.Node",
    slot: str,
    bsdf: "bpy.types.Node",
) -> None:
    profile = _SLOT_PROFILE.get(slot)
    if profile is None or not profile[0]:
        return

    socket_name = profile[0]
    if socket_name not in bsdf.inputs:
        return

    if slot == "normals":
        # Insert a Normal Map node between the image and the BSDF.
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (tex_node.location.x + 250, tex_node.location.y)
        nt.links.new(tex_node.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        return

    nt.links.new(tex_node.outputs["Color"], bsdf.inputs[socket_name])
    if slot == "diffuse" and "Alpha" in bsdf.inputs:
        nt.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])


def _load_image(
    path: str,
    *,
    pack_fs: "IPackFileSystem | None",
    image_search_root: str | None,
) -> "bpy.types.Image | None":
    """Resolve and load an image. Returns the bpy Image (possibly with
    a missing source) or ``None`` when the path is empty."""
    if not path:
        return None

    candidates = [path]
    p = PurePosixPath(path)
    if p.suffix.lower() != ".dds":
        candidates.append(str(p.with_suffix(".dds")))

    resolved_disk: str | None = None
    if pack_fs is not None:
        for cand in candidates:
            try:
                if pack_fs.exists(cand):
                    # `RealFileSystem._resolve` returns a `Path`; we
                    # need the disk path for `bpy.data.images.load`.
                    resolved_disk = _pack_fs_disk_path(pack_fs, cand)
                    if resolved_disk is not None:
                        break
            except Exception:
                continue

    if resolved_disk is None and image_search_root is not None:
        # Last resort: literal join with the search root.
        for cand in candidates:
            joined = str(PurePosixPath(image_search_root) / cand)
            resolved_disk = joined
            break

    img_name = PurePosixPath(path).name
    existing = bpy.data.images.get(img_name)
    if existing is not None:
        return existing

    if resolved_disk is not None:
        try:
            return bpy.data.images.load(resolved_disk, check_existing=True)
        except Exception:
            pass

    # Create a placeholder image so the node still has *something* and
    # the user can relink it from the UI.
    return bpy.data.images.new(img_name, width=4, height=4)


def _pack_fs_disk_path(pack_fs: "IPackFileSystem", path: str) -> str | None:
    """Best-effort: get a real disk path from an `IPackFileSystem`
    entry. Only works for `RealFileSystem`-backed lookups."""
    resolver = getattr(pack_fs, "_resolve", None)
    if resolver is None:
        return None
    try:
        result = resolver(path)
    except Exception:
        return None
    return str(result) if result is not None else None


__all__ = ["build_material"]
