import maya.cmds as cmds
from collections import defaultdict
from operator import itemgetter

class ClothSys:
    """
    Represents a Nucleus system in Maya and provides organized access to related nodes:
    - Nucleus node
    - Cloth nodes
    - Hair system nodes
    - Rigid nodes
    - Constraint nodes

    This is a non-UI representation intended to support simulation workflows.

    TODO: Link constraint to associated cloth
    """


    def __init__(self, nucleus_node):
        self.nucleus = nucleus_node
        self._name = None
        self._ncloth = None
        self._nhair = None
        self._nrigid = None
        self._nconstraint = None

    @property
    def name(self):
        """Retrieves the name of the associated asset or node."""
        if not self._name:
            self._name = self._determine_name()
        return self._name

    def _determine_name(self):
        """Determines the asset or node name based on hierarchy or prefix."""
        try:
            parent = cmds.listRelatives(self.nucleus, parent=True) or []
            if parent:
                for _ in range(3):
                    parent = cmds.listRelatives(parent[0], parent=True) or []
                    if not parent:
                        break
                    if cmds.nodeType(parent[0]) == 'RAsset':
                        return parent[0].split(':')[0]
                return parent[0].split(':')[-1]  # Fallback if no asset node
            return self.nucleus.split(':')[0]
        except Exception:
            return "Unknown"

    @property
    def ncloth(self):
        """Lazily loads and returns connected nCloth nodes."""
        if self._ncloth is None:
            self._ncloth = self._get_connected_shapes("nCloth")
        return self._ncloth

    @property
    def nhair(self):
        """Lazily loads and returns connected hairSystem nodes."""
        if self._nhair is None:
            self._nhair = self._get_connected_shapes("hairSystem")
        return self._nhair

    @property
    def nrigid(self):
        """Lazily loads and returns connected nRigid nodes."""
        if self._nrigid is None:
            self._nrigid = self._get_connected_shapes("nRigid")
        return self._nrigid

    @property
    def nconstraint(self):
        """Lazily loads and returns connected dynamicConstraint nodes."""
        if self._nconstraint is None:
            self._nconstraint = self._get_connected_shapes("dynamicConstraint")
        return self._nconstraint

    def _get_connected_shapes(self, node_type):
        """Returns unique shape nodes connected to the nucleus of a specified type."""
        try:
            connections = cmds.listConnections(self.nucleus, type=node_type) or []
            shapes = list(set(cmds.listRelatives(connections, shapes=True, fullPath=True) or []))
            return shapes
        except Exception:
            return []

    @property
    def system(self):
        """Provides a dictionary representation of the Nucleus system."""
        return {
            "nucleus": self.nucleus,
            "nCloth": self.ncloth,
            "nRigid": self.nrigid,
            "nHair": self.nhair,
            "nConstraint": self.nconstraint
        }

    def to_dict(self):
        """Returns a dictionary format of the system, which can be used for JSON export."""
        return self.system

    def __repr__(self):
        return f"ClothSys(nucleus='{self.nucleus}', name='{self.name}')"


def dw_get_hierarchy():
    """
    Builds a hierarchical dictionary of Nucleus systems in the scene.

    Output Structure:
        {
            'ObjectName': {
                'nucleusNode1': {
                    'nCloth': [<clothShapeName>],
                    'nRigid': [<dynConstraintShapeName>],
                    'nConstraint': [<nRigidShapeName>]
                },
                ...
            },
            ...
        }
    """

    # Initialize an empty dictionary to store the output hierarchy
    output = defaultdict(lambda: defaultdict(list))

    # Get all Nucleus nodes in the scene
    scene_nucleus = cmds.ls(type='nucleus')

    for nucleus_node in scene_nucleus:
        # Create a ClothSys instance to organize connections for this nucleus node
        nucleus_system = ClothSys(nucleus_node)

        # Check if the top-level dictionary already has the object name
        object_name = nucleus_system.object_name
        if object_name not in output:
            output[object_name] = defaultdict(list)

        # Populate the nucleus details for each type of system component
        for node_type, connected_nodes in nucleus_system.system.items():
            output[object_name][nucleus_node][node_type] = connected_nodes

    return output


