"""Per-file model loader.

Port of CgfConverter/CryEngineCore/Model.cs.

Reads the file header, the chunk table, and then dispatches each chunk
through the chunk registry. The result is a `Model` with a
``chunk_map: dict[int, Chunk]`` that the higher-level CryEngine
aggregator (Phase 1.5) consumes.
"""

from __future__ import annotations

from typing import BinaryIO

from ..enums import ChunkType, FileType, FileVersion
from ..io.binary_reader import BinaryReader
from . import chunks  # noqa: F401  -- triggers @chunk registration
from .chunk_registry import Chunk, make_chunk, make_header
from .chunks.header import ChunkHeader


class Model:
    """One parsed CryEngine file (.cgf, .cga, .chr, .skin, ...)."""

    def __init__(self) -> None:
        self.file_name: str | None = None
        self.file_signature: str | None = None
        self.file_type: FileType | None = None
        self.file_version: FileVersion = FileVersion.Unknown
        self.chunk_table_offset: int = 0
        self.num_chunks: int = 0

        self.chunk_headers: list[ChunkHeader] = []
        self.chunk_map: dict[int, Chunk] = {}

    @property
    def is_ivo(self) -> bool:
        return self.file_signature == "#ivo"

    # --- public entrypoints --------------------------------------------

    @classmethod
    def from_path(cls, path: str) -> "Model":
        with open(path, "rb") as fh:
            return cls.from_stream(path, fh)

    @classmethod
    def from_stream(cls, name: str, stream: BinaryIO) -> "Model":
        m = cls()
        m._load(name, stream)
        return m

    # --- loader --------------------------------------------------------

    def _load(self, name: str, stream: BinaryIO) -> None:
        self.file_name = name
        br = BinaryReader(stream)
        self._read_file_header(br)
        self._read_chunk_table(br)
        self._read_chunks(br)

    def _read_file_header(self, br: BinaryReader) -> None:
        br.seek(0)
        self.file_signature = br.read_fstring(4)

        if self.file_signature == "CrCh":
            self.file_version = FileVersion(br.read_u32())  # 0x746
            self.num_chunks = br.read_u32()
            self.chunk_table_offset = br.read_i32()
            return
        if self.file_signature == "#ivo":
            self.file_version = FileVersion(br.read_u32())  # 0x900
            self.num_chunks = br.read_u32()
            self.chunk_table_offset = br.read_i32()
            return

        # Otherwise it's an 8-byte "CryTek" signature for older versions.
        br.seek(0)
        self.file_signature = br.read_fstring(8)
        if self.file_signature == "CryTek":
            self.file_type = FileType(br.read_u32())
            self.file_version = FileVersion(br.read_u32())  # 0x744 / 0x745
            self.chunk_table_offset = br.read_i32() + 4
            self.num_chunks = br.read_u32()
            return

        raise ValueError(f"Unsupported file signature: {self.file_signature!r}")

    def _read_chunk_table(self, br: BinaryReader) -> None:
        br.seek(self.chunk_table_offset)
        for _ in range(self.num_chunks):
            header = make_header(self.file_version)
            header.read(br)
            self.chunk_headers.append(header)  # type: ignore[arg-type]

        # 0x744 has no per-entry size; derive from next entry's offset.
        if self.file_version == FileVersion.x0744:
            for i in range(self.num_chunks):
                if i < self.num_chunks - 2:
                    self.chunk_headers[i].size = (
                        self.chunk_headers[i + 1].offset
                        - self.chunk_headers[i].offset
                    )

    def _read_chunks(self, br: BinaryReader) -> None:
        for hdr in self.chunk_headers:
            ck = make_chunk(hdr.chunk_type, hdr.version_raw)
            ck.load(self, hdr)
            try:
                ck.read(br)
            except Exception:
                # Defensive: never let one bad chunk abort the file.
                # The aggregator can decide whether to surface this.
                pass
            ck.skip_to_end(br)
            self.chunk_map[hdr.id] = ck
