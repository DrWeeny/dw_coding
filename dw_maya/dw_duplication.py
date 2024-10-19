import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import maya.mel as mel
import maya.api.OpenMaya as om  # API python 2.0
import re
from operator import itemgetter

import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_doCreateGeometryCache as dcgc

import xml.etree.ElementTree as ET


@acceptString('sel')
def freshDuplicate(sel=list):
    """
    Function to duplicate selected objects (mesh, nurbsCurve) while preserving connections temporarily.

    Args:
        sel (list): List of selected objects to duplicate.

    Returns:
        list: List of duplicated objects.
    """
    valid_types = ['mesh', 'nurbsCurve']
    shapes = dwu.lsTr(sel, type=valid_types, p=False, ni=True)  # Filter selected valid types
    output = []  # To store the resulting duplicated objects
    mass_disconnect = []  # To store connection data for later disconnection

    for shape in shapes:
        transform = dwu.lsTr(shape)[0]  # Get the transform parent
        node_type = cmds.nodeType(shape)  # Get the node type (mesh/nurbsCurve)
        zip_names = dwu.unique_name(transform)[0]  # Get unique name for new object

        # Create the new shape node
        new_node = cmds.createNode(node_type, name='dw_tmp_nodeShape#')
        new_transform = cmds.listRelatives(new_node, parent=True)[0]
        new_name = cmds.rename(new_transform, zip_names[-1])  # Rename to unique name
        new_shape = cmds.listRelatives(new_name, ni=True)[0]  # Get the shape of the new node

        # Get input/output connections
        conn_out = dwu.get_type_io(shape)
        conn_in = dwu.get_type_io(new_shape, io=0)

        # Connect the original shape's output to the new shape's input
        cmds.connectAttr(conn_out, conn_in, force=True)
        mass_disconnect.append([conn_out, conn_in])  # Store for disconnection

        output.append(new_name)

    # Refresh Maya viewport after duplication
    cmds.refresh()

    # Disconnect the attributes after refresh to create a clean duplicate
    for out_conn, in_conn in mass_disconnect:
        cmds.disconnectAttr(out_conn, in_conn)

    # Select the newly created duplicates in the scene
    cmds.select(output)

    return output

