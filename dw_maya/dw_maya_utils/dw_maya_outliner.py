"""
Maya DAG Outliner Utilities

Build Python dict representations of the Maya DAG hierarchy.

Features:
    - Flat hierarchy dict keyed by fullpath with shape type and depth info.
    - Nested tree dict mirroring the DAG parent-child structure.

Functions:
    get_scene_hierarchy : Return {fullpath: {shapes, depth}} for all transforms.
    build_tree_structure: Return a nested parent-child tree from the DAG.

Example:
    >>> import dw_maya.dw_maya_utils.dw_maya_outliner as dw_outliner
    >>> tree = dw_outliner.build_tree_structure()

Author: DrWeeny
"""

import maya.api.OpenMaya
from maya import cmds
from dw_maya.dw_decorators import acceptString


@acceptString('nodes')
def set_outliner_node_colour(nodes:list, color:list, use:bool=True):
    for n in nodes:
        cmds.setAttr(n + ".useOutlinerColor", use)
        cmds.setAttr(n + ".outlinerColor", *color)

@acceptString('nodes')
def set_hidden_in_outliner(nodes:list, value:bool=True):
    for n in nodes:
        cmds.setAttr('{}.hiddenInOutliner'.format(n), value)

def get_scene_hierarchy():
    """
    Get all transform nodes in the scene organized by hierarchy.

    Returns:
        dict: {fullpath: {'shapes': [typeName, ...], 'depth': int}}
    """
    dag_iterator = maya.api.OpenMaya.MItDag(
        maya.api.OpenMaya.MItDag.kDepthFirst,
        maya.api.OpenMaya.MFn.kTransform,
    )

    hierarchy = {}

    while not dag_iterator.isDone():
        dag_path  = dag_iterator.getPath()
        full_path = dag_path.fullPathName()

        shapes = []
        for i in range(dag_path.numberOfShapesDirectlyBelow()):
            dag_path.extendToShape(i)
            shape_node = maya.api.OpenMaya.MFnDagNode(dag_path)
            shapes.append(shape_node.typeName())
            dag_path.pop()

        hierarchy[full_path] = {
            "shapes": shapes,
            "depth" : dag_path.length(),
        }

        dag_iterator.next()

    return hierarchy


def build_tree_structure():
    """
    Build a parent-child tree structure from DAG paths.

    Returns:
        dict: Nested tree where each node has 'full_path', 'shapes' and
              'children' keys.
    """
    hierarchy = get_scene_hierarchy()
    tree = {}

    for path, data in hierarchy.items():
        parts   = path.split("|")[1:]  # strip leading empty segment
        current = tree

        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {
                    "full_path": "|".join([""] + parts[: i + 1]),
                    "shapes"   : data["shapes"] if i == len(parts) - 1 else [],
                    "children" : {},
                }
            current = current[part]["children"]

    return tree
