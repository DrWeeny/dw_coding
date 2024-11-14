import sys, os
from typing import List

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)


import maya.cmds as cmds
import maya.OpenMaya as om
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_presets_io as dwpreset
import dw_maya.dw_decorators as dwdeco
import dw_maya.dw_json as dwjson
import re

class MAttr(object):
    """
    Represent a Maya attribute and provide a Pythonic interface for interacting with Maya nodes' attributes.

    Args:
        node (str): a string for the maya node affected
        attr (str): a string that represent the attribute
    Attributes:
        attr_bypass (str): regex to bypass the compound attributes, because i need to connect and getattr
    """
    attr_bypass = re.compile('\[(\d+)?:(\d+)?\]')

    def __init__(self, node, attr='result'):
        self.__dict__['node'] = node  #: str: current priority node evaluated
        self.__dict__['attribute'] = attr  #: str: current priority node evaluated
        self.__dict__['idx'] = 0  #: str: current priority node evaluated

    def __getitem__(self, item):
        """
        getitem has been overrided so you can select the compound attributes
        ``mn = MayaNode('cluster1')``
        ``mn.node.weightList[0]``
        ``mn.node.weightList[1].weights[0:100]``

        Notes:
            the notations with list[0:0:0] is class slice whereas list[0] is just and int

        Args:
            item (Any): should be slice class or an int

        Returns:
            cls : MAttr is updated with the chosen index/slice
        """
        if isinstance(item, int):
            self.__dict__['attribute'] = f'{self.attr}[{item}]'
        else:
            if not item.start and not item.stop and not item.step:
                item = ':'
            else:
                item = ':'.join([str(i) for i in [item.start, item.stop, item.step] if i != None])
            self.__dict__['attribute'] = f'{self.attr}[{item}]'
        return self

    def __getattr__(self, attr):
        """
        Override to dynamically access Maya node attributes.

        Args:
            attr (str): name of the attribute

        Returns:
            str: it join all the attributes that has been chained : weightList[0].weight

        """
        myattr = f'{self.attribute}.{attr}'
        if myattr in self.listAttr(myattr):
            return MAttr(self._node, myattr)
        else:
            return self.__getattribute__(attr)

    def __iter__(self):
        """
        To loop throught attributes values if needed (for example if we have an enum)
        Returns:
        """
        return self

    def __next__(self):
        """
        Support iteration over attribute values.

        Returns:
            Next value from the attribute.

        Raises:
            StopIteration: If the end of the list is reached.
        """
        mylist = self.getAttr()
        if not isinstance(mylist, (list, tuple)):
            mylist = [mylist]
        else:
            if isinstance(mylist[0], (list, tuple)):
                if len(mylist) == 1:
                    mylist = mylist[0]
        try:
            item = mylist[self.__dict__['idx']]
        except IndexError:
            raise StopIteration()
        self.__dict__['idx'] += 1
        return item

    def __repr__(self):
        """
        Represent the data when you execute the class
        Returns:
            str: type attribute + value
        """
        try:
            return f'<<{str(self._type)}>>\n{" " * 16}{self.getAttr()}'
        except Exception as e:
            return f"Warning: Could not retrieve value. Error: {e}"


    def __str__(self):
        """
        String representation of the attribute value
        Returns:
            str: return the getAttr() as a string
        """
        return str(self.getAttr())

    def __gt__(self, other):
        """Connect this attribute to another attribute using the '>' operator."""

        if isinstance(other, MAttr):
            cmds.connectAttr(self.fullattr, other.fullattr, force=True)
            print(f'Connected {self.fullattr} to {other.fullattr}')
            return True

    def __eq__(self, other):
        """Check if two attributes or an attribute and a value are equal."""
        if isinstance(other, MAttr):
            return self.getAttr() == other.getAttr()
        else:
            return self.getAttr() == other

    def __ne__(self, other):
        """Check if two attributes or an attribute and a value are not equal. (unnecessary in Python 3)"""
        return not self.__eq__(other)

    def setAttr(self, *args, **kwargs):
        """
        This is the cmds.setAttr but with string type supported with no flags requirement
        Args:
            *args (Any): maya arguments for the commands
            **kwargs (Any): all the flag you would try to parse
        """
        if args:
            if not isinstance(args[0], str) and len(args) == 1:
                cmds.setAttr('{}.{}'.format(self._node, self.attr), args[0], **kwargs)
            elif isinstance(args[0], str) and len(args) == 1:
                cmds.setAttr('{}.{}'.format(self._node, self.attr), args[0], type='string', **kwargs)
        elif kwargs:
            cmds.setAttr('{}.{}'.format(self._node, self.attr), *args, **kwargs)

    def getAttr(self, **kwargs):
        """
        this is the cmds.getAttr
        Returns:
            Any: cmds.getAttr()
        """
        if self.attr in self.listAttr(self.attr) or self.attr_bypass.search(self.attr):
            return cmds.getAttr('{}.{}'.format(self._node, self.attr), **kwargs)

    @dwdeco.acceptString('destination')
    def connectAttr(self, destination: List[str], force=True):
        """
        Connects this attribute to another attribute(s).

        Args:
            destination (list): List of attributes to connect to.
            force (bool): Whether to force the connection.

        Raises:
            ValueError: If invalid destinations are specified.
        """
        _isConnec = [True if '.' in i and cmds.ls(i) else False for i in destination]
        if not all(_isConnec):
            invalid_input = ', '.join([i for x, i in zip(_isConnec, destination) if not x])
            cmds.error(f"No valid attributes found in: {invalid_input}")

        if self.attr in self.listAttr(self.attr) or self.attr_bypass.search(self.attr):
            try:
                cmds.connectAttr(f'{self._node}.{self.attr}', d, force=force)
            except Exception as e:
                print(f"Failed to connect {self._node}.{self.attr} to {d}: {e}")

    def setChannelBoxVisibility(self, hide=True):
        """Hide or show the attribute in the channel box."""
        cmds.setAttr(self.fullattr, k=not hide)

    def listAttr(self, attr=None):
        """
        used to check if the attribute exist in his short or long form
        Args:
            attr (str): check if the attribute exist
        Returns:
            list: all the attributes available or the attribute
        """
        if attr:
            fullattr = f'{self._node}.{attr}'
            return cmds.listAttr(fullattr) + cmds.listAttr(fullattr, shortNames=True)
        return cmds.listAttr(self._node) + cmds.listAttr(self._node, shortNames=True)

    @property
    def _node(self):
        """
        This is the node inherated
        Returns:
            str: node from MayaNode
        """
        return self.__dict__['node']

    @property
    def attr(self):
        """
        Current Attribute
        Returns:
            str: attribute name
        """
        return self.__dict__['attribute']

    @property
    def fullattr(self):
        return '{}.{}'.format(self.node, self.attr)

    @property
    def _type(self):
        """
        Returns:
            str: type of the current attribute
        """
        o = cmds.getAttr('{}.{}'.format(self._node, self.attr), type=True)
        if isinstance(o, (list, tuple)):
            return list(set(o))
        return o

    def listConnections(self, **kwargs):
        """List all connections to/from this attribute."""
        attr = '{}.{}'.format(self._node, self.attr)
        return cmds.listConnections(attr, **kwargs)

    def disconnectAttr(self, source=True, destination=True):
        """Disconnect this attribute from its connections."""
        attr = '{}.{}'.format(self._node, self.attr)
        conn = cmds.listConnections(attr, p=True, d=False, s=True,
                                    scn=True)
        dest = cmds.listConnections(attr, p=True, d=True, s=False,
                                    scn=True)
        if conn and source:
            for c in conn:
                cmds.disconnectAttr(c, attr)

        if dest and destination:
            for d in dest:
                cmds.disconnectAttr(attr, d)

