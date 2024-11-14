"""This Module should provide methods for feathers, guide system,
nhair and yeti setup
Example:
    Examples can be given using either the ``Example`` or ``Examples``
    sections. Sections support any reStructuredText formatting, including
    literal blocks::
        $ python example_google.py
Section breaks are created by resuming unindented text. Section breaks
are also implicitly created anytime a new section starts.
Attributes:
    module_level_variable1 (int): Module level variables may be documented in
        either the ``Attributes`` section of the module docstring, or in an
        inline docstring immediately following the variable.
        Either form is acceptable, but the two should not be mixed. Choose
        one convention to document module level variables and be consistent
        with it.
Todo:
    * For module TODOs
    * You have to also use ``sphinx.ext.todo`` extension
.. _Google Python Style Guide:
   http://google.github.io/styleguide/pyguide.html
"""
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import maya.mel as mel
from collections import defaultdict
import re

from dw_maya.dw_decorators import acceptString


def get_root_tip(sel: list, mode=1):
    """
    Retrieves either the root or tip control vertex (CV) of the specified NURBS curve(s).

    This function selects the first or last CV of each curve in `sel` based on the specified mode,
    allowing easy identification of either endpoint.

    Args:
        sel (list): List of curve objects to process. Only NURBS curves are considered.
        mode (int): Selection mode. If `1`, retrieves the tip (last CV); if `0`, retrieves the root (first CV).

    Returns:
        list: A list of strings, each representing a CV in the format "curveShape.cv[index]".

    Raises:
        ValueError: If `sel` contains objects that are not NURBS curves.

    Example:
        >>> get_root_tip(["curve1", "curve2"], mode=1)
        ['curve1.cv[3]', 'curve2.cv[5]']
    """
    # Ensure we are only working with NURBS curves
    sel = cmds.ls(sel, dag=True, type='nurbsCurve')
    output = []

    for s in sel:
        cvs = cmds.ls(s + '.cv[*]', flatten=True)  # Get all CVs of the curve

        if not cvs:
            cmds.warning(f"No CVs found for curve: {s}")
            continue

        # Pick the tip (last) or root (first) CV depending on the mode
        if mode:
            # Mode 1: Tip (last CV)
            index = len(cvs) - 1
        else:
            # Mode 0: Root (first CV)
            index = 0

        output.append('{}.cv[{}]'.format(s, index))

    return output