@acceptString('dupList')
def cleanDuplication(dupList, cTransformations=1, cLayer=1, cSet=1, cShader=1, cExtraAttribute=1, parentRoot=1):
    """
    Cleans up duplicated objects by removing history, freezing transformations, removing from layers, sets, shaders, and extra attributes, and optionally re-parenting to root.

    Args:
        dupList (list): List of duplicated objects.
        cTransformations (int): Flag to freeze transformations.
        cLayer (int): Flag to remove from display layers.
        cSet (int): Flag to remove from object sets.
        cShader (int): Flag to remove shaders and reset to lambert1.
        cExtraAttribute (int): Flag to remove extra user-defined attributes.
        parentRoot (int): Flag to re-parent to world root.

    Returns:
        None
    """
    for dup in dupList:
        # Delete History
        cmds.delete(dup, ch=True)

        # Freeze Transformation
        if cTransformations:
            attrs = ['t', 'r', 's']
            axes = ['x', 'y', 'z']
            output_attrs = ['{}.{}.{}'.format(dup, attr, axis) for attr in attrs for axis in axes]
            if [0] * 6 + [1] * 3 != [cmds.getAttr(attr) for attr in output_attrs]:
                for attr in output_attrs:
                    cmds.setAttr(attr, e=True, l=False)
                cmds.makeIdentity(dup, apply=True, t=True, r=True, s=True, n=0, pn=True)

        # Gather current connections and history
        current_connections = cmds.listConnections(dup) or []
        current_history = cmds.listHistory(dup, ac=True) or []

        # Delete Child Nodes that are not valid geometry (mesh, nurbsCurve)
        shape_nodes = cmds.ls(dup, dag=True, type=['mesh', 'nurbsCurve'], ni=True)
        shape_nodes.append(dup)
        all_nodes = cmds.ls(dup, dag=True)
        extra_nodes = list(set(all_nodes) - set(shape_nodes))
        if extra_nodes:
            cmds.delete(extra_nodes)

        # Remove from Display Layers
        if cLayer:
            display_layers = [conn for conn in current_connections if cmds.nodeType(conn) == 'displayLayer']
            for layer in display_layers:
                cmds.disconnectAttr(layer + '.drawInfo', dup + '.drawOverride')

        # Remove from Object Sets
        if cSet:
            object_sets = [conn for conn in current_connections if cmds.nodeType(conn) == 'objectSet']
            for obj_set in object_sets:
                inst_obj_group = cmds.listConnections(dup + '.instObjGroups', p=True)
                if inst_obj_group:
                    cmds.disconnectAttr(dup + '.instObjGroups', inst_obj_group[0])

        # Remove Shaders and reset to default (lambert1)
        if cShader:
            shading_engines = [h for h in current_history if cmds.nodeType(h) == 'shadingEngine']
            for shading_engine in shading_engines:
                if shading_engine != 'initialShadingGroup':
                    shader_connections = cmds.listConnections(cmds.listRelatives(dup, shapes=True), p=True)
                    for shader_conn in shader_connections:
                        if shader_conn.startswith(shading_engine):
                            try:
                                cmds.disconnectAttr(cmds.listConnections(shader_conn, p=True)[0], shader_conn)
                            except:
                                cmds.disconnectAttr(shader_conn, cmds.listConnections(shader_conn, p=True)[0])

            # Assign lambert1
            cmds.hyperShade(dup, assign='lambert1')

            # Delete groupId nodes associated with shaders
            shader_inputs = cmds.listConnections(cmds.listRelatives(dup, shapes=True), p=True)
            if shader_inputs:
                group_ids = [gid.split('.')[0] for gid in shader_inputs if cmds.nodeType(gid) == 'groupId']
                if group_ids:
                    cmds.delete(group_ids)

        # Remove Extra Attributes
        if cExtraAttribute:
            sel = cmds.ls(dup, dag=True)
            for s in sel:
                custom_attrs = cmds.listAttr(s, ud=True) or []
                for attr in custom_attrs:
                    try:
                        cmds.setAttr('{}.{}'.format(s, attr), e=True, l=False)
                        cmds.deleteAttr(s, at=attr)
                    except:
                        pass

        # Parent to root if necessary
        if parentRoot:
            if len(cmds.ls(dup, l=True)[0].split('|')) > 2:
                cmds.parent(dup, world=True)


@acceptString('sel')
def dupMesh(sel=[], **kwargs):
    """
    Duplicates mesh objects, assigns them unique names, and cleans them up by removing history, layers, shaders, and extra attributes.

    :param sel: List of selected objects to duplicate. Defaults to current selection.
    :param kwargs: Optional keyword arguments such as 'forbiddenName' to avoid specific names during duplication.
    :return: List of duplicated and cleaned mesh objects.
    """
    pairingNames = {}

    # Use the current selection if no objects are provided
    if not sel:
        sel = cmds.ls(sl=1)

    # Generate unique names for the selected objects
    zipNames = dwu.unique_name(sel, **kwargs)

    # Create a dictionary pairing original names with the new unique names
    for x in range(len(zipNames)):
        pairingNames[zipNames[x][0]] = [zipNames[x][1]]

    # Duplicate the objects and rename them to the generated unique names
    dopple = cmds.duplicate(pairingNames.keys(), n='dw_tmp_name001', rc=True)
    for d, n in zip(dopple, pairingNames.values()):
        cmds.rename(d, n[0])

    # Reorder duplicates using the new names from the zipNames list
    dup = [i[1] for i in zipNames]

    # Clean up the duplicated objects (history, transformations, layers, shaders, extra attributes)
    cleanDuplication(dup, cTransformations=True, cLayer=True, cSet=True, cShader=False, cExtraAttribute=True)

    return dup


