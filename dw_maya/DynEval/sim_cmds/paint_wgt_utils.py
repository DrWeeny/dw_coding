from maya import cmds, mel
from typing import List
from .info_management import dw_get_hierarchy
from ..sim_widget.wgt_combotree import TreeComboBox
from dw_maya.dw_maya_utils import lsTr
from dw_maya.dw_nucleus_utils.dw_core import get_nucx_node, get_pervertex_maps, get_nucx_map_type

from dw_logger import get_logger

logger = get_logger()


def get_maya_sel():
    sel = lsTr(sl=True, dag=True, type="mesh")
    return sel

def nice_name(name:str, ns=False):
    if not ns:
        return name.split("|")[-1].split(":")[-1]
    return name.split("|")[-1]

def set_weights(node: str, weights: List[float], is_deformer: bool = False):
    """Set weights on either nucleus map or deformer

    Args:
        node: Full node path (node.attribute for nucleus, node for deformer)
        weights: List of weight values
        is_deformer: Whether this is a deformer node
    """
    if is_deformer:
        from dw_maya.dw_deformers.dw_core import set_deformer_weights
        set_deformer_weights(node, weights)
    else:
        # Nucleus map case
        node_name, attr = node.split('.')
        from dw_maya.dw_nucleus_utils.dw_core import set_nucx_map_data
        set_nucx_map_data(node_name, attr, weights)

def get_ncloth_mesh(node_list: list):
    result = []
    if isinstance(node_list, str):
        node_list = [node_list]
    for node in node_list:
        hist = cmds.listHistory(node + '.inputMesh', il=1)
        o = [i for i in hist if cmds.nodeType(i) == 'mesh']
        o = [i for i in o if len(i.split('.')) == 1]
        o = cmds.listRelatives(o, p=True, f=True)[0]
        result.append(nice_name(o))
    return result

def get_ncloth_from_mesh(mesh):
    nucx = get_nucx_node(mesh)
    return nucx

def get_nucx_maps_from_mesh(mesh):
    nucx = get_nucx_node(mesh)
    maps = get_pervertex_maps(nucx)

    maps.sort()
    return maps, nucx

def set_data_treecombo(treecombo: TreeComboBox,
                       mesh_selection:str = None):
    cloth_nodes, nrigid_nodes = [], []
    system = dw_get_hierarchy()

    found_selection = False

    for char, solver_nodes in system.items():
        for solver in solver_nodes:
            if "nCloth" in system[char][solver]:
                cloth_nodes = get_ncloth_mesh(system[char][solver]["nCloth"])
            if "nRigid" in system[char][solver]:
                nrigid_nodes = get_ncloth_mesh(system[char][solver]["nRigid"])

            if cloth_nodes or nrigid_nodes:
                try:
                    treecombo.add_nucleus_data(
                        nucleus_name=nice_name(solver, True),
                        cloths=cloth_nodes,
                        rigids=nrigid_nodes
                    )

                    # If we have a mesh to select, try to select it
                    if mesh_selection and isinstance(mesh_selection, str):
                        logger.debug(f"Attempting to select mesh: {mesh_selection}")
                        if treecombo.select_item_by_text(mesh_selection):
                            found_selection = True
                            logger.debug(f"Successfully selected mesh: {mesh_selection}")

                except Exception as e:
                    logger.error(f"Failed to add items in {treecombo}: {e}")

            if mesh_selection and not found_selection:
                logger.warning(f"Could not find mesh {mesh_selection} in the tree combo")