@acceptString('sel')
def set_pivot(sel, method=(1, 12), **kwargs):
    """
    Sets the pivot point for the selected objects based on the specified method.

    This function allows setting the pivot based on either the bounding box center or the highest vertex position.
    A query mode can also be used to list available methods.

    Args:
        sel (list): The list of selected objects for which to adjust the pivot.
        method (tuple): A tuple with (method_type, method_value).
                        method_type: `0` for bounding box center, `1` for highest vertex position.
                        method_value: Further specification depending on method_type.
        **kwargs: Additional keyword arguments. If 'query' is set to True, lists available methods.

    Returns:
        None

    Raises:
        ValueError: If an invalid method is specified or if `sel` is empty.

    Example:
        >>> set_pivot(["object1", "object2"], method=(1, 12))
    """
    methDic = {0: 'bbox', 1: 'pos'}

    # Query mode to show available methods
    q = kwargs.get('query', False)
    if q:
        if isinstance(method, bool):
            # Display available methods
            methods = ['{}: {}'.format(k, v) for k, v in methDic.items()]
            print('Methods available:\n    {}'.format('\n    '.join(methods)))
            return methDic
        else:
            method_name = methDic.get(method[0], 'Unknown method')
            print('Selected method:', method_name)
            return method_name

    for obj in sel:
        # Bounding box method
        if method[0] == 0:
            bb = cmds.xform(obj, q=True, bb=True, ws=True)
            # Calculate center of bounding box (average of min and max points)
            center = [(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2]
            pos = center

        # Vertex position method
        elif method[0] == 1:
            vertices = cmds.ls(obj + '.vtx[*]', fl=True)
            if not vertices:
                cmds.warning(f"No vertices found for {obj}")
                continue

            # Fetch the world space positions of the vertices
            pos = cmds.xform(vertices, q=True, t=True, ws=True)
            vertex_count = len(pos) // 3

            # Find the vertex with the highest Y position (as an example)
            index, max_y = max(enumerate(pos[1::3]), key=lambda x: x[1])
            p = index * 3
            pos = pos[p:p + 3]

        else:
            cmds.warning(f"Invalid method specified for {obj}")
            continue

        # Set the rotate and scale pivot to the calculated position
        cmds.xform(obj, ws=True, rotatePivot=pos)
        cmds.xform(obj, ws=True, scalePivot=pos)


def pgy_get_type(node: str) -> str:
    """
    Retrieves the type of a specified Yeti node.

    This function checks if the node exists and is of type 'pgYetiMaya'. If these conditions are met,
    it returns the type parameter value using the pgYetiGraph command.

    Args:
        node (str): Name of the Yeti node.

    Returns:
        str: Type of the Yeti node.

    Raises:
        ValueError: If the specified node does not exist.
        TypeError: If the node is not a valid Yeti node.

    Example:
        >>> pgy_get_type("yetiNode1")
        "YetiNodeType"
    """
    if not cmds.objExists(node):
        raise ValueError(f"The node '{node}' does not exist.")
    if cmds.nodeType(node) != 'pgYetiMaya':
        raise TypeError(f"The node '{node}' is not a valid Yeti node.")

    return cmds.pgYetiGraph(node=node, param='type', getParamValue=True)


def pgy_get_param(node: str, param: str) -> any:
    """
    Retrieves the value of a specified parameter for a Yeti node.

    Args:
        node (str): Name of the Yeti node.
        param (str): Name of the parameter to retrieve.

    Returns:
        any: Value of the specified parameter for the Yeti node.

    Raises:
        ValueError: If the node does not exist.
        TypeError: If the node is not a Yeti node or if the parameter is invalid.

    Example:
        >>> pgy_get_param("yetiNode1", "geometry")
        "/path/to/geometry"
    """
    if not cmds.objExists(node):
        raise ValueError(f"The node '{node}' does not exist.")
    if cmds.nodeType(node) != 'pgYetiMaya':
        raise TypeError(f"The node '{node}' is not a valid Yeti node.")

    return cmds.pgYetiGraph(node=node, param=param, getParamValue=True)


def yeti_description() -> dict:
    """
    Gathers detailed information about all Yeti nodes in the scene.

    This function retrieves data for each Yeti node, including geometry, groom data, and guide sets.
    It forces Yeti node evaluation as needed to ensure correct data retrieval.

    Returns:
        dict: A dictionary where each key is a Yeti node identifier (e.g., "yetiNode_fgeo") and each
              value is a list of geometries, groom data, or guide sets associated with that node.

    Example:
        >>> yeti_description()
        {
            "yetiNode1_fgeo": ["/path/to/geometry1", "/path/to/geometry2"],
            "yetiNode1_groom": ["groomNode1", "groomNode2"],
            "yetiNode1_guides": ["guideSet1"]
        }
    """
    yeti_data = {}
    yeti_nodes = cmds.ls(type='pgYetiMaya')

    for yeti_node in yeti_nodes:
        # Force the Yeti node evaluation (required for correct parameter reading)
        parent = cmds.listRelatives(yeti_node, p=True)
        if parent:
            cmds.select(parent, r=True)
            mel.eval(f'pgYetiForceUpdate("{yeti_node}");')
            cmds.refresh()

        # Get all import nodes and filter them by type
        import_nodes = cmds.pgYetiGraph(yeti_node, listNodes=True, type="import")

        # Find geometry (fgeo) and groom data
        geometry_nodes = [pgy_get_param(node, "geometry") for node in import_nodes if pgy_get_type(node) == 0]
        groom_nodes = [pgy_get_param(node, "geometry") for node in import_nodes if pgy_get_type(node) == 1]

        # Get guide sets
        guide_sets = cmds.listConnections(f'{yeti_node}.guideSets', type='objectSet')

        # Store results in the dictionary
        yeti_data[f'{yeti_node}_fgeo'] = geometry_nodes
        yeti_data[f'{yeti_node}_groom'] = groom_nodes
        yeti_data[f'{yeti_node}_guides'] = guide_sets or []

    return yeti_data


def yeti_guide(topGrp: str, patternReplace: dict) -> dict:
    """
    Gather guide system information related to a Yeti node and organize it into a dictionary.

    Example:
        description = yeti_guide('C_guides_GRP', {'_guides_GRP': '_PYGShape'})

    Args:
        topGrp (str): The top group of the guide system.
        patternReplace (dict): A dictionary where keys are patterns in strings to be replaced and
                               values are the new strings to replace them with.

    Returns:
        dict: A dictionary containing guide system information, such as curve data, spans, and
              Yeti-related info (fgeo, emitter, guideSets, etc.).
    """

    # Gather Yeti information using the yeti_description function
    yeti_info = yeti_description()

    # Initialize an empty dictionary to store guide data
    guides_dic = defaultdict(dict)

    # Find the guide group in the scene
    guides_grp = cmds.ls(topGrp)

    if guides_grp:
        guide_groups = cmds.listRelatives(guides_grp, children=True)

        # Remove the 'guideDummy' if it exists in the guide groups
        if 'guideDummy' in guide_groups:
            guide_groups.remove('guideDummy')

        # Process each guide group and gather its information
        for guide in guide_groups:
            key_name = '_'.join(guide.split('_')[1:-2])

            # Retrieve curve shapes and transforms for the guide
            guide_curves_sh = cmds.ls(guide, dag=True, type='nurbsCurve')
            guide_curves_tr = cmds.listRelatives(guide_curves_sh, parent=True)

            # Count the number of CVs and spans
            cvs_count = len(cmds.ls(f'{guide_curves_sh[0]}.cv[:]', flatten=True))
            spans = cvs_count - 2

            # Prepare placeholders for Yeti data (fgeo, emitter, etc.)
            fgeos = []
            emitter = None
            graph = None
            guides = None

            # Match the guide with Yeti groom and geometry information
            for key, value in yeti_info.items():
                if key.endswith('_groom'):
                    groom_name = guide[:]

                    # Apply pattern replacements to find the matching groom
                    for pattern, replacement in patternReplace.items():
                        groom_name = groom_name.replace(pattern, replacement)

                    if groom_name in yeti_info[key]:
                        graph = key.replace('_groom', '')
                        geos_key = key.replace('_groom', '_fgeo')
                        guides_key = key.replace('_groom', '_guides')

                        guides = yeti_info[guides_key]
                        emitter = yeti_info[geos_key][0]
                        fgeos = yeti_info[geos_key][1:]
                        break

            # Store the guide information in the dictionary
            guides_dic[key_name] = {
                "curves": guide_curves_tr,
                "count": len(guide_curves_tr),
                "cvs": cvs_count,
                "spans": spans,
                "fgeo": fgeos,
                "emitter": emitter,
                "guideSets": guides,
                "graph": graph
            }

    return guides_dic


def recursive_name(name: str) -> str:
    """
    Provide a formatted name with an iteration number, ensuring the name is unique in Maya.

    Args:
        name (str): A string with '{}' placeholder where the iteration number will be placed.
                    Example: 'object_{}' will become 'object_1', 'object_2', etc.

    Returns:
        str: A unique name with an incremented number inserted into the placeholder.
    """
    # Regular expression to check for the '{}' placeholder
    pattern = r'\{\}'

    # Ensure the placeholder '{}' exists in the provided name
    if not re.search(pattern, name):
        raise ValueError("Provided name must include '{}' as a placeholder for the iteration number.")

    # Start from 1 and increment until a unique name is found
    iteration = 1
    while cmds.objExists(name.format(iteration)):
        iteration += 1
        if iteration > 10000:
            raise RuntimeError("Exceeded maximum iterations. Could not find a unique name.")


def mag(p1, p2):
    """
    Calculate the Euclidean distance between two 3D points p1 and p2.

    Args:
        p1 (list or tuple): The first point as [x, y, z].
        p2 (list or tuple): The second point as [x, y, z].

    Returns:
        float: The Euclidean distance between p1 and p2.
    """
    if len(p1) != 3 or len(p2) != 3:
        raise ValueError("Both points must have exactly 3 coordinates (x, y, z).")

    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2 + (p1[2] - p2[2]) ** 2) ** 0.5


