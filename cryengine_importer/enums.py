"""Port of CgfConverter/Enums/Enums.cs.

Only the enums needed by Phase 1+ of the importer are included.
Kept in a single module so chunk modules can `from .. import enums as E`.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag


class FileVersion(IntEnum):
    Unknown = 0
    x0744 = 0x744
    x0745 = 0x745
    x0746 = 0x746
    x0900 = 0x900


class FileType(IntEnum):
    Geometry = 0xFFFF0000
    Animation = 0xFFFF0001


class MtlNameType(IntFlag):
    Basic = 0x00
    Library = 0x01
    MwoChild = 0x02
    Single = 0x10
    Child = 0x12
    Unknown1 = 0x0B
    Unknown2 = 0x04


class ChunkType(IntEnum):
    Any = 0x0
    Mesh = 0xCCCC0000
    Helper = 0xCCCC0001
    VertAnim = 0xCCCC0002
    BoneAnim = 0xCCCC0003
    GeomNameList = 0xCCCC0004
    BoneNameList = 0xCCCC0005
    MtlList = 0xCCCC0006
    MRM = 0xCCCC0007
    SceneProps = 0xCCCC0008
    Light = 0xCCCC0009
    PatchMesh = 0xCCCC000A
    Node = 0xCCCC000B
    Mtl = 0xCCCC000C
    Controller = 0xCCCC000D
    Timing = 0xCCCC000E
    BoneMesh = 0xCCCC000F
    BoneLightBinding = 0xCCCC0010
    MeshMorphTarget = 0xCCCC0011
    BoneInitialPos = 0xCCCC0012
    SourceInfo = 0xCCCC0013
    MtlName = 0xCCCC0014
    ExportFlags = 0xCCCC0015
    DataStream = 0xCCCC0016
    MeshSubsets = 0xCCCC0017
    MeshPhysicsData = 0xCCCC0018
    CompiledBones = 0xACDC0000
    CompiledPhysicalBones = 0xACDC0001
    CompiledMorphTargets = 0xACDC0002
    CompiledPhysicalProxies = 0xACDC0003
    CompiledIntFaces = 0xACDC0004
    CompiledIntSkinVertices = 0xACDC0005
    CompiledExt2IntMap = 0xACDC0006
    BreakablePhysics = 0xACDC0007
    FaceMap = 0xAAFC0000
    SpeedInfo = 0xAAFC0002
    FootPlantInfo = 0xAAFC0003
    BonesBoxes = 0xAAFC0004
    FoliageInfo = 0xAAFC0005
    GlobalAnimationHeaderCAF = 0xAAFC0007
    MotionParams = 0x3002

    # Star Citizen variants
    NodeSC = 0xCCCC100B
    CompiledBonesSC = 0xCCCC1000
    CompiledPhysicalBonesSC = 0xCCCC1001
    CompiledMorphTargetsSC = 0xCCCC1002
    CompiledPhysicalProxiesSC = 0xCCCC1003
    CompiledIntFacesSC = 0xCCCC1004
    CompiledIntSkinVerticesSC = 0xCCCC1005
    CompiledExt2IntMapSC = 0xCCCC1006
    UnknownSC1 = 0xCCCC2004

    # Star Citizen #ivo file chunks
    NodeMeshCombo = 0x70697FDA
    MtlNameIvo = 0x8335674E
    MtlNameIvo320 = 0x83353333
    CompiledPhysicalBonesIvo = 0x90C687DC
    CompiledPhysicalBonesIvo320 = 0x90C66666
    MeshInfo = 0x92914444
    MeshIvo = 0x9293B9D8
    IvoSkin = 0xB875B2D9
    IvoSkin2 = 0xB8757777
    CompiledBones_Ivo = 0xC201973C
    CompiledBones_Ivo2 = 0xC2011111
    BShapesGPU = 0x57A3BEFD
    BShapes = 0x875CCB28

    # Star Citizen #ivo animation chunks
    IvoAnimInfo = 0x4733C6ED        # Animation info chunk (CAF), v901
    IvoCAFData = 0xA9496CB5         # #caf animation data
    IvoDBAData = 0x194FBC50         # #dba animation data blocks
    IvoDBAMetadata = 0xF7351608     # DBA metadata / string table

    # Star Citizen 4.5+ chunk types — safely skipped (metadata / LOD).
    # Per v2.0.0 ChunkConverter.New: routed to ChunkUnknown so the
    # registry's unknown fallback handles them. Listed here so chunk
    # tables with these types parse cleanly without "unknown enum"
    # noise.
    IvoAssetMetadata = 0xBE5E493E   # Asset GUIDs (128 bytes)
    IvoLodDistances = 0x9351756F    # LOD distance thresholds
    IvoLodMeshData = 0x58DE1772     # LOD1-4 meshes (large)
    IvoBoundingData = 0x2B7ECF9F    # Bounding / animation data
    IvoChunkTerminator = 0xE0181074 # EOF marker in .cgam files
    IvoMtlNameVariant = 0x83353533  # Material name variant (rare)

    BinaryXmlDataSC = 0xCCCBF004


class HelperType(IntEnum):
    POINT = 0
    DUMMY = 1
    XREF = 2
    CAMERA = 3
    GEOMETRY = 4


class MtlNamePhysicsType(IntEnum):
    NONE = 0xFFFFFFFF
    DEFAULT = 0x00000000
    NOCOLLIDE = 0x00000001
    OBSTRUCT = 0x00000002
    DEFAULTPROXY = 0x000000FF
    UNKNOWN = 0x00001100
    UNKNOWN2 = 0x00001000


class DatastreamType(IntEnum):
    VERTICES = 0x00
    NORMALS = 0x01
    UVS = 0x02
    COLORS = 0x03
    COLORS2 = 0x04
    INDICES = 0x05
    TANGENTS = 0x06
    DUMMY0 = 0x07
    DUMMY1 = 0x08
    BONEMAP = 0x09
    FACEMAP = 0x0A
    VERTMATS = 0x0B
    QTANGENTS = 0x0C
    SKINDATA = 0x0D
    DUMMY2 = 0x0E
    VERTSUVS = 0x0F
    NUMTYPES = 0x10
    IVONORMALS = 0x9CF3F615
    IVONORMALS2 = 0x38A581FE
    IVOCOLORS2 = 0xD9EED421
    IVOINDICES = 0xEECDC168
    IVOTANGENTS = 0xB95E9A1B
    IVOQTANGENTS = 0xEE057252
    IVOBONEMAP = 0x677C7B23
    IVOVERTSUVS = 0x91329AE9
    IVOVERTSUVS2 = 0xB3A70D5E
    IVOBONEMAP32 = 0x6ECA3708
    IVOUNKNOWN = 0x9D51C5EE


class MeshChunkFlag(IntFlag):
    MESH_IS_EMPTY = 0x0001
    HAS_TEX_MAPPING_DENSITY = 0x0002
    HAS_EXTRA_WEIGHTS = 0x0004
    HAS_FACE_AREA = 0x0008


class CtrlType(IntEnum):
    NONE = 0
    CRYBONE = 1
    LINEAR1 = 2
    LINEAR3 = 3
    LINEARQ = 4
    BEZIER1 = 5
    BEZIER3 = 6
    BEZIERQ = 7
    TBC1 = 8
    TBC3 = 9
    TBCQ = 10
    BSPLINE2O = 11
    BSPLINE1O = 12
    BSPLINE2C = 13
    BSPLINE1C = 14
    CONST = 15


class KeyTimesFormat(IntEnum):
    """ChunkController_905 EKeyTimesFormat."""

    eF32 = 0
    eUINT16 = 1
    eByte = 2
    eF32StartStop = 3
    eUINT16StartStop = 4
    eByteStartStop = 5
    eBitset = 6


class CompressionFormat(IntEnum):
    """ChunkController_905 ECompressionFormat (quaternion / vec3 packs)."""

    eNoCompress = 0
    eNoCompressQuat = 1
    eNoCompressVec3 = 2
    eShotInt3Quat = 3
    eSmallTreeDWORDQuat = 4
    eSmallTree48BitQuat = 5
    eSmallTree64BitQuat = 6
    ePolarQuat = 7
    eSmallTree64BitExtQuat = 8
    eAutomaticQuat = 9


class AnimAssetFlags(IntFlag):
    """ChunkController_905 AssetFlags."""

    Additive = 0x001
    Cycle = 0x002
    Loaded = 0x004
    Lmg = 0x008
    LmgValid = 0x020
    Created = 0x800
    Requested = 0x1000
    Ondemand = 0x2000
    Aimpose = 0x4000
    AimposeUnloaded = 0x8000
    NotFound = 0x10000
    Tcb = 0x20000
    Internaltype = 0x40000
    BigEndian = 0x80000000


class IvoGeometryType(IntEnum):
    """Per-NodeMeshCombo_900 entry geometry kind. Port of
    CgfConverter/Enums/Enums.cs#IvoGeometryType."""

    Geometry = 0x0
    Helper2 = 0x2
    Helper3 = 0x3


