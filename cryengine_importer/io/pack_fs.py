"""Pack file system abstractions.

Port of CgfConverter/PackFileSystem/. Provides a small interface that
can be backed by the real filesystem, by stacked search paths
(cascaded), or in future phases by zip / WiiU stream archives.
"""

from __future__ import annotations

import io
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Iterable


def _normalize(path: str) -> str:
    """Normalize a CryEngine path: forward slashes, lowercased,
    no leading slash. CryEngine paths are case-insensitive on disk."""
    p = path.replace("\\", "/").lstrip("/")
    return p


class IPackFileSystem(ABC):
    """Interface mirroring CgfConverter/PackFileSystem/IPackFileSystem.cs."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def open(self, path: str) -> BinaryIO: ...

    @abstractmethod
    def read_all_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    def glob(self, pattern: str) -> Iterable[str]: ...


class RealFileSystem(IPackFileSystem):
    """Backed by an on-disk directory.

    Port of CgfConverter/PackFileSystem/RealFileSystem.cs.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path | None:
        # Try the given path verbatim; if not found, do a case-insensitive
        # walk component-by-component (CryEngine PAKs are case-insensitive).
        rel = _normalize(path)
        candidate = self._root / rel
        if candidate.is_file():
            return candidate
        # Case-insensitive resolve.
        cur = self._root
        for part in rel.split("/"):
            if not part:
                continue
            try:
                entries = list(cur.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                return None
            match = next((e for e in entries if e.name.lower() == part.lower()), None)
            if match is None:
                return None
            cur = match
        return cur if cur.is_file() else None

    def exists(self, path: str) -> bool:
        return self._resolve(path) is not None

    def open(self, path: str) -> BinaryIO:
        resolved = self._resolve(path)
        if resolved is None:
            raise FileNotFoundError(path)
        return resolved.open("rb")

    def read_all_bytes(self, path: str) -> bytes:
        resolved = self._resolve(path)
        if resolved is None:
            raise FileNotFoundError(path)
        return resolved.read_bytes()

    def glob(self, pattern: str) -> Iterable[str]:
        for p in self._root.glob(pattern.replace("\\", "/")):
            if p.is_file():
                yield str(p.relative_to(self._root)).replace(os.sep, "/")


class CascadedPackFileSystem(IPackFileSystem):
    """Stack of file systems searched in LIFO order.

    Port of CgfConverter/PackFileSystem/CascadedPackFileSystem.cs.
    """

    def __init__(self, layers: Iterable[IPackFileSystem] = ()) -> None:
        self._layers: list[IPackFileSystem] = list(layers)

    def push(self, fs: IPackFileSystem) -> None:
        self._layers.append(fs)

    def exists(self, path: str) -> bool:
        return any(fs.exists(path) for fs in reversed(self._layers))

    def open(self, path: str) -> BinaryIO:
        for fs in reversed(self._layers):
            if fs.exists(path):
                return fs.open(path)
        raise FileNotFoundError(path)

    def read_all_bytes(self, path: str) -> bytes:
        for fs in reversed(self._layers):
            if fs.exists(path):
                return fs.read_all_bytes(path)
        raise FileNotFoundError(path)

    def glob(self, pattern: str) -> Iterable[str]:
        seen: set[str] = set()
        for fs in reversed(self._layers):
            for p in fs.glob(pattern):
                if p not in seen:
                    seen.add(p)
                    yield p


class InMemoryFileSystem(IPackFileSystem):
    """Test helper. Holds a dict of path -> bytes."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self._files: dict[str, bytes] = {
            _normalize(k): v for k, v in (files or {}).items()
        }

    def add(self, path: str, data: bytes) -> None:
        self._files[_normalize(path)] = data

    def exists(self, path: str) -> bool:
        return _normalize(path) in self._files

    def open(self, path: str) -> BinaryIO:
        key = _normalize(path)
        if key not in self._files:
            raise FileNotFoundError(path)
        return io.BytesIO(self._files[key])

    def read_all_bytes(self, path: str) -> bytes:
        key = _normalize(path)
        if key not in self._files:
            raise FileNotFoundError(path)
        return self._files[key]

    def glob(self, pattern: str) -> Iterable[str]:
        # Minimal glob: only supports trailing '*' and exact matches.
        if pattern.endswith("*"):
            prefix = _normalize(pattern[:-1])
            for k in self._files:
                if k.startswith(prefix):
                    yield k
        else:
            n = _normalize(pattern)
            if n in self._files:
                yield n
