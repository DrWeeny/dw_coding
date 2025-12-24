import maya.cmds as cmds
from dw_maya.dw_maya_utils import lsTr
from collections import defaultdict

def get_exportable_type_list():
    return ["mesh", "nurbsCurve", "locator", "pgYetiMaya", "AlembicNode"]

def get_counter_name_remap_type_list(**kwargs):
    """
    Build type name remapping dictionary for shape type display names.

    Args:
        **kwargs: Custom type remapping (maya_type="display_name")

    Returns:
        dict: Type remapping dictionary

    Example:
        remap = get_counter_name_remap_type_list(pgYetiMaya="yeti_cache")
        # Returns: {"mesh": "mesh", "nurbsCurve": "curve", "pgYetiMaya": "yeti_cache", ...}
    """
    counter_dic = {}

    # Add custom remappings from kwargs (validate they're real Maya types)
    for key, value in kwargs.items():
        try:
            # Check if it's a valid Maya node type
            cmds.nodeType(key, isTypeName=True)
            counter_dic[key] = value
        except:
            pass

    # Add default exportable type mappings
    for _type in get_exportable_type_list():
        if _type not in counter_dic:
            if _type == "mesh":
                counter_dic[_type] = "mesh"
            elif _type == "nurbsCurve":
                counter_dic[_type] = "curve"
            elif _type == "pgYetiMaya":
                counter_dic[_type] = "yeti"
            elif _type == "npAbcShape":
                counter_dic[_type] = "abc_cache"

    return counter_dic


def count_types(namespace: str,
                counter_dic: dict = None,
                input_type_list: list = None,
                **kwargs) -> dict:
    """
    Count shape types for a namespace and update the counter dictionary.

    Args:
        namespace: Asset namespace to count types for
        counter_dic: Existing counter dictionary to update
        input_type_list: List of Maya node types to count
        **kwargs: Custom type name remapping (nodeType="display_name")

    Returns:
        dict: Updated counter dictionary {namespace: {type: count}}

    Example:
        counter = count_types("bettySTD_01", None, ["mesh", "mesh", "nurbsCurve"])
        # Returns: {"bettySTD_01": {"mesh": 2, "curve": 1}}
    """
    if not counter_dic:
        counter_dic = defaultdict(lambda: defaultdict(int))

    if not input_type_list:
        return counter_dic

    if not isinstance(input_type_list, (list, tuple)):
        input_type_list = [input_type_list]

    _count_base = get_counter_name_remap_type_list(**kwargs)
    _done = []

    for _type in input_type_list:
        if _type in _done:
            continue

        type_key = _count_base.get(_type)
        if type_key:
            counter_dic[namespace][type_key] += input_type_list.count(_type)
            _done.append(_type)

    return counter_dic


def get_exportable_transforms(node: list,
                              intermediate_transforms:bool=False) -> list:
    """
    Get all mesh nodes under a given node.

    Args:
        node: Maya node path

    Returns:
        list: List of mesh shape nodes
    """
    type_list = get_exportable_type_list()
    output_list = lsTr(node, dag=True, type=type_list, ni=True, long=True) or []

    if intermediate_transforms:
        _tr = cmds.ls(node, dag=True, type="transform", ni=True, long=True) or []
        output_list += _tr

    final_output = list(set(output_list))

    return final_output