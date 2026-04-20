"""Material data model.

Port of CgfConverter/Models/Materials/Material.cs (and friends:
Texture.cs, MaterialFlags.cs, Color.cs, PublicParams.cs).

The *parser* lives here as plain-Python dataclasses + an
`from_xml(elem)` constructor — Blender translation lives in
`blender/material_builder.py`.

A `.mtl` file is one of:
- a "library" containing ``<SubMaterials>`` with N child ``<Material>``
  elements (one per material slot referenced by mesh subsets), or
- a "single" material (no submaterials).

For consistency with the C# code, when we load a single-material file
we wrap it in a one-element ``sub_materials`` list so callers can
always index by `mat_id`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import Iterable
from xml.etree import ElementTree as ET


class MaterialFlags(IntFlag):
    """Port of CgfConverter/Models/Materials/MaterialFlags.cs."""

    Wire = 0x0001
    TwoSided = 0x0002
    Additive = 0x0004
    DetailDecal = 0x0008
    Lighting = 0x0010
    NoShadow = 0x0020
    AlwaysUsed = 0x0040
    PureChild = 0x0080
    MultiSubmtl = 0x0100
    NoPhysicalize = 0x0200
    NoDraw = 0x0400
    NoPreview = 0x0800
    NotInstanced = 0x1000
    CollisionProxy = 0x2000
    Scatter = 0x4000
    RequireForwardRendering = 0x8000
    NonRemovable = 0x10000
    HideOnBreak = 0x20000
    UiMaterial = 0x40000
    ShaderGenMask64Bit = 0x80000
    RaycastProxy = 0x100000
    RequireNearestCubemap = 0x200000


# Map ``<Texture Map="...">`` strings to a normalized slot name.
# Mirrors `Texture.MapTypeEnum` switch in C# Texture.cs.
_MAP_TO_SLOT: dict[str, str] = {
    "Diffuse": "diffuse",
    "Bumpmap": "normals",
    "Normal": "normals",
    "Specular": "specular",
    "Environment": "env",
    "Detail": "detail",
    "SecondSmoothness": "second_smoothness",
    "Heightmap": "height",
    "Height": "height",
    "Decal": "decal",
    "SubSurface": "subsurface",
    "Custom": "custom",
    "[1] Custom": "custom_secondary",
    "Opacity": "opacity",
    "Smoothness": "smoothness",
    "GlossNormalA": "smoothness",
    "Emittance": "emittance",
    "Occlusion": "occlusion",
    "Specular2": "specular2",
    "TexSlot1": "diffuse",   # Diffuse alias
    "TexSlot2": "normals",
    "TexSlot4": "specular",
    "TexSlot9": "diffuse",
    "TexSlot10": "specular",
    "TexSlot12": "blend",
}


# Texture-filename suffix conventions used across stock CryEngine titles
# (MWO, Aion, ArcheAge, Crysis, Star Citizen, modded Crysis assets).
# A texture file's *basename* (without extension) ending in one of
# these suffixes is treated as that channel, regardless of what the
# ``<Texture Map="...">`` attribute says — Crytek artists often leave
# ``Map="Diffuse"`` even on packed normal/gloss maps.
#
# Order matters: `_pom_height` and `_displ` must be checked before the
# generic `_disp` / `_height` fallbacks. Longest match wins.
_SUFFIX_TO_SLOT: tuple[tuple[str, str], ...] = (
    # Packed normal + gloss (DXT5nm-style): RGB normal, A channel = gloss.
    ("_ddna", "normals_gloss"),
    # Plain normal map (no gloss in alpha).
    ("_ddn", "normals"),
    # Diffuse / albedo.
    ("_diff", "diffuse"),
    # Specular reflectivity map.
    ("_spec", "specular"),
    # Parallax-occlusion height map (used as displacement input).
    ("_pom_height", "height"),
    # Displacement / height (two spellings in the wild).
    ("_displ", "height"),
    ("_disp", "height"),
    # Branch-decal class — damage / stencil overlays. Routed to a
    # separate "decal" slot rather than overwriting Base Color, so
    # the Blender bridge can wire them as a second material slot or
    # leave them unconnected with a label.
    ("_damage", "decal"),
    ("_stencil", "decal"),
    ("_decal", "decal"),
    # Glow / emissive.
    ("_em", "emittance"),
    # Ambient occlusion.
    ("_ao", "occlusion"),
)


def classify_texture_suffix(file_path: str) -> str | None:
    """Return the normalized slot name for a CryEngine texture filename.

    Looks at the basename (without extension), case-insensitively, and
    returns the first matching entry in :data:`_SUFFIX_TO_SLOT`. Returns
    ``None`` when no convention matches — callers should then fall back
    to the ``<Texture Map="...">`` attribute via
    :data:`_MAP_TO_SLOT`.

    The special slot ``"normals_gloss"`` indicates a DDNA-style packed
    map (RGB normal + A gloss); the Blender bridge wires both Normal
    and Roughness from a single image.
    """
    if not file_path:
        return None
    # Strip directory + extension; keep just the base name.
    name = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = name.lower()
    for suffix, slot in _SUFFIX_TO_SLOT:
        if name.endswith(suffix):
            return slot
    return None


@dataclass
class Texture:
    """A single ``<Texture Map="..." File="...">`` entry."""

    map: str = ""           # raw "Map" attribute
    file: str = ""          # raw "File" attribute (forward-slash path)
    type_id: int = 0

    @property
    def slot(self) -> str:
        """Normalized slot name (``diffuse`` / ``normals`` / ...).

        File-suffix conventions (``_ddna`` / ``_ddn`` / ``_diff`` /
        ``_spec`` / ``_displ`` / ``_pom_height`` / ``_disp`` /
        ``_decal`` / ``_damage`` / ``_stencil`` / ``_em`` / ``_ao``)
        win over the raw ``Map`` attribute, because Crytek artists
        frequently leave ``Map="Diffuse"`` even on packed normal/gloss
        maps. Falls back to the ``Map`` table, then to a lower-cased
        version of the raw map string for unknown values.
        """
        suffix_slot = classify_texture_suffix(self.file)
        if suffix_slot is not None:
            return suffix_slot
        return _MAP_TO_SLOT.get(self.map, self.map.lower())

    @classmethod
    def from_xml(cls, el: ET.Element) -> "Texture":
        return cls(
            map=el.attrib.get("Map", ""),
            file=el.attrib.get("File", "").replace("\\", "/"),
            type_id=int(el.attrib.get("Type", "0") or 0),
        )


def _parse_color(s: str | None) -> tuple[float, float, float] | None:
    """Parse a CryEngine colour: comma-separated RGB in [0, 1]."""
    if not s:
        return None
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


# ---- PublicParams (tint palette) helpers ----------------------------
#
# CryEngine `<PublicParams ...>` carries shader-specific scalar / colour
# inputs as XML attributes; values are either single floats
# (``"0.55536944"``) or comma-separated 3-floats for RGB
# (``"0.04518621,0.04518621,0.04518621"``). Star Citizen's
# `LayerBlend` shader uses these for tint-palette colours
# (``DiffuseTint1``, ``DirtColor`` etc.) — exposing them as Blender
# RGB inputs lets artists re-tint imported assets without round-tripping
# through `.mtl`.


def parse_color_value(value: str) -> tuple[float, float, float] | None:
    """Parse a CryEngine PublicParams colour string.

    Returns the RGB triple or ``None`` when the string isn't 3
    comma-separated floats. Strict — anything that fails to parse is
    silently skipped at the caller.
    """
    return _parse_color(value)


def parse_scalar_value(value: str) -> float | None:
    """Parse a single-float PublicParams value, or ``None``."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def extract_color_params(
    public_params: dict[str, str],
) -> dict[str, tuple[float, float, float]]:
    """Subset of ``public_params`` whose values parse as RGB triples.

    Insertion order is preserved so the Blender bridge can lay out
    nodes deterministically.
    """
    out: dict[str, tuple[float, float, float]] = {}
    for k, v in public_params.items():
        rgb = parse_color_value(v)
        if rgb is not None:
            out[k] = rgb
    return out