def get_centroid(sel):
    """
    Calculate the centroid (average position) of selected vertices.

    Args:
        sel (list): A list of selected vertices or components.

    Returns:
        tuple: The centroid (x, y, z) of the selected vertices.
    """
    if not sel:
        raise ValueError("Selection is empty. Please provide a valid selection.")

    # Get the object and convert selection to vertices
    obj = cmds.ls(sel, o=True)
    sel = cmds.polyListComponentConversion(sel, tv=True)
    sel = cmds.ls(sel, flatten=True)

    if len(sel) == 0:
        raise ValueError("No vertices found in selection.")

    # Collect positions of vertices
    if len(obj) > 1:
        pos = []
        for s in sel:
            p = cmds.xform(s, q=1, t=1, ws=1)
            pos.extend(p)
    else:
        pos = cmds.xform(sel, q=1, t=1, ws=1)

    nb = len(sel)
    # Compute the centroid (average position)
    myCenter = (sum(pos[0::3]) / nb, sum(pos[1::3]) / nb, sum(pos[2::3]) / nb)

    return myCenter


def grow_vertex_selection():
    """
    Grows the vertex selection in Maya by including the previous and next vertices
    in the current selection for both individual and ranged selections.
    """
    sel = cmds.ls(selection=True, flatten=True)
    new_sel = []

    for item in sel:
        # Look for indices within brackets e.g. .cv[1:3] or .vtx[4]
        indices = re.search(r"\[\d[\d:]*\]", item)
        if indices:
            result = indices.group(0)
            s, e = None, None

            # Handle ranges like [1:5]
            if ":" in result:
                s = re.search(r"(?<=\[)\d+", result).group()
                e = re.search(r"(?<=:)\d+(?=\])", result).group()
                s = max(int(s) - 1, 0)  # Ensure the start index doesn't go below 0
                e = int(e) + 1  # Extend the end index by 1
            else:
                # Handle individual indices like [4]
                i = re.search(r"(?<=\[)\d+(?=\])", result).group()
                i = int(i)
                s = max(i - 1, 0)
                e = i + 1

            # Build the new selection range
            new_index_range = f"[{s}:{e}]"
            # Replace the original selection with the new expanded range
            new_sel.append(re.sub(r"\[\d[\d:]*\]", new_index_range, item))

    # Apply the new selection
    if new_sel:
        cmds.select(new_sel, replace=True)


