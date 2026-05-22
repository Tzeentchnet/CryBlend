"""Core: model loader, chunk registry, asset aggregator."""

from .chunk_registry import Chunk, chunk, header_for, make_chunk, make_header, registered_chunks
from .cdf_assembly import CdfAssemblyPlan, CdfAttachmentPlan, build_cdf_assembly_plan
from .cdf_loader import load_cdf, parse_cdf
from .cryengine import CryEngine, UnsupportedFileError
from .model import Model

__all__ = [
    "CdfAssemblyPlan",
    "CdfAttachmentPlan",
    "Chunk",
    "CryEngine",
    "Model",
    "UnsupportedFileError",
    "build_cdf_assembly_plan",
    "chunk",
    "header_for",
    "load_cdf",
    "make_chunk",
    "make_header",
    "parse_cdf",
    "registered_chunks",
]
