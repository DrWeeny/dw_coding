from maya import cmds
from typing import Optional, List
from dw_maya.dw_decorators import acceptString
import re

from dw_logger import get_logger

logger = get_logger()

class MAttr(object):
    """Wrapper for Maya attributes providing Pythonic access.

    Provides a clean interface for getting/setting attribute values and
    managing connections.

    Args:
        node: Parent node name
        attr: Attribute name

    Examples:
        >>> node = MayaNode('pCube1')
        >>> tx = node.translateX  # Returns MAttr
        >>> tx.value = 10  # Sets translate X
        >>> tx.connect('pCube2.translateX')  # Create connection
    """
    _COMPOUND_PATTERN = re.compile('\[(\d+)?:(\d+)?\]')

    def __init__(self, node: str, attr:str ='result'):
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
        Dynamically access Maya node attributes.
        """
        myattr = f"{self.attr}.{attr}"
        if myattr in self.listAttr(myattr):
            return MAttr(self._node, myattr)
        try:
            return object.__getattribute__(self, attr)
        except AttributeError:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{attr}'")

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
        """Connect attributes using the greater than operator.

        Enables the syntax: node.attr1 > node.attr2

        Args:
            other (MAttr): Target attribute to connect to

        Returns:
            bool: True if connection succeeded

        Example:
            >>> sphere.tx > cube.tx  # Connects translateX
        """
        if isinstance(other, MAttr):
            cmds.connectAttr(self.fullattr, other.fullattr, force=True)
            print(f'Connected {self.fullattr} to {other.fullattr}')
            return True
        else:
            print(f'FAILED {self.fullattr} to {other.fullattr}')

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
        if self.attr in self.listAttr(self.attr) or self._COMPOUND_PATTERN.search(self.attr):
            return cmds.getAttr('{}.{}'.format(self._node, self.attr), **kwargs)

    @acceptString('destination')
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

        if self.attr in self.listAttr(self.attr) or self._COMPOUND_PATTERN.search(self.attr):
            try:
                cmds.connectAttr(f'{self._node}.{self.attr}', destination, force=force)
            except Exception as e:
                logger.error(f"Failed to connect {self._node}.{self.attr}: {e}")

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
    def attr(self):
        """
        Current Attribute
        Returns:
            str: attribute name
        """
        return self.__dict__['attribute']

    @property
    def _node(self):
        """
        This is the node inherated
        Returns:
            str: node from MayaNode
        """
        return self.__dict__['node']

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