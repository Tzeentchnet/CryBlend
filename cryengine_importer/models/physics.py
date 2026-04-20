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

``PrimitiveType.POLYHEDRON`` is intentionally **not** decoded: pyffi's
schema for it is variable-size with multiple ``Unknown`` / ``Junk?`` /
``not sure`` annotations and ``PhysicsDataType{0,1}`` substructs whose
``Num Data 1`` field is documented as "usually 0xffffffff" without a
firm rule. Shipping a guess would be worse than skipping the payload.
The ``PhysicsData`` reader records the primitive type and stops there
when it encounters a polyhedron, so the chunk-table walk still
advances cleanly via the chunk header's ``size`` field.
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
    polyhedron_skipped: bool = False

    @property
    def primitive(self) -> Optional[PhysicsPrimitiveType]:
        """Typed primitive type, or ``None`` for unknown raw values."""
        try:
            return PhysicsPrimitiveType(self.primitive_type)
        except ValueError:
            return None


def read_physics_data(br) -> PhysicsData:
    """Read one ``PhysicsData`` record from ``br``.

    Stops cleanly after the primitive-type uint when the primitive is
    ``POLYHEDRON`` (sets :attr:`PhysicsData.polyhedron_skipped`); the
    caller is responsible for using the chunk header's ``size`` to
    advance past the unread bytes.
    """
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
        # See module docstring — pyffi's polyhedron schema is too
        # under-specified to ship without a real fixture.
        pd.polyhedron_skipped = True
    # Unknown raw values: do nothing; chunk header size advances us.
    return pd
