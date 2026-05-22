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
from .dds import (
    DdsDx10Header,
    DdsError,
    DdsInfo,
    DdsPixelFormat,
    DdsSidecar,
    classify_split_sidecars,
    find_split_sidecars,
    load_dds_info,
    parse_dds_header,
    read_dds_info,
)
from . import cry_xml

__all__ = [
    "AssetCompanions",
    "BinaryReader",
    "CascadedPackFileSystem",
    "DdsDx10Header",
    "DdsError",
    "DdsInfo",
    "DdsPixelFormat",
    "DdsSidecar",
    "InMemoryFileSystem",
    "IPackFileSystem",
    "RealFileSystem",
    "ZipFileSystem",
    "classify_split_sidecars",
    "cry_xml",
    "find_split_sidecars",
    "find_geometry_files",
    "load_dds_info",
    "parse_dds_header",
    "read_dds_info",
    "resolve_companions",
]