class ObjPointer(object):
    """
    A class that wraps around Maya's MObject, MDagPath, and MFnDependencyNode.

    Provides functionality to handle Maya nodes, their paths, and names.

    Derived from: https://www.toadstorm.com/blog/?p=628

    Args:
        node_name (str): The name of the Maya node to wrap.

    Attributes:
        _mobject (om.MObject): The Maya MObject of the node.
        _mdagpath (om.MDagPath): The DAG path to the node.
        _node (om.MFnDependencyNode): A function set for the Maya node.
    """

    def __init__(self, node_name: str):
        """
        Initialize the ObjPointer with the given node name.

        Args:
            node_name (str): The name of the Maya node.
        """
        self.__dict__['_mobject'] = om.MObject()
        self.__dict__['_mdagpath'] = om.MDagPath()
        self.__dict__['_node'] = om.MFnDependencyNode()
        selection = om.MSelectionList()
        try:
            selection.add(node_name)
            selection.getDependNode(0, self.__dict__['_mobject'])
            self.__dict__['_node'] = om.MFnDependencyNode(self.__dict__['_mobject'])
            selection.getDagPath(0, self.__dict__['_mdagpath'], om.MObject())
        except:
            pass

    def setDAG(self, node_name):
        """
        Set the DAG path for the given node name.

        This is used to reset or update the DAG path for the Maya node.

        Args:
            node_name (str): The name of the Maya node.
        """
        self.__dict__['_mobject'] = om.MObject()
        self.__dict__['_mdagpath'] = om.MDagPath()
        self.__dict__['_node'] = om.MFnDependencyNode()
        selection = om.MSelectionList()
        try:
            selection.add(node_name)
            selection.getDependNode(0, self.__dict__['_mobject'])
            self.__dict__['_node'] = om.MFnDependencyNode(self.__dict__['_mobject'])
            selection.getDagPath(0, self.__dict__['_mdagpath'], om.MObject())
        except Exception as e:
            print(f"Failed to initialize node {node_name}: {e}")

    def name(self, long: bool = False) -> str:
        """
        Get the name of the Maya node.

        Args:
            long (bool): If True, return the full DAG path; otherwise, return the partial path.

        Returns:
            str: The node's name, either as a full DAG path or a partial name.
        """
        if self.__dict__['_mdagpath'].isValid():
            if long:
                return self.__dict__['_mdagpath'].fullPathName()
            return self.__dict__['_mdagpath'].partialPathName()
        else:
            if not self.__dict__['_mobject'].isNull():
                return self.__dict__['_node'].name()


