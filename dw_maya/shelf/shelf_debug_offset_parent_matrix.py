"""
Check for transforms with offsetParentMatrix connections or inheritsTransform disabled.

These settings can cause issues in CFX pipelines where simulation rigs expect
standard transform hierarchies.
"""
import maya.cmds as cmds


def check_offset_parent_matrix(root=None):
    """
    Find transforms with connections to offsetParentMatrix attribute.

    Args:
        root: Optional root node to search under. If None, searches entire scene.

    Returns:
        list: Transform nodes with offsetParentMatrix connections
    """
    if root:
        transforms = cmds.listRelatives(root, allDescendents=True, type='transform', fullPath=True) or []
        transforms.append(root)
    else:
        transforms = cmds.ls(type='transform', long=True)

    issues = []
    for xform in transforms:
        attr = f"{xform}.offsetParentMatrix"
        if cmds.objExists(attr):
            connections = cmds.listConnections(attr, source=True, destination=False, plugs=True)
            if connections:
                issues.append(xform)

    return issues


def check_inherits_transform(root=None):
    """
    Find transforms with inheritsTransform disabled.

    Args:
        root: Optional root node to search under. If None, searches entire scene.

    Returns:
        list: Transform nodes with inheritsTransform set to False
    """
    if root:
        transforms = cmds.listRelatives(root, allDescendents=True, type='transform', fullPath=True) or []
        transforms.append(root)
    else:
        transforms = cmds.ls(type='transform', long=True)

    issues = []
    for xform in transforms:
        attr = f"{xform}.inheritsTransform"
        if cmds.objExists(attr):
            if not cmds.getAttr(attr):
                issues.append(xform)

    return issues


def check_transform_issues(root=None, verbose=True):
    """
    Check for both offsetParentMatrix and inheritsTransform issues.

    Args:
        root: Optional root node to search under. If None, searches entire scene.
        verbose: Print results to console (default: True)

    Returns:
        dict: Dictionary with 'offsetParentMatrix' and 'inheritsTransform' lists
    """
    opm_issues = check_offset_parent_matrix(root)
    it_issues = check_inherits_transform(root)

    if verbose:
        print("=" * 50)
        print("TRANSFORM ISSUES CHECK")
        print("=" * 50)

        if opm_issues:
            print(f"\noffsetParentMatrix connections found ({len(opm_issues)}):")
            for node in opm_issues:
                conn = cmds.listConnections(f"{node}.offsetParentMatrix", source=True, plugs=True)
                print(f"  - {node}")
                print(f"      connected from: {conn}")
        else:
            print("\nNo offsetParentMatrix connections found.")

        if it_issues:
            print(f"\ninheritsTransform disabled ({len(it_issues)}):")
            for node in it_issues:
                print(f"  - {node}")
        else:
            print("\nNo inheritsTransform issues found.")

        print("=" * 50)

    return {
        'offsetParentMatrix': opm_issues,
        'inheritsTransform': it_issues
    }


def select_transform_issues(root=None):
    """
    Select all transforms with offsetParentMatrix or inheritsTransform issues.

    Args:
        root: Optional root node to search under.
    """
    results = check_transform_issues(root, verbose=True)
    all_issues = results['offsetParentMatrix'] + results['inheritsTransform']
    all_issues = list(set(all_issues))

    if all_issues:
        cmds.select(all_issues)
        print(f"\nSelected {len(all_issues)} nodes with issues.")
    else:
        cmds.select(clear=True)
        print("\nNo issues found.")


# Check entire scene
check_transform_issues()

# Check specific rig namespace
# check_transform_issues(root="*:rig")

# Select problematic nodes
select_transform_issues()

# Get just offsetParentMatrix issues
opm_nodes = check_offset_parent_matrix()

# Get just inheritsTransform issues
it_nodes = check_inherits_transform()