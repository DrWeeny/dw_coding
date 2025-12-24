import maya.api.OpenMaya as om


def get_scene_hierarchy():
    """
    Get all transform nodes in the scene organized by hierarchy.

    Returns:
        dict: Nested dictionary representing the DAG hierarchy
              {node_path: {'children': {...}, 'shapes': [...]}}
    """
    # Filter for transform nodes only
    dag_iterator = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kTransform)

    hierarchy = {}

    while not dag_iterator.isDone():
        dag_path = dag_iterator.getPath()
        full_path = dag_path.fullPathName()

        # Get shape nodes under this transform
        shapes = []
        if dag_path.numberOfShapesDirectlyBelow() > 0:
            for i in range(dag_path.numberOfShapesDirectlyBelow()):
                dag_path.extendToShape(i)
                shape_node = om.MFnDagNode(dag_path)
                shapes.append(shape_node.typeName())
                dag_path.pop()  # Return to transform level

        hierarchy[full_path] = {
            'shapes': shapes,
            'depth': dag_path.length()
        }

        dag_iterator.next()

    return hierarchy


def build_tree_structure():
    """
    Build a parent-child tree structure from DAG paths.

    Returns:
        dict: Tree structure with nested children
    """
    hierarchy = get_scene_hierarchy()
    tree = {}

    for path, data in hierarchy.items():
        parts = path.split('|')[1:]  # Remove empty first element
        current = tree

        for i, part in enumerate(parts):
            if part not in current:
                current[part] = {
                    'full_path': '|'.join([''] + parts[:i + 1]),
                    'shapes': data['shapes'] if i == len(parts) - 1 else [],
                    'children': {}
                }
            current = current[part]['children']

    return tree
