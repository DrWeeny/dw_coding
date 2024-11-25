from maya import cmds, mel
from .info_management import dw_get_hierarchy
from ..sim_widget.wgt_combotree import TreeComboBox
from dw_maya.dw_maya_utils import lsTr

from dw_logger import get_logger

logger = get_logger()

def get_maya_sel():
    sel = lsTr(sl=True, dag=True, type="mesh")
    return sel

def nice_name(name:str, ns=False):
    if not ns:
        return name.split("|")[-1].split(":")[-1]
    return name.split("|")[-1]

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

def set_data_treecombo(treecombo: TreeComboBox,
                       mesh_selection:str = None):
    cloth_nodes, nrigid_nodes = [], []
    system = dw_get_hierarchy()

    for char, solver_nodes in system.items():
        for solver in solver_nodes:
            if "nCloth" in system[char][solver]:
                cloth_nodes = get_ncloth_mesh(system[char][solver]["nCloth"])
            if "nRigid" in system[char][solver]:
                nrigid_nodes = get_ncloth_mesh(system[char][solver]["nRigid"])

            if cloth_nodes or nrigid_nodes:
                try :
                    treecombo.add_nucleus_data(nucleus_name=nice_name(solver, True),
                                               cloths=cloth_nodes,
                                               rigids=nrigid_nodes)
                    if mesh_selection and isinstance(mesh_selection, str):
                        print("mesh:"+mesh_selection)
                        treecombo.select_item_by_text(mesh_selection)
                except:
                    logger.error(f"Failed to Add items in {treecombo}")