def sort_list_by_outliner(nodes):
    """
    Sorts a list of Maya nodes according to their order in the Maya Outliner.

    Args:
        nodes (list): List of Maya node names to sort.

    Returns:
        list: The input list sorted according to the order in the Maya Outliner.
    """
    # Get all DAG nodes in the current Maya scene with their order
    maya_nodes = cmds.ls(dag=True)
    node_indices = {node: idx for idx, node in enumerate(maya_nodes)}

    # Filter nodes to those found in the DAG and obtain their outliner order
    outliner_list = [node for node, _ in sorted(
        ((node, node_indices[node]) for node in nodes if node in node_indices),
        key=itemgetter(1)
    )]

    return outliner_list

def get_cloth_mesh_sh(ncloth_shape: str) -> list:
    """
    Finds and returns the mesh shape node connected to the outputMesh attribute
    of a given nCloth shape node.

    Args:
        ncloth_shape (str): The name of the nCloth shape node.

    Returns:
        list: A list containing the names of connected mesh shape nodes, or an empty list if none found.
    """
    if not cmds.objExists(ncloth_shape):
        cmds.warning(f"Node '{ncloth_shape}' does not exist.")
        return []

    if cmds.nodeType(ncloth_shape) != 'nCloth':
        cmds.warning(f"Node '{ncloth_shape}' is not of type 'nCloth'.")
        return []

    # Retrieve mesh connections from the outputMesh attribute of the nCloth node
    connected_meshes = cmds.listConnections(
        f"{ncloth_shape}.outputMesh", s=True, d=False, sh=True, type='mesh'
    )

    return connected_meshes if connected_meshes else []


def get_model_from_cloth_node(cloth_sh: str) -> str:
    """
    Retrieves the long name of the model connected to the input mesh of a specified cloth node.

    Args:
        cloth_sh (str): Name of the cloth shape node.

    Returns:
        str: Long name of the connected model node, or None if not found.
    """
    if not cmds.objExists(cloth_sh):
        cmds.warning(f"Node '{cloth_sh}' does not exist.")
        return None

    if cmds.nodeType(cloth_sh) != 'nCloth':
        cmds.warning(f"Node '{cloth_sh}' is not of type 'nCloth'.")
        return None

    # Retrieve connections to the inMesh attribute of the cloth node
    connections = cmds.listConnections(f"{cloth_sh}.inMesh", sh=True, type='nCloth')

    # Return None if no connections are found
    if not connections:
        return None

    # Filter out any connections that have attribute names (connections directly to the node only)
    model_nodes = [node for node in connections if len(node.split('.')) == 1]

    # Return the long name of the first valid model node found
    return cmds.ls(model_nodes[0], long=True)[0] if model_nodes else None

def get_nucleus_sh_from_sel() -> str:
    """Gets the first nucleus-related node from the current selection.

    Returns:
        str: Name of the nucleus-related node if found; otherwise, None.
    """
    try:
        sel = cmds.ls(sl=True)[0]
    except IndexError:
        cmds.warning("No selection made.")
        return None

    node_type = cmds.nodeType(sel)

    if node_type == 'transform':
        # Check for nCloth or hairSystem nodes under the transform
        ncloth_nodes = cmds.ls(sel, dag=True, type=['nCloth', 'hairSystem'], long=True)
        mesh_nodes = cmds.ls(sel, dag=True, type='mesh', long=True, ni=True)

        if ncloth_nodes:
            return ncloth_nodes[0]

        if mesh_nodes:
            # Attempt to retrieve the cloth node associated with the mesh
            cloth_node = get_model_from_cloth_node(mesh_nodes[0])
            return cloth_node if cloth_node else None

        return None

    # Directly selected nCloth or hairSystem node
    if node_type in ['nCloth', 'hairSystem']:
        return sel

    # Directly selected nucleus node
    if node_type == 'nucleus':
        return sel

    cmds.warning("Selection is not connected to a nucleus, nCloth, or hairSystem node.")
    return None
