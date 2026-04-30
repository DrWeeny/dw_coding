from typing import Type, Callable
from maya import cmds

_NODE_CLASSES: dict[str, Type] = {}
_CONDITION_CLASSES: list[tuple[Callable, Type]] = []


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