def dup_wCache():
    """
    Duplicates the selected object, cleans the duplicated object, and imports the associated geometry cache.
    The duplicated object is renamed with '_cached_' and the current frame number.

    :return: List of duplicated objects with imported cache.
    """

    # Get the currently selected object and current frame number
    mySel = cmds.ls(sl=1)[0]
    frameNb = int(cmds.currentTime(q=1))

    # Duplicate the selected object and rename it to include '_cached_' and the frame number
    feed = cmds.duplicate(n=mySel + '_cached_' + str(frameNb), rr=True, rc=True)

    # Retrieve the cacheFile node from the original object's history
    myCacheNode = cmds.ls(cmds.listHistory(mySel), type='cacheFile')

    # Clean the duplicated object (remove history, transformations, etc.)
    cleanDuplication(feed, cTransformations=True, cLayer=True, cSet=True, cShader=False, cExtraAttribute=True)

    # Construct the cache file path using the cacheFile node's attributes
    myCachePath = cmds.getAttr(myCacheNode[0] + '.cachePath') + cmds.getAttr(myCacheNode[0] + '.cacheName') + '.xml'

    # cmds.doImportCacheFile()
    # use Mel because im bored to translate mel command doImportCacheFile(xmlFile::str,
    #                                                                     fileType::"" (optionnal)
    #                                                                     objects::list
    #                                                                     empty::list)

    # Use MEL to import the cache file for the duplicated object
    lineToEval = 'doImportCacheFile("{0}", "xmlcache", {{"{1}"}}, {{}});'.format(myCachePath, feed[0])
    mel.eval(lineToEval)

    return feed


def dup_abc():
    """
    Duplicates an Alembic cached object by importing the Alembic file associated with the selected mesh
    and renames the newly imported meshes with an '_abc_v1' suffix.

    :return: List of newly imported meshes
    """

    # Get the selected mesh shapes
    shape = cmds.ls(sl=True, dag=True, type="mesh")

    # Retrieve the AlembicNode from the selected object's history
    abc_nodes = [i for i in cmds.listHistory(shape) if cmds.nodeType(i) == 'AlembicNode']

    if not abc_nodes:
        cmds.error("No AlembicNode found in the history of the selected object.")
        return

    # Get the file path of the Alembic cache from the AlembicNode
    cache_path = cmds.getAttr(f'{abc_nodes[0]}.abc_File')

    # List all current nodes in the scene before import
    existing_nodes = set(cmds.ls())

    # Import the Alembic cache into the scene
    cmds.AbcImport(cache_path, mode='import')

    # Determine which new nodes were added to the scene
    imported_meshes = set(cmds.ls()) - existing_nodes

    # Generate unique names for the imported meshes with '_abc_v1' pattern
    for mesh in imported_meshes:
        if cmds.objExists(mesh):
            new_name = f'{mesh}_abc_v1'
            cmds.rename(mesh, new_name)

    return list(imported_meshes)


def dw_delete(mesh, idList):
    """
    Deletes the specified faces from the given mesh using the OpenMaya API.

    :param mesh: The name of the mesh to delete faces from.
    :param idList: A list of face indices to delete.
    :raises RuntimeError: If there is a failure in retrieving the mesh using OpenMaya.
    """
    try:
        # Create a selection list and add the mesh to it
        selectionList = om.MSelectionList()
        selectionList.add(mesh)

        # Get the DAG path of the mesh and retrieve the MFnMesh function set
        nodeDagPath = selectionList.getDagPath(0)
        mfnMesh = om.MFnMesh(nodeDagPath)

        # Delete the specified faces
        for faceId in idList:
            mfnMesh.deleteFace(faceId)

        # Update the mesh surface after modifications
        mfnMesh.updateSurface()

    except Exception as e:
        # Raise a specific runtime error with the mesh name and original exception
        raise RuntimeError(f'Failed to process {mesh}: {e}')

