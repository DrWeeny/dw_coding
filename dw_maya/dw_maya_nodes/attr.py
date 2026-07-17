from maya import cmds
import maya.api.OpenMaya as om
from typing import Optional, List
from dw_maya.dw_decorators import acceptString
import re

from dw_logger import get_logger

logger = get_logger()


def _iter_connected_pairs(plug: om.MPlug,
                          source: bool = True,
                          destination: bool = True):
    """Yield (source_plug, destination_plug) names for every connection on
    ``plug``, recursing into compound children and array elements.

    cmds.listConnections on a parent plug does not report its children's
    connections (asking on ``translate`` misses a keyed ``translateX``);
    walking the MPlug tree catches them all with the exact plug names.
    """
    if plug.isArray:
        for i in range(plug.evaluateNumElements()):
            yield from _iter_connected_pairs(plug.elementByPhysicalIndex(i),
                                             source,
                                             destination)
        return
    if plug.isCompound:
        for i in range(plug.numChildren()):
            yield from _iter_connected_pairs(plug.child(i),
                                             source,
                                             destination)
        # No return: the compound itself can be connected as a whole.
    if source and plug.isDestination:
        yield (plug.source().name(), plug.name())
    if destination and plug.isSource:
        for dst in plug.destinations():
            yield (plug.name(), dst.name())

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

    # Attribute types are immutable in Maya (you cannot change a double to a
    # string after creation).  Caching is therefore safe for the full session.
    # Cleared on file new/open via MayaNode._clear_all_caches().
    _type_cache: dict = {}

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
        # warning: this mutates the MAttr in place and returns self. Safe in
        # normal chains because MayaNode.__getattr__ hands out a fresh MAttr
        # per access, but a *stored* wrapper accumulates indices:
        #   w = mn.weightList; w[0]; w[1]  ->  'weightList[0][1]'
        # todo: return a new MAttr(self._node, indexed_attr) instead of
        # mutating self (behavior change - audit chained callers first).
        if isinstance(item, int):
            self.__dict__['attribute'] = f'{self.attr}[{item}]'
        else:
            if not item.start and not item.stop and not item.step:
                item = ':'
            else:
                item = ':'.join([str(i) for i in [item.start, item.stop, item.step] if i != None])
            self.__dict__['attribute'] = f'{self.attr}[{item}]'
        return self

    def __setitem__(self, item, value):
        """Assign values through index/slice notation.

        Enables the natural counterpart of the sliced read::

            node.weightList[0].weights[0:7] = values   # multi of scalars
            node.weightList[0].weights[:] = values     # explicit range rewrite
            node.myArrays[2] = values                  # doubleArray element

        Maya cannot expand an unbounded ``:`` when the multi holds no element
        plug yet (unpainted deformer weights), so a full or open-ended slice
        is rewritten to an explicit ``[start:stop]`` computed from the value
        count - which also lets ``setAttr`` create the missing elements.

        Note:
            Slice bounds follow Maya's *inclusive* plug ranges, matching what
            ``__getitem__`` builds (``[0:7]`` is 8 elements), not Python's
            exclusive slicing.
        """
        if isinstance(item, int):
            MAttr(self._node, f'{self.attr}[{item}]').setAttr(value)
            return
        if not isinstance(item, slice):
            raise TypeError(
                f'MAttr indices must be int or slice, not {type(item).__name__}'
            )
        if item.step not in (None, 1):
            raise ValueError('MAttr slice assignment does not support a step')

        values = list(value) if isinstance(value, (list, tuple)) else [value]
        if not values:
            return

        start = item.start if item.start is not None else 0
        stop = item.stop if item.stop is not None else start + len(values) - 1

        # Elements that are themselves sequences (multi of doubleArray etc.)
        # need one type-dispatched setAttr per element.
        if isinstance(values[0], (list, tuple)):
            for offset, element in enumerate(values):
                MAttr(self._node, f'{self.attr}[{start + offset}]').setAttr(element)
            return

        cmds.setAttr(f'{self._node}.{self.attr}[{start}:{stop}]',
                     *values,
                     size=len(values))

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
        # Pattern check first: it is free, and cmds.listAttr raises on a
        # slice plug whose elements do not exist yet (virgin multi).
        if self._COMPOUND_PATTERN.search(self.attr) or self.attr in self.listAttr(self.attr):
            try:
                result = cmds.getAttr(f'{self._node}.{self.attr}', **kwargs)
            except (RuntimeError, ValueError):
                # Maya expands '[:]' over *existing* element plugs; a sparse
                # multi with no element yet (e.g. unpainted deformer weights)
                # matches nothing and errors. An empty multi reads as [].
                if self.attr.endswith('[:]'):
                    base = self.attr[:-3]
                    try:
                        if not cmds.getAttr(f'{self._node}.{base}', size=True):
                            return []
                    except (RuntimeError, ValueError):
                        # The parent element can itself be unmaterialized
                        # (weightList[0] on a virgin cluster), failing the
                        # size probe. If the leaf attribute exists on the
                        # node, the path is valid but empty - not a typo.
                        leaf = re.sub(r'\[[^\]]*\]', '', base).split('.')[-1]
                        try:
                            if cmds.attributeQuery(leaf, node=self._node, exists=True):
                                return []
                        except RuntimeError:
                            pass
                raise
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
        Return the attribute's type string, using a class-level cache.

        Attribute types are immutable in Maya, so the cached value is always
        valid for the life of the session.  The cache is cleared globally by
        MayaNode._clear_all_caches() on file-new / file-open events.

        Returns:
            str: Maya attribute type (e.g. 'double', 'double3', 'message').
        """
        cache_key = f"{self._node}.{self.attr}"
        cached = MAttr._type_cache.get(cache_key)
        if cached is not None:
            return cached
        result = cmds.getAttr(cache_key, type=True)
        if isinstance(result, (list, tuple)):
            # Sliced/multi plugs report one type per element; a homogeneous
            # list collapses to its scalar string so setAttr's set-membership
            # dispatch works (a list is unhashable).
            dedup = list(set(result))
            result = dedup[0] if len(dedup) == 1 else dedup
        MAttr._type_cache[cache_key] = result
        return result

    @classmethod
    def invalidate_type_cache(cls, node: Optional[str] = None) -> None:
        """
        Clear the attribute type cache for a specific node or entirely.

        Normally not needed (types are immutable), but useful after
        cmds.deleteAttr or scene import operations.

        Args:
            node: Node name/path whose entries to remove.
                  When None, the entire cache is cleared.

        Example:
            >>> MAttr.invalidate_type_cache("pCube1")
            >>> MAttr.invalidate_type_cache()  # clear all
        """
        if node is None:
            cls._type_cache.clear()
        else:
            prefix = f"{node}."
            stale = [k for k in cls._type_cache if k.startswith(prefix)]
            for k in stale:
                del cls._type_cache[k]

    def listConnections(self, **kwargs):
        """List all connections to/from this attribute."""
        return cmds.listConnections(f'{self._node}.{self.attr}', **kwargs)

    def disconnectAttr(self,
                       source: bool = True,
                       destination: bool = True) -> list:
        """Break every connection on this plug, children/elements included.

        Walks the MPlug tree so a child/element connection is caught when
        asking on the parent (e.g. a keyed ``translateX`` when asking on
        ``translate``), and the disconnect targets the plug really wired in
        (a unitConversion, not the node beyond it).

        Args:
            source: Break incoming connections.
            destination: Break outgoing connections.

        Returns:
            list: The broken connections as (source_plug, destination_plug).
        """
        attr = f'{self._node}.{self.attr}'
        sel = om.MSelectionList()
        try:
            sel.add(attr)
            plug = sel.getPlug(0)
        except RuntimeError:
            logger.warning(f"disconnectAttr: no plug '{attr}'")
            return []
        pairs = list(_iter_connected_pairs(plug, source, destination))

        broken = []
        for src, dst in pairs:
            try:
                cmds.disconnectAttr(src, dst)
                broken.append((src, dst))
            except RuntimeError as e:
                logger.warning(f"disconnectAttr: could not break "
                               f"{src} -> {dst}: {e}")
        return broken