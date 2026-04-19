"""ChunkBinaryXmlData_3 — embedded CryXmlB document.

Port of CgfConverter/CryEngineCore/Chunks/ChunkBinaryXmlData_3.cs.

Reads the chunk body as a CryXmlB / pbxml blob and exposes the
parsed XML element tree as ``self.data``. Used by IVO (#ivo) files
to embed material / scene metadata.
"""

from __future__ import annotations

import io
from xml.etree.ElementTree import Element

from ...enums import ChunkType
from ...io import cry_xml
from ..chunk_registry import Chunk, chunk


class ChunkBinaryXmlData(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.data: Element | None = None


@chunk(ChunkType.BinaryXmlDataSC, 0x3)
class ChunkBinaryXmlData3(ChunkBinaryXmlData):
    def read(self, br) -> None:
        super().read(br)
        # The chunk body covers ``size`` bytes from ``offset``; subtract
        # whatever the base reader already consumed (reads 0 for IVO).
        consumed = max(0, br.tell() - self.offset)
        bytes_to_read = self.size - consumed
        if bytes_to_read <= 0:
            return
        blob = br.read_bytes(bytes_to_read)
        try:
            self.data = cry_xml.read_stream(io.BytesIO(blob))
        except Exception:
            # Defensive: an unrecognised payload should not abort the
            # whole file (mirrors the chunk-loader's outer try/except).
            self.data = None