def list_cv_index(curves=list, index=0):
    """
    Retrieves the specified CVs from the given list of NURBS curves.

    Args:
        curves (list): List of curve transforms, groups, or curve shapes.
        index (int): The CV index to retrieve. Use 0 for the root, -1 for the tip, or a specific CV index.

    Returns:
        list: A list of CVs at the specified index from each curve.
    """
    crvs_sh = cmds.ls(curves, dag=True, type='nurbsCurve', ni=True)
    cv_index = []

    for c in crvs_sh:
        # Get the total number of CVs in the curve
        num_cvs = cmds.getAttr(f"{c}.spans") + cmds.getAttr(f"{c}.degree")

        # Handle negative indices for reverse indexing (e.g., tip with -1)
        if index < 0:
            index = num_cvs + index

        # Ensure index is within valid range
        if 0 <= index < num_cvs:
            cv_index.append(f"{c}.cv[{index}]")
        else:
            cmds.warning(f"Invalid index {index} for curve {c} with {num_cvs} CVs.")

    return cv_index


def sel_curves_by_component(sel, curves, threshold=0.1):
    """
    Finds curves based on the proximity of selected mesh components to the curve roots (cv[0]).

    Args:
        sel (list): List of selected mesh components.
        curves (list): List of NURBS curves or curve groups.
        threshold (float): Distance threshold to consider a curve "close" to a mesh vertex.

    Returns:
        list: Curves whose roots are within the threshold distance of the selected components.
    """
    if not sel or not curves:
        cmds.warning("No selection or curves provided.")
        return []

    # Convert selected components to vertices and get their positions
    sel_vtx = cmds.polyListComponentConversion(sel, tv=True)
    sel_vtx_fl = cmds.ls(sel_vtx, fl=True)
    sel_pos = [cmds.pointPosition(p) for p in sel_vtx_fl]

    # Get root CVs (cv[0]) of the provided curves
    crv_roots = list_cv_index(curves, 0)

    # Initialize a set to avoid duplicates
    result = set()

    # Calculate distance between each vertex and curve root, compare to threshold
    for vertex_pos in sel_pos:
        for root_cv in crv_roots:
            root_pos = cmds.pointPosition(root_cv)
            if mag(vertex_pos, root_pos) < threshold:
                result.add(root_cv.split('.')[0])  # Add curve transform node

    return list(result)


