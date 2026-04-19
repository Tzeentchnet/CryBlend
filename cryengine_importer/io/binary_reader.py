"""Binary stream reader.

Port of CgfConverter/Utilities/BinaryReaderExtensions.cs and
CgfConverter/Services/EndiannessChangeableBinaryReader.cs.

Combined into a single class because Python doesn't have C#'s
extension-method idiom. The reader holds an `is_big_endian` flag that
chunk code toggles per the chunk header version's high bit.
"""

from __future__ import annotations

import math
import struct
from typing import BinaryIO

# Pre-built struct format specifiers for hot-path reads.
_LE = {
    "i8": struct.Struct("<b"),
    "u8": struct.Struct("<B"),
    "i16": struct.Struct("<h"),
    "u16": struct.Struct("<H"),
    "i32": struct.Struct("<i"),
    "u32": struct.Struct("<I"),
    "i64": struct.Struct("<q"),
    "u64": struct.Struct("<Q"),
    "f32": struct.Struct("<f"),
    "f64": struct.Struct("<d"),
}
_BE = {
    "i8": struct.Struct(">b"),
    "u8": struct.Struct(">B"),
    "i16": struct.Struct(">h"),
    "u16": struct.Struct(">H"),
    "i32": struct.Struct(">i"),
    "u32": struct.Struct(">I"),
    "i64": struct.Struct(">q"),
    "u64": struct.Struct(">Q"),
    "f32": struct.Struct(">f"),
    "f64": struct.Struct(">d"),
}


