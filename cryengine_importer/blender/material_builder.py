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

import logging
import hashlib
from pathlib import Path, PurePosixPath
import tempfile
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

import bpy  # type: ignore[import-not-found]

from ..io.dds import (
    DdsError,
    classify_split_sidecars,
    find_split_sidecars,
    read_dds_bytes,
    read_dds_info,
)
from ..materials.material import MaterialFlags

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem
    from ..materials.material import Material, Texture


# Slot -> (input socket name on Principled BSDF, color-space, non-color)
_SLOT_PROFILE: dict[str, tuple[str, bool]] = {
    # slot: (principled_input, is_data_texture)
    "diffuse": ("Base Color", False),
    "normals": ("Normal", True),
    "normals_gloss": ("Normal", True),  # DDNA: RGB normal + A gloss
    "specular": ("Specular IOR Level", True),
    "opacity": ("Alpha", True),
    "emittance": ("Emission Color", False),
    "occlusion": ("", True),  # not wired yet
    "height": ("", True),     # wired to Output's Displacement input
    "detail": ("", True),     # detail bump map; combined into Normal
    "decal": ("", False),     # branch decal: dropped onto a labelled, unconnected node
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
    name = _material_name(material)
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    if _material_is_nodraw(material):
        _build_nodraw_material(mat)
        return mat

    _set_blend_method(mat, "OPAQUE")
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
    if _material_is_eye_shader(material):
        _configure_eye_shader(bsdf)
    if material.opacity < 1.0 and "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = material.opacity
        _set_blend_method(mat, "BLEND")
    elif material.alpha_test > 0.0:
        _set_blend_method(mat, "CLIP")
        try:
            mat.alpha_threshold = material.alpha_test
        except Exception:  # pragma: no cover - bpy version variance
            pass
    elif material.texture("opacity") is not None:
        _set_blend_method(mat, "BLEND")

    if material.is_two_sided:
        mat.use_backface_culling = False

    # Place texture nodes vertically to the left of the BSDF.
    y = 300
    diffuse_tex_node: "bpy.types.Node | None" = None
    texcoord_node: "bpy.types.Node | None" = None
    for tex in material.textures:
        texture_node = _add_texture_node(
            nt,
            tex,
            material=material,
            pack_fs=pack_fs,
            image_search_root=image_search_root,
            y=y,
        )
        y -= 280
        if texture_node is None:
            continue
        node, image_resolved = texture_node
        if not image_resolved:
            _mark_missing_texture_node(node)
            continue
        if texcoord_node is None:
            texcoord_node = nt.nodes.new("ShaderNodeTexCoord")
            texcoord_node.location = (-900, 300)
        if "UV" in texcoord_node.outputs and "Vector" in node.inputs:
            nt.links.new(texcoord_node.outputs["UV"], node.inputs["Vector"])
        _wire_texture(nt, node, tex.slot, bsdf, output, material=material)
        if tex.slot == "diffuse" and diffuse_tex_node is None:
            diffuse_tex_node = node

    _wire_tint_palette(nt, material, bsdf, diffuse_tex_node, y=y)

    return mat


def _material_is_nodraw(material: "Material") -> bool:
    shader = (material.shader or "").lower()
    return shader == "nodraw" or MaterialFlags.NoDraw in material.flags


def _material_name(material: "Material") -> str:
    label = _clean_blender_name(material.name or "")
    source = _clean_blender_name(PurePosixPath(material.source_file or "").stem)
    if source and label:
        if source.lower() == label.lower():
            return source
        return f"{source}_{label}"
    return source or label or "cryengine_material"


def _clean_blender_name(value: str) -> str:
    return value.replace("\\", "_").replace("/", "_").strip()


def _material_is_eye_shader(material: "Material") -> bool:
    return (material.shader or "").lower() == "eye"


def _configure_eye_shader(bsdf: "bpy.types.Node") -> None:
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 1.0
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.18
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0


def _build_nodraw_material(mat: "bpy.types.Material") -> None:
    mat.diffuse_color = (0.0, 0.0, 0.0, 0.0)
    _set_blend_method(mat, "BLEND")
    try:
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        output = nt.nodes.new("ShaderNodeOutputMaterial")
        transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
        nt.links.new(transparent.outputs["BSDF"], output.inputs["Surface"])
    except Exception:  # pragma: no cover - bpy version variance
        logger.debug("failed to build transparent Nodraw material", exc_info=True)


# ---------------------------------------------------------------- helpers


def _add_texture_node(
    nt: "bpy.types.NodeTree",
    tex: "Texture",
    *,
    material: "Material | None",
    pack_fs: "IPackFileSystem | None",
    image_search_root: str | None,
    y: int,
) -> "tuple[bpy.types.Node, bool] | None":
    if not tex.file:
        return None

    img, image_resolved = _load_image(
        tex.file,
        pack_fs=pack_fs,
        image_search_root=image_search_root,
    )
    node = nt.nodes.new("ShaderNodeTexImage")
    node.location = (-600, y)
    node.label = tex.map
    node.image = img

    if node.image is not None and _texture_uses_packed_alpha(tex, material):
        try:
            node.image.alpha_mode = "CHANNEL_PACKED"
        except Exception:  # pragma: no cover - bpy version variance
            logger.debug(
                "failed to set CHANNEL_PACKED alpha mode on %r",
                getattr(node.image, "name", "?"),
                exc_info=True,
            )

    is_data = _SLOT_PROFILE.get(tex.slot, ("", False))[1]
    if is_data and node.image is not None:
        try:
            node.image.colorspace_settings.name = "Non-Color"
        except Exception:  # pragma: no cover - bpy version variance
            logger.debug(
                "failed to set Non-Color colorspace on %r",
                getattr(node.image, "name", "?"),
                exc_info=True,
            )
    return node, image_resolved


def _mark_missing_texture_node(node: "bpy.types.Node") -> None:
    node.label = f"Missing: {node.label}" if node.label else "Missing Texture"
    try:
        node.mute = True
    except Exception:  # pragma: no cover - bpy version variance
        pass


def _set_blend_method(mat: "bpy.types.Material", value: str) -> None:
    try:
        mat.blend_method = value
    except Exception:  # pragma: no cover - bpy version variance
        pass


def _wire_texture(
    nt: "bpy.types.NodeTree",
    tex_node: "bpy.types.Node",
    slot: str,
    bsdf: "bpy.types.Node",
    output: "bpy.types.Node",
    *,
    material: "Material | None" = None,
) -> None:
    profile = _SLOT_PROFILE.get(slot)
    if profile is None:
        return

    # DDNA — packed normal (RGB) + gloss (A). Wire the colour to a
    # Normal Map node and the alpha to (1 - alpha) → Roughness.
    if slot == "normals_gloss":
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (tex_node.location.x + 250, tex_node.location.y)
        nt.links.new(tex_node.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        if "Roughness" in bsdf.inputs:
            inv = nt.nodes.new("ShaderNodeInvert")
            inv.location = (tex_node.location.x + 250, tex_node.location.y - 180)
            nt.links.new(tex_node.outputs["Alpha"], inv.inputs["Color"])
            nt.links.new(inv.outputs["Color"], bsdf.inputs["Roughness"])
        return

    if slot == "normals":
        # Insert a Normal Map node between the image and the BSDF.
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (tex_node.location.x + 250, tex_node.location.y)
        nt.links.new(tex_node.outputs["Color"], nm.inputs["Color"])
        _connect_normal(nt, nm.outputs["Normal"], bsdf, location=nm.location)
        return

    if slot == "detail":
        tex_node.label = f"Detail: {tex_node.label}".strip()
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.label = "Detail Normal"
        nm.location = (tex_node.location.x + 250, tex_node.location.y)
        if "Strength" in nm.inputs:
            nm.inputs["Strength"].default_value = _detail_bump_strength(material)
        nt.links.new(tex_node.outputs["Color"], nm.inputs["Color"])
        _connect_normal(nt, nm.outputs["Normal"], bsdf, location=nm.location)
        return

    # Height / displacement — feed the Output node's Displacement input
    # via a Displacement node (mid-grey neutral, scale defaults to 1).
    if slot == "height":
        disp = nt.nodes.new("ShaderNodeDisplacement")
        disp.location = (tex_node.location.x + 250, tex_node.location.y)
        nt.links.new(tex_node.outputs["Color"], disp.inputs["Height"])
        if "Displacement" in output.inputs:
            nt.links.new(disp.outputs["Displacement"], output.inputs["Displacement"])
        return

    # Branch decals (damage / stencil / decal) — leave as a labelled,
    # unconnected node so artists can manually wire into a second
    # material slot or a layered shader without losing the reference.
    if slot == "decal":
        tex_node.label = f"Decal: {tex_node.label}".strip()
        return

    if (
        slot == "specular"
        and material is not None
        and material.use_gloss_in_specular_map
        and "Roughness" in bsdf.inputs
    ):
        inv = nt.nodes.new("ShaderNodeInvert")
        inv.location = (tex_node.location.x + 250, tex_node.location.y - 180)
        nt.links.new(tex_node.outputs["Alpha"], inv.inputs["Color"])
        nt.links.new(inv.outputs["Color"], bsdf.inputs["Roughness"])

    if slot == "opacity":
        if "Alpha" not in bsdf.inputs:
            return
        _connect_alpha(
            nt,
            _texture_alpha_output(tex_node),
            bsdf,
            material=material,
            location=tex_node.location,
        )
        return

    if not profile[0]:
        return

    socket_name = profile[0]
    if socket_name not in bsdf.inputs:
        return

    nt.links.new(tex_node.outputs["Color"], bsdf.inputs[socket_name])
    if slot == "diffuse" and "Alpha" in bsdf.inputs:
        if (
            material is not None
            and material.use_gloss_in_diffuse_alpha
            and "Roughness" in bsdf.inputs
        ):
            inv = nt.nodes.new("ShaderNodeInvert")
            inv.location = (tex_node.location.x + 250, tex_node.location.y - 180)
            nt.links.new(tex_node.outputs["Alpha"], inv.inputs["Color"])
            nt.links.new(inv.outputs["Color"], bsdf.inputs["Roughness"])
        elif _diffuse_alpha_drives_opacity(material):
            _connect_alpha(
                nt,
                tex_node.outputs["Alpha"],
                bsdf,
                material=material,
                location=tex_node.location,
            )


def _connect_alpha(
    nt: "bpy.types.NodeTree",
    alpha_socket: "bpy.types.NodeSocket",
    bsdf: "bpy.types.Node",
    *,
    material: "Material | None",
    location,
) -> None:
    if "Alpha" not in bsdf.inputs:
        return
    target = bsdf.inputs["Alpha"]
    threshold = _alpha_clip_threshold(material)
    if threshold is None:
        for link in _links_to_input(nt, bsdf, "Alpha"):
            nt.links.remove(link)
        nt.links.new(alpha_socket, target)
        return

    clip = nt.nodes.new("ShaderNodeMath")
    clip.operation = "GREATER_THAN"
    clip.label = "Alpha Test"
    clip.location = (location.x + 250, location.y - 180)
    clip.inputs[1].default_value = threshold
    nt.links.new(alpha_socket, clip.inputs[0])
    for link in _links_to_input(nt, bsdf, "Alpha"):
        nt.links.remove(link)
    nt.links.new(clip.outputs[0], target)


def _alpha_clip_threshold(material: "Material | None") -> float | None:
    if material is None or material.alpha_test <= 0.0:
        return None
    return max(0.0, min(1.0, material.alpha_test))


def _connect_normal(
    nt: "bpy.types.NodeTree",
    normal_socket: "bpy.types.NodeSocket",
    bsdf: "bpy.types.Node",
    *,
    location,
) -> None:
    if "Normal" not in bsdf.inputs:
        return
    target = bsdf.inputs["Normal"]
    existing_links = _links_to_input(nt, bsdf, target.name)
    if not existing_links:
        nt.links.new(normal_socket, target)
        return

    prior_socket = existing_links[-1].from_socket
    for link in existing_links:
        nt.links.remove(link)

    add = nt.nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.location = (location.x + 250, location.y)
    normalize = nt.nodes.new("ShaderNodeVectorMath")
    normalize.operation = "NORMALIZE"
    normalize.location = (location.x + 500, location.y)
    nt.links.new(prior_socket, add.inputs[0])
    nt.links.new(normal_socket, add.inputs[1])
    nt.links.new(add.outputs[0], normalize.inputs[0])
    nt.links.new(normalize.outputs[0], target)


def _detail_bump_strength(material: "Material | None") -> float:
    if material is None:
        return 1.0
    raw = getattr(material, "public_params", {}).get("DetailBumpScale")
    if raw is None:
        return 1.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0


def _texture_alpha_output(tex_node: "bpy.types.Node") -> "bpy.types.NodeSocket":
    if "Alpha" in tex_node.outputs:
        return tex_node.outputs["Alpha"]
    return tex_node.outputs["Color"]


def _links_to_input(
    nt: "bpy.types.NodeTree",
    node: "bpy.types.Node",
    socket_name: str,
) -> list["bpy.types.NodeLink"]:
    return [
        link
        for link in list(nt.links)
        if _same_node(link.to_node, node)
        and getattr(link.to_socket, "name", None) == socket_name
    ]


def _same_node(left: "bpy.types.Node", right: "bpy.types.Node") -> bool:
    if left is right or left == right:
        return True
    return getattr(left, "name", None) == getattr(right, "name", None)


def _texture_uses_packed_alpha(tex: "Texture", material: "Material | None") -> bool:
    """True when an image's alpha channel is shader data, not opacity."""
    slot = tex.slot
    if slot in {"normals_gloss", "custom", "custom_secondary", "detail", "decal", "blend"}:
        return True
    if material is None:
        return False
    if slot == "diffuse" and material.use_gloss_in_diffuse_alpha:
        return True
    if slot == "diffuse" and not _diffuse_alpha_drives_opacity(material):
        return True
    if slot == "specular" and material.use_gloss_in_specular_map:
        return True
    return False


def _diffuse_alpha_drives_opacity(material: "Material | None") -> bool:
    if material is None:
        return False
    if material.use_gloss_in_diffuse_alpha:
        return False
    if material.texture("opacity") is not None:
        return False
    if material.opacity < 1.0 or material.alpha_test > 0.0:
        return True
    return False


def _wire_tint_palette(
    nt: "bpy.types.NodeTree",
    material: "Material",
    bsdf: "bpy.types.Node",
    diffuse_tex_node: "bpy.types.Node | None",
    *,
    y: int,
) -> None:
    """Surface PublicParams RGB colours as labelled inputs.

    Primary tint slots (``DiffuseTint``, ``DiffuseTint1`` …) are
    multiplied into Base Color via a chain of MixRGB(MULTIPLY) nodes
    inserted between the diffuse texture (or BSDF socket default) and
    the Principled BSDF Base Color input. Non-primary colour params
    (``DiffuseTintWear*``, ``DirtColor`` …) are still emitted as
    labelled RGB nodes so artists can wire them by hand.
    """
    # Local import to keep this module's top-level cost minimal.
    from ..materials.material import (
        extract_color_params,
        is_primary_tint_key,
    )

    color_params = extract_color_params(material.public_params)
    if not color_params:
        return

    # Lay RGB nodes out below the texture column.
    rgb_x = -600
    primary_chain_output: "bpy.types.NodeSocket | None" = None

    for key, rgb in color_params.items():
        rgb_node = nt.nodes.new("ShaderNodeRGB")
        rgb_node.location = (rgb_x, y)
        rgb_node.label = key
        rgb_node.name = f"Tint_{key}"
        rgb_node.outputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
        y -= 220

        if not is_primary_tint_key(key):
            continue

        # Build / extend a Multiply mix chain that runs into Base Color.
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.location = (rgb_x + 250, y + 220)

        if primary_chain_output is None:
            # First primary tint — feed from the diffuse texture's
            # Color output, or fall back to the BSDF's existing Base
            # Color default.
            if diffuse_tex_node is not None:
                # Drop any existing link into Base Color so the mix
                # chain sits in the middle.
                for link in _links_to_input(nt, bsdf, "Base Color"):
                    nt.links.remove(link)
                nt.links.new(
                    diffuse_tex_node.outputs["Color"], mix.inputs["Color1"]
                )
            else:
                bc = bsdf.inputs["Base Color"].default_value
                mix.inputs["Color1"].default_value = (bc[0], bc[1], bc[2], bc[3])
        else:
            nt.links.new(primary_chain_output, mix.inputs["Color1"])

        nt.links.new(rgb_node.outputs["Color"], mix.inputs["Color2"])
        primary_chain_output = mix.outputs["Color"]

    if primary_chain_output is not None:
        nt.links.new(primary_chain_output, bsdf.inputs["Base Color"])


def _load_image(
    path: str,
    *,
    pack_fs: "IPackFileSystem | None",
    image_search_root: str | None,
) -> "tuple[bpy.types.Image | None, bool]":
    """Resolve and load an image plus whether it loaded from disk.

    Missing sources still return a placeholder image so the node keeps
    the relinkable virtual path, but callers should not wire it into the
    shader graph as though it were texture data.
    """
    if not path:
        return None, False

    resolved_disk: str | None = None
    if pack_fs is not None:
        resolved_disk = _resolve_pack_fs_image_path(pack_fs, path)

    if resolved_disk is None and image_search_root is not None:
        # Last resort: literal join with the search root.
        for cand in _image_path_candidates(path):
            joined = Path(str(PurePosixPath(image_search_root) / cand))
            if joined.is_file():
                resolved_disk = str(joined)
                break

    if resolved_disk is not None:
        _log_dds_diagnostics(resolved_disk)
        try:
            return bpy.data.images.load(resolved_disk, check_existing=True), True
        except Exception:
            logger.info(
                "failed to load image from disk: %s", resolved_disk, exc_info=True
            )

    # Create a placeholder image so the node still has *something* and
    # the user can relink it from the UI. Keep the virtual path in the
    # data-block name so missing textures from different folders do not
    # reuse each other merely because their basenames match.
    img_name = _image_data_name(path)
    existing = bpy.data.images.get(img_name)
    if existing is not None:
        return existing, False
    return bpy.data.images.new(img_name, width=4, height=4), False


def _resolve_pack_fs_image_path(
    pack_fs: "IPackFileSystem",
    path: str,
) -> str | None:
    for cand in _image_path_candidates(path):
        try:
            resolved = _pack_fs_image_path(pack_fs, cand)
        except Exception:
            logger.debug("pack_fs lookup failed for %r", cand, exc_info=True)
            continue
        if resolved is not None:
            return resolved
    return None


def _image_path_candidates(path: str) -> list[str]:
    normalized = path.replace("\\", "/").strip()
    base_candidates = [normalized]
    p = PurePosixPath(normalized)
    if p.suffix.lower() != ".dds":
        base_candidates.append(str(p.with_suffix(".dds")))

    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in base_candidates:
        for variant in _object_root_path_variants(candidate):
            key = variant.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(variant)
    return candidates


def _object_root_path_variants(path: str) -> tuple[str, ...]:
    parts = path.split("/")
    if not parts or parts[0].lower() != "objects":
        return (path,)
    if len(parts) >= 2 and parts[1].lower() == "objects":
        collapsed = "/".join([parts[0], *parts[2:]])
        return (path, collapsed)
    nested = "/".join([parts[0], "objects", *parts[1:]])
    return (path, nested)


def _image_data_name(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    return normalized or PurePosixPath(path).name or "texture"


def _log_dds_diagnostics(path: str) -> None:
    if not path.lower().endswith(".dds"):
        return
    try:
        info = read_dds_info(path)
    except (DdsError, OSError):
        logger.debug("DDS diagnostics failed for %s", path, exc_info=True)
        return
    logger.debug(
        "DDS diagnostics: %s format=%s size=%sx%s mips=%s payload=%s/%s split=%s",
        path,
        info.format_name,
        info.width,
        info.height,
        info.mipmap_count,
        info.actual_payload_size,
        info.expected_payload_size,
        info.split_status,
    )
    for warning in info.warnings:
        logger.debug("DDS diagnostics warning for %s: %s", path, warning)


def _pack_fs_disk_path(pack_fs: "IPackFileSystem", path: str) -> str | None:
    """Best-effort: get a real disk path from an `IPackFileSystem`
    entry. Only works for `RealFileSystem`-backed lookups."""
    layers = getattr(pack_fs, "_layers", None)
    if layers is not None:
        for layer in reversed(layers):
            try:
                if not layer.exists(path):
                    continue
            except Exception:
                logger.debug(
                    "pack_fs layer lookup raised for %r", path, exc_info=True
                )
                continue
            resolved = _pack_fs_disk_path(layer, path)
            if resolved is not None:
                return resolved
        return None

    resolver = getattr(pack_fs, "_resolve", None)
    if resolver is None:
        return None
    try:
        result = resolver(path)
    except Exception:
        logger.debug(
            "pack_fs resolver raised for %r", path, exc_info=True
        )
        return None
    return str(result) if isinstance(result, Path) else None


def _pack_fs_image_path(pack_fs: "IPackFileSystem", path: str) -> str | None:
    if _is_dds_reference(path):
        split_path = _write_split_dds_temp(path, pack_fs)
        if split_path is not None:
            return split_path

    if not pack_fs.exists(path):
        return None
    if _is_numbered_dds_part(path):
        return _write_split_dds_temp(path, pack_fs)
    return _pack_fs_disk_path(pack_fs, path)


def _write_split_dds_temp(path: str, pack_fs: "IPackFileSystem") -> str | None:
    sidecars = find_split_sidecars(path, pack_fs)
    if classify_split_sidecars(sidecars) != "split-complete":
        return None

    data = read_dds_bytes(path, pack_fs)
    digest_source = "|".join(
        ["split-dds-v2", path.replace("\\", "/").lower()]
        + [f"{part.index}:{part.path}:{part.size}" for part in sidecars]
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:12]
    name = PurePosixPath(_strip_numbered_dds_part(path)).name or "texture.dds"
    if not name.lower().endswith(".dds"):
        name = f"{name}.dds"
    stem = PurePosixPath(name).stem or "texture"
    out_dir = _split_dds_temp_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_{digest}.dds"
    if not out_path.exists() or out_path.stat().st_size != len(data):
        out_path.write_bytes(data)
    logger.debug(
        "assembled split DDS %s from %d part(s) into %s",
        path,
        len(sidecars),
        out_path,
    )
    return str(out_path)


def _split_dds_temp_dir() -> Path:
    return Path(tempfile.gettempdir()) / "cryblend_split_dds"


def _is_dds_reference(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    return lowered.endswith(".dds") or _is_numbered_dds_part(lowered)


def _is_numbered_dds_part(path: str) -> bool:
    normalized = path.replace("\\", "/").strip()
    base, sep, suffix = normalized.rpartition(".")
    return bool(sep and suffix.isdigit() and base.lower().endswith(".dds"))


def _strip_numbered_dds_part(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    base, sep, suffix = normalized.rpartition(".")
    if sep and suffix.isdigit() and base:
        return base
    return normalized


__all__ = ["build_material"]
