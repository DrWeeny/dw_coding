#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    Weeny

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools\\maya'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from pprint import pprint

# internal
from maya import cmds, mel
# internal

# external
from .dw_maya_data import Flags
from .dw_maya_components import get_next_free_multi_index
from dw_decorators import acceptString

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def get_type_io(mtype=str, **kwargs):
    """
    this function has been created to return the main inputs or outputs of a node

    Examples:
        `name = 'pSphere1'
        attr_in = get_type_io(name, io=0)
        attr_out = get_type_io(name)`

        `name = 'transformGeometry1',
        attr_in_transform = get_type_io(name, io=0, sel=0)
        attr_in_inputGeometry = get_type_io(name, io=0, sel=1)`

        `name = 'wrap1'
        attr_out_default = get_type_io(name)
        # Result : wrap1.outputGeometry[0]`
        attr_out_noIndex = get_type_io(name, id=False)
        # Result :  wrap1.outputGeometry
        attr_out_format = get_type_io(name, id=2)
        # Result :  wrap1.outputGeometry[{}]
        attr_only = get_type_io(name, id=False, join=False)
        # Result : outputGeometry

    Args:
        mtype (str): transform is ignored, it tries by default
                     the shape of the name provided
                     if not, it is checking if you have provided
                     a nodeType string
    Kwargs:
        io (int) : select input or output, default 1 - output
        index or id (int) : if the output would be a list,
        you can select the list index, default None
        multi or m (bool) : remove the default [0]
        at the end of certain attributes, default True and has [0]
        join or j (bool) : return a this '{name}.{attr}', default is True
        query or q (bool) : print the node accepted,
        return the list of input/output for the type supported

    Returns:
        (str) : '{name}.{attr}' or 'attr'
        Or
        (list) : values of input/output
    """
    io = Flags(kwargs, 1, 'io')
    id = Flags(kwargs, None, 'index', 'id')
    multi = Flags(kwargs, 1, 'multi', 'm')
    join = Flags(kwargs, True, 'join', 'j')
    query = Flags(kwargs, False, 'query', 'q')

    # Ignore transforms
    if mtype == 'transform':
        return None
    # Handle node type checking
    if mtype not in cmds.ls(nt=True) and cmds.objExists(mtype):
        short = cmds.ls(mtype, dag=True, type='shape', ni=True)
        _test = [True for i in cmds.ls(short) if '|' in i]
        if any(_test):
            sh = cmds.ls(mtype, dag=True, type='shape', ni=True, l=True)
        else:
            sh = short
        if sh:
            _mtype = cmds.nodeType(sh)
        else:
            _mtype = cmds.nodeType(mtype)

   # Output attribute mappings by node type
    output = {}
    output['mesh'] = ['inMesh', 'worldMesh[0]']
    output['wrap'] = [
        ['basePoints[0]', 'input[0].inputGeometry', 'driverPoints[0]',
         'geomMatrix'], 'outputGeometry[0]']
    # todo  see if we implement worldSpace[0] as output
    #       and outmesh for mesh
    output['nurbsCurve'] = ['create', 'local']
    output['polyUnite'] = ['inputPoly[0]', 'output']
    output['polySeparate'] = ['inputPoly', 'output[0]']
    output['eSTmeshDeformer'] = [None, 'outputGeometry[0]']
    output['cvWrap'] = [['driver'], 'outputGeometry']
    output['transformGeometry'] = [['transform', 'inputGeometry'],
                                   'outputGeometry']
    output['choice'] = ['input[0]', 'output']
    # TODO make some checks
    output['locator'] = ['message', ['inverseMatrix[0]', 'worldMatrix[0]',
                                     'worldPosition[0]']]
    output['groupParts'] = ['inputGeometry', 'outputGeometry']
    output['tweak'] = ['input[0]', 'outputGeometry[0]']
    output['blendShape'] = ['inputTarget[0].inputTargetGroup[0]',
                            'outputGeometry[0]']

    output['nucleus'] = [['inputCurrent[0]', 'inputStart[0]'],
                         'outputObjects[0]']
    output['nComponent'] = ['objectId', 'outComponent']
    output['dynamicConstraint'] = ['componentIds[0]',
                                   ['evalCurrent[0]', 'evalStart[0]']]
    output['nCloth'] = [['inputMesh', 'nextState'], ['outputMesh', 'nucleusId']]
    output['nRigid'] = [['inputMesh', 'startFrame'],
                        ['outputMesh', 'nucleusId']]
    output['hairSystem'] = [['inputHair[0]'],
                        ['outputHair[0]', 'nucleusId']]

    output['follicle'] = [['startPosition', 'startPositionMatrix', 'inputMesh'],
                        ['outCurve', 'outHair']]

    # Query mode: return list of attributes for the given node type
    if query:
        if _mtype in output:
            return output[_mtype]
        else:
            pprint.pprint(output)
            cmds.error(f"sorry, this node '{_mtype}' is not implemented")

    # Extract the appropriate attribute based on io and id
    if id is not None:
        attr = output[_mtype][io][id]
    else:
        attr = output[_mtype][io]

    # Handle multi-index formatting
    # if attribute is a multi i.e: outputHair[0] and flag is set to multi
    # we can find the next available and even return a list of multi if there are multiple inputs
    if not multi:
        attr = [a.split('[')[0] for a in attr]
    elif multi:
        if isinstance(attr, list):
            attr_nofmt = [a.replace('[0]', '[{}]') for a in attr if
                          '[' not in a]
            attr_fmt = [a.replace('[0]', '[{}]') for a in attr if '[' in a]
            if multi == 2:
                attr = attr_nofmt + [
                    fmt.format(get_next_free_multi_index(mtype + '.' + a)) for
                    fmt, a in zip(attr_fmt, attr)]
            else:
                attr = attr_nofmt + [fmt.format(0) for fmt, a in
                                     zip(attr_fmt, attr)]
        else:
            if '[' in attr:
                attr_fmt = attr.replace('[0]', '[{}]')
                if multi == 2:
                    attr = attr_fmt.format(
                        get_next_free_multi_index(mtype + '.' + attr))
                else:
                    attr = attr_fmt.format(0)

    if join:
        if isinstance(attr, list):
            return [f'{mtype}.{j}' for j in attr]
        return f'{mtype}.{attr}'
    return attr


