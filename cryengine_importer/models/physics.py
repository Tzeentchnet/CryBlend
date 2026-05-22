"""Physics-data dataclasses + readers for ``MeshPhysicsData`` chunks.

The on-disk layout is **not** specified by the upstream C# tree
(``CgfConverter/Models/PhysicsData.cs`` declares the record fields but
never actually reads them — the corresponding ``ChunkMeshPhysicsData_800``
is annotated ``// TODO`` and just calls ``base.Read``). The authoritative
spec used here is **PyFFI's** ``cgf.xml`` schema:

  https://github.com/niftools/pyffi  →  ``pyffi/formats/cgf/cgf.xml``
  (struct ``PhysicsData``, ``PhysicsCube``, ``PhysicsCylinder``,
  ``PhysicsShape6``, ``MeshPhysicsDataChunk``).

File-format layouts aren't copyrightable, and PyFFI itself ships under
the BSD-3 licence. We translate that schema into the same ``read_*``
helper style we use elsewhere in ``models/``.

**Scope** — we decode the well-defined cases:

* ``MeshPhysicsDataChunk_800`` 24-byte header + ``PhysicsData`` payload
  + raw ``tetrahedra_data`` bytes.
* ``PhysicsData`` 60-byte prefix + ``primitive_type`` switch.
* ``PrimitiveType.CUBE`` (132 bytes) — ``PhysicsCube`` + ``PhysicsStruct1``.
* ``PrimitiveType.CYLINDER`` / ``UNKNOWN6`` (104 bytes) — ``PhysicsCylinder``
  / ``PhysicsShape6`` (identical layout per pyffi).
* ``PrimitiveType.POLYHEDRON`` embedded geometry — counts, optional
    vertex map, vertices, triangle indices, and triangle flags. The
    trailing solver/contact records remain opaque and are skipped via
    the chunk's declared ``physics_data_size``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class PhysicsPrimitiveType(IntEnum):
    """Port of pyffi ``cgf.xml#PhysicsPrimitiveType`` (matches the C#
    ``CgfConverter`` ``PhysicsPrimitiveType`` enum byte-for-byte)."""

    CUBE = 0
    POLYHEDRON = 1
    CYLINDER = 5
    UNKNOWN6 = 6


# ----------------------------------------------------------- shared -------


_IDENTITY_3X3: tuple[tuple[float, ...], ...] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
)


@dataclass
class PhysicsStruct1:
    """64-byte sub-record used twice inside ``PhysicsCube``.

    Per pyffi: ``Matrix33`` (36) + ``int`` (4) + ``float[6]`` (24).
    """

    matrix: tuple[tuple[float, ...], ...] = _IDENTITY_3X3
    unknown_2: int = 0
    unknown_3: tuple[float, ...] = (0.0,) * 6


def _read_physics_struct1(br) -> PhysicsStruct1:
    return PhysicsStruct1(
        matrix=br.read_matrix3x3(),
        unknown_2=br.read_i32(),
        unknown_3=tuple(br.read_f32() for _ in range(6)),
    )


@dataclass
class PhysicsDataType2:
    """68-byte sub-record used inside ``PhysicsCylinder`` / ``PhysicsShape6``.

    Per pyffi: ``Matrix33`` (36) + ``int`` (4) + ``float[6]`` (24)
    + ``int`` (4).
    """

    matrix: tuple[tuple[float, ...], ...] = _IDENTITY_3X3
    unknown_2: int = 0
    unknown_3: tuple[float, ...] = (0.0,) * 6
    unknown_4: int = 0


def _read_physics_data_type2(br) -> PhysicsDataType2:
    return PhysicsDataType2(
        matrix=br.read_matrix3x3(),
        unknown_2=br.read_i32(),
        unknown_3=tuple(br.read_f32() for _ in range(6)),
        unknown_4=br.read_i32(),
    )


# ----------------------------------------------------------- shapes -------


@dataclass
class PhysicsCube:
    """132-byte cube primitive (``PrimitiveType.CUBE``).

    Per pyffi: 2 × ``PhysicsStruct1`` (128) + ``int`` (4).
    """

    a: PhysicsStruct1 = field(default_factory=PhysicsStruct1)
    b: PhysicsStruct1 = field(default_factory=PhysicsStruct1)
    unknown_16: int = 0


def read_physics_cube(br) -> PhysicsCube:
    return PhysicsCube(
        a=_read_physics_struct1(br),
        b=_read_physics_struct1(br),
        unknown_16=br.read_i32(),
    )


@dataclass
class PhysicsCylinder:
    """104-byte cylinder primitive.

    Used for both ``PrimitiveType.CYLINDER`` (5) and
    ``PrimitiveType.UNKNOWN6`` (6) — pyffi notes the two layouts are
    identical. Per pyffi: ``float[8]`` (32) + ``int`` (4) +
    ``PhysicsDataType2`` (68).
    """

    unknown_1: tuple[float, ...] = (0.0,) * 8
    unknown_2: int = 0
    unknown_3: PhysicsDataType2 = field(default_factory=PhysicsDataType2)


def read_physics_cylinder(br) -> PhysicsCylinder:
    return PhysicsCylinder(
        unknown_1=tuple(br.read_f32() for _ in range(8)),
        unknown_2=br.read_i32(),
        unknown_3=_read_physics_data_type2(br),
    )


@dataclass
class PhysicsPolyhedron:
    """Decoded mesh portion of ``PrimitiveType.POLYHEDRON``.

    The records after ``data_type`` are CryPhysics internals whose
    layout varies by subtype. They are not needed to display/import a
    collision proxy mesh, so the reader captures the stable geometry
    portion and skips the remaining payload by declared size.
    """

    num_vertices: int = 0
    num_triangles: int = 0
    unknown_17: int = 0
    unknown_18: int = 0
    has_vertex_map: int = 0
    vertex_map: tuple[int, ...] = ()
    use_data_stream: int = 0
    vertices: tuple[tuple[float, float, float], ...] = ()
    triangles: tuple[tuple[int, int, int], ...] = ()
    unknown_210: int | None = None
    triangle_flags: tuple[int, ...] = ()
    triangle_map: tuple[int, ...] = ()
    unknown_45: bytes = b""
    unknown_461: int | None = None
    unknown_462: int | None = None
    unknown_tail: tuple[float, ...] = ()
    data_type: int | None = None

    @property
    def has_embedded_geometry(self) -> bool:
        return bool(self.vertices and self.triangles)


# ----------------------------------------------------------- payload ------


@dataclass
class PhysicsData:
    """Decoded ``PhysicsData`` payload (pyffi ``cgf.xml#PhysicsData``).

    The 60-byte prefix is always read; the trailing primitive-specific
    block is decoded for ``CUBE`` / ``CYLINDER`` / ``UNKNOWN6`` and
    left as ``None`` for ``POLYHEDRON`` (see module docstring).
    """

    unknown_4: int = 0
    unknown_5: int = 0
    inertia: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mass: float = 0.0
    unknown_11: int = 0
    unknown_12: int = 0
    unknown_13: float = 0.0
    unknown_14: float = 0.0
    primitive_type: int = -1  # raw uint; -1 means "no payload was read"
    cube: Optional[PhysicsCube] = None
    cylinder: Optional[PhysicsCylinder] = None  # also used for UNKNOWN6
    polyhedron: Optional[PhysicsPolyhedron] = None
    polyhedron_skipped: bool = False

    @property
    def primitive(self) -> Optional[PhysicsPrimitiveType]:
        """Typed primitive type, or ``None`` for unknown raw values."""
        try:
            return PhysicsPrimitiveType(self.primitive_type)
        except ValueError:
            return None


def read_physics_data(br, *, payload_size: int | None = None) -> PhysicsData:
    """Read one ``PhysicsData`` record from ``br``.

    ``payload_size`` is the declared size of the enclosing
    ``PhysicsData`` payload. Passing it lets variable-size polyhedrons
    and unknown primitive records advance to the end of the payload
    before any following tetrahedra bytes are read.
    """
    payload_start = br.tell()
    payload_end = payload_start + payload_size if payload_size is not None else None
    pd = PhysicsData()
    pd.unknown_4 = br.read_i32()
    pd.unknown_5 = br.read_i32()
    pd.inertia = (br.read_f32(), br.read_f32(), br.read_f32())
    pd.rotation = br.read_quat()
    pd.center = br.read_vec3()
    pd.mass = br.read_f32()
    pd.unknown_11 = br.read_i32()
    pd.unknown_12 = br.read_i32()
    pd.unknown_13 = br.read_f32()
    pd.unknown_14 = br.read_f32()
    pd.primitive_type = br.read_u32()

    typed = pd.primitive
    if typed == PhysicsPrimitiveType.CUBE:
        pd.cube = read_physics_cube(br)
    elif typed in (PhysicsPrimitiveType.CYLINDER, PhysicsPrimitiveType.UNKNOWN6):
        pd.cylinder = read_physics_cylinder(br)
    elif typed == PhysicsPrimitiveType.POLYHEDRON:
        pd.polyhedron = read_physics_polyhedron(br, payload_end=payload_end)
        pd.polyhedron_skipped = not (
            pd.polyhedron is not None and pd.polyhedron.has_embedded_geometry
        )

    if payload_end is not None and br.tell() < payload_end:
        br.seek(payload_end)
    return pd


def read_physics_polyhedron(br, *, payload_end: int | None = None) -> PhysicsPolyhedron | None:
    """Read the stable geometry section of a polyhedron primitive.

    Returns ``None`` if the payload is too short or uses an unsupported
    geometry mode. When ``payload_end`` is provided, the stream is
    positioned at that end before returning.
    """
    try:
        if payload_end is not None and payload_end - br.tell() < 18:
            return None
        polyhedron = PhysicsPolyhedron(
            num_vertices=br.read_u32(),
            num_triangles=br.read_u32(),
            unknown_17=br.read_i32(),
            unknown_18=br.read_i32(),
        )
        has_vertex_map = br.read_u8()
        vertex_map: tuple[int, ...] = ()
        if has_vertex_map == 1:
            if payload_end is not None and payload_end - br.tell() < polyhedron.num_vertices * 2 + 1:
                return None
            vertex_map = tuple(br.read_u16() for _ in range(polyhedron.num_vertices))
        use_data_stream = br.read_u8()

        vertices: tuple[tuple[float, float, float], ...] = ()
        triangles: tuple[tuple[int, int, int], ...] = ()
        unknown_210: int | None = None
        triangle_flags: tuple[int, ...] = ()
        triangle_map: tuple[int, ...] = ()

        if use_data_stream == 0:
            geometry_size = polyhedron.num_vertices * 12 + polyhedron.num_triangles * 6
            geometry_size += 1 + polyhedron.num_triangles
            if payload_end is not None and payload_end - br.tell() < geometry_size:
                return None
            vertices = tuple(br.read_vec3() for _ in range(polyhedron.num_vertices))
            triangles = tuple(
                (br.read_u16(), br.read_u16(), br.read_u16())
                for _ in range(polyhedron.num_triangles)
            )
            unknown_210 = br.read_i8()
            triangle_flags = tuple(br.read_u8() for _ in range(polyhedron.num_triangles))
        elif use_data_stream == 1:
            if payload_end is not None and payload_end - br.tell() < polyhedron.num_triangles * 2:
                return None
            triangle_map = tuple(br.read_u16() for _ in range(polyhedron.num_triangles))
        else:
            return None

        unknown_45 = b""
        unknown_461: int | None = None
        unknown_462: int | None = None
        unknown_tail: tuple[float, ...] = ()
        data_type: int | None = None
        if payload_end is None or payload_end - br.tell() >= 56:
            unknown_45 = br.read_bytes(16)
            unknown_461 = br.read_i32()
            unknown_462 = br.read_i32()
            unknown_tail = tuple(br.read_f32() for _ in range(7))
            data_type = br.read_u32()

        return PhysicsPolyhedron(
            num_vertices=polyhedron.num_vertices,
            num_triangles=polyhedron.num_triangles,
            unknown_17=polyhedron.unknown_17,
            unknown_18=polyhedron.unknown_18,
            has_vertex_map=has_vertex_map,
            vertex_map=vertex_map,
            use_data_stream=use_data_stream,
            vertices=vertices,
            triangles=triangles,
            unknown_210=unknown_210,
            triangle_flags=triangle_flags,
            triangle_map=triangle_map,
            unknown_45=unknown_45,
            unknown_461=unknown_461,
            unknown_462=unknown_462,
            unknown_tail=unknown_tail,
            data_type=data_type,
        )
    except EOFError:
        return None