class VertexFormat(IntEnum):
    """Port of CgfConverter/Enums/Enums.cs#VertexFormat. Only the
    fields actually referenced by the IVO chunk readers are described;
    the rest are placeholders so on-disk values round-trip cleanly."""

    eVF_Unknown = 0
    eVF_P3F_C4B_T2F = 1
    eVF_P3F_C4B_T2F_T2F = 2
    eVF_P3S_C4B_T2S = 3
    eVF_P3S_C4B_T2S_T2S = 4
    eVF_P3S_N4B_C4B_T2S = 5
    eVF_P3F_C4B_T4B_N3F2 = 6
    eVF_TP3F_C4B_T2F = 7
    eVF_TP3F_T2F_T3F = 8
    eVF_P3F_T3F = 9
    eVF_P3F_T2F_T3F = 10
    eVF_T2F = 11
    eVF_W4B_I4S = 12
    eVF_C4B_C4B = 13
    eVF_P3F_P3F_I4B = 14
    eVF_P3F = 15
    eVF_C4B_T2S = 16
    eVF_P2F_T4F_C4F = 17
    eVF_P2F_T4F_T4F_C4F = 18
    eVF_P2S_N4B_C4B_T1F = 19
    eVF_P3F_C4B_T2S = 20
    eVF_P2F_C4B_T2F_F4B = 21
    eVF_P3F_C4B = 22
    eVF_P3F_C4F_T2F = 23