@acceptString('sel')
def outmesh(sel, **kwargs):
    """
    Duplicates the provided mesh or its components and processes them for output.

    :param sel: either component or a mesh name (faces, edges, vertices).
    :param kwargs: optional flags such as 'fresh' to force fresh duplication.
    :return: List of new duplicated meshes or mesh components.
    """

    # Get 'fresh' flag from kwargs, defaulting to False if not present
    fresh = dwu.Flags(kwargs, False, 'fresh')

    # Determine if selection is a full mesh or specific components
    obj = list(set(cmds.ls(sel, o=True)))

    # Regex pattern to identify components (faces, edges, vertices)
    p = re.compile(r'\.(f|e|vtx)\[\d{1,}:?\d{1,}?\]')
    test_sel = all([p.search(i) for i in sel])

    # Handle full object selections
    if len(obj) == len(sel):
        obj = sel
    else:
        if not test_sel:
            # Sort selected components to match the original object list
            sel_sorted = []
            for o in obj:
                idx = sel.index(o)
                sel_sorted.append([o, idx])

            obj = [i[0] for i in sorted(sel_sorted, key=itemgetter(1))]

    output = []

    # If selection is not a component (full mesh)
    if not test_sel:
        if fresh:
            new_objs = freshDuplicate(obj)
        else:
            new_objs = dupMesh(obj)

        # Iterate over the original and new meshes to connect their attributes
        for shape, target in zip(obj, new_objs):
            s, t = cmds.listRelatives(shape, target, s=1, ni=1)
            conn_out = dwu.get_type_io(s)
            conn_in = dwu.get_type_io(t, io=0)
            cmds.connectAttr(conn_out, conn_in)
        output += new_objs

    # Handle mesh components (faces, edges, vertices)
    else:
        if p.search(sel[0]):
            toface = cmds.polyListComponentConversion(sel, tf=True)
        else:
            toface = sel

        faceNb = cmds.polyEvaluate(obj[0], f=True)
        allComponents = range(faceNb)
        selComponents = cmds.ls(toface, flatten=True)
        selComponents = [int(re.findall(r'\d+', i)[-1]) for i in selComponents]

        selInverted = list(set(allComponents) - set(selComponents))

        # Duplicate the selected mesh for outmesh processing
        new_mesh = dupMesh(sel[0].split('.')[0])[0]
        shape, target = cmds.listRelatives(sel[0].split('.')[0], new_mesh, s=1, ni=1)
        cmds.connectAttr(f'{shape}.outMesh', f'{target}.inMesh')
        output.append(new_mesh)

        # Delete the unselected faces (invert the selection)
        maya_range = dwu.create_maya_ranges(selInverted)
        selToDel = [f'{new_mesh}.f[{i}]' for i in maya_range]
        cmds.delete(selToDel)

    return output


