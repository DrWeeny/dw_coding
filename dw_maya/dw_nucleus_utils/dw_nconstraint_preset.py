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


@acceptString('nconstraint')
def getAllConstraintsPresets(nconstraint=None, namespace=':'):
    """
    Retrieves attribute presets for all dynamicConstraint nodes in a given namespace.

    Args:
        nconstraint (list or None): List of dynamicConstraint nodes to get presets for.
                                    If None, it finds all dynamicConstraint nodes in the
                                    specified namespace.
        namespace (str): The namespace to filter constraints by. Defaults to the root namespace ':'.

    Returns:
        dict: A dictionary containing all attribute presets for the specified dynamicConstraint nodes.
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

    # Get presets for each constraint
    presets = {}
    for nc_name in nconstraint:
        nc = nConstraint(nc_name)
        if nc.nodeType == 'dynamicConstraint':
            presets = dwu.merge_two_dicts(presets, nc.attrPreset())

    return presets


def createAllConstraintPresets(dataDic, targ_ns=':'):
    """
    Creates dynamicConstraint nodes from a preset dictionary or JSON file.

    Args:
        dataDic (dict or str): Either a dictionary of constraint presets or a path to a JSON file
                               containing the preset data.
        targ_ns (str): The target namespace where the dynamicConstraint nodes will be created.
                       Defaults to the root namespace ':'.

    Returns:
        list: A list of created dynamicConstraint node names.
    """
    if isinstance(dataDic, str):  # Check if it's a file path
        if pyu.path.isfile(dataDic):
            dataDic = dwpreset.load_json(dataDic)
        else:
            raise ValueError('Invalid JSON file path provided.')

    output = []
    for key, value in dataDic.items():
        if key.endswith('_nodeType') and value == 'dynamicConstraint':
            node_name = key.rsplit('_', 1)[0]
            namespace = targ_ns if targ_ns != ':' else ''
            constraint_name = f"{namespace}:{node_name}" if namespace else node_name

            # Extract the specific preset for this constraint node
            node_preset = {
                node_name: dataDic[node_name],
                f'{node_name}_nodeType': dataDic[f'{node_name}_nodeType']
            }

            # Use the inherited MayaNode functionality to create and load the node
            # Pass the preset dict to __init__ which will trigger loadNode() automatically
            constraint = nConstraint(constraint_name, preset=node_preset, blendValue=1.0)
            output.append(constraint.tr)

    return output


def saveNConstraintRig(namespace=':', path=str, file=str, nconstraint=None):
    """
    Saves dynamicConstraint node presets into a JSON file.

    Args:
        namespace (str): The namespace to filter constraints by. Defaults to the root namespace ':'.
        path (str): The directory path where the JSON file will be saved.
        file (str): The name of the JSON file (without extension).
        nconstraint (list or None): A list of dynamicConstraint nodes to save. If None, it collects
                                    all constraints from the specified namespace.

    Returns:
        str: The full path to the saved JSON file.

    Raises:
        IOError: If the specified path does not exist or is not writable.
    """
    # Get constraints based on namespace if not provided
    if not nconstraint:
        if namespace == ':':
            nconstraint = [i for i in cmds.ls(type='dynamicConstraint') if ':' not in i]
        else:
            nconstraint = None

    # Get presets for the specified constraints
    constraints_presets = getAllConstraintsPresets(nconstraint=nconstraint, namespace=namespace)

    # Ensure valid file path and save JSON
    fullpath = os.path.join(path, f"{file}.json" if '.' not in file else file)
    if os.path.exists(path):
        dwpreset.save_json(fullpath, constraints_presets)
        print(f'nConstraint preset saved to {fullpath}')
        return fullpath
    else:
        raise IOError(f"Cannot save to the directory: {path}")
