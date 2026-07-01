from typing import Type, Callable, Dict, List, Tuple
from maya import cmds

_NODE_CLASSES: Dict[str, Type] = {}
_CONDITION_CLASSES: List[Tuple[Callable, Type]] = []


def register_type(node_type: str, cls: Type) -> None:
    """Register by Maya node type string."""
    _NODE_CLASSES[node_type] = cls


def register_condition(condition: Callable, cls: Type) -> None:
    """Register by condition (def is_cloth).
    Example:
        def _is_cloth(node) -> bool:
            return (node.type == "mesh" and
                    bool(cmds.listConnections(node, type='nCloth')))
        def _is_rigid(node) -> bool:
            return (node.type == "mesh" and
                    bool(cmds.listConnections(node, type='nRigid')))

        def _is_bounding(node) -> bool:
            return cmds.attributeQuery('boundingRole', node=node, exists=True)

        register_condition(_is_cloth,    ClothNode)
        register_condition(_is_rigid,    RigidNode)
        register_condition(_is_bounding, BoundingMesh)
    """
    _CONDITION_CLASSES.append((condition, cls))


def resolve(node: str) -> Type:
    from dw_maya.dw_maya_nodes import MayaNode

    node_type = cmds.nodeType(node)

    # 1. exact match → highest priority
    if node_type in _NODE_CLASSES:
        return _NODE_CLASSES[node_type]

    # 2. walk the inheritance chain
    # cmds.nodeType(node, inherited=True) → ['containerBase', ..., 'geometryFilter', 'cluster']
    inherited = cmds.nodeType(node, inherited=True) or []
    for parent_type in reversed(inherited):  # most specific first
        if parent_type in _NODE_CLASSES:
            return _NODE_CLASSES[parent_type]

    # 3. condition-based (ClothNode etc.)
    instance = MayaNode(node)
    for condition, cls in _CONDITION_CLASSES:
        if condition(instance):
            return cls

    return MayaNode


def resolve_type(node_type: str) -> Type:
    """Resolve a class from a node-type *string* (no live node required).

    The type-driven twin of :func:`resolve`, used to rebuild nodes from a saved
    preset. Mirrors steps 1-2 (exact match -> inherited walk) using
    ``cmds.nodeType(..., isTypeName=True)``; condition-based rules are skipped
    since they need a live node to inspect.
    """
    from dw_maya.dw_maya_nodes import MayaNode

    if not node_type:
        return MayaNode

    # 1. exact match
    if node_type in _NODE_CLASSES:
        return _NODE_CLASSES[node_type]

    # 2. walk the inheritance chain of the type name
    try:
        inherited = cmds.nodeType(node_type, inherited=True, isTypeName=True) or []
    except Exception:
        inherited = []
    for parent_type in reversed(inherited):  # most specific first
        if parent_type in _NODE_CLASSES:
            return _NODE_CLASSES[parent_type]

    return MayaNode