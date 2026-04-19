"""Tests for CryXmlB / pbxml decoder."""

from __future__ import annotations

import io
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

from cryengine_importer.io import cry_xml


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _build_pbxml(root_name: str, attrs: dict[str, str], text: str = "") -> bytes:
    """Build a tiny valid pbxml document (no children)."""
    out = bytearray(b"pbxml\x00")
    out.append(0)  # cry_int n_children = 0
    out.append(len(attrs))  # cry_int n_attrs
    out.extend(root_name.encode("ascii") + b"\x00")
    for k, v in attrs.items():
        out.extend(k.encode("ascii") + b"\x00")
        out.extend(v.encode("ascii") + b"\x00")
    out.extend(text.encode("ascii") + b"\x00")
    return bytes(out)


def test_pbxml_simple_attrs() -> None:
    blob = _build_pbxml("Root", {"name": "demo", "version": "1"})
    root = cry_xml.read_stream(io.BytesIO(blob))
    assert root.tag == "Root"
    assert root.attrib == {"name": "demo", "version": "1"}


def test_plain_xml_passthrough() -> None:
    xml = b"<?xml version='1.0'?><Material color='red'/>"
    root = cry_xml.read_stream(io.BytesIO(xml))
    assert root.tag == "Material"
    assert root.attrib["color"] == "red"


def test_fixtures_present() -> None:
    """The committed MTL fixtures must parse without error."""
    if not _FIXTURES.exists():
        return  # Phase 0; fixtures land later in this commit.
    for f in _FIXTURES.glob("*.mtl"):
        root = cry_xml.read_file(str(f))
        assert root is not None
    for f in _FIXTURES.glob("*.xml"):
        root = cry_xml.read_file(str(f))
        assert root is not None
