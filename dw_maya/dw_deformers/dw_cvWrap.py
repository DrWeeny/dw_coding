import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from maya import cmds, mel

from dw_maya.dw_decorators import acceptString, timeIt


@timeIt
def cvWeights2Geo(crv):
    """
    Distribute weights along the control vertices (CVs) of a NURBS curve and apply them to a cvWrap deformer.

    Args:
        crv (str): The name of the curve to process.

    Raises:
        RuntimeError: If no cvWrap node is found for the curve.

    """
    curve_sh = lsTr(crv, ni=True, type='nurbsCurve', p=False)
    cvs_len = [len(cmds.ls(c + '.cv[:]', fl=True)) for c in curve_sh]
    for c, length in zip(curve_sh, cvs_len):
        # Calculate weights based on normalized position along the curve
        weights = [float(x) / (length - 1) for x in range(length)]

        # Find cvWrap nodes and related connections
        cwOut = cmds.listConnections(c, t='cvWrap')
        if not cwOut:
            raise RuntimeError(f"No cvWrap node found for curve {c}")
        cwOut=cwOut[0]

        attr = cmds.listConnections(c + '.create', p=True)[0]
        if attr.startswith(cwOut):
            nb = re.findall(r"\d+", attr)[-1]
            weight_attr = f'weightList[{nb}].weights'

            # Set weights on the input node and reverse weights on the output node
            cmds.setAttr(f'{cwOut}.{weight_attr}[0:{length - 1}]', *weights, size=length)
            cmds.setAttr(f'{cwOut}.{weight_attr}[0:{length - 1}]', *weights[::-1], size=length)

@acceptString('mesh')
def cvWrap2Geo(item, mesh):
    """
    Apply cvWrap deformer to chunks of curves for a given mesh. The function supports the 251 connection limit
    of the cvWrap node by chunking the input curves.

    Args:
        item (list): List of curves or items to wrap.
        mesh (str or list): The target mesh or list of two meshes (outer, inner).

    Returns:
        list: Names of created cvWrap nodes.
    """
    # Check if the mesh argument is valid
    if not isinstance(mesh, list) and not isinstance(mesh, str):
        raise ValueError("Invalid mesh input. Must be a list or a string.")

    # Chunk the curves into manageable groups of 251 (cvWrap limitation)
    crv_chunks = chunks(item, 251)

    # Handle mesh list (assuming only the first mesh is used, clarify based on requirements)
    outer = inner = None
    if isinstance(mesh, list):
        if len(mesh) == 2:
            outer, inner = mesh
        else:
            raise ValueError("Invalid mesh list. Expecting a list of two meshes (outer, inner).")
    else:
        outer = mesh

    output = []

    # Iterate over chunks and apply cvWrap
    for mesh_item in [outer]:  # Only outer is used
        for x, curve_chunk in enumerate(crv_chunks):
            # Apply cvWrap deformer
            cv_wrap = cmds.cvWrap(curve_chunk, mesh_item, radius=.1)

            # Get the connected mesh (assuming mesh is second in the list)
            connected_mesh = cmds.listConnections(cv_wrap, t='mesh')[1]
            mesh_name = connected_mesh.split('|')[-1].split(':')[-1]

            # Rename the cvWrap node for clarity
            new_name = cmds.rename(cv_wrap, f'{mesh_name}_{cv_wrap}_{x}')
            output.append(new_name)

    return output