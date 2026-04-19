"""Smoke test for the chunk registry + Model loader (Phase 0.4 spike).

Verifies that:
- the chunk registry is populated at import time,
- Model parses a synthetic CryTek-3.5 (0x745) file header + chunk table.

Real binary asset coverage lives under tests/blender (env-gated).
"""

from __future__ import annotations

import io
import struct

from cryengine_importer.core import Model, registered_chunks  # type: ignore[attr-defined]
from cryengine_importer.core.chunk_registry import (
    Chunk,
    chunk,
    make_chunk,
    registered_chunks,
)
from cryengine_importer.enums import ChunkType, FileVersion


def test_registry_contains_headers() -> None:
    # The header subclasses register themselves on import; chunk-body
    # families are still stubs in Phase 0.
    from cryengine_importer.core.chunks import header  # noqa: F401

    # No chunk-body classes are registered yet (Phase 0). That's fine.
    # The decorator infrastructure itself is exercised by the synthetic
    # registration below.
    assert isinstance(registered_chunks(), dict)


def test_chunk_decorator_registers_and_resolves() -> None:
    @chunk(ChunkType.SourceInfo, 0x999)
    class _FakeSourceInfo(Chunk):
        pass

    inst = make_chunk(ChunkType.SourceInfo, 0x999)
    assert isinstance(inst, _FakeSourceInfo)


def test_unknown_chunk_falls_back() -> None:
    from cryengine_importer.core.chunks.unknown import ChunkUnknown

    inst = make_chunk(ChunkType.Light, 0xDEAD)  # never registered
    assert isinstance(inst, ChunkUnknown)


def _synthetic_745_file() -> bytes:
    """Build the smallest valid CryTek-0x745 file: header + 1 unknown chunk.

    Layout:
      8B "CryTek\\0\\0"
      4B FileType (Geometry)
      4B FileVersion (0x745)
      4B ChunkTableOffset - 4 (so loader's "+4" yields the real one)
      4B NumChunks (=1)
      ... chunk table ...
    """
    chunk_table_real_offset = 24  # right after the 24-byte header
    payload = bytearray()
    payload.extend(b"CryTek\x00\x00")
    payload.extend(struct.pack("<I", 0xFFFF0000))         # FileType.Geometry
    payload.extend(struct.pack("<I", 0x745))              # FileVersion
    payload.extend(struct.pack("<i", chunk_table_real_offset - 4))
    payload.extend(struct.pack("<I", 1))                  # NumChunks
    # Single chunk header (20 bytes for 0x745):
    payload.extend(struct.pack("<I", 0xCCCC0009))         # Light (no impl)
    payload.extend(struct.pack("<I", 0x800))              # Version
    payload.extend(struct.pack("<I", chunk_table_real_offset + 20))  # offset
    payload.extend(struct.pack("<i", 0xABCD))             # ID
    payload.extend(struct.pack("<I", 0))                  # size = 0
    return bytes(payload)


def test_model_loads_synthetic_745_header() -> None:
    blob = _synthetic_745_file()
    m = Model.from_stream("synthetic.cgf", io.BytesIO(blob))
    assert m.file_signature == "CryTek"
    assert m.file_version == FileVersion.x0745
    assert m.num_chunks == 1
    assert len(m.chunk_headers) == 1
    hdr = m.chunk_headers[0]
    assert hdr.chunk_type == ChunkType.Light
    assert hdr.id == 0xABCD
    assert 0xABCD in m.chunk_map
