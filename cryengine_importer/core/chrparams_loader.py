"""ChrParams XML loader.

Port of CgfConverter/ChrParams/ChrParams.cs + Animation.cs.

A `.chrparams` XML file lives next to a `.chr` and lists named
animations + the `.caf` / `.anim` files that contain them. Reading it
turns "load every CAF in the AnimationList" into a deterministic
operation, and lets us name Blender actions with their in-game names.

The file format is plain XML in CryEngine 3+, but we route through
`io.cry_xml` so pbxml / CryXmlB variants (rare in chrparams files but
not impossible) are handled transparently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..io import cry_xml
from ..models.animation import ChrParams, ChrParamsAnimation

if TYPE_CHECKING:
    from ..io.pack_fs import IPackFileSystem


def load_chrparams(path: str, pack_fs: "IPackFileSystem") -> ChrParams | None:
    """Load and parse ``path`` (a `.chrparams` file). Returns ``None``
    when the file isn't present in ``pack_fs``."""
    if not pack_fs.exists(path):
        return None
    with pack_fs.open(path) as stream:
        root = cry_xml.read_stream(stream)
    return parse_chrparams(root, source_file_name=path)


def parse_chrparams(root, *, source_file_name: str | None = None) -> ChrParams:
    """Parse a chrparams `<Params>` root element into a `ChrParams`."""
    out = ChrParams(source_file_name=source_file_name)
    # <Params><AnimationList><Animation name=".." path=".."/>...
    anim_list = root.find("AnimationList")
    if anim_list is not None:
        for el in anim_list.findall("Animation"):
            out.animations.append(
                ChrParamsAnimation(
                    name=el.get("name"),
                    path=el.get("path"),
                )
            )
    return out


__all__ = ["load_chrparams", "parse_chrparams"]