def create_single_crv_by_vtx(sel_component, curves, threshold=0.1):
    """
    Select the single closest curve to each mesh component based on vertex proximity.

    Args:
        sel_component (list): Mesh component to find the closest curve to.
        curves (list): List of NURBS curves to compare.
        threshold (float): Maximum distance to consider a curve as "close" to the component.

    Returns:
        list: Closest curve transforms to the mesh component.
    """
    if not sel_component or not curves:
        cmds.warning("No selection or curves provided.")
        return []

    # Get root CVs (cv[0]) of the provided curves
    crv_roots = list_cv_index(curves, 0)

    # Convert the selected component to faces
    sel_faces = cmds.polyListComponentConversion(sel_component, tf=True)
    sel_faces_fl = cmds.ls(sel_faces, fl=True)

    result = []
    for face in sel_faces_fl:
        # Get centroid of the face component
        face_centroid = get_centroid(face)

        # Find closest curve within threshold
        candidates = []
        for root in crv_roots:
            root_pos = cmds.pointPosition(root)
            distance = mag(face_centroid, root_pos)
            if distance < threshold:
                candidates.append((root, distance))

        # If there are any candidates, pick the closest one
        if candidates:
            closest_curve = min(candidates, key=lambda x: x[1])[0]
            result.append(closest_curve.split('.')[0])  # Add the curve transform

    # Return only unique curve transforms
    return list(set(result))


def group_curves_by_proximity(threshold=0.1):
    """
    Groups curve guides based on their proximity to the selected mesh components.

    Select mesh components and pick a group of curves as the last selection.
    The function will create a group with all the curves detected and a subgroup
    with one single curve per vertex.

    Args:
        threshold (float): The distance threshold within which curves are grouped.

    Returns:
        None
    """
    sel = cmds.ls(sl=True, fl=True)
    component = sel[:-1]
    curve_grp = sel[-1]
    crv = sel_curves_by_component(component, curve_grp, threshold)
    name = '{}_subguides_{{:03d}}_grp'.format(curve_grp.split('_')[1])
    new_name = recursive_name(name)
    grp = cmds.group(crv, n=new_name)
    single = create_single_crv_by_vtx(component, grp, threshold)
    grp = cmds.group([i.split('.')[0] for i in single],
                     n='{}_loopguides_{}_grp'.format(curve_grp.split('_')[1],
                                                     grp.split('_')[-2]))
    if not cmds.objExists('guide_loop_set'):
        loop_set = cmds.sets(n='guide_loop_set', em=True)
    else:
        loop_set = 'guide_loop_set'
    sub = cmds.sets(crv + component, n=new_name.replace('_grp', '_set'))
    cmds.sets(sub, edit=True, fe=loop_set)
