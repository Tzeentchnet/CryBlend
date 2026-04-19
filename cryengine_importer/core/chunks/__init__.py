"""Chunk implementations.

Importing this package triggers the @chunk decorators on every chunk
class, populating the registry in `..chunk_registry`. The Model loader
calls ``import .chunks`` once at startup.
"""

from __future__ import annotations

# Order matters only insofar as headers must be importable before
# Model.load runs; chunk-body classes can come in any order.
from . import header  # noqa: F401
from . import unknown  # noqa: F401
from . import source_info  # noqa: F401
from . import export_flags  # noqa: F401
from . import timing_format  # noqa: F401
from . import scene_prop  # noqa: F401
from . import helper  # noqa: F401
from . import mtl_name  # noqa: F401
from . import mesh  # noqa: F401
from . import mesh_subsets  # noqa: F401
from . import data_stream  # noqa: F401
from . import node  # noqa: F401

# Phase 3 — skinning chunks
from . import compiled_bones  # noqa: F401
from . import compiled_physical_bones  # noqa: F401
from . import compiled_physical_proxies  # noqa: F401
from . import compiled_int_skin_vertices  # noqa: F401
from . import compiled_int_faces  # noqa: F401
from . import compiled_ext_to_int_map  # noqa: F401
from . import bone_name_list  # noqa: F401

# Phase 4 — animation chunks
from . import controller  # noqa: F401
from . import bone_anim  # noqa: F401
from . import global_animation_header_caf  # noqa: F401

# Phase 5 — Star Citizen IVO (#ivo) chunks
from . import mtl_name_900  # noqa: F401
from . import mesh_900  # noqa: F401
from . import compiled_bones_ivo  # noqa: F401
from . import node_mesh_combo  # noqa: F401
from . import binary_xml_data  # noqa: F401
from . import ivo_skin_mesh  # noqa: F401

# Phase 5c-E — Star Citizen IVO #caf / #dba animation chunks
from . import ivo_anim_info  # noqa: F401
from . import ivo_caf  # noqa: F401
from . import ivo_dba_data  # noqa: F401
from . import ivo_dba_metadata  # noqa: F401

# Phase 6 — morph targets / blend shapes
from . import morph_targets  # noqa: F401

# Phase 7 — physics & misc
from . import mesh_physics_data  # noqa: F401