def extract_scalar_params(public_params: dict[str, str]) -> dict[str, float]:
    """Subset of ``public_params`` whose values parse as single floats."""
    out: dict[str, float] = {}
    for k, v in public_params.items():
        # Skip values that look like a colour triple — those are caught
        # by :func:`extract_color_params`.
        if "," in v:
            continue
        f = parse_scalar_value(v)
        if f is not None:
            out[k] = f
    return out


def is_primary_tint_key(key: str) -> bool:
    """True when ``key`` is a *primary* diffuse tint slot.

    Convention (Star Citizen ``LayerBlend`` and friends):

    * ``DiffuseTint``, ``DiffuseTint1``, ``DiffuseTint2`` ... — primary
      tint colours that *multiply* the base diffuse.
    * ``DiffuseTintWear*`` — wear-layer tints; *blend* into a separate
      layer, not multiplied with the base. Excluded.
    * ``DirtColor``, ``DustColor``, ``GrimeColor`` etc. — overlay /
      decal colours. Excluded.

    Excluded tints are still surfaced as labelled RGB nodes by the
    Blender bridge — they're just not wired into Base Color.
    """
    if not key:
        return False
    k = key.lower()
    if "wear" in k:
        return False
    # ``DiffuseTint`` optionally followed by digits.
    if k == "diffusetint":
        return True
    if k.startswith("diffusetint") and k[len("diffusetint"):].isdigit():
        return True
    return False


def extract_tint_colors(
    material: "Material",
) -> dict[str, tuple[float, float, float]]:
    """All RGB-valued PublicParams on ``material``.

    Sugar over ``extract_color_params(material.public_params)`` so
    callers don't have to reach through the field name.
    """
    return extract_color_params(material.public_params)


