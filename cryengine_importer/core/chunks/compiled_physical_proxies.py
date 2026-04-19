"""ChunkCompiledPhysicalProxies.

Port of CgfConverter/CryEngineCore/Chunks/ChunkCompiledPhysicalProxies*.cs.
Only 0x800 is implemented; 0x801 is a stub in the C# tree too.
"""

from __future__ import annotations

from ...enums import ChunkType
from ...models.skinning import PhysicalProxy
from ..chunk_registry import Chunk, chunk


class ChunkCompiledPhysicalProxies(Chunk):
    def __init__(self) -> None:
        super().__init__()
        self.num_physical_proxies: int = 0
        self.physical_proxies: list[PhysicalProxy] = []


@chunk(ChunkType.CompiledPhysicalProxies, 0x800)
class ChunkCompiledPhysicalProxies800(ChunkCompiledPhysicalProxies):
    def read(self, br) -> None:
        super().read(br)

        self.num_physical_proxies = br.read_u32()

        for _ in range(self.num_physical_proxies):
            proxy = PhysicalProxy()
            proxy.id = br.read_u32()
            num_vertices = br.read_u32()
            num_indices = br.read_u32()
            proxy.material = br.read_u32()

            proxy.vertices = [br.read_vec3() for _ in range(num_vertices)]
            proxy.indices = [br.read_u16() for _ in range(num_indices)]
            # The reference C# walks `proxy.Material` bytes here as a
            # trailing material-name blob; preserve that behaviour.
            br.skip(proxy.material)

            self.physical_proxies.append(proxy)
