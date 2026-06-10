from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class SimSystem:
    name: str                            # 'nucleus', 'ziva', 'qualoth'
    solver_types: list[str]              # ['nucleus']
    sim_node_types: list[str]            # ['nCloth', 'hairSystem', 'nRigid']
    discover: Callable[[], list[str]]    # () -> list of solver nodes in scene
    make_item: Callable[[str], Any]      # (maya_node) -> SimItem
    cache_ops: type                      # class with create/attach/delete methods

_registry: dict[str, SimSystem] = {}    # keyed by node_type string

def register(system: SimSystem) -> None:
    for node_type in system.solver_types + system.sim_node_types:
        _registry[node_type] = system

def get_system(node_type: str) -> SimSystem:
    return _registry.get(node_type)

def discover_all() -> dict[str, list[str]]:
    """
    Returns {system_name: [solver_node, ...]} for all registered systems.
    Used by the tree builder — one call, all backends.
    """
    result = {}
    seen = set()
    for system in set(_registry.values()):
        solvers = [n for n in system.discover() if n not in seen]
        seen.update(solvers)
        if solvers:
            result[system.name] = solvers
    return result