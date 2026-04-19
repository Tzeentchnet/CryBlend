"""Chunk registry and base class.

Port of CgfConverter/CryEngineCore/Chunks/Chunk.cs.

C# uses a reflection-based factory keyed on `{ClassName}_{Version:X}`.
We replace that with a `@chunk(chunk_type, version)` decorator that
populates a `(ChunkType, version)` -> class dict at import time. This is
explicit, greppable, and friendly to static-analysis tools.

To register a chunk, subclass `Chunk` (or one of the family base
classes) and decorate it::

    @chunk(ChunkType.Mesh, 0x802)
    class ChunkMesh802(Chunk):
        def read(self, br): ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

from ..enums import ChunkType, FileVersion

if TYPE_CHECKING:
    from ..io.binary_reader import BinaryReader
    from .model import Model
    from .chunks.header import ChunkHeader


T = TypeVar("T", bound="Chunk")


class Chunk:
    """Base class for all chunk readers.

    Subclasses override :meth:`read`. The framework calls
    :meth:`load` first to attach the parent model + header, then
    :meth:`read` with a positioned, endian-configured reader.
    """

    # Set by registry decorator on subclasses.
    _chunk_type: ChunkType | None = None
    _chunk_version: int | None = None

    def __init__(self) -> None:
        self.model: "Model | None" = None
        self.header: "ChunkHeader | None" = None

        # Mirrors C# fields.
        self.version_raw: int = 0
        self.id: int = 0
        self.size: int = 0
        self.offset: int = 0
        self.chunk_type: ChunkType = ChunkType.Any
        self.data_size: int = 0

    # --- read API ------------------------------------------------------

    def load(self, model: "Model", header: "ChunkHeader") -> None:
        self.model = model
        self.header = header

    @property
    def is_big_endian(self) -> bool:
        return (self.version_raw & 0x80000000) != 0

    @property
    def version(self) -> int:
        return self.version_raw & 0x7FFFFFFF

    def read(self, br: "BinaryReader") -> None:
        """Position the reader at this chunk and (for old file
        versions) consume the per-chunk preamble. Subclasses should
        call ``super().read(br)`` first, then read their own body.
        """
        assert self.header is not None and self.model is not None

        self.chunk_type = self.header.chunk_type
        self.version_raw = self.header.version_raw
        self.offset = self.header.offset
        self.id = self.header.id
        self.size = self.header.size
        self.data_size = self.size

        br.seek(self.offset)

        # Old (CryTek) file versions repeat type/version/offset/id at
        # the start of each chunk body. Newer (CrCh, #ivo) do not.
        if self.model.file_version in (FileVersion.x0744, FileVersion.x0745):
            br.is_big_endian = False
            self.chunk_type = ChunkType(br.read_u32())
            self.version_raw = br.read_u32()
            self.offset = br.read_u32()
            self.id = br.read_i32()
            self.data_size = self.size - 16

        br.is_big_endian = self.is_big_endian

    def skip_to_end(self, br: "BinaryReader") -> None:
        """Advance reader to the end of this chunk's declared size."""
        if self.size == 0:
            return
        end = self.offset + self.size
        if br.tell() < end:
            br.seek(end)

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} type={self.chunk_type.name if isinstance(self.chunk_type, ChunkType) else self.chunk_type} "
            f"ver=0x{self.version:X} id={self.id:#x} size={self.size}>"
        )


# --------------------------------------------------------------- registry


# Map from (ChunkType int, version int) -> Chunk subclass
_REGISTRY: dict[tuple[int, int], type[Chunk]] = {}

# Header subclasses keyed on FileVersion int.
_HEADER_REGISTRY: dict[int, type[Chunk]] = {}


def chunk(chunk_type: ChunkType, version: int) -> Callable[[type[T]], type[T]]:
    """Class decorator that registers ``cls`` for (chunk_type, version)."""

    def deco(cls: type[T]) -> type[T]:
        cls._chunk_type = chunk_type
        cls._chunk_version = version & 0x7FFFFFFF
        key = (int(chunk_type), cls._chunk_version)
        if key in _REGISTRY:
            existing = _REGISTRY[key]
            if existing is not cls:
                raise RuntimeError(
                    f"Duplicate chunk registration for {chunk_type.name} v0x{version:X}: "
                    f"{existing.__name__} vs {cls.__name__}"
                )
        _REGISTRY[key] = cls
        return cls

    return deco


def header_for(file_version: FileVersion) -> Callable[[type[T]], type[T]]:
    """Class decorator that registers a `ChunkHeader` subclass."""

    def deco(cls: type[T]) -> type[T]:
        _HEADER_REGISTRY[int(file_version)] = cls
        return cls

    return deco


def make_header(file_version: FileVersion) -> "ChunkHeader":
    cls = _HEADER_REGISTRY.get(int(file_version))
    if cls is None:
        raise NotImplementedError(
            f"No ChunkHeader registered for file version 0x{int(file_version):X}"
        )
    return cls()  # type: ignore[return-value]


def make_chunk(chunk_type: ChunkType, version_raw: int) -> Chunk:
    """Resolve a chunk class for ``(chunk_type, version)``.

    Falls back to ``ChunkUnknown`` when no implementation is registered;
    this matches C#'s behaviour and lets partial coverage still parse a
    file (the unknown chunks are skipped).
    """
    version = version_raw & 0x7FFFFFFF
    cls = _REGISTRY.get((int(chunk_type), version))
    if cls is None:
        # Try a class registered for any version (sentinel = -1).
        cls = _REGISTRY.get((int(chunk_type), -1))
    if cls is None:
        from .chunks.unknown import ChunkUnknown
        return ChunkUnknown()
    return cls()


def registered_chunks() -> dict[tuple[int, int], type[Chunk]]:
    """Snapshot of the registry. For diagnostics / tests."""
    return dict(_REGISTRY)
