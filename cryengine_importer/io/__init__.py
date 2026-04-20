"""IO subpackage: binary reader, pack file system, CryXmlB."""

from .binary_reader import BinaryReader
from .pack_fs import (
    CascadedPackFileSystem,
    InMemoryFileSystem,
    IPackFileSystem,
    RealFileSystem,
    ZipFileSystem,
)
from .asset_resolver import AssetCompanions, find_geometry_files, resolve_companions
from . import cry_xml

__all__ = [
    "AssetCompanions",
    "BinaryReader",
    "CascadedPackFileSystem",
    "InMemoryFileSystem",
    "IPackFileSystem",
    "RealFileSystem",
    "ZipFileSystem",
    "cry_xml",
    "find_geometry_files",
    "resolve_companions",
]
