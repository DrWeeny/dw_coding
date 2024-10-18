import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)


import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
Flags = dwu.Flags
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_yeti as dwpgy
from collections import defaultdict
from itertools import chain
import os

def make_dir(path: str):
    """
    Create all the directories if they don't exist.
    Args:
        path (str): The directory path.
    Returns:
        str: The created directory path.
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def importAbc(path: str, namespace=':', top=True, **kwargs) -> dict:

    '''
    import an abc with a specific namespace
    it will return the top node as output, you can use kwargs for the : AbcImport

    Args:
        path (str): abc file path
        namespace (str): any string
        top (bool): return every nodes or just the top one
    Kwargs ():
        AbcImport  [options] File [File2 File3 ... ]

        Options:
        -rpr/ reparent      DagPath
                            reparent the whole hierarchy under a node in the
                            current Maya scene
        -ftr/ fitTimeRange
                            Change Maya time slider to fit the range of input file.
        -rcs / recreateAllColorSets
                            IC3/4fArrayProperties with face varying scope on
                            IPolyMesh and ISubD are treated as color sets even if
                            they weren't written out of Maya.
        -ct / connect       string node1 node2 ...
                            The nodes specified in the argument string are supposed to be the names of top level nodes
                            from the input file.
                            If such a node doesn't exist in the provided input file, awarning will be given and
                            nothing will be done.
                            If Maya DAG node of the same name doesn't exist in the    current Maya scene,
                            a warning will be given and nothing will be done.
                            If such a node exists both in the input file and in the   current Maya scene,
                            data for the whole hierarchy from the nodes down
                            (inclusive) will be substituted by data from the input file, and
                            connections to the AlembicNode will be made or updated accordingly.
                            If string "/" is used as the root name,  all top level  nodes
                            from the input file will be used for updating the current Maya scene.
                            Again if certain node doesn't exist in the current scene, a warning will be given and
                            nothing will be done.
                            If a single node is specified and it exists in the Maya scene but doesn't exist in the archive,
                            children of that node will be connected to the children of the archive.
        -crt/ createIfNotFound
                            Used only when -connect flag is set.
        -rm / removeIfNoUpdate
                            Used only when -connect flag is set.
        -sts/ setToStartFrame
                            Set the current time to the start of the frame range
        -m  / mode          string ("open"|"import"|"replace")
                            Set read mode to open/import/replace (default to import)
        -ft / filterObjects "regex1 regex2 ..."
                            Selective import cache objects whose name matches with
        -eft / excludeFilterObjects "regex1 regex2 ..."
                            Selective exclude cache objects whose name matches with
        the input regular expressions.
        -h  / help          Print this message
        -d  / debug         Turn on debug message printout

        Specifying more than one file will layer those files together.

        Example:
        AbcImport -h;
        AbcImport -d -m open "/tmp/test.abc";
        AbcImport -ftr -ct "/" -crt -rm "/tmp/test.abc";
        AbcImport -ct "root1 root2 root3 ..." "/tmp/test.abc";
        AbcImport "/tmp/test.abc" "/tmp/justUVs.abc" "/tmp/other.abc"
    Returns:

    '''
    try:
        result={}
        ns_cur = cmds.namespaceInfo(currentNamespace=True)
        if not cmds.namespace(exists=namespace):
            namespace = cmds.namespace(add=namespace)
        cmds.namespace(set=namespace)
        nodes_tr_before = cmds.ls(type='transform')
        nodes_abc_before = cmds.ls(type='AlembicNode')

        if not os.path.exists(path):
            cmds.error(f"Alembic file doesn't exist: {path}")

        # Import Alembic file
        cmds.AbcImport(path, mode='import')

        # Reset the namespace
        cmds.namespace(set=ns_cur)

        # Get the nodes after the import
        nodes_tr_after = cmds.ls(type='transform')
        nodes_abc_after = cmds.ls(type='AlembicNode')
        abc = list(set(nodes_abc_after)-set(nodes_abc_before)) or nodes_abc_after
        nodes = list(set(nodes_tr_after) - set(nodes_tr_before)) or nodes_tr_after

        # Handle case when no AlembicNode was created
        if nodes and not abc:
            abc = ['']  #: an alembic cache could not be created because there is no animation

        # Process the imported nodes
        if top:
            root_grp = cmds.ls(nodes, dag=True, type='transform', l=True)
            root_grp = [[i, len(i.split('|'))] for i in root_grp]
            root_hierarchy = sorted(root_grp, key=lambda gx: gx[1], reverse=False)
            for r in root_hierarchy:
                if r[1] in result:
                    result[r[1]].append(r[0])
                else:
                    result[r[1]] = [r[0]]
            indexes = sorted(result.keys())
            return {abc[0]: list(set(result[indexes[0]]))}
        else:
            result[abc[0]] = nodes

        return result
    except Exception as e:
        cmds.namespace(set=':')
        cmds.error(e)

@acceptString('nodes')
def exportAbc(file=str, nodes=list, frameRange=None, uvWrite=True, dataFormat='ogawa', sn=True, withHierarchy=True, **kwargs):

    '''
    cacheTimeRanges				= maya.cmds.optionVar(q='Alembic_exportCacheTimeRanges')
    startFrames					= maya.cmds.optionVar(q='Alembic_exportStarts')
    endFrames					= maya.cmds.optionVar(q='Alembic_exportEnds')
    evaluateEverys				= maya.cmds.optionVar(q='Alembic_exportEvaluateEverys')
    enableSamples				= maya.cmds.optionVar(q='Alembic_exportEnableFrameRelativeSamples')
    lowFrameRelativeSamples		= maya.cmds.optionVar(q='Alembic_exportLowFrameRelativeSamples')
    highFrameRelativeSamples		= maya.cmds.optionVar(q='Alembic_exportHighFrameRelativeSamples')

    enablePreRoll				= bool(maya.cmds.optionVar(q='Alembic_exportEnablePreRoll'))
    preRollStartFrame			= float(maya.cmds.optionVar(q='Alembic_exportPreRollStartFrame'))
    preRollStep					= float(maya.cmds.optionVar(q='Alembic_exportPreRollStep'))
    attr						= maya.cmds.optionVar(q='Alembic_exportAttr')
    attrPrefix					= maya.cmds.optionVar(q='Alembic_exportAttrPrefix')
    verbose						= bool(maya.cmds.optionVar(q='Alembic_exportVerbose'))
    noNormals					= bool(maya.cmds.optionVar(q='Alembic_exportNoNormals'))
    renderableOnly				= bool(maya.cmds.optionVar(q='Alembic_exportRenderableOnly'))
    stripNamespaces				= bool(maya.cmds.optionVar(q='Alembic_exportStripNamespaces'))
    uvWrite						= bool(maya.cmds.optionVar(q='Alembic_exportUVWrite'))
    writeColorSets				= bool(maya.cmds.optionVar(q='Alembic_exportWriteColorSets'))
    writeFaceSets				= bool(maya.cmds.optionVar(q='Alembic_exportWriteFaceSets'))
    wholeFrameGeo				= bool(maya.cmds.optionVar(q='Alembic_exportWholeFrameGeo'))
    worldSpace					= bool(maya.cmds.optionVar(q='Alembic_exportWorldSpace'))
    writeVisibility				= bool(maya.cmds.optionVar(q='Alembic_exportWriteVisibility'))
    filterEulerRotations		= bool(maya.cmds.optionVar(q='Alembic_exportFilterEulerRotations'))
    writeCreases				= bool(maya.cmds.optionVar(q='Alembic_exportWriteCreases'))
    dataFormat					= int(maya.cmds.optionVar(q='Alembic_exportDataFormat'))
    perFrameCallbackMel			= maya.cmds.optionVar(q='Alembic_exportPerFrameCallbackMel')
    postJobCallbackMel				= maya.cmds.optionVar(q='Alembic_exportPostJobCallbackMel')
    perFrameCallbackPython		= maya.cmds.optionVar(q='Alembic_exportPerFrameCallbackPython')
    postJobCallbackPython		= maya.cmds.optionVar(q='Alembic_exportPostJobCallbackPython')

    #preRollFlags = "-frameRange {0} {1} -step {2} -preRoll ".format(preRollStartFrame, preRollEndFrame, preRollStep)
    for i in attrArray:
        if (len(i) > 0) :
            job += "-attr "
            job += maya.cmds.formValidObjectName(i)
            job += " "

    for i in attrPrefixArray :
        if (len(i) > 0) :
            job += "-attrPrefix "
            job += maya.cmds.formValidObjectName(i)
            job += " "

    if (verbose) :
        command += "-verbose "


    if (noNormals) :
        job += "-noNormals "


    if (renderableOnly) :
        job += "-ro "


    if (stripNamespaces) :
        job += "-stripNamespaces "

    if (uvWrite) :
        job += "-uvWrite "

    if (writeColorSets) :
        job += "-writeColorSets "

    if (writeFaceSets) :
        job += "-writeFaceSets "

    if (wholeFrameGeo) :
        job += "-wholeFrameGeo "

    if (worldSpace) :
        job += "-worldSpace "

    if (writeVisibility) :
        job += "-writeVisibility "

    if (filterEulerRotations) :
        job += "-eulerFilter "

    if (writeCreases) :
        job += "-writeCreases "

    if (dataFormat == 2):
        job += "-dataFormat ogawa "

    Args:
        file ():
        root ():
        frameRange ():
        uvWrite ():
        dataFormat ():
        withHierarchy ():
        *args ():

    Tips :
    For preserving the hierarchy you need to parse the top nodes into the command instead of the nodes/shapes
    Furthermore you need to select the nodes you wish to select (in order to not export the whole group)

    Returns:
        None

    '''
    # This List is used to feed the abc command (which is string based)
    args_list = []
    # =====================================================================================
    # VALIDATE THE PATH
    # =====================================================================================
    if file.startswith('/') and file.endswith('.abc'):
        file = f"-file {file}"
        args_list.append(file)
    elif '/' not in file:
        if len(cmds.workspace(fileRuleEntry='alembicCache')) == 0:
            cmds.workspace(fileRule=["alembicCache", "cache/alembic"])
        workspace = cmds.workspace(fileRuleEntry='alembicCache')
        workspace = cmds.workspace(expandName=workspace)

        make_dir(workspace)
        if '.' not in file:
            file = f'{file}.abc'
        elif not file.endswith('.abc'):
            cmds.error('please give a valid name')
        file = f"{workspace}/{file}"
        file = "-file {}".format(file)
        args_list.append(file)
    else:
        cmds.error('please input a valid path')

    # Set Frame Range :
    if not frameRange:
        min_frm = cmds.playbackOptions(q=True, min=True)
        max_frm = cmds.playbackOptions(q=True, max=True)
    elif isinstance(frameRange, (list, tuple)):
        if len(frameRange) == 1:
            min_frm = max_frm = int(frameRange[0])
        else:
            min_frm, max_frm = frameRange
    elif isinstance(frameRange, (float, int, str)):
        min_frm = max_frm = int(frameRange)
    else:
        cmds.error('frameRange argument take a list of two numbers or just one number if it is a still frame ')
    frm_rng = '-frameRange {} {}'.format(min_frm, max_frm)
    args_list.append(frm_rng)

    # Set UV Write :
    if uvWrite:
        args_list.append('-uvWrite')

    # Set Data Format
    fmt = '-dataFormat {}'.format(dataFormat)
    args_list.append(fmt)

    # Set The Nodes to Export
    root = cmds.ls(nodes, l=True)
    if withHierarchy:
        root = dwu.get_common_roots(root)
    if not nodes:
        cmds.error('nothing listed')

    for n in root:
        r = '-root {}'.format(n)
        args_list.append(r)

    # Set Export Roots
    if withHierarchy:
        args_list.append("-sl")
        cmds.select(nodes)

    if sn:
        args_list.append("-sn 1")

    attrs = dwu.Flags(kwargs, None, 'userAttrPrefix')
    if isinstance(attrs, (list, tuple)):
        for a in attrs:
            r = '-userAttrPrefix {}'.format(a)
            args_list.append(r)
    elif isinstance(attrs, str):
        r = '-userAttrPrefix {}'.format(attrs)
        args_list.append(r)

    SAMPLING_END_ON_FRAME = -1
    SAMPLING_CENTER_ON_FRAME = 0
    SAMPLING_START_ON_FRAME = 1

    samplesPerFrame = dwu.Flags(kwargs, 3, 'samplesPerFrame')
    samplingTiming = SAMPLING_START_ON_FRAME
    samplesRange = 1.0

    if samplesPerFrame > 1:
        if samplingTiming == SAMPLING_START_ON_FRAME:
          sstart = 0.0
          send = samplesRange

        elif samplingTiming == SAMPLING_CENTER_ON_FRAME:
          sstart = -0.5 * samplesRange
          send = 0.5 * samplesRange

        else:
          sstart = -samplesRange
          send = 0.0

        sstep = float(samplesRange) / (samplesPerFrame - 1)
        scur = sstart
        while scur <= send:
            args_list.append(f" -frameRelativeSample {scur}")
            scur += sstep

    args_string = ' '.join(args_list)
    cmds.AbcExport(j=args_string)
    print(f'cmds.AbcExport(j={args_string})')

# Scene Connectors Methods :
def getAbcConnections(AbcNode, namespace=':', target_ns=[], filter=[]):

    attr_map = ['outPolyMesh', 'outLoc', 'outSubDMesh', 'outNCurveGrp', 'transOp', 'prop', 'outCamera']
    if filter:
        attr_map = list(set(attr_map)-set(filter))

    con_dic = defaultdict(list)
    for a in attr_map:
        abc_attr = '{}.{}'.format(AbcNode, a)
        plug = cmds.listConnections(abc_attr, plugs = True, scn = True)
        if plug:
            for p in plug:
                target = [p.split(namespace)[-1]]
                if target_ns:
                    target = ['{}:{}'.format(ns, target[0]) for ns in target_ns]
                    target = [t.replace('::', ':') for t in target]
                for targ in target:
                    if cmds.objExists(targ):
                        if a != 'time1.outTime':
                            destinationAttrs = cmds.listConnections(p, plugs=True, source=False, scn=True) or []
                            sourceAttrs = cmds.listConnections(p, plugs=True, destination=False, scn=True) or []
                            for destAttr in destinationAttrs:
                                con_dic[destAttr].append(targ)
                                con_dic[destAttr] = list(set(con_dic[destAttr]))
                            for srcAttr in sourceAttrs:
                                con_dic[srcAttr].append(targ)
                                con_dic[srcAttr] = list(set(con_dic[srcAttr]))

    return con_dic

def getAbcStatic(topnodes=[], target_ns=None):
    value_dic = defaultdict(list)

    # Get all transform nodes under the top nodes
    transNodes = cmds.ls(topnodes, dag=True, type='transform')
    for n in transNodes:
        target = [n.rsplit(':', 1)[-1]]

        # If target namespace is provided, modify target names accordingly
        if target_ns:
            target = [f'{ns}:{target[0]}' for ns in target_ns]
            target = [t.replace('::', ':') for t in target]
        for targ in target:
            if cmds.objExists(targ):
                # get the main values from translate, rotate, scale
                for at in 'trs':
                    key = f'{targ}.{at}'  # pShphere1.t
                    for ax in 'xyz':
                        ch_attr = f'{n}.{at}{ax}'
                        if cmds.getAttr(ch_attr, settable = True):
                            value = cmds.getAttr(ch_attr)
                            value_dic[key].append(value)
                        else:
                            value_dic[key].append(None)
                    # optimisation to setAttr t,r,s with xyz if it is possible
                    if any([True for v in value_dic[key] if v is None]):
                        for x, ax in enumerate('xyz'):
                            if value_dic[key][x]:
                                value_dic[key + ax].append(value_dic[key][x])
                        del value_dic[key]
                # get also the visibility of the node
                key = f'{targ}.visibility'
                ch_attr = f'{n}.visibility'
                if cmds.getAttr(ch_attr, settable=True):
                    value = cmds.getAttr(ch_attr)
                    value_dic[key].append(value)
    return value_dic

def setAbcStatic(static: dict):
    for k, v in static.items():
        current = cmds.getAttr(k)
        if isinstance(current, list):
            current = current[0]
        else:
            v = v[0]
        if current != v:
            if cmds.getAttr(k, settable=True):
                if isinstance(v, (list, tuple)):
                    cmds.setAttr(k, *v)
                elif isinstance(v, str):
                    cmds.setAttr(k, v, type='string')
                else:
                    cmds.setAttr(k, v)
            else:
                print('{} has been not set to {} because it is not settable'.format(k, v))

def setAbcConnections(connections: dict):
    for k, v in connections.items():
        for c in v:
            if cmds.getAttr(c, lock=True):
                cmds.setAttr(c, lock=False)
            cmds.connectAttr(k, c, force=True)

def cleanAbcConnections(abc: str, connections: dict):
    targ_attrs = list(chain(*connections.values()))
    attribute = cmds.listConnections(abc, plugs=True, scn=True)
    for a in attribute:
        if a != 'time1.outTime' and a not in targ_attrs:
            destinationAttrs = cmds.listConnections(a, plugs=True, source=False, scn=True) or []
            sourceAttrs = cmds.listConnections(a, plugs=True, destination=False, scn=True) or []
            if a not in connections.values():
                for destAttr in destinationAttrs:
                    cmds.disconnectAttr(a, destAttr)
                for srcAttr in sourceAttrs:
                    cmds.disconnectAttr(srcAttr, a)

def importShotAbc(path, target_namespace=':', alembic_namespace='anim', **kwargs):
    """
    Import Alembic file for a shot and manage the alembic connections, static values, and hierarchy.

    Args:
        path (str): The file path of the Alembic (.abc) file.
        target_namespace (str, optional): The namespace for the imported alembic nodes. Defaults to ':'.
        alembic_namespace (str, optional): The namespace used for Alembic nodes within Maya. Defaults to 'anim'.
        kwargs (dict): Additional options for importing and managing the Alembic file. Supported flags:
            - face_sets (bool): Handle face sets for Yeti or other specific purposes.
            - top (bool): Return only the top nodes if True. Defaults to True.
            - debug (bool): Return debug information like Alembic connections, static values, etc. Defaults to False.
            - delete (bool): Delete the imported Alembic nodes after processing. Defaults to True.
            - connectMode (int): Connection mode. Defaults to 0 (standard connection).

    Returns:
        dict: A dictionary containing the Alembic nodes and related information, depending on the debug flag.
              If debug=True, it returns `[abc_geos, static_dic, con_dic, face_set]`.
              If debug=False, it returns just the Alembic geometry nodes.

    Behavior:
        - Imports the Alembic file using the provided namespace.
        - Queries and sets static attribute values for matching nodes in the target namespace.
        - Handles direct or blendshape-based connections between Alembic nodes and target nodes.
        - Optionally handles Yeti face sets (if face_sets=True).
        - Optionally deletes the imported Alembic nodes after processing or hides and reparents them in the hierarchy.
        - Provides detailed debug information if requested (when debug=True).

    Example Usage:
        # Simple Alembic import without deleting the top nodes:
        importShotAbc('/path/to/alembic.abc', target_namespace='my_ns', delete=False)

        # Alembic import with debug information and face sets handling:
        debug_info = importShotAbc('/path/to/alembic.abc', face_sets=True, debug=True)
    """
    face = Flags(kwargs, None, 'face_sets', 'face')
    top = Flags(kwargs, True, 'top')
    debug = Flags(kwargs, False, 'debug')
    delete = Flags(kwargs, True, 'delete')
    directConnect = Flags(kwargs, 0, 'connectMode')

    # the name for the abc namespace
    if target_namespace == ':':
        ns = target_namespace + alembic_namespace
    else:
        ns = '{}:{}'.format(target_namespace, alembic_namespace)

    # Import the Alembic file
    abc_geos = importAbc(path, ns, top)

    # AlembicNode name
    abc = list(abc_geos.keys())[0]

    # Queries Direct Connections
    con_dic = getAbcConnections(abc, ns, [target_namespace])
    # Query the value on all nodes
    topGrp = list(abc_geos.values())[0]
    static_dic = getAbcStatic(topGrp, [target_namespace])
    # This Query is for yeti, during the connection, it lost face in sets
    # We Should disconnect and reconnect the yeti nodes from geometries
    if face:
        face_set = dwpgy.getFaceSet(face)
    # re-fork everything
    # TODO : should we refork if a node as a certain pattern (for example for cfx)
    # TODO : add also namespace to those
    setAbcStatic(static_dic)
    if not directConnect:
        setAbcConnections(con_dic)
        cleanAbcConnections(abc, con_dic)
    elif directConnect == 1:
        print('direct connect')
        setBsConnections(con_dic)
    # delete the top nodes in order to clean the vision from all those nodes
    if delete:
        cmds.delete(*abc_geos.values())
    else:
        # reparent the top nodes to the hierarchy and put every shape as intermediate object
        if target_namespace != ':':
            grp_name = f'{target_namespace}:abcImport'
        else:
            grp_name = 'abcImport'
        if not cmds.objExists(grp_name):
            cmds.group(em=True, name=grp_name)

        # Reparent and hide top groups
        for s in abc_geos.values():
            node_short = cmds.ls(s)[0]
            cmds.setAttr(f'{node_short}.visibility', 0)
            cmds.parent(node_short, grp_name)
            shs = cmds.ls(node_short, dag=True, l=True, type='shape')
            for sh in shs:
                cmds.setAttr(f'{sh}.intermediateObject', 1)
        # parent the new group to the asset
        if target_namespace != ':':
            cmds.parent(grp_name, '{}:all'.format(target_namespace))
        else:
            cmds.parent(grp_name, 'all')

    if face:
        # dwu.wait_idle()
        # cmds.evalDeferred('dwpgy.setFaceSet({})'.format(face_set), lowestPriority=True)
        cmds.evalDeferred(f'dwpgy.debugFaceSet("{face}", {face_set})', lowestPriority=True)
    if debug:
        return [abc_geos, static_dic, con_dic, face_set]
    else:
        return abc_geos

def setBsConnections(connections=dict):
    """
    This function sets blendShape connections for specific Alembic attributes. It creates
    a blendShape connection between the source and target geometry based on the given connections.

    Args:
        connections (dict): A dictionary of Alembic connections.
                            The key is the source attribute, and the value is a list of target attributes.

    Returns:
        list: A list of created blendShape node names.
    """
    bs_list = []
    # Attributes that should trigger blendShape connections
    attrForBlend = ['outSubDMesh', 'outPolyMesh', 'outNCurveGrp']
    for k, v in connections.items():
        abc_attr = k.split('.')[-1].split('[')[0]
        print(abc_attr, attrForBlend)
        if abc_attr in attrForBlend:
            src_ns = k.rsplit(':', 1)
            node, targ_ns = v[0].split('.')[0].rsplit(':', 1)

            src_node = f'{src_ns}:{node}'
            targ_node = f'{targ_ns}:{node}'
            bs_name = cmds.blendShape(src_node, targ_node, en=1, tc=1, o='world',
                                                           w=(0, 1), before=True,
                                                           name=f'bs_simConnect_{node}')[0]
            # Add custom attribute 'sim_influence' to target transform and connect it to blendShape enable
            targ_tr = cmds.listRelatives(targ_node, p=True)[0]
            attr = dwu.addAttribute(targ_tr, 'sim_influence', 1)
            cmds.connectAttr(attr, f'{bs_name}.en')
            bs_list.append(bs_name)
    return bs_list
