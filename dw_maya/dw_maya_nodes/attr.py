from maya import cmds
from typing import Optional, List
from dw_maya.dw_decorators_utils import acceptString
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
    NUMERIC_TYPES = {"double", "long", "short", "bool", "int", "float", "byte", "doubleLinear", "doubleAngle"}
    LIST_TYPES = {"double3", "float3", "long3", "short3"}
    CONNECTION_TYPES = {"message"}

    # Compound vector/colour attributes — setAttr needs values *unpacked*
    # e.g. cmds.setAttr('joint.translate', x, y, z)
    COMPOUND_TYPES = {
        "double2", "double3", "double4",
        "float2",  "float3",  "float4",
        "long2",   "long3",   "long4",
        "short2",  "short3",  "short4",
    }

    # Array attributes — setAttr needs  (attr, list, type='doubleArray')
    ARRAY_TYPES = {
        "doubleArray", "floatArray", "Int32Array",
        "vectorArray", "pointArray", "stringArray",
        "matrix",  # 16-element flat list, type flag required
    }

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
        """
        check if the value if superior to another value
        """
        if isinstance(other, MAttr):
            return self.getAttr() > other.getAttr()
        return self.getAttr() > other

    def __lt__(self, other):
        """
        check if the value if inferior to another value
        """
        if isinstance(other, MAttr):
            return self.getAttr() < other.getAttr()
        return self.getAttr() < other

    def __ge__(self, other):
        """
        check if the value if superior or equal to another value
        """
        if isinstance(other, MAttr):
            return self.getAttr() >= other.getAttr()
        return self.getAttr() >= other

    def __le__(self, other):
        """
        check if the value if inferior or equal to another value
        """
        if isinstance(other, MAttr):
            return self.getAttr() <= other.getAttr()
        return self.getAttr() <= other

    # ------------------------------------------------------------------
    # In-place arithmetic helpers
    # ------------------------------------------------------------------

    def _raw_value(self, other):
        """Return the plain Python value of *other* (unwrap MAttr if needed)."""
        return other.getAttr() if isinstance(other, MAttr) else other

    def _inplace_op(self, op, other):
        """Apply *op(a, b)* element-wise for vectors, scalar otherwise.

        Handles the fact that ``cmds.getAttr`` returns ``[(x, y, z)]`` for
        compound attributes (LIST_TYPES), while ``cmds.setAttr`` expects the
        components unpacked as positional arguments.

        Args:
            op (callable): Binary operator, e.g. ``operator.add``.
            other: A plain scalar/sequence or another :class:`MAttr`.

        Returns:
            MAttr: *self*, so the in-place assignment keeps the wrapper alive.
        """
        current = self.getAttr()
        other_val = self._raw_value(other)

        if self._type in self.LIST_TYPES:
            # getAttr returns [(x, y, z)] — unwrap the outer list
            cv = current[0] if (
                isinstance(current, (list, tuple))
                and isinstance(current[0], (list, tuple))
            ) else current

            if isinstance(other_val, (list, tuple)):
                ov = other_val[0] if isinstance(other_val[0], (list, tuple)) else other_val
            else:
                ov = [other_val] * len(cv)   # broadcast scalar → vector

            new_vec = tuple(op(a, b) for a, b in zip(cv, ov))
            self.setAttr(*new_vec)           # setAttr needs unpacked components
        else:
            self.setAttr(op(current, other_val))

        return self  # ← critical: keep the MAttr alive after `a -= b`

    # ------------------------------------------------------------------
    # In-place arithmetic operators
    # ------------------------------------------------------------------

    def __iadd__(self, other):
        """``node.tx += value`` — adds *value* to the attribute in-place."""
        import operator
        return self._inplace_op(operator.add, other)

    def __isub__(self, other):
        """``node.tx -= value`` — subtracts *value* from the attribute in-place."""
        import operator
        return self._inplace_op(operator.sub, other)

    def __imul__(self, other):
        """``node.tx *= value`` — multiplies the attribute in-place.

        For vector attributes (double3 etc.) the scalar is broadcast to all
        components, or a matching sequence is applied element-wise.
        """
        import operator
        return self._inplace_op(operator.mul, other)

    def __itruediv__(self, other):
        """``node.tx /= value`` — true-divides the attribute in-place.

        Raises:
            ZeroDivisionError: If *other* (or any component of *other*) is 0.
        """
        import operator
        return self._inplace_op(operator.truediv, other)

    def __ifloordiv__(self, other):
        """``node.tx //= value`` — floor-divides the attribute in-place.

        Raises:
            ZeroDivisionError: If *other* (or any component of *other*) is 0.
        """
        import operator
        return self._inplace_op(operator.floordiv, other)

    def __imod__(self, other):
        """``node.tx %= value`` — applies modulo to the attribute in-place.

        Note:
            Modulo on vector attributes is applied component-wise.
        """
        import operator
        return self._inplace_op(operator.mod, other)

    def __ipow__(self, other):
        """``node.tx **= value`` — raises the attribute to a power in-place.

        Note:
            For vector attributes the exponent is applied component-wise.
            Fractional exponents on negative values will raise a ``ValueError``.
        """
        import operator
        return self._inplace_op(operator.pow, other)

    def __rshift__(self, other):
        """Connect attributes using the greater than operator.

        Enables the syntax: node.attr1 >> node.attr2
        """
        if isinstance(other, MAttr):
            cmds.connectAttr(self.fullattr, other.fullattr, force=True)
            logger.info(f'Connected {self.fullattr} to {other.fullattr}')
            return True
        else:
            logger.warning(f'Failed to connect {self.fullattr} to {other}')

    def __lshift__(self, other):
        """Connect attributes using the greater than operator.

        Enables the syntax: node.attr1 << node.attr2
        """
        if isinstance(other, MAttr):
            cmds.connectAttr(other.fullattr,self.fullattr,  force=True)
            logger.info(f'Connected {other.fullattr} to {self.fullattr}')
            return True
        else:
            logger.warning(f'Failed to connect {self.fullattr} to {other}')

    def __eq__(self, other):
        """Check if two attributes or an attribute and a value are equal."""
        if isinstance(other, MAttr):
            return self.getAttr() == other.getAttr()
        else:
            return self.getAttr() == other

    def __ne__(self, other):
        """Check if two attributes or an attribute and a value are not equal. (unnecessary in Python 3)"""
        return not self.__eq__(other)

    def __bool__(self):
        t = self._type

        # Numeric scalar → truthiness directe (0 = False, sinon True)
        if t in self.NUMERIC_TYPES:
            return bool(self.getAttr())

        # Compound/list → any value non-zero
        if t in self.LIST_TYPES:
            value = self.getAttr()  # [(x, y, z)]
            return any(v != 0 for v in value[0])

        # message ou autre → existe = True
        return True

    def setAttr(self, *args, **kwargs):
        """Set the attribute value with automatic type-aware dispatch.

        Handles three cases transparently so callers never need to worry
        about Maya's quirky ``setAttr`` signatures:

        * **Compound** (``double3``, ``float3``, …)  — values are *unpacked*:
          ``cmds.setAttr('node.translate', x, y, z)``
        * **Array** (``doubleArray``, ``Int32Array``, …) — list passed with
          ``type=`` flag: ``cmds.setAttr('node.weights', [...], type='doubleArray')``
        * **Scalar / string / other** — passed as-is.

        Args:
            *args:    Value(s) to set.  A single sequence is dispatched by type.
            **kwargs: Extra flags forwarded to ``cmds.setAttr`` (e.g. ``type=``).
        """
        full_attr = f'{self._node}.{self.attr}'

        # No-value call (e.g. trigger evaluation)
        if not args:
            cmds.setAttr(full_attr, **kwargs)
            return

        # Multiple positional args → already unpacked by caller
        if len(args) > 1:
            cmds.setAttr(full_attr, *args, **kwargs)
            return

        value = args[0]

        # --- string ---------------------------------------------------------
        if isinstance(value, str):
            cmds.setAttr(full_attr, value, type='string', **kwargs)
            return

        # --- sequence (list or tuple) ---------------------------------------
        if isinstance(value, (list, tuple)) and 'type' not in kwargs:
            attr_type = self._type

            if attr_type in self.COMPOUND_TYPES:
                # Flatten one level: getAttr returns [(x,y,z)]; setAttr needs x,y,z
                flat = (value[0] if (len(value) == 1
                                     and isinstance(value[0], (list, tuple)))
                        else value)
                cmds.setAttr(full_attr, *flat, **kwargs)
                return

            if attr_type in self.ARRAY_TYPES:
                # Array attrs need explicit type= flag
                cmds.setAttr(full_attr, value, type=attr_type, **kwargs)
                return

            # Unknown sequence type — try unpack first, fall back to list
            try:
                cmds.setAttr(full_attr, *value, **kwargs)
            except Exception:
                cmds.setAttr(full_attr, value, **kwargs)
            return

        # --- scalar (int, float, bool …) ------------------------------------
        cmds.setAttr(full_attr, value, **kwargs)

    def getAttr(self, **kwargs):
        """
        this is the cmds.getAttr
        Returns:
            Any: cmds.getAttr() — compound attributes (double3 etc.) are
            returned as a plain tuple ``(x, y, z)`` rather than Maya's raw
            ``[(x, y, z)]`` list-of-tuple, so arithmetic and assignment work
            naturally without extra unwrapping.
        """
        if self.attr in self.listAttr(self.attr) or self._COMPOUND_PATTERN.search(self.attr):
            result = cmds.getAttr(f'{self._node}.{self.attr}', **kwargs)
            # Normalize Maya compound format: [(x, y, z)] → (x, y, z)
            if (isinstance(result, list) and len(result) == 1
                    and isinstance(result[0], tuple)):
                return result[0]
            return result

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
            raise ValueError(f"No valid attributes found in: {invalid_input}")

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
        return f'{self.node}.{self.attr}'

    @property
    def _type(self):
        """
        Returns:
            str: type of the current attribute
        """
        o = cmds.getAttr(f'{self._node}.{self.attr}', type=True)
        if isinstance(o, (list, tuple)):
            return list(set(o))
        return o

    def listConnections(self, **kwargs):
        """List all connections to/from this attribute."""
        return cmds.listConnections(f'{self._node}.{self.attr}', **kwargs)

    def disconnectAttr(self, source=True, destination=True):
        """Disconnect this attribute from its connections."""
        attr = f'{self._node}.{self.attr}'
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