def add_attr(node=str,
             long_name=str,
             value=None,
             attr_type='long',
             **kwargs):
    """Add attribute to a node
    Arguments:
        node (dagNode): The object to add the new attribute.
        long_name (str): The attribute name.
        attr_type (str): The Attribute Type. Exp: 'string', 'bool',
            'long', etc..
        value (float or int): The default value.
        niceName (str): The attribute nice name. (optional)
        shortName (str): The attribute short name. (optional)
        minValue (float or int): minimum value. (optional)
        maxValue (float or int): maximum value. (optional)
        keyable (bool): Set if the attribute is keyable or not. (optional)
        readable (bool): Set if the attribute is readable or not. (optional)
        storable (bool): Set if the attribute is storable or not. (optional)
        writable (bool): Set if the attribute is writable or not. (optional)
        channelBox (bool): Set if the attribute is in the channelBox or not,
            when the attribute is not keyable. (optional)
    Returns:
        str: The long name of the new attribute
    """
    if not cmds.attributeQuery(long_name, node=node, exists=True):
        data = Flags(kwargs, None, 'shortName', 'sn', dic={})
        data = Flags(kwargs, None, 'niceName', 'nn', key='shortName', dic=data)
        if attr_type == "string":
            data["dataType"] = attr_type
        elif attr_type == 'enum':
            data["attributeType"] = 'enum'
            enum = Flags(kwargs, None, 'enumName', 'en')
            if not enum:
                cmds.error(
                    'please use enumName or en flags to specify a list of items')
            if isinstance(enum, (list, tuple)):
                data["enumName"] = ':'.join(enum) + ':'
            elif isinstance(enum, basestring):
                if ':' in enum:
                    if enum.endswith(':'):
                        enum = enum[:-1]
                    data["enumName"] = enum.split(':') + ['']
                    data["enumName"] = ':'.join(data["enumName"])
                else:
                    cmds.error(
                        'enumName or en must be a list or join string list of `:`')
            else:
                cmds.error(
                    'enumName or en must be a list or join string list of `:`')
        else:
            data["attributeType"] = attr_type

        if not kwargs.has_key('defaultValue') and attr_type not in [
            "string"]:
            data["defaultValue"] = value
        elif kwargs.has_key('defaultValue') and attr_type not in ["string"]:
            data = Flags(kwargs, None, 'defaultValue', 'dv', dic=data)
        data = Flags(kwargs, None, 'minValue', 'min', dic=data)
        data = Flags(kwargs, None, 'maxValue', 'max', dic=data)

        data = Flags(kwargs, True, 'keyable', 'k', dic=data)
        data = Flags(kwargs, True, 'readable', 'r', dic=data)
        data = Flags(kwargs, True, 'storable', 's', dic=data)
        data = Flags(kwargs, True, 'writable', 'w', dic=data)

        if 'defaultValue' in data:
            if data['defaultValue'] == None:
                del data['defaultValue']
        print(data)
        cmds.addAttr(node, longName=long_name, **data)

        chbox = Flags(kwargs, True, 'channelBox', key='keyable', dic={})
        if chbox:
            cmds.setAttr('{}.{}'.format(node, long_name), e=True, **chbox)
    else:
        if attr_type != 'string':
            if not isinstance(value, (list, tuple)):
                value = [value]
            cmds.setAttr('{}.{}'.format(node, long_name), *value)
        else:
            cmds.setAttr('{}.{}'.format(node, long_name), value, type='string')

    return '{}.{}'.format(node, long_name)


@acceptString('attributes')
def lock_attr(node=str, attributes=list, lock=bool, keyable=bool):
    """Lock or unlock attributes of a node.
    Arguments:
        node(dagNode): The node with the attributes to lock/unlock.
        attributes (list of str): The list of the attributes to lock/unlock.
    """
    for attr_name in attributes:
        node.setAttr(attr_name, lock=lock, keyable=keyable)