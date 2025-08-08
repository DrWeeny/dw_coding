"""
Sources :
    - https://www.andynicholas.com/post/houdini-python-finding-all-nodes-of-a-type-in-the-scene
"""

import hou
from typing import Optional, Union, Tuple
from dw_maya.dw_decorators import acceptString

AUTOUPDATE = hou.updateMode.AutoUpdate
MANUAL = hou.updateMode.Manual
ONMOUSEUP = hou.updateMode.OnMouseUp

def get_node_instances(category, node_name):
    if isinstance(category, basestring):
        category = str_to_category(category)

    if not isinstance(category, hou.NodeTypeCategory):
        raise TypeError("Not a valid NodeTypeCategory")

    result = []
    for type_name, node_type in category.nodeTypes().iteritems():
        name_part = hou.hda.componentsFromFullNodeTypeName(type_name)[2]
        if node_name == name_part:
            result.extend(node_type.instances())
    return result

def str_to_category(category:str)->hou.NodeTypeCategory:
    """
    We can pass this “vopnet”, or “VopNET” and it’ll still give us the vopNetNodeTypeCategory
    Note that the context for ROPs is given as “Driver”.
    :return: node type category
    """
    category = category.title()
    if category.endswith("net"):
        category = category[:-3] + "Net"
    return hou.nodeTypeCategories().get(category)

def get_node_type_categories()->list:
    return hou.nodeTypeCategories().items()

def get_sop_node_by_type(node_type:str)->list:
    return hou.sopNodeTypeCategory().nodeType(node_type).instances()

def has_parm(node: hou.Node, parm_name: str) -> bool:
    return node.parm(parm_name) is not None

@acceptString("node")
def preserve_node_parms(node_list:hou.Node, parm_list:list=None)->dict:
    """
    function used so we can update HDAs to the latest version and preserve some of the parms
    """
    result = {}

    for node in node_list:

        if parm_list:
            node_path = node.path()
            result[node_path] = {}

            for parm in parm_list:
                if has_parm(node, parm):
                    result[node_path][parm] = node.parm(parm).eval()

    return result

def restore_node_parms(preserve_dict:dict=None):
    if preserve_dict:
        for node_path in preserve_dict:
            node = hou.node(node_path)
            for parm_name in preserve_dict[node_path]:
                if has_parm(node, parm_name):
                    node.parm(parm_name).set(preserve_dict[node_path][parm_name])

def get_current_hda_version(node:hou.Node)->hou.HDADefinition:
    if isinstance(node, str):
        node = hou.node(node)
    node_defintion = node.type().definition()
    return node_defintion

def get_hda_versions(node:hou.Node)->List[hou.HDADefinition]:
    """
    list all the history of a hda SOP::nodename::1.0, SOP::nodename::1.2
    """
    node_type = node.type()
    node_definition = node_type.definition()
    hda_file = node_definition.libraryFilePath()
    hda_version_list = hou.hda.definitionsInFile(hda_file)
    return hda_version_list

def get_hda_components(node:hou.Node)->Tuple[str,str,str,str]:
    """
    :returns :
    <scope>::<namespace>::<name>::<version>
    (scope, namespace, nodetype, version)
    """
    return hou.hda.componentsFromFullNodeTypeName(node.type().name())

def set_hda_version_to_latest(node: hou.Node) -> str:
    """
    set the node to the latest version
    """
    version_list = get_hda_versions(node)
    latest = version_list[-1]
    latest_name = latest.nodeType().name()

    if get_current_hda_version(node) != latest:
        node.changeNodeType(latest_name,
                            keep_name=True,
                            keep_parms=False,
                            keep_network_contents=False,
                            force_change_on_node_type_match=False)
    return latest_name

def get_sop_nodes_with_type(_type:str=None)->list:
    """
    list all sop nodes with the given type
    """
    return hou.sopNodeTypeCategory().nodeType(_type).instances()

def get_current_houdini_eval_mode()->Union[AUTOUPDATE, MANUAL, ONMOUSEUP]:
    return hou.updateModeSetting()

def force_timeshift_refresh()->bool:
    """
    function to prevent a bug where houdini keep the old cache in timeshift node after swapping animation
    this function toggle the node to force a recache
    #todo we should initialize the shot with an empty anim
    """
    # get time shifts
    ts_nodes = get_sop_nodes_with_type("timeshift")

    if not ts_nodes:
        return False

    # get current evaluation mode
    update_mode = hou.updateModeSetting()

    # if there are some timeshifts force the refresh and switch auto update
    if update_mode != AUTOUPDATE:
        # switch to auto-update
        hou.setUpdateMode(AUTOUPDATE)
        # refresh to set it active
        hou.updateModeSetting()

    # find all nodes which are not bypassed and toggle them
    for ts in ts_nodes:
        if not ts.isBypassed():
            ts.bypass(1)
            ts.bypass(0)

    # restore evaluation mode if it was different from auto update
    if ts_nodes and update_mode != AUTOUPDATE:
        hou.setUpdateMode(update_mode)
        hou.updateModeSetting()

    return True
