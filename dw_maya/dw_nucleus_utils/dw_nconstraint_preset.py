import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from .dw_nconstraint_class import nConstraint
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_presets_io as dwpreset
import dw_maya.dw_presets_io.preset_components as pcomp


@acceptString('nconstraint')
def getAllConstraintsPresets(nconstraint=None, namespace=':'):
    """
    Capture all dynamicConstraint nodes in a namespace as dw_preset entries.

    Uses the component pipeline (``nConstraint.createPreset`` ->
    AttributeComponent + NConstraintNetworkComponent), so each entry is the
    v2 ``{identity: {nodeType, attributes, network}}`` shape - ready to drop
    under an envelope ``nodes`` key.

    Args:
        nconstraint (list or None): dynamicConstraint nodes to capture. If None,
                                    every constraint in the namespace is found.
        namespace (str): Namespace to filter constraints by (``:`` for root).

    Returns:
        dict: ``{identity: body}`` entries for the matched constraints.
    """
    def filter_constraints(constraints, namespace):
        filtered_constraints = []
        for const in constraints:
            nc = nConstraint(const)
            if nc.nucleus:
                if namespace == ':' and ':' not in nc.nucleus:
                    filtered_constraints.append(const)
                elif namespace != ':' and nc.nucleus.startswith(namespace + ':'):
                    filtered_constraints.append(const)
        return filtered_constraints

    # If no constraints are provided, find all in the specified namespace
    if not nconstraint or nconstraint == [None]:
        all_constraints = cmds.ls(type='dynamicConstraint')
        nconstraint = filter_constraints(all_constraints, namespace)

    # Capture each constraint as a v2 preset entry
    nodes = {}
    for nc_name in nconstraint:
        nc = nConstraint(nc_name)
        if nc.nodeType == 'dynamicConstraint':
            nodes.update(nc.createPreset())

    return nodes


def createAllConstraintPresets(dataDic, targ_ns=':'):
    """
    Rebuild dynamicConstraint nodes from a dw_preset envelope (dict or file).

    Dispatches each entry through ``node_from_preset`` -> the registry resolves
    ``dynamicConstraint`` to :class:`nConstraint`, whose components recreate the
    node, its attributes and its network. Requires the cloth/hair/nucleus
    targets to already exist in the scene.

    Args:
        dataDic (dict or str): A dw_preset envelope (or path to its JSON file).
        targ_ns (str): Namespace the rebuilt constraints land in (``:`` = root).

    Returns:
        list: Transform names of the created dynamicConstraint nodes.
    """
    if isinstance(dataDic, str):  # Check if it's a file path
        if os.path.isfile(dataDic):
            dataDic = dwpreset.load_json(dataDic)
        else:
            raise ValueError('Invalid JSON file path provided.')

    nodes = dataDic.get('nodes', dataDic) if isinstance(dataDic, dict) else {}
    ctx = pcomp.PresetContext(target_ns=targ_ns, create=True)

    output = []
    for identity, body in nodes.items():
        if not isinstance(body, dict) or body.get('nodeType') != 'dynamicConstraint':
            continue
        node = pcomp.node_from_preset(identity, body, ctx)
        output.append(node.tr)

    return output


def saveNConstraintRig(namespace=':', path=str, file=str, nconstraint=None):
    """
    Save dynamicConstraint presets as a versioned dw_preset envelope.

    Args:
        namespace (str): Namespace to filter constraints by (``:`` for root).
        path (str): Directory the JSON file is written to.
        file (str): JSON file name (extension optional).
        nconstraint (list or None): Constraints to save; None collects all in the
                                    namespace.

    Returns:
        str: Full path to the saved JSON file.

    Raises:
        IOError: If the directory does not exist or is not writable.
    """
    # Get constraints based on namespace if not provided
    if not nconstraint:
        if namespace == ':':
            nconstraint = [i for i in cmds.ls(type='dynamicConstraint') if ':' not in i]
        else:
            nconstraint = None

    # Capture entries and wrap them in a dw_preset envelope
    nodes = getAllConstraintsPresets(nconstraint=nconstraint, namespace=namespace)
    envelope = {"format": pcomp.PRESET_FORMAT, "version": pcomp.PRESET_VERSION, "nodes": nodes}

    # Ensure valid file path and save JSON
    fullpath = os.path.join(path, f"{file}.json" if '.' not in file else file)
    if os.path.exists(path):
        dwpreset.save_json(fullpath, envelope)
        print(f'nConstraint preset saved to {fullpath}')
        return fullpath
    else:
        raise IOError(f"Cannot save to the directory: {path}")
