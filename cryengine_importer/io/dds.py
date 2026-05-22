"""DDS header diagnostics for CryEngine textures.

This module intentionally does *not* decode image pixels. CryBlend lets
Blender load image data, but we still need a small pure-Python reader to
answer practical questions before import: what compressed format is this,
does it look complete, does it carry CryEngine metadata, and are there
DDS-Unsplitter-style split sidecars next to it?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pack_fs import IPackFileSystem


class DdsError(ValueError):
    """Raised when bytes do not contain a readable DDS header."""


_DDS_MAGIC = b"DDS "
_DDS_HEADER_SIZE = 124
_DDS_PIXEL_FORMAT_SIZE = 32
_DX10_HEADER_SIZE = 20
_MIN_HEADER_BYTES = 4 + _DDS_HEADER_SIZE

_DDSCAPS2_CUBEMAP = 0x00000200
_DDSCAPS2_CUBEMAP_POSITIVEX = 0x00000400
_DDSCAPS2_CUBEMAP_NEGATIVEX = 0x00000800
_DDSCAPS2_CUBEMAP_POSITIVEY = 0x00001000
_DDSCAPS2_CUBEMAP_NEGATIVEY = 0x00002000
_DDSCAPS2_CUBEMAP_POSITIVEZ = 0x00004000
_DDSCAPS2_CUBEMAP_NEGATIVEZ = 0x00008000
_DDSCAPS2_CUBEMAP_FACES = (
    _DDSCAPS2_CUBEMAP_POSITIVEX,
    _DDSCAPS2_CUBEMAP_NEGATIVEX,
    _DDSCAPS2_CUBEMAP_POSITIVEY,
    _DDSCAPS2_CUBEMAP_NEGATIVEY,
    _DDSCAPS2_CUBEMAP_POSITIVEZ,
    _DDSCAPS2_CUBEMAP_NEGATIVEZ,
)


_FOURCC_NAMES: dict[str, str] = {
    "DXT1": "BC1/DXT1",
    "DXT3": "BC2/DXT3",
    "DXT5": "BC3/DXT5",
    "ATI1": "BC4/ATI1",
    "BC4U": "BC4/ATI1",
    "BC4S": "BC4 signed",
    "ATI2": "BC5/ATI2",
    "BC5U": "BC5/ATI2",
    "BC5S": "BC5 signed",
    "DX10": "DX10 extended",
}

_FOURCC_BLOCK_BYTES: dict[str, int] = {
    "DXT1": 8,
    "ATI1": 8,
    "BC4U": 8,
    "BC4S": 8,
    "DXT3": 16,
    "DXT5": 16,
    "ATI2": 16,
    "BC5U": 16,
    "BC5S": 16,
}

_DXGI_FORMATS: dict[int, tuple[str, int | None]] = {
    70: ("BC1_TYPELESS", 8),
    71: ("BC1_UNORM", 8),
    72: ("BC1_UNORM_SRGB", 8),
    73: ("BC2_TYPELESS", 16),
    74: ("BC2_UNORM", 16),
    75: ("BC2_UNORM_SRGB", 16),
    76: ("BC3_TYPELESS", 16),
    77: ("BC3_UNORM", 16),
    78: ("BC3_UNORM_SRGB", 16),
    79: ("BC4_TYPELESS", 8),
    80: ("BC4_UNORM", 8),
    81: ("BC4_SNORM", 8),
    82: ("BC5_TYPELESS", 16),
    83: ("BC5_UNORM", 16),
    84: ("BC5_SNORM", 16),
    94: ("BC6H_TYPELESS", 16),
    95: ("BC6H_UF16", 16),
    96: ("BC6H_SF16", 16),
    97: ("BC7_TYPELESS", 16),
    98: ("BC7_UNORM", 16),
    99: ("BC7_UNORM_SRGB", 16),
}


@dataclass(frozen=True)
class DdsPixelFormat:
    size: int
    flags: int
    fourcc: str
    rgb_bit_count: int
    red_mask: int
    green_mask: int
    blue_mask: int
    alpha_mask: int


@dataclass(frozen=True)
class DdsDx10Header:
    dxgi_format: int
    resource_dimension: int
    misc_flag: int
    array_size: int
    misc_flags2: int

    @property
    def format_name(self) -> str:
        return _DXGI_FORMATS.get(self.dxgi_format, (f"DXGI_{self.dxgi_format}", None))[0]


@dataclass(frozen=True)
class DdsSidecar:
    index: int
    path: str
    size: int


@dataclass(frozen=True)
class DdsInfo:
    path: str | None
    width: int
    height: int
    depth: int
    mipmap_count: int
    flags: int
    pitch_or_linear_size: int
    pixel_format: DdsPixelFormat
    caps: int
    caps2: int
    caps3: int
    caps4: int
    reserved2: int
    data_offset: int
    total_size: int | None
    format_name: str
    block_bytes: int | None
    dx10_header: DdsDx10Header | None = None
    expected_payload_size: int | None = None
    actual_payload_size: int | None = None
    cryengine_marker_offset: int | None = None
    cryengine_marker_raw: str | None = None
    sidecars: tuple[DdsSidecar, ...] = ()
    split_status: str = "plain"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_cryengine_marker(self) -> bool:
        return self.cryengine_marker_offset is not None

    @property
    def is_probably_complete(self) -> bool | None:
        if self.expected_payload_size is None or self.actual_payload_size is None:
            return None
        return self.actual_payload_size >= self.expected_payload_size


def read_dds_info(path: str | Path, *, sidecars: tuple[DdsSidecar, ...] = ()) -> DdsInfo:
    """Read DDS header diagnostics from a real file path."""
    p = Path(path)
    with p.open("rb") as stream:
        header = stream.read(_MIN_HEADER_BYTES + _DX10_HEADER_SIZE)
    return parse_dds_header(
        header,
        path=str(p),
        total_size=p.stat().st_size,
        sidecars=sidecars,
    )


def load_dds_info(
    path: str,
    pack_fs: "IPackFileSystem",
    *,
    include_sidecars: bool = True,
) -> DdsInfo:
    """Read DDS diagnostics from an :class:`IPackFileSystem` path."""
    sidecars = find_split_sidecars(path, pack_fs) if include_sidecars else ()
    if sidecars and classify_split_sidecars(sidecars) == "split-complete":
        data = read_dds_bytes(path, pack_fs, include_sidecars=include_sidecars)
    else:
        data = pack_fs.read_all_bytes(path)
    return parse_dds_header(
        data[: _MIN_HEADER_BYTES + _DX10_HEADER_SIZE],
        path=path,
        total_size=len(data),
        sidecars=sidecars,
    )


def parse_dds_header(
    data: bytes,
    *,
    path: str | None = None,
    total_size: int | None = None,
    sidecars: tuple[DdsSidecar, ...] = (),
) -> DdsInfo:
    """Parse a DDS header from ``data`` and return diagnostics."""
    if len(data) < _MIN_HEADER_BYTES:
        raise DdsError(f"DDS header truncated: expected at least {_MIN_HEADER_BYTES} bytes")
    if data[:4] != _DDS_MAGIC:
        raise DdsError("DDS magic missing")

    header = struct.unpack_from("<31I", data, 4)
    header_size = header[0]
    if header_size != _DDS_HEADER_SIZE:
        raise DdsError(f"Unsupported DDS header size {header_size}")

    flags = header[1]
    height = header[2]
    width = header[3]
    pitch_or_linear_size = header[4]
    depth = header[5]
    mipmap_count = header[6] or 1

    pf_offset = 4 + 72
    pf_values = struct.unpack_from("<8I", data, pf_offset)
    pf_size = pf_values[0]
    if pf_size != _DDS_PIXEL_FORMAT_SIZE:
        raise DdsError(f"Unsupported DDS pixel-format size {pf_size}")
    fourcc = _decode_fourcc(pf_values[2])
    pixel_format = DdsPixelFormat(
        size=pf_size,
        flags=pf_values[1],
        fourcc=fourcc,
        rgb_bit_count=pf_values[3],
        red_mask=pf_values[4],
        green_mask=pf_values[5],
        blue_mask=pf_values[6],
        alpha_mask=pf_values[7],
    )

    caps = header[26]
    caps2 = header[27]
    caps3 = header[28]
    caps4 = header[29]
    reserved2 = header[30]

    data_offset = _MIN_HEADER_BYTES
    dx10_header: DdsDx10Header | None = None
    if fourcc == "DX10":
        if len(data) < _MIN_HEADER_BYTES + _DX10_HEADER_SIZE:
            raise DdsError("DDS DX10 header truncated")
        dx10_values = struct.unpack_from("<5I", data, _MIN_HEADER_BYTES)
        dx10_header = DdsDx10Header(*dx10_values)
        data_offset += _DX10_HEADER_SIZE

    format_name, block_bytes = _format_name_and_block_size(pixel_format, dx10_header)
    expected_payload = _expected_payload_size(
        width,
        height,
        mipmap_count,
        block_bytes=block_bytes,
        rgb_bit_count=pixel_format.rgb_bit_count,
        face_count=_dds_face_count(caps2),
    )
    actual_payload = total_size - data_offset if total_size is not None else None
    marker_offset, marker_raw = _find_cryengine_marker(data[:_MIN_HEADER_BYTES])
    split_status = classify_split_sidecars(sidecars)

    warnings = _build_warnings(
        format_name=format_name,
        fourcc=fourcc,
        marker_offset=marker_offset,
        expected_payload=expected_payload,
        actual_payload=actual_payload,
        split_status=split_status,
    )

    return DdsInfo(
        path=path,
        width=width,
        height=height,
        depth=depth,
        mipmap_count=mipmap_count,
        flags=flags,
        pitch_or_linear_size=pitch_or_linear_size,
        pixel_format=pixel_format,
        caps=caps,
        caps2=caps2,
        caps3=caps3,
        caps4=caps4,
        reserved2=reserved2,
        data_offset=data_offset,
        total_size=total_size,
        format_name=format_name,
        block_bytes=block_bytes,
        dx10_header=dx10_header,
        expected_payload_size=expected_payload,
        actual_payload_size=actual_payload,
        cryengine_marker_offset=marker_offset,
        cryengine_marker_raw=marker_raw,
        sidecars=sidecars,
        split_status=split_status,
        warnings=warnings,
    )


def find_split_sidecars(
    path: str,
    pack_fs: "IPackFileSystem",
    *,
    max_index: int = 64,
) -> tuple[DdsSidecar, ...]:
    """Find DDS-Unsplitter-style numbered sidecars next to ``path``."""
    for base in _split_bases(path):
        out: list[DdsSidecar] = []
        for index in range(max_index + 1):
            candidate = f"{base}.{index}"
            try:
                if not pack_fs.exists(candidate):
                    continue
                out.append(
                    DdsSidecar(
                        index=index,
                        path=candidate,
                        size=len(pack_fs.read_all_bytes(candidate)),
                    )
                )
            except Exception:
                continue
        if out:
            return tuple(out)
    return ()


def read_dds_bytes(
    path: str,
    pack_fs: "IPackFileSystem",
    *,
    include_sidecars: bool = True,
) -> bytes:
    """Read a DDS file, assembling numbered split parts when present."""
    if include_sidecars:
        sidecars = find_split_sidecars(path, pack_fs)
        if sidecars and classify_split_sidecars(sidecars) == "split-complete":
            parts = tuple(pack_fs.read_all_bytes(part.path) for part in sidecars)
            reordered = _try_assemble_mip_sidecars(parts)
            if reordered is not None:
                return reordered
            return b"".join(parts)
    return pack_fs.read_all_bytes(path)


def classify_split_sidecars(sidecars: tuple[DdsSidecar, ...]) -> str:
    """Classify numbered DDS sidecars as plain/complete/incomplete."""
    if not sidecars:
        return "plain"
    indexes = sorted(s.index for s in sidecars)
    if indexes[0] != 0:
        return "split-incomplete"
    expected = list(range(indexes[-1] + 1))
    return "split-complete" if indexes == expected else "split-incomplete"


def _split_base(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    return str(p.with_suffix("")) if p.suffix.lower() == ".dds" else str(p)


def _split_bases(path: str) -> tuple[str, ...]:
    normalized = path.replace("\\", "/").strip()
    numbered_base = _strip_numbered_suffix(normalized)
    candidates: list[str] = []
    if numbered_base is not None:
        candidates.append(numbered_base)
    else:
        candidates.append(normalized)
        legacy = _split_base(normalized)
        if legacy != normalized:
            candidates.append(legacy)

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if not candidate or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return tuple(out)


def _try_assemble_mip_sidecars(parts: tuple[bytes, ...]) -> bytes | None:
    """Return a DDS with mip sidecars reordered, or ``None``.

    Some CryEngine texture extracts store ``.dds.0`` as the DDS header
    plus the smallest mip payloads, followed by ``.dds.1`` ... ``.dds.N``
    as increasingly larger mip levels. A normal DDS stores payloads in
    the opposite order: largest/base level first, then smaller mips. If
    the sidecar sizes match that CryEngine pattern, rebuild the standard
    payload order so Blender does not decode all mip levels into the
    base image.
    """
    if len(parts) < 2 or not parts[0].startswith(_DDS_MAGIC):
        return None

    try:
        info = parse_dds_header(parts[0], total_size=len(parts[0]))
    except DdsError:
        return None
    if info.mipmap_count <= 1:
        return None

    mip_sizes = _mip_payload_sizes(
        info.width,
        info.height,
        info.mipmap_count,
        block_bytes=info.block_bytes,
        rgb_bit_count=info.pixel_format.rgb_bit_count,
        face_count=_dds_face_count(info.caps2),
    )
    if mip_sizes is None:
        return None

    side_payload_sizes = [len(part) for part in parts[1:]]
    side_count = len(side_payload_sizes)
    if side_count >= len(mip_sizes):
        return None
    expected_side_sizes = list(reversed(mip_sizes[:side_count]))
    tail = parts[0][info.data_offset:]
    expected_tail_sizes = list(reversed(mip_sizes[side_count:]))
    expected_tail_size = sum(expected_tail_sizes)
    if side_payload_sizes != expected_side_sizes or len(tail) != expected_tail_size:
        return None

    header = parts[0][:info.data_offset]
    tail_chunks: list[bytes] = []
    offset = 0
    for size in expected_tail_sizes:
        tail_chunks.append(tail[offset:offset + size])
        offset += size
    return header + b"".join(reversed(parts[1:])) + b"".join(reversed(tail_chunks))


def _strip_numbered_suffix(path: str) -> str | None:
    base, sep, suffix = path.rpartition(".")
    if not sep or not suffix.isdigit() or not base:
        return None
    return base


def _decode_fourcc(value: int) -> str:
    raw = struct.pack("<I", value)
    text = raw.rstrip(b"\0").decode("ascii", errors="replace")
    return text


def _format_name_and_block_size(
    pixel_format: DdsPixelFormat, dx10_header: DdsDx10Header | None
) -> tuple[str, int | None]:
    fourcc = pixel_format.fourcc
    if dx10_header is not None:
        name, block_bytes = _DXGI_FORMATS.get(
            dx10_header.dxgi_format,
            (f"DXGI_{dx10_header.dxgi_format}", None),
        )
        return name, block_bytes
    if fourcc:
        return _FOURCC_NAMES.get(fourcc, fourcc), _FOURCC_BLOCK_BYTES.get(fourcc)
    if pixel_format.rgb_bit_count:
        return f"RGB{pixel_format.rgb_bit_count}", None
    return "unknown", None


def _expected_payload_size(
    width: int,
    height: int,
    mipmap_count: int,
    *,
    block_bytes: int | None,
    rgb_bit_count: int,
    face_count: int = 1,
) -> int | None:
    sizes = _mip_payload_sizes(
        width,
        height,
        mipmap_count,
        block_bytes=block_bytes,
        rgb_bit_count=rgb_bit_count,
        face_count=face_count,
    )
    return sum(sizes) if sizes is not None else None


def _mip_payload_sizes(
    width: int,
    height: int,
    mipmap_count: int,
    *,
    block_bytes: int | None,
    rgb_bit_count: int,
    face_count: int = 1,
) -> list[int] | None:
    if width <= 0 or height <= 0:
        return None
    levels = max(1, mipmap_count)
    sizes: list[int] = []
    w = width
    h = height
    if block_bytes is not None:
        for _ in range(levels):
            blocks_w = max(1, (w + 3) // 4)
            blocks_h = max(1, (h + 3) // 4)
            sizes.append(blocks_w * blocks_h * block_bytes)
            w = max(1, w // 2)
            h = max(1, h // 2)
        return [size * max(1, face_count) for size in sizes]
    if rgb_bit_count > 0:
        bytes_per_pixel = max(1, (rgb_bit_count + 7) // 8)
        for _ in range(levels):
            sizes.append(w * h * bytes_per_pixel)
            w = max(1, w // 2)
            h = max(1, h // 2)
        return [size * max(1, face_count) for size in sizes]
    return None


def _dds_face_count(caps2: int) -> int:
    if not caps2 & _DDSCAPS2_CUBEMAP:
        return 1
    faces = sum(1 for flag in _DDSCAPS2_CUBEMAP_FACES if caps2 & flag)
    return faces or 6


def _find_cryengine_marker(data: bytes) -> tuple[int | None, str | None]:
    for marker in (b"CRYF", b"FYRC"):
        offset = data.find(marker)
        if offset >= 0:
            return offset, marker.decode("ascii")
    return None, None


def _build_warnings(
    *,
    format_name: str,
    fourcc: str,
    marker_offset: int | None,
    expected_payload: int | None,
    actual_payload: int | None,
    split_status: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if marker_offset is not None:
        warnings.append("CryEngine CRYF metadata marker present")
    if fourcc in {"ATI1", "ATI2", "BC4U", "BC4S", "BC5U", "BC5S"}:
        warnings.append(f"{format_name} may not open in older Photoshop DDS plugins")
    if split_status == "split-complete":
        warnings.append("DDS-Unsplitter-style numbered sidecars detected")
    elif split_status == "split-incomplete":
        warnings.append("DDS split sidecars are non-contiguous or missing index 0")
    if expected_payload is not None and actual_payload is not None:
        if actual_payload < expected_payload:
            warnings.append(
                f"DDS payload is shorter than expected ({actual_payload} < {expected_payload})"
            )
        elif actual_payload > expected_payload:
            extra = actual_payload - expected_payload
            if marker_offset is not None and extra <= 16:
                warnings.append(f"DDS payload includes {extra} CryEngine trailer bytes")
            else:
                warnings.append(
                    f"DDS payload has extra bytes ({actual_payload} > {expected_payload})"
                )
    return tuple(warnings)


__all__ = [
    "DdsDx10Header",
    "DdsError",
    "DdsInfo",
    "DdsPixelFormat",
    "DdsSidecar",
    "classify_split_sidecars",
    "find_split_sidecars",
    "load_dds_info",
    "parse_dds_header",
    "read_dds_bytes",
    "read_dds_info",
]