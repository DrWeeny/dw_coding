from typing import Type, Callable
from maya import cmds

_NODE_CLASSES: dict[str, Type] = {}
_CONDITION_CLASSES: list[tuple[Callable, Type]] = []


def register_type(node_type: str, cls: Type) -> None:
    """Register by Maya node type string."""
    _NODE_CLASSES[node_type] = cls


def register_condition(condition: Callable, cls: Type) -> None:
    """Register by condition (ex: cloth connecté à nucleus)."""
    _CONDITION_CLASSES.append((condition, cls))


def resolve(node: str) -> Type:
    """Returns the most specialized class for a node."""
    from dw_maya.dw_maya_nodes import MayaNode

    node_type = cmds.nodeType(node)

    # 1. higher prio
    if node_type in _NODE_CLASSES:
        return _NODE_CLASSES[node_type]

    # 2. conditionnal for cloth
    instance = MayaNode(node)
    for condition, cls in _CONDITION_CLASSES:
        if condition(instance):
            return cls

    return MayaNode