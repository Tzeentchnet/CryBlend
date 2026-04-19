"""CryXmlB / pbxml binary XML decoder.

Port of CgfConverter/CryXmlB/CryXmlSerializer.cs.

Auto-detects three formats by magic bytes:
- ``pbxml\\0``  -> Cry pbxml format (recursive cry-int + cstring)
- ``CryXmlB\\0`` -> Star Citizen CryXmlB format (header + tables)
- anything else -> plain XML, parsed with xml.etree

Returns an `xml.etree.ElementTree.Element` (root). The C# code returns
`XmlDocument` but we use ET because it's the standard library tree the
rest of the codebase expects.
"""

from __future__ import annotations

import io
import struct
from typing import BinaryIO
from xml.etree import ElementTree as ET

from .binary_reader import BinaryReader

PBXML_MAGIC = b"pbxml\x00"
CRYXMLB_MAGIC = b"CryXmlB\x00"


def read_file(path: str) -> ET.Element:
    with open(path, "rb") as fh:
        return read_stream(fh)


def read_stream(stream: BinaryIO) -> ET.Element:
    # Slurp into memory if not seekable so we can peek the magic.
    if not stream.seekable():
        data = stream.read()
        stream = io.BytesIO(data)

    pos = stream.tell()
    peek = stream.read(max(len(PBXML_MAGIC), len(CRYXMLB_MAGIC)))
    stream.seek(pos)

    if peek.startswith(PBXML_MAGIC):
        return _load_pbxml(BinaryReader(stream))
    if peek.startswith(CRYXMLB_MAGIC):
        return _load_cryxmlb(BinaryReader(stream))

    # Plain XML. Read remainder and let ET parse.
    return ET.parse(stream).getroot()


# --------------------------------------------------------------------- pbxml


def _load_pbxml(br: BinaryReader) -> ET.Element:
    magic = br.read_bytes(len(PBXML_MAGIC))
    if magic != PBXML_MAGIC:
        raise ValueError("Not a pbxml stream")
    return _pbxml_element(br)


def _pbxml_element(br: BinaryReader) -> ET.Element:
    n_children = br.read_cry_int()
    n_attrs = br.read_cry_int()
    name = br.read_cstring()

    el = ET.Element(name)
    for _ in range(n_attrs):
        key = br.read_cstring()
        value = br.read_cstring()
        el.set(key, value)

    text = br.read_cstring()
    if text:
        el.text = text

    for i in range(n_children):
        expected_length = br.read_cry_int()
        expected_position = br.tell() + expected_length
        child = _pbxml_element(br)
        el.append(child)
        # Last child has expected_length == 0 in the C# implementation.
        if i + 1 == n_children:
            if expected_length != 0:
                raise ValueError("pbxml: last child must have expected_length 0")
        else:
            if br.tell() != expected_position:
                raise ValueError(
                    f"pbxml: expected position {expected_position}, got {br.tell()}"
                )
    return el


# ---------------------------------------------------------------- CryXmlB


def _load_cryxmlb(br: BinaryReader) -> ET.Element:
    """Star Citizen CryXmlB format.

    Layout (port of CgfConverter/CryXmlB/CryXmlSerializer.cs::LoadScXmlFile):

        char[8] magic "CryXmlB\\0"
        i32 fileLength
        i32 nodeTableOffset, i32 nodeTableCount   (28 bytes / entry)
        i32 referenceTableOffset, i32 referenceTableCount   (8 bytes / entry, attrs)
        i32 orderTableOffset, i32 orderTableCount   (4 bytes / entry, unused here)
        i32 contentOffset, i32 contentLength

    Each node entry (28 bytes):
        i32 NameOffset
        i32 ItemType
        i16 AttributeCount
        i16 ChildCount
        i32 ParentNodeId  (-1 = root)
        i32 FirstAttributeIndex
        i32 FirstChildIndex
        i32 Reserved

    Strings live in the content area as NUL-terminated blobs whose
    offsets are relative to ``contentOffset``. Children are stitched
    via ParentNodeId (the order table is informational only).
    """
    magic = br.read_bytes(len(CRYXMLB_MAGIC))
    if magic != CRYXMLB_MAGIC:
        raise ValueError("Not a CryXmlB stream")

    _file_length = br.read_i32()
    node_table_offset = br.read_i32()
    node_table_count = br.read_i32()
    ref_table_offset = br.read_i32()
    ref_table_count = br.read_i32()
    _order_table_offset = br.read_i32()
    _order_table_count = br.read_i32()
    content_offset = br.read_i32()
    content_length = br.read_i32()

    # --- strings dictionary ---
    br.seek(content_offset)
    blob = br.read_bytes(content_length) if content_length > 0 else b""
    strings: dict[int, str] = {}
    cursor = 0
    while cursor < len(blob):
        end = blob.find(b"\x00", cursor)
        if end < 0:
            end = len(blob)
        strings[cursor] = blob[cursor:end].decode("utf-8", errors="replace")
        cursor = end + 1

    def s(off: int, default: str = "") -> str:
        return strings.get(off, default)

    # --- node table ---
    br.seek(node_table_offset)
    nodes: list[dict] = []
    for _ in range(node_table_count):
        nodes.append({
            "name_off": br.read_i32(),
            "item_type": br.read_i32(),
            "attr_count": br.read_i16(),
            "child_count": br.read_i16(),
            "parent_id": br.read_i32(),
            "first_attr": br.read_i32(),
            "first_child": br.read_i32(),
            "_reserved": br.read_i32(),
        })

    # --- attribute reference table (key_off, val_off) ---
    br.seek(ref_table_offset)
    attrs: list[tuple[int, int]] = [
        (br.read_i32(), br.read_i32()) for _ in range(ref_table_count)
    ]

    # --- build elements + attach attrs + stitch tree ---
    elements: dict[int, ET.Element] = {}
    attr_idx = 0
    root: ET.Element | None = None
    for node_id, nd in enumerate(nodes):
        el = ET.Element(s(nd["name_off"]))
        for _ in range(nd["attr_count"]):
            k_off, v_off = attrs[attr_idx]
            attr_idx += 1
            el.set(s(k_off), s(v_off, "BUGGED"))
        elements[node_id] = el
        parent = elements.get(nd["parent_id"])
        if parent is not None:
            parent.append(el)
        elif root is None:
            root = el

    if root is None and elements:
        root = elements[0]
    if root is None:
        raise ValueError("CryXmlB: no nodes")
    return root