def make_dir(path):
    """
    Create all the directories in the specified path if they do not exist.

    :param path: The directory path to create.
    :return: The path string.
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


@acceptString('sel')
def dupAnim(sel=[]):
    """
    Duplicates the selected objects, bakes them, and creates a geometry cache for them.

    Args:
        sel: List of selected Maya objects (meshes or curves).

    Returns:
        msh_output: List of new baked mesh names.
    """
    # If no selection provided, take the current Maya selection
    if not sel:
        sel = cmds.ls(sl=True)

    restore_panels = []

    # Define temporary cache directory
    directory = os.path.join(cmds.workspace(fileRuleEntry='fileCache'), 'tmp_bake')

    # Ensure directory exists
    if not os.path.isdir(directory):
        make_dir(directory)

    # Retrieve names of existing files in the directory to avoid duplicates
    filesName = [f.split('.')[0] for f in os.listdir(directory) if f.endswith('.xml')]

    # Duplicate and clean the mesh with unique names
    duplicates = dupMesh(sel, forbiddenName=filesName)

    # Isolate view to improve performance
    evaluation = cmds.evaluationManager(q=True, mode=True)
    if 'off' not in evaluation:
        cmds.warning('You may want to switch to DG evaluation mode: cmds.evaluationManager(mode="off")')
    else:
        restore_panels = isolate_viewport_for_bake()

    # Create cache for the duplicated objects
    fileXml = dcgc.doCreateGeometryCache(duplicates[0], directory)

    # Use MEL to import the cache file
    objListMel = dwu.convert_list_to_mel_str(duplicates)
    cmd_format = 'doImportCacheFile("{0}", "xmlcache", {1}, {{}});'
    mel.eval(cmd_format.format(fileXml[0], objListMel))

    # Restore the original viewport settings if changed
    if restore_panels:
        for panel in restore_panels:
            cmds.isolateSelect(panel, state=0)

    # Rename duplicated meshes with a 'bake_' prefix
    msh_output = []
    for obj in duplicates:
        if not obj.startswith('bake_'):
            new_name = cmds.rename(obj, 'bake_' + obj)
            msh_output.append(new_name)
        else:
            msh_output.append(obj)

    return msh_output


def isolate_viewport_for_bake():
    """
    Isolates the viewport for performance improvements during cache bake.

    Returns:
        restore_panels: List of model panels to restore later.
    """
    restore_panels = []
    modelPanels = [i for i in cmds.lsUI(p=True) if 'modelPanel' in i]
    for panel in modelPanels:
        if not cmds.isolateSelect(panel, q=True, state=True):
            cmds.isolateSelect(panel, state=True)
            restore_panels.append(panel)
    return restore_panels


def dupWCache(sel=[], cache_path=None):
    """
    Duplicates the selected object and applies the associated cache.

    Args:
        sel: List of selected Maya objects (meshes or other nodes).
        cache_path: Optional file path to a cache XML file for applying to the duplicated object.

    Returns:
        The name of the newly duplicated and cached object.
    """
    # If no selection provided, take the first object in the current selection
    if not sel:
        sel = cmds.ls(sl=True)[0]

    # Duplicate the selected mesh
    feed = dupMesh(sel)

    # Case 1: Cache path provided directly (manual mode)
    if cache_path:
        # Format the MEL command to import the cache from the provided path
        importCacheCmd = 'doImportCacheFile("{0}", "xmlcache", {{"{1}"}}, {{}});'.format(cache_path, feed[0])
        mel.eval(importCacheCmd)

        # Extract version information (vXXX) from cache path if available
        version_match = re.search(r'v\d{3}', cache_path)
        version_str = version_match.group(0) if version_match else ''

        # Rename the duplicated object with a meaningful name based on version and selection
        name = 'sim_{}_{}'.format(version_str, sel).replace('__', '_')
        renamed_obj = cmds.rename(feed[0], name)

        return renamed_obj

    # Case 2: Cache path not provided, infer from existing cache node
    else:
        # Find any existing cache node attached to the selected object
        myCacheNode = cmds.ls(cmds.listHistory(sel), type='cacheFile')

        if myCacheNode:
            # Get the cache path and name from the cache node attributes
            cache_path = cmds.getAttr(myCacheNode[0] + '.cachePath')
            cache_name = cmds.getAttr(myCacheNode[0] + '.cacheName')
            myCachePath = cache_path + cache_name + '.xml'

            # Import the cache file using MEL
            importCacheCmd = 'doImportCacheFile("{0}", "xmlcache", {{"{1}"}}, {{}});'.format(myCachePath, feed[0])
            mel.eval(importCacheCmd)

            # Rename the duplicated object if it doesn't start with 'bake_'
            if not feed[0].startswith('bake_'):
                renamed_obj = cmds.rename(feed[0], 'bake_' + feed[0])
            else:
                renamed_obj = feed[0]

            return renamed_obj
        else:
            cmds.error("No cache node found for the selected object.")


def instanceObjects(sel=[]):
    """
    Create instances of selected objects instead of full duplicates.

    Args:
        sel (list): List of objects to instance.

    Returns:
        list: List of created instances.
    """
    if not sel:
        sel = cmds.ls(sl=True)

    instances = []
    for obj in sel:
        instance = cmds.instance(obj)
        instances.append(instance[0])

    return instances


def dupWithPivotAdjustment(sel=[], pivotType='boundingBoxCenter'):
    """
    Duplicate objects and adjust their pivot position.

    Args:
        sel (list): List of objects to duplicate.
        pivotType (str): Type of pivot adjustment ('boundingBoxCenter', 'origin', or custom position).

    Returns:
        list: List of duplicated objects with adjusted pivots.
    """
    if not sel:
        sel = cmds.ls(sl=True)

    duplicates = cmds.duplicate(sel, rr=True)

    for dup in duplicates:
        if pivotType == 'boundingBoxCenter':
            bbox = cmds.xform(dup, q=True, bb=True, ws=True)
            center = [(bbox[0] + bbox[3]) / 2, (bbox[1] + bbox[4]) / 2, (bbox[2] + bbox[5]) / 2]
            cmds.xform(dup, piv=center, ws=True)
        elif pivotType == 'origin':
            cmds.xform(dup, piv=[0, 0, 0], ws=True)
        # Add more custom pivot positioning options as needed

    return duplicates