class MayaNode(ObjPointer):
    """Represent a maya node as a class like pymel

    Only provide the name as a string, if you use preset, you can create a new node

    Note:
        Should use maya api for getting the node

    Args:
        name (str): a string for the maya node you want to encapsulate
        preset (:obj:`dict`, optional): Used for creating a new node from 'attrPreset'
        blendValue (float, optional): Value used for attribute blending (default is 1)
        you can also just specify the nodeType with a string instead

    Attributes:
        maya_attr_name (maya_data): Any attribute from the name will look for actual maya attribute

    """

    def __init__(self, name: str, preset: dict, blendValue=1):
        super(MayaNode, self).__init__(name)

        # this dict method is used to avoid calling __getattr__
        _input = self.name()
        if _input:
            self.__dict__['node'] = _input #: str: current priority node evaluated
        else:
            self.__dict__['node'] = name
        self.__dict__['item'] = 1  #: int: can be either 0 or 1 and should be exented with Mesh or Cluster

        preset = preset or {}  # Default to an empty dict if preset is None
        if preset:
            if ':' in name:
                targ_ns = name.rsplit(':', 1)[0]
            else:
                targ_ns = ''

            self.loadNode(preset, blendValue, targ_ns)

    def __getitem__(self, item: int):
        """
        getitem has been overrided so you can select the main nodes sh or tr so when you do:
        ``mn = MayaNode('pCube1')``
        ``mn[0].node`` result as the transform
        ``mn[1].node`` result as the shape

        Note:
            By default ``mn.node`` is the transform
        """
        return self.setNode(item)

    def __getattr__(self, attr: str):
        """
            Override to dynamically access Maya node attributes.
            Caches compound attributes to optimize repeated access and set them
        if you type an attribute, it will try to find if it exists in either shape or transform
        if it exists in both, it will always warn you that it returns shape in priority
        ``mn = MayaNode('pCube1')``
        ``mn.translateX = 10`` result in doing a cmds.setAttr
        ``mn.translateX.setAttr(10)``
        ``mn.translateX.getAttr()`` note that you to use get in order to do getAttr otherwise it __repr__ or __str__

        ``mn = MayaNode('cluster1')``
        ``mn.weightList[1].weights.getAttr()`` is equivalent of cmds.getAttr('cluster1.weightList[1].weights[:]')

        Note:
            You cant have the value without .getAttr()
        """
        myattr = f'{self.attribute}.{attr}'
        if hasattr(self, '_attr_cache') and myattr in self._attr_cache:
            return self._attr_cache[myattr]
        if myattr in self.listAttr(myattr):
            cached_attr = MAttr(self._node, myattr)
            # Cache the attribute for repeated access
            self._attr_cache[myattr] = cached_attr
            return cached_attr
        else:
            return self.__getattribute__(attr)

    def __setattr__(self, key: str, value):
        """
        setattr has been overrided so you can set the value also with `=`
        ``mn = MayaNode('pCube1')``
        ``mn.translateX = 10`` result in doing a cmds.setAttr

        Note:
            it support maya kwargs/flags, the method is support string type
        """
        if key in self.listAttr(key):
            try:
                if not isinstance(value, str):
                    MAttr(self.node, key).setAttr(value)
            except AttributeError:
                if not isinstance(value, str):
                    cmds.setAttr('{}.{}'.format(self.node, self.attr), value)
                elif isinstance(value, str):
                    cmds.setAttr('{}.{}'.format(self.node, self.attr), value, type='string')

    @property
    def __node(self) -> str:
        """
        This one is used to get the actual node from __dict__
        """
        return self.name()

    def setNode(self, index: int):
        """
        set the current node by __dict__, it is used with __getitem__
        Args:
            index (int): 0 and 1 available by default, might need more index for cluster for example
        Returns:
            cls: return itself

        """
        self.__dict__['item'] = index
        return self

    @property
    def node(self) -> str:
        """Returns the current node (transform or shape)."""
        id = self.__dict__['item']
        if id == 0:
            return self.tr or self.sh
        else:
            return self.sh or self.tr

    @property
    def nodeType(self) -> str:
        """str: return the current node type, by default it always return the shape"""
        return cmds.nodeType(self.__node or self.sh)

    @property
    def sh(self) -> str:
        """str: return the main node (everything but not transform)"""
        if cmds.nodeType(self.__node) != 'transform':
            return self.__node
        else:
            _sh = cmds.listRelatives(self.__node, type='shape', ni=True)
            return _sh[0] if _sh else None

    @property
    def tr(self) -> str:
        """Returns the transform node, or shape if transform doesn't exist."""
        if cmds.nodeType(self.__node) == 'transform':
            return self.__node
        else:
            _tr = cmds.listRelatives(self.__node, p=True)
            if _tr:
                _sh = cmds.listRelatives(_tr, type='shape', ni=True)
                if _sh:
                    return _tr[0]
        return self.sh

    def addAttr(self, long_name: str, value=None, attr_type='long', **kwargs) -> 'MAttr':
        """ like cmds.addAttr
        Args:
            node=str,
            long_name=str,
            value=None,
            attr_type='long'
            *args: from cmds
            **kwargs: derived from cmds

        Returns:
            MAttr

        """
        out = dwu.add_attr(self.__node,
                           long_name=long_name,
                           value=value,
                           attr_type=attr_type,
                           **kwargs)
        return MAttr(self.node, out.split('.')[-1])

    def listAttr(self, attr: str = None) -> list:

        """ list all the attr of the node or if the attr exist

        Args:
            attr (str, optional): name of an attribute

        Returns:
            list: it gives the list of attributes existing

        """

        current = self.node
        tr = self.tr
        sh = self.sh

        attr_list_tr = []
        if tr:
            attr_list_tr += cmds.listAttr(tr)
            attr_list_tr += cmds.listAttr(tr, shortNames = True)

        attr_list_sh = []
        if sh:
            attr_list_sh += cmds.listAttr(sh)
            attr_list_sh += cmds.listAttr(sh, shortNames = True)

        # current state of the class is on transform
        if current == tr:
            if attr:
                if attr in attr_list_tr and attr in attr_list_sh:
                    if sh != tr:
                        cmds.warning(f'Attribute `{attr}` exists in both shape and transform, returning transform value.')

                elif attr not in attr_list_tr:
                    if attr in attr_list_sh:
                        self.__dict__['item'] = 1
                        return attr_list_sh
            return attr_list_tr
        # current state of the class is shape
        elif current == sh:
            if attr:
                if attr in attr_list_tr and attr in attr_list_sh:
                    if sh != tr:
                        cmds.warning(f'Attribute `{attr}` exists in both shape and transform, returning shape value.')
                elif attr not in attr_list_sh:
                    if attr in attr_list_tr:
                        self.__dict__['item'] = 0
                        return attr_list_tr
            return attr_list_sh

    def getAttr(self, attr) -> "MAttr":
        if attr in self.listAttr(attr):
            return MAttr(self.node, attr)

    def getNamespace(self) -> str:
        short = self.node.split('|')[-1]
        if ":" in short:
            return short.rsplit(':', 1)[0]
        else:
            return ':'

    def attrPreset(self, node=None) -> dict:
        """
        common method to create a preset of the node
        if nothing is specified it will try to make a dictionnary with both tr and sh

        Args:
            node (str, optional): name of the node

        Returns:
            dict: it gives the list of attributes existing

        """

        if node is not None:
            if node == 0:
                return dwpreset.createAttrPreset(self.tr)
            else:
                return dwpreset.createAttrPreset(self.sh)
        else:
            if self.tr == self.sh:
                return dwpreset.createAttrPreset(self.node)
            else:
                tr_dic = dwpreset.createAttrPreset(self.tr)
                sh_dic = dwpreset.createAttrPreset(self.sh)
                combine_dic = dwu.merge_two_dicts(tr_dic, sh_dic)

                out_dic = {}
                key = self.tr.split(':')[-1]
                out_dic[key] = combine_dic
                out_dic['{}_nodeType'.format(key)] = self.nodeType

                return out_dic

    def listHistory(self, **kwargs) -> list:
        _type = None
        if 'type' in kwargs:
            _type = kwargs['type']
            del kwargs['type']
        sel = cmds.listHistory(self.node, **kwargs)
        if sel and _type:
            sel = [s for s in sel if cmds.ls(s, type=_type)]
        return sel

    def parentTo(self, node):
        if isinstance(node, MayaNode):
            cmds.parent(self.tr, node.tr)
        else:
            cmds.parent(self.tr, node)

    def rename(self, name: str) -> str:
        """
        Rename the transform and the shape and update the class with the new name
        It keeps the maya way of renaming where, renaming the shape will rename trnsform
        and if you rename the transform will rename the shape
        Also it will try to keep the Shape with Shape at the end
        If there is no transform, it will make a straight rename

        Args:
            node (str, optional): name of the node

        Returns:
            cls: the class self is returned so you can keep playing with the node
        """
        sh_p = '[Ss]hape(\d+)?$'
        p = re.compile(sh_p)

        try:
            if self.tr == self.sh:
                cmds.rename(self.tr, name)
            else:
                if self.sh == name:
                    # if shape, was set on creation
                    _tmp = cmds.rename(self.sh, 'dwTmpRename')
                    # if name has maya Shape pattern, do the replace
                    if p.search(name):
                        id = p.search(name).group(1) or ''
                        _sh = cmds.rename(self.sh, name)
                        self.__dict__['node'] = name
                        _tr_name = p.sub(id, name)
                        self.__dict__['node'] = name
                        _tr = cmds.rename(self.tr, _tr_name, ignoreShape=True)
                    else:
                        _sh = cmds.rename(self.sh, name)
                        self.__dict__['node'] = name
                        cmds.rename(self.tr, name, ignoreShape=True)
                        self.__dict__['node'] = name
                        cmds.rename(self.sh, name + 'Shape')
                else:
                    cmds.rename(self.tr, name, ignoreShape=True)
                    self.__dict__['node'] = name
                    cmds.rename(self.sh, name+'Shape')
            self.__dict__['node'] = name
            return self.tr
        except Exception as e:
            print(f"Failed to rename the node: {e}")

    def createNode(self, preset, targ_ns=':'):
        """
        Like maya cmds.createNode() but work with preset dictionnary or single string
        One of the good thing, it is giving a constant name. IE :

        `cmds.createNode('mesh', name='toto')` result into a polysurface1 transform and a shape mesh called toto
        `mn = MayaNode('toto', 'mesh')` result creating toto transform and a shape called totoShape

        Also if the preset is a dictionnary it must contain a key:nodeType, value:mesh and it will set all the other
        attributes.

        Args:
            preset (Any):

        Returns:
            str: new node name
            :param targ_ns: namespace

        """

        if isinstance(preset, str):
            # If we give some string, it will conform the dictionnary
            _type = preset[:]
            if _type not in cmds.ls(nt=True):
                cmds.error('Please provide a valid : string nodeType or a key `nodeType`')
            preset = {self.__dict__['node'] + '_nodeType': _type}

        # we try to determine if we create a node from scratch or if we load it
        # in case of loading, we need to remap the dictionnary keys with the correct namespace
        if targ_ns == ':'  or targ_ns == '':
            # in this case we have created the node with a basestring type so we need to add the namespace
            _type = self.__dict__['node'] + '_nodeType'
            if _type not in preset:
                _type = targ_ns + ':' + self.__dict__['node'] + '_nodeType'
        else:
            # In this case we create a node with a namespace but the preset is namespace agnostic
            _type = self.__dict__['node'] + '_nodeType'
            if _type not in preset:
                _type = self.__dict__['node'].rsplit(':', 1)[-1] + '_nodeType'

        # this part is for creating a good node name, at the end of the proc it will rename
        flags = dwu.Flags(preset, self.__dict__['node'], 'name', 'n', dic={})

        new_node = cmds.createNode(preset[_type])
        self.setDAG(new_node)
        self.__dict__['node'] = new_node

        if flags:
            new_name = self.rename(**flags)
            return new_name

    def saveNode(self, path: str, file: str):
        """
        save the node as json
        Args:
            path (str): /path/gneh/
            file (str): myfile

        Returns:
            /path/gneh/myfile.json
        """
        if path.startswith('/'):
            if not path.endswith('/'):
                path += '/'
            if '.' not in file:
                file += '.json'
            fullpath = path + file

            print('node saved as json to {}'.format(fullpath))
            return dwjson.saveJson(fullpath, self.attrPreset())

    def loadNode(self, preset: dict, blend=1, targ_ns=':'):
        """

        Args:
            preset ():

        Returns:
        :param preset: dictionnary of a preset created by this library
        :param blend: like maya it is used to blend all values with the current values with this amount
        TODO : make a git like ui to compare diff between values
        :param targ_ns: namespace to transfer the value (so it can be one object transferred to another one)

        """

        if isinstance(preset, str):
            self.createNode(preset)

        if not isinstance(preset, str):
            for k in preset:
                if not k.endswith('_nodeType'):
                    if targ_ns not in [':', '']:
                        nodename = targ_ns + ':' + k
                    else:
                        nodename = k
                    ntype = preset[k + '_nodeType']
                    if nodename == self.__dict__['node']:
                        if not cmds.objExists(nodename):
                            new_name = self.createNode(preset, targ_ns)
                        else:
                            new_name = k

                        dwpreset.blendAttrDic(k, new_name, preset[k], blend)
                        mainType = preset[k][k]['nodeType']
                        if mainType != ntype:
                            for sh in preset[k]:
                                if 'nodeType' in preset[k][sh]:
                                    if preset[k][sh]['nodeType'] == ntype:
                                        dwpreset.blendAttrDic(sh, self.sh, preset[k], blend)
                                        break
                        break
