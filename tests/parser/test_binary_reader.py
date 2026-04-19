"""Tests for the binary reader (no Blender required)."""

from __future__ import annotations

import io
import struct

import pytest

from cryengine_importer.io.binary_reader import BinaryReader


def _r(data: bytes) -> BinaryReader:
    return BinaryReader(io.BytesIO(data))


def test_endianness_toggle() -> None:
    br = _r(b"\x01\x02\x03\x04" + b"\x01\x02\x03\x04")
    assert br.read_u32() == 0x04030201  # little
    br.is_big_endian = True
    assert br.read_u32() == 0x01020304  # big


def test_basic_scalars() -> None:
    payload = struct.pack("<bBhHiIqQfd", -1, 255, -2, 65500, -3, 7, -4, 9, 1.5, 2.25)
    br = _r(payload)
    assert br.read_i8() == -1
    assert br.read_u8() == 255
    assert br.read_i16() == -2
    assert br.read_u16() == 65500
    assert br.read_i32() == -3
    assert br.read_u32() == 7
    assert br.read_i64() == -4
    assert br.read_u64() == 9
    assert br.read_f32() == pytest.approx(1.5)
    assert br.read_f64() == pytest.approx(2.25)


def test_strings() -> None:
    br = _r(b"hello\x00\x00\x00")
    assert br.read_fstring(8) == "hello"
    br = _r(b"hi\x00rest")
    assert br.read_cstring() == "hi"
    assert br.read_bytes(4) == b"rest"


def test_pstring() -> None:
    payload = struct.pack("<I", 5) + b"world"
    assert _r(payload).read_pstring() == "world"


def test_cry_int_single_byte() -> None:
    # Values < 0x80 fit in one byte.
    assert _r(b"\x05").read_cry_int() == 5
    assert _r(b"\x7F").read_cry_int() == 0x7F


def test_cry_int_multi_byte() -> None:
    # 0x80 sets the continuation bit -> next byte. (0x80 & 0x7F)=0,
    # then (0x05 & 0x7F)=5 -> (0 << 7) | 5 = 5.
    assert _r(b"\x80\x05").read_cry_int() == 5
    # 0x81 0x00 -> ((1 & 0x7F) << 7) | (0 & 0x7F) = 128
    assert _r(b"\x81\x00").read_cry_int() == 128


def test_cry_int_with_flag() -> None:
    # bit 6 of first byte is the flag; result uses bottom 6 bits only.
    val, flag = _r(b"\x45").read_cry_int_with_flag()  # 0x45 = 0b0100_0101
    assert val == 0x05
    assert flag is True
    val, flag = _r(b"\x05").read_cry_int_with_flag()
    assert val == 0x05
    assert flag is False


def test_cry_half_zero() -> None:
    # All-zero bits should decode to 0.0.
    assert _r(b"\x00\x00").read_cry_half() == 0.0


def test_cry_half_one() -> None:
    # 0x3C00: exponent field = 15. With CryHalf's bias (15+112=127)
    # this is IEEE 1.0. CryHalf shares its bit layout with IEEE half
    # but uses a different exponent bias.
    out = _r(b"\x00\x3C").read_cry_half()
    assert out == pytest.approx(1.0)


def test_vec3_and_quat() -> None:
    payload = struct.pack("<fff", 1.0, 2.0, 3.0) + struct.pack("<ffff", 0.0, 0.0, 0.0, 1.0)
    br = _r(payload)
    assert br.read_vec3() == (1.0, 2.0, 3.0)
    assert br.read_quat() == (0.0, 0.0, 0.0, 1.0)


def test_align_to() -> None:
    br = _r(b"\x00" * 16)
    br.read_bytes(3)
    br.align_to(4)
    assert br.tell() == 4
    br.align_to(8)
    assert br.tell() == 8
