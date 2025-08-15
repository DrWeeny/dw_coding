import hou
from typing import Any



def list_recipe(filename:str) -> list:
    """

    :param filename:
    :return:
    """
    return hou.hda.definitionsInFile(filename)


def get_current_network_tab():
    """
    # Find the active Network Editor pane tab
    # If you have multiple Network Editor panes, you might need a more specific way
    # to identify the one you're interested in (e.g., by its path or name).
    # For simplicity, this example assumes you want the first Network Editor tab found."""
    network_editor_tab = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    return network_editor_tab

def applyTabToolRecipe(recipe_name: str,
                       panetab_obj = None,
                       nodepositionx:int=None,
                       nodepositiony:int=None,
                       inputs:list=None,
                       outputs:list=None)-> dict[str, Any]:
    """

    :param recipe_name:
    :param panetab_obj:
    :param nodepositionx:
    :param nodepositiony:
    :param inputs:
    :param outputs:
    :return:
    """
    kwargs = {}

    if not panetab_obj:
        panetab_obj = get_current_network_tab()

    kwargs["pane"]=panetab_obj

    current_sel = hou.selectedNodes()

    current_pos = None

    if not nodepositionx and not nodepositiony and not inputs:
        if current_sel:
            current_pos = current_sel[0].position() + hou.Vector2(1.5, 0)
        else:
            current_pos = hou.Vector2(0, 0)
    elif nodepositionx or nodepositiony and not inputs:
        current_pos = (nodepositionx, nodepositiony)

    if current_pos != None:
        kwargs["nodepositionx"] = current_pos[0]
        kwargs["nodepositiony"] = current_pos[1]

    if inputs:
        kwargs["inputs"] = inputs
    if outputs:
        kwargs["outputs"] = outputs

    output = hou.data.applyTabToolRecipe(recipe_name, kwargs, parms=True, parmtemplates=True, children=True, editables=True, skip_notes=True)
    return output

def applyDecorationRecipe(recipe_name: str,
                          central_node: hou.OpNode,
                          insert_mode:bool=False,
                          parms=True,
                          parmtemplates=True,
                          children=True,
                          editables=True,
                          skip_notes=True)-> dict[str, Any]:
    """
    todo extend into looking if the tool exists in the library
    :param recipe_name: full name with namespace
    :param central_node:
    :param insert_mode: Rewire existing connections into and out of the given node.
    :param parms:
    :param parmtemplates:
    :param children:
    :param editables:
    :param skip_notes:
    :return:
    """

    output = hou.data.applyDecorationRecipe(recipe_name,
                                          central_node=central_node,
                                          insert_mode=insert_mode,
                                          parms=parms,
                                          parmtemplates=parmtemplates,
                                          children=children,
                                          editables=editables,
                                          skip_notes=skip_notes)

    return output

def set_hda_version_from_definition(filename:str,
                                    hda_name:str,
                                    version:str):
    """

    :param filename:
    :param hda_name:
    :param version:
    :return:
    """

    definition_list = hou.hda.definitionsInFile(filename)

    match_definitions = [d for d in definition_list if d.nodeTypeName() == hda_name]

    if len(match_definitions) == 1:
        my_def = match_definitions[0]
        my_def.setVersion(str(version))

def get_hda_version_from_definition(filename,
                                    hda_name)->float:
    """

    :param filename:
    :param hda_name:
    :return:
    """
    definition_list = hou.hda.definitionsInFile(filename)
    match_definitions = [d for d in definition_list if d.nodeTypeName() == hda_name]
    if len(match_definitions) == 1:
        my_def = match_definitions[0]
        return int(my_def.getVersion())


def node_synch_from_recipe_tool(node: list[hou.OpNode],
                                filename: str,
                                recipe_name: str = None):
    """
    Check node attributes and check if it needs to be synched with his recipe
    :param node:
    :param filename:
    :param recipe_name:
    :return:
    """
    for n in node:
        do_synch = n.parm("do_synch").eval()
        if do_synch:
            if not recipe_name:
                recipe_name = n.parm("recipe_name").eval()
                if not recipe_name:
                    raise ValueError("No recipe name specified")
            vers_parm = n.parm("version")
            if not vers_parm:
                raise ValueError("No version specified")
            else:
                tool_version = get_hda_version_from_definition(filename, recipe_name)
                if tool_version > float(vers_parm):
                    applyDecorationRecipe(recipe_name, n)

def find_all_non_node_network_items(node_list:list, children:bool=True):
    # type_list = (hou.IndirectInput,
    #             hou.NetworkBox,
    #             hou.Node,
    #             hou.StickyNote)
    node_list_out = []
    for n in node_list:
        if isinstance(n, hou.NetworkMovableItem) and not isinstance(n, hou.Node):
            node_list_out.append(n)
        else:
            if children:
                for c in n.allItems():
                    if isinstance(c, hou.NetworkMovableItem) and not isinstance(c, hou.Node):
                        node_list_out.append(c)
    return node_list_out

def get_network_movable_item(node_list:list):
    return [n for n in node_list if isinstance(n ,hou.NetworkMovableItem)]


def save_as_decorator_recipe(node_list:list,
                             title:str,
                             namespace:str,
                             definition_filename:str,
                             version:str,
                             central_node:hou.OpNode,
                             nodetype_patterns="",
                             comment="",
                             selected_node = None,
                             **kwargs):


    """
    ARGS :
        title : nice name
        namespace : namespace of the hda
        definition_filename : filename of the Recipe hda
        version : version of the hda
        central_node : node which his at the origin of the decoration
        nodetype_patterns : such as Sop/ropnet


    KWARGS :
            nodes_only = False,
            central_children = False,
            children = True,
            central_editables = False,
            editables = True,
            flags = False,
            central_parms: Union[bool, Sequence[hou.ParmTuple], Sequence[str]] = True,
            parms = True,
            spareparms = True,
            parms_as_brief = True,
            default_parmvalues = False,
            evaluate_parmvalues = False,
            parmtemplates = "spare_only",
            metadata = False,
            verbose = False

    BUG :
    kwargs used in documentation are supposed to be processed in an enum post process
    but they are not effective right now :
        self.target_parms = self.central_parms
        self.target_children = self.central_children
        self.target_editables = self.central_editables
        self.target_name_in_data = ""
    """


    name = f"{nodetype_patterns.lower()}::{namespace}::{title.lower()}"
    label = title.lower()

    if version:
        try :
            version = float(version)
        except ValueError:
            raise ValueError(f"Invalid version: {version}")

    movable_items = find_all_non_node_network_items(node_list)

    # set default options for saving decoration preset
    if not "central_children" in kwargs:
        kwargs["central_children"] = True
    if not "central_editables" in kwargs:
        kwargs["central_editables"] = True

    # bug fix
    if "central_children" in kwargs:
        kwargs["target_children"] = kwargs["central_children"]
    if "central_editables" in kwargs:
        kwargs["target_editables"] = kwargs["central_editables"]
    if "central_parms" in kwargs:
        kwargs["target_parms"] = kwargs["central_parms"]

    hou.data.saveDecorationRecipe(name=name,
                                  label=label,
                                  location=definition_filename,
                                  central_node=central_node,
                                  decorator_items=movable_items,
                                  comment=comment,
                                  selected_node=selected_node,
                                  **kwargs)

    set_hda_version_from_definition(definition_filename, name, version)
