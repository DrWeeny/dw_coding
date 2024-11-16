import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from dw_maya.dw_maya_utils import Flags, get_type_io


def createForceBS(_source_msh: str, _target_msh: str, **kwargs) -> list:
    """
    Creates a blend shape (BS) between the source and target meshes with a custom naming convention and cleans up the scene.

    Args:
        _source_msh (str): The name of the source mesh that drives the blend shape.
        _target_msh (str): The name of the target mesh that will be deformed by the blend shape.
        **kwargs: Additional blend shape options (e.g., prefix, name, etc.).

    Returns:
        list: Returns the created blend shape node and the name of the intermediate shape.
    """

    # Extract prefix from kwargs (default is empty string)
    _prefix = Flags(kwargs, '', 'prefix')
    if _prefix != '':
        del kwargs['prefix']

    # Naming conventions for the blend shape
    _name_forcebs_sh = f'forceBs_{_prefix}_{_target_msh.replace(":", "_")}'.replace('__', '_') + 'Shape'
    _bs_name = f'bs_{_prefix}_{_target_msh.replace(":", "_")}'.replace('__', '_')

    # Check if a custom name is provided
    if kwargs.get('name'):
        _name_forcebs_sh = f'forceBs_{kwargs["name"]}Shape'
    else:
        kwargs['name'] = _bs_name

    # Create a temporary mesh shape
    bs_msh_sh = cmds.createNode('mesh', n=_name_forcebs_sh)
    bs_msh_tr = cmds.listRelatives(bs_msh_sh, parent=True)[0]

    # Connect the target mesh's output to the temporary mesh's input
    _target_out = get_type_io(_target_msh)
    bs_msh_in = get_type_io(bs_msh_sh, io=0)
    cmds.connectAttr(_target_out, bs_msh_in)
    cmds.delete(bs_msh_tr, ch=True)  # Clean up history on the temporary mesh

    # Create the blend shape
    bs = cmds.blendShape(_source_msh, bs_msh_tr, **kwargs)

    # Connect the blend shape output to the target mesh
    bs_out = get_type_io(bs[0])
    _target_in = get_type_io(_target_msh, io=0)
    cmds.connectAttr(bs_out, _target_in, f=True)

    # Clean up the original temporary connection
    bs_msh_sh_in = get_type_io(bs_msh_sh, io=0)
    cmds.disconnectAttr(bs_out, bs_msh_sh_in)

    # Reparent the temporary mesh shape under the target mesh and delete the transform node
    cmds.parent(bs_msh_sh, _target_msh, s=True, r=True)

    # TODO: Clean way to find the orig shape
    cmds.parent(f'{bs_msh_sh}Orig', _target_msh, s=True, r=True)
    cmds.delete(bs_msh_tr)

    # Mark the temporary mesh shape as intermediate (invisible)
    cmds.setAttr(f'{bs_msh_sh}.io', 1)

    # Return the blend shape node and the name of the intermediate shape
    return [bs[0], _name_forcebs_sh]