def _parse_gen_mask(string_gen_mask: str | None) -> set[str]:
    """``"%FOO%BAR"`` -> ``{"FOO", "BAR"}``.

    Mirrors `Utilities/ParsedGenMask.cs` constructor.
    """
    if not string_gen_mask:
        return set()
    return {p for p in string_gen_mask.split("%") if p}


@dataclass
class Material:
    """A CryEngine material (single or sub-material).

    Mirrors `Models/Materials/Material.cs` minus the XML serialization
    plumbing.
    """

    name: str | None = None
    shader: str | None = None
    flags: MaterialFlags = MaterialFlags(0)
    diffuse: tuple[float, float, float] | None = None
    specular: tuple[float, float, float] | None = None
    emissive: tuple[float, float, float] | None = None
    opacity: float = 1.0
    shininess: float = 0.0
    glossiness: float = 0.0
    glow_amount: float = 0.0
    alpha_test: float = 0.0
    surface_type: str | None = None
    gen_mask: int = 0
    string_gen_mask: str | None = None
    public_params: dict[str, str] = field(default_factory=dict)
    textures: list[Texture] = field(default_factory=list)
    sub_materials: list["Material"] = field(default_factory=list)
    source_file: str | None = None

    # ----- gen-mask helpers ------------------------------------------

    @property
    def gen_mask_flags(self) -> set[str]:
        """Decoded ``%FOO%BAR`` flags as an unordered set."""
        return _parse_gen_mask(self.string_gen_mask)

    @property
    def use_specular_map(self) -> bool:
        return "GLOSS_MAP" in self.gen_mask_flags

    @property
    def use_bump_map(self) -> bool:
        return "BUMP_MAP" in self.gen_mask_flags

    @property
    def use_gloss_in_specular_map(self) -> bool:
        return "SPECULARPOW_GLOSSALPHA" in self.gen_mask_flags

    @property
    def is_two_sided(self) -> bool:
        return MaterialFlags.TwoSided in self.flags

    # ----- texture lookup --------------------------------------------

    def texture(self, slot: str) -> Texture | None:
        """First texture whose normalized slot matches ``slot``."""
        for t in self.textures:
            if t.slot == slot:
                return t
        return None

    # ----- construction ----------------------------------------------

    @classmethod
    def from_xml(cls, el: ET.Element) -> "Material":
        m = cls(
            name=el.attrib.get("Name"),
            shader=el.attrib.get("Shader"),
            surface_type=el.attrib.get("SurfaceType"),
            string_gen_mask=el.attrib.get("StringGenMask"),
            diffuse=_parse_color(el.attrib.get("Diffuse")),
            specular=_parse_color(el.attrib.get("Specular")),
            emissive=_parse_color(el.attrib.get("Emissive")),
        )

        flags_attr = el.attrib.get("MtlFlags")
        if flags_attr:
            try:
                m.flags = MaterialFlags(int(flags_attr))
            except ValueError:
                m.flags = MaterialFlags(0)

        gm = el.attrib.get("GenMask")
        if gm:
            try:
                m.gen_mask = int(gm, 16)
            except ValueError:
                m.gen_mask = 0

        for attr, target in (
            ("Opacity", "opacity"),
            ("Shininess", "shininess"),
            ("Glossiness", "glossiness"),
            ("GlowAmount", "glow_amount"),
            ("AlphaTest", "alpha_test"),
        ):
            v = el.attrib.get(attr)
            if v is not None:
                try:
                    setattr(m, target, float(v))
                except ValueError:
                    pass

        for child in el:
            tag = _strip_ns(child.tag)
            if tag == "Textures":
                m.textures = [Texture.from_xml(t) for t in child if _strip_ns(t.tag) == "Texture"]
            elif tag == "PublicParams":
                m.public_params = dict(child.attrib)
            elif tag == "SubMaterials":
                m.sub_materials = [
                    Material.from_xml(c)
                    for c in child
                    if _strip_ns(c.tag) == "Material"
                ]

        return m

    @classmethod
    def from_xml_root(cls, root: ET.Element) -> "Material":
        """Build a material from the root of a parsed .mtl document.

        Like the C# loader, when the root is a single material with no
        ``<SubMaterials>`` we wrap it as the sole entry of its own
        ``sub_materials`` list so callers can always index by mat id.
        """
        mat = cls.from_xml(root)
        if not mat.sub_materials:
            mat.sub_materials = [mat]
        return mat


def _strip_ns(tag: str) -> str:
    """Strip an ``{ns}`` prefix from an ElementTree tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


__all__ = [
    "Material",
    "MaterialFlags",
    "Texture",
    "classify_texture_suffix",
    "extract_color_params",
    "extract_scalar_params",
    "extract_tint_colors",
    "is_primary_tint_key",
    "parse_color_value",
    "parse_scalar_value",
]
