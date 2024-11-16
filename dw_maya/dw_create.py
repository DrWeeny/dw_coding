import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from math import pow, sqrt
from itertools import chain
from typing import List, Optional, Tuple
import re
import dw_maya.dw_maya_nodes as dwnn

def create_implicite_sphere(name = None):
    """
    Creates an implicit sphere in Maya using a custom MayaNode class.

    Args:
        name (str, optional): The name of the implicit sphere. Defaults to 'implicitSphere#'.
        **kwargs: Additional keyword arguments to be passed to MayaNode.

    Returns:
        MayaNode: An instance of the MayaNode class representing the implicit sphere.
    """
    if not name:
        name = 'implicitSphere#'
    return dwnn.MayaNode(name, 'implicitSphere')


def createSquareSphere(res=4):
    """
    Creates a cube that is smoothed and shrink-wrapped into a spherical shape.

    Args:
        res (int, optional): Resolution parameter affecting the subdivisions of the resulting sphere. Default is 4.

    Returns:
        str: The name of the resulting cube transformed into a spherical shape.
    """
    # Create the base cube
    cub = cmds.polyCube(n='qSphere#')

    # Calculate subdivisions based on the given resolution
    v = round(sqrt(pow(4, res)))*2

    # Create a temporary sphere for the shrink wrap process
    sph = cmds.polySphere(n='proj_tmp', sa=v, sh=v)
    cmds.polySmooth(cub, dv=4, mth=0, sdt=2, ovb=1, ofb=3, ofc=0, ost=0, ocr=0, bnr=1,
                    c=1, kb=1, ksb=1, khe=0, kt=1, kmb=1, suv=1, peh=0, sl=1,
                    dpe=1, ps=0.1, ro=1, ch=1)
    # Apply shrink wrap deformer using the sphere as the target
    import dw_maya.dw_deformers as dwdef
    shWrp = dwdef.shrinkWrap(cub[0], sph[0], projection=3, reverse=1)

    # Delete the history of the cube and remove the temporary sphere
    cmds.delete(cub, constructionHistory=True)
    cmds.delete(sph)
    return cub[0]


def pointOnPolyConstraint(input_vertex: str,
                          tr: str,
                          name: Optional[str] = None,
                          uv: List[Tuple[int, int]] = None,
                          replace: bool = False):
    """
    Replacement for the Maya pointOnPolyConstraint command, addressing bugs with UV settings.

    Args:
        input_vertex (str): The vertex to constrain. Support Face even if it will select a random vertex
        tr (str): The transform node to constrain the vertex to.
        name (str, optional): Custom name for the constraint.
        replace (bool, optional): Whether to replace an existing constraint.

    Returns:
        str: The name of the created or modified pointOnPolyConstraint node.
    """
    if uv and len(uv) != 2:
        cmds.error("uv input shoud be [u, v] format")
    uv_values = uv or []  # Ensure default is a new list instance

    # if other type of component has been input, change to vertices
    to_vertices = cmds.polyListComponentConversion(input_vertex, tv=True)
    vertices = cmds.ls(to_vertices, fl=True)

    # Handle replace logic
    if replace:
        o = cmds.ls(input_vertex, o=True)
        con = cmds.listConnections(o, d=True, type='pointOnPolyConstraint')
        pos = cmds.pointPosition(input_vertex)
        if con:
            for x, a in enumerate('XYZ'):
                addL = cmds.createNode('addDoubleLinear',
                                       name=f'offset{a}Localisation')
                cmds.setAttr(f'{addL}.input1', -pos[x])
                cmds.connectAttr(f'{con[0]}.constraintTranslate{a}',
                                 f'{addL}.input2')
                cmds.connectAttr(f'{addL}.output',
                                 f'{tr}.translate{a}')
            return con[0]
    else:
        # maya python command doesn't set the uv values for whatever reason
        # the attr name has to be guessed i suppose with the input object and the len
        ptC = cmds.pointOnPolyConstraint(vertices, tr)[0]

        # Guess the UV attribute names based on vertices
        pattern = re.compile('[U-V]\d$')
        attrs = cmds.listAttr(ptC)
        uv_attrs = [f'{ptC}.{a}' for a in attrs if pattern.search(a)]

        # Retrieve and set UV values for each vertex
        if not uv_values:
            from dw_maya.dw_maya_utils import get_uv_from_vtx
            uv_values = chain(*[get_uv_from_vtx(i) for i in vertices])

        for attr, value in zip(uv_attrs, uv_values):
            cmds.setAttr(attr, value)

        # cleaning the default connections going into the locator
        con = [i for i in cmds.listConnections(ptC, p=True) if
               re.search('^(rotate|translate)[X-Z]$', i.split('.')[-1])]
        dest = [i for i in cmds.listConnections(con, p=True)]
        plugs = zip(dest, con)
        for p in plugs:
            cmds.disconnectAttr(*p)
            cmds.setAttr(p[1], 0)

        return ptC