class BinaryReader:
    """A seekable binary reader with endianness toggle."""

    __slots__ = ("_s", "is_big_endian")

    def __init__(self, stream: BinaryIO) -> None:
        self._s = stream
        self.is_big_endian: bool = False

    # --- stream plumbing ------------------------------------------------

    @property
    def stream(self) -> BinaryIO:
        return self._s

    def tell(self) -> int:
        return self._s.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._s.seek(offset, whence)

    def skip(self, n: int) -> None:
        self._s.seek(n, 1)

    def read_bytes(self, n: int) -> bytes:
        data = self._s.read(n)
        if len(data) != n:
            raise EOFError(f"Wanted {n} bytes, got {len(data)} at offset {self._s.tell()}")
        return data

    def align_to(self, unit: int) -> None:
        pos = self._s.tell()
        self._s.seek((pos + unit - 1) // unit * unit)

    @property
    def length(self) -> int:
        pos = self._s.tell()
        self._s.seek(0, 2)
        end = self._s.tell()
        self._s.seek(pos)
        return end

    # --- scalar reads ---------------------------------------------------

    def _table(self) -> dict[str, struct.Struct]:
        return _BE if self.is_big_endian else _LE

    def read_u8(self) -> int:
        return self._table()["u8"].unpack(self.read_bytes(1))[0]

    def read_i8(self) -> int:
        return self._table()["i8"].unpack(self.read_bytes(1))[0]

    def read_u16(self) -> int:
        return self._table()["u16"].unpack(self.read_bytes(2))[0]

    def read_i16(self) -> int:
        return self._table()["i16"].unpack(self.read_bytes(2))[0]

    def read_u32(self) -> int:
        return self._table()["u32"].unpack(self.read_bytes(4))[0]

    def read_i32(self) -> int:
        return self._table()["i32"].unpack(self.read_bytes(4))[0]

    def read_u64(self) -> int:
        return self._table()["u64"].unpack(self.read_bytes(8))[0]

    def read_i64(self) -> int:
        return self._table()["i64"].unpack(self.read_bytes(8))[0]

    def read_f32(self) -> float:
        return self._table()["f32"].unpack(self.read_bytes(4))[0]

    def read_f64(self) -> float:
        return self._table()["f64"].unpack(self.read_bytes(8))[0]

    def read_half(self) -> float:
        # IEEE 754 half-float (binary16). struct supports 'e'.
        fmt = ">e" if self.is_big_endian else "<e"
        return struct.unpack(fmt, self.read_bytes(2))[0]

    # --- string reads ---------------------------------------------------

    def read_fstring(self, n: int) -> str:
        """Read fixed-length ASCII string, trimmed at first NUL."""
        raw = self.read_bytes(n)
        nul = raw.find(b"\x00")
        if nul >= 0:
            raw = raw[:nul]
        return raw.decode("ascii", errors="replace")

    def read_cstring(self) -> str:
        """Read NUL-terminated ASCII string."""
        out = bytearray()
        while True:
            b = self._s.read(1)
            if not b or b == b"\x00":
                break
            out.extend(b)
        return out.decode("ascii", errors="replace")

    def read_pstring(self) -> str:
        """Read a Pascal-style string: u32 length + UTF-8 bytes."""
        n = self.read_u32()
        if n == 0:
            return ""
        return self.read_bytes(n).decode("utf-8", errors="replace")

    # --- variable-length CryInt (pbxml) --------------------------------

    def read_cry_int(self) -> int:
        """Variable-length int used by pbxml.

        Port of BinaryReaderExtensions.ReadCryInt(Stream).
        """
        current = self._s.read(1)
        if not current:
            raise EOFError("Unexpected EOF in CryInt")
        cur = current[0]
        result = cur & 0x7F
        while (cur & 0x80) != 0:
            current = self._s.read(1)
            if not current:
                raise EOFError("Unexpected EOF in CryInt")
            cur = current[0]
            result = (result << 7) | (cur & 0x7F)
        return result

    def read_cry_int_with_flag(self) -> tuple[int, bool]:
        """Variable-length int with an extra flag bit (WiiU stream).

        Port of BinaryReaderExtensions.ReadCryIntWithFlag.
        """
        current = self._s.read(1)
        if not current:
            raise EOFError("Unexpected EOF in CryIntWithFlag")
        cur = current[0]
        result = cur & 0x3F
        flag = (cur & 0x40) != 0
        while (cur & 0x80) != 0:
            current = self._s.read(1)
            if not current:
                raise EOFError("Unexpected EOF in CryIntWithFlag")
            cur = current[0]
            result = (result << 7) | (cur & 0x7F)
        return result, flag

    # --- CryHalf (Lumberyard CryHalf.inl format) -----------------------

    def read_cry_half(self) -> float:
        """Custom 16-bit float used by some Cry vertex streams.

        Port of CryHalf.ConvertCryHalfToFloat (Utilities/CryHalf.cs).
        Range ~ +/- 131000.
        """
        value = self.read_u16()
        mantissa = value & 0x03FF
        if (value & 0x7C00) != 0:  # normalized
            exponent = (value >> 10) & 0x1F
        elif mantissa != 0:  # denormalized -> normalize
            exponent = 1
            while True:
                exponent -= 1
                mantissa <<= 1
                if (mantissa & 0x0400) != 0:
                    break
            mantissa &= 0x03FF
        else:  # zero -> matches C# (uint)-112 = 0xFFFFFF90
            exponent = 0xFFFFFF90
        # Build IEEE 754 single. C# relies on uint32 overflow when
        # adding 112; we mask to mimic.
        sign = (value & 0x8000) << 16
        exp = ((exponent + 112) & 0xFF) << 23
        mant = mantissa << 13
        bits = (sign | exp | mant) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def read_dymek_half(self) -> float:
        """Dymek's 8.8 fixed-point format / 127.

        Port of CryHalf.ConvertDymekHalfToFloat. Used in some SC vertex
        streams. Range ~ +/- 1.008.
        """
        value = self.read_u16()
        # int part: signed byte from top 8 bits
        int_byte = (value >> 8) & 0xFF
        if int_byte & 0x80:
            int_part = int_byte - 0x100
        else:
            int_part = int_byte
        # frac part: low 8 bits, interpreted as fixed binary fraction
        frac_byte = value & 0xFF
        frac = 0.0
        for i in range(8):
            if frac_byte & (1 << (7 - i)):
                frac += math.pow(2, -(i + 1))
        return (int_part + frac) / 127.0

    # --- vector / matrix helpers ---------------------------------------

    def read_vec3(self) -> tuple[float, float, float]:
        return (self.read_f32(), self.read_f32(), self.read_f32())

    def read_vec3_half(self) -> tuple[float, float, float]:
        return (self.read_half(), self.read_half(), self.read_half())

    def read_vec3_cry_half(self) -> tuple[float, float, float]:
        return (self.read_cry_half(), self.read_cry_half(), self.read_cry_half())

    def read_vec3_dymek_half(self) -> tuple[float, float, float]:
        return (self.read_dymek_half(), self.read_dymek_half(), self.read_dymek_half())

    def read_vec4(self) -> tuple[float, float, float, float]:
        return (self.read_f32(), self.read_f32(), self.read_f32(), self.read_f32())

    def read_quat(self) -> tuple[float, float, float, float]:
        # x, y, z, w -- matches System.Numerics.Quaternion layout.
        return (self.read_f32(), self.read_f32(), self.read_f32(), self.read_f32())

    def read_uv(self) -> tuple[float, float]:
        return (self.read_f32(), self.read_f32())

    def read_uv_half(self) -> tuple[float, float]:
        return (self.read_half(), self.read_half())

    def read_irgba(self, alpha: float | None = None) -> tuple[float, float, float, float]:
        r = self.read_u8() / 255.0
        g = self.read_u8() / 255.0
        b = self.read_u8() / 255.0
        a = self.read_u8() / 255.0 if alpha is None else alpha
        return (r, g, b, a)

    def read_bbox(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return (self.read_vec3(), self.read_vec3())

    def read_matrix3x3(self) -> tuple[tuple[float, ...], ...]:
        """Row-major 3x3."""
        return tuple(
            (self.read_f32(), self.read_f32(), self.read_f32()) for _ in range(3)
        )

    def read_matrix3x4(self) -> tuple[tuple[float, ...], ...]:
        """Row-major 3x4 (3 rows of 4 floats)."""
        return tuple(
            (self.read_f32(), self.read_f32(), self.read_f32(), self.read_f32())
            for _ in range(3)
        )

    def read_matrix4x4(self) -> tuple[tuple[float, ...], ...]:
        return tuple(
            (self.read_f32(), self.read_f32(), self.read_f32(), self.read_f32())
            for _ in range(4)
        )

    # --- compressed quaternion formats (Phase 4 — Controller_905) -----

    def read_short_int3_quat(self) -> tuple[float, float, float, float]:
        """ShortInt3Quat — 3 signed shorts; W reconstructed from x/y/z.

        Port of Models/Structs/Structs.cs#ShortInt3Quat (implicit cast).
        """
        max_short = 32767.0
        x = self.read_i16() / max_short
        y = self.read_i16() / max_short
        z = self.read_i16() / max_short
        w_sq = 1.0 - (x * x + y * y + z * z)
        w = math.sqrt(w_sq) if w_sq > 0.0 else 0.0
        return (x, y, z, w)

    def read_small_tree_dword_quat(self) -> tuple[float, float, float, float]:
        """32-bit packed quat (3 components x 10 bits + 2-bit max-index)."""
        max_10bit = 723.0
        range_10bit = 0.707106781186
        value = self.read_u32()
        max_idx = (value >> 30) & 0x3
        comp = [0.0, 0.0, 0.0, 0.0]
        shift = 0
        sqrsum = 0.0
        for i in range(4):
            if i == max_idx:
                continue
            packed = (value >> shift) & 0x3FF
            c = packed / max_10bit - range_10bit
            comp[i] = c
            sqrsum += c * c
            shift += 10
        comp[max_idx] = math.sqrt(max(0.0, 1.0 - sqrsum))
        return (comp[0], comp[1], comp[2], comp[3])

    def read_small_tree_48bit_quat(self) -> tuple[float, float, float, float]:
        """48-bit packed quat (3 x 15 bits + 2-bit max-index)."""
        max_15bit = 23170.0
        range_15bit = 0.707106781186
        m1 = self.read_u16()
        m2 = self.read_u16()
        m3 = self.read_u16()
        v64 = (m3 << 32) | (m2 << 16) | m1
        max_idx = (v64 >> 46) & 0x3
        comp = [0.0, 0.0, 0.0, 0.0]
        shift = 0
        sqrsum = 0.0
        for i in range(4):
            if i == max_idx:
                continue
            packed = (v64 >> shift) & 0x7FFF
            c = packed / max_15bit - range_15bit
            comp[i] = c
            sqrsum += c * c
            shift += 15
        comp[max_idx] = math.sqrt(max(0.0, 1.0 - sqrsum))
        return (comp[0], comp[1], comp[2], comp[3])

    def read_small_tree_64bit_quat(self) -> tuple[float, float, float, float]:
        """64-bit packed quat (3 x 20 bits + 2-bit max-index)."""
        max_20bit = 741454.0
        range_20bit = 0.707106781186
        m1 = self.read_u32()
        m2 = self.read_u32()
        v64 = (m2 << 32) | m1
        max_idx = (v64 >> 62) & 0x3
        comp = [0.0, 0.0, 0.0, 0.0]
        shift = 0
        sqrsum = 0.0
        for i in range(4):
            if i == max_idx:
                continue
            packed = (v64 >> shift) & 0xFFFFF
            c = packed / max_20bit - range_20bit
            comp[i] = c
            sqrsum += c * c
            shift += 20
        comp[max_idx] = math.sqrt(max(0.0, 1.0 - sqrsum))
        return (comp[0], comp[1], comp[2], comp[3])

    def read_small_tree_64bit_ext_quat(self) -> tuple[float, float, float, float]:
        """64-bit extended packed quat (2 x 21 bits + 1 x 20 bits + 2-bit max-index).

        Mirrors Models/Structs/Structs.cs#SmallTree64BitExtQuat. Note
        the C# encoder writes 21-bit components but advances by 20 bits;
        we match its decoder exactly (reading 21 bits, advancing 21).
        """
        max_20bit = 741454.0
        range_20bit = 0.707106781186
        max_21bit = 1482909.0
        range_21bit = 0.707106781186
        m1 = self.read_u32()
        m2 = self.read_u32()
        v64 = (m2 << 32) | m1
        max_idx = (v64 >> 62) & 0x3
        comp = [0.0, 0.0, 0.0, 0.0]
        shift = 0
        sqrsum = 0.0
        target = 0
        for i in range(4):
            if i == max_idx:
                continue
            if target < 2:
                packed = (v64 >> shift) & 0x1FFFFF
                c = packed / max_21bit - range_21bit
                shift += 21
            else:
                packed = (v64 >> shift) & 0xFFFFF
                c = packed / max_20bit - range_20bit
                shift += 20
            comp[i] = c
            sqrsum += c * c
            target += 1
        comp[max_idx] = math.sqrt(max(0.0, 1.0 - sqrsum))
        return (comp[0], comp[1], comp[2], comp[3])

    # --- IVO (Star Citizen #ivo) helpers — Phase 5 --------------------

    def read_quat_snorm16(self) -> tuple[float, float, float, float]:
        """4 i16 / 32767 — the SNorm quaternion layout used by IVO
        tangent / qtangent / bone-mapping streams. Matches
        ``BinaryReaderExtensions.ReadQuaternion(InputType.SNorm)``."""
        return (
            self.read_i16() / 32767.0,
            self.read_i16() / 32767.0,
            self.read_i16() / 32767.0,
            self.read_i16() / 32767.0,
        )

    def read_quat_dymek_half(self) -> tuple[float, float, float, float]:
        """4 Dymek 8.8 fixed-point components / 127. Matches
        ``BinaryReaderExtensions.ReadQuaternion(InputType.DymekHalf)``."""
        return (
            self.read_dymek_half(),
            self.read_dymek_half(),
            self.read_dymek_half(),
            self.read_dymek_half(),
        )

    def read_vec3_snorm16(self) -> tuple[float, float, float]:
        """3 i16 / 32767 — used by IVOVERTSUVS bpe=16 vertex packs.
        Matches ``BinaryReaderExtensions.ReadVector3(InputType.SNorm)``."""
        return (
            self.read_i16() / 32767.0,
            self.read_i16() / 32767.0,
            self.read_i16() / 32767.0,
        )

    def read_ivo_mesh_details(self):
        """Port of ``BinaryReaderExtensions.ReadMeshDetails`` — the
        12-field IvoGeometryMeshDetails struct that prefixes
        ChunkIvoSkinMesh_900's submesh table."""
        from ..models.ivo import IvoGeometryMeshDetails
        from ..enums import VertexFormat

        fmt_raw = 0
        d = IvoGeometryMeshDetails()
        d.flags2 = self.read_u32()
        d.number_of_vertices = self.read_u32()
        d.number_of_indices = self.read_u32()
        d.number_of_submeshes = self.read_u32()
        d.unknown = self.read_i32()
        d.bounding_box = self.read_bbox()
        d.scaling_bounding_box = self.read_bbox()
        fmt_raw = self.read_u32()
        try:
            d.vertex_format = VertexFormat(fmt_raw)
        except ValueError:
            d.vertex_format = fmt_raw
        return d

    def read_ivo_mesh_subset(self):
        """Port of ``BinaryReaderExtensions.ReadMeshSubset`` — one
        IvoMeshSubset row inside ChunkIvoSkinMesh_900."""
        from ..models.ivo import IvoMeshSubset

        s = IvoMeshSubset()
        s.mat_id = self.read_u16()
        s.node_parent_index = self.read_u16()
        s.first_index = self.read_i32()
        s.num_indices = self.read_i32()
        s.first_vertex = self.read_i32()
        s.unknown = self.read_i32()
        s.num_vertices = self.read_i32()
        s.radius = self.read_f32()
        s.center = self.read_vec3()
        s.unknown1 = self.read_i32()
        s.unknown2 = self.read_i32()
        return s
