"""Provides a high-level, Pythonic interface to Maya nodes.

A module that wraps Maya nodes with a PyMel-like interface but maintaining
Maya.cmds performance characteristics. Handles both transform and shape nodes
with intuitive attribute access.

Classes:
    MayaNode: Main class for Maya node operations

Version: 1.0.0

Author:
    DrWeeny
"""

from typing import Union, Optional, Dict, Any, List

from maya import cmds
import re

from . import ObjPointer, MAttr
from dw_maya.dw_constants.node_re_mappings import SHAPE_PATTERN
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_presets_io
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_logger import get_logger

logger = get_logger()


class MayaNode(ObjPointer):
    """High-level wrapper for Maya nodes with Pythonic attribute access.

    Provides a PyMel-like interface for Maya nodes while maintaining Maya.cmds
    performance. Handles both transform and shape nodes transparently.

    Args:
        name: Node name to wrap
        preset: Optional preset dictionary for node creation/configuration
        blend_value: Value for attribute blending when using presets

    Examples:
        >>> node = MayaNode('pCube1')
        >>> node.translateX = 10  # Direct attribute setting
        >>> node[0].node  # Access transform
        >>> node[1].node  # Access shape

    Notes:
        - Index 0 returns the transform, 1 the first shape, and N>=2 the
          N-th shape (a transform may carry several shapes — common in rig /
          groom setups).
        - ``.sh`` always returns the *first* shape (warns once when the
          transform has more than one; use :meth:`shapes` / :meth:`list_shapes`
          or ``node[2]``, ``node[3]``… to reach the others).
        - Attributes are accessed directly using Python attribute syntax
        - Shape attributes take priority when duplicated with transform
    """

    #: Ordered preset components this class owns. Used in createPreset.
    #: Hierarchy runs first: it re-parents in relative mode, so the local
    #: values AttributeComponent writes afterwards give the right world pose.
    preset_components = (pcomp.HierarchyComponent(), # restore parenting
                         pcomp.AttributeComponent(), # store attributes
                         pcomp.ConnectionComponent(io=(True, True)), # save connections
                         pcomp.KeyframeComponent()) # save keyframed animCurves (opt-in)

    def __init__(self, name: str,
                 preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        """Initialize MayaNode with optional preset loading."""
        # Check if we're creating a new node
        creating_new = isinstance(preset, (dict, str)) and not cmds.objExists(name)

        # Initialize parent with silent mode if creating new node
        super().__init__(name, warning=not creating_new)

        # this dict method is used to avoid calling __getattr __
        _input = self.name()
        if _input:
            self.__dict__['node'] = _input  #: str: current priority node evaluated
        else:
            self.__dict__['node'] = name
        self.__dict__['item'] = 1  #: int: can be either 0 or 1 and should be exented with Mesh or Cluster

        # Handle preset if provided
        if preset:
            namespace = name.rsplit(':', 1)[0] if ':' in name else ''
            self.loadNode(preset, blend_value, namespace)

    def __getitem__(self, index: int):
        """Access the transform (0), first shape (1), or N-th shape (>=2).

        Args:
            index: 0 for transform, 1 for the first shape, N for the N-th
                shape (1-based over the shape list, so ``node[2]`` is the
                second shape).

        Returns:
            Self with updated node index

        Example:
            >>> node = MayaNode('pCube1')
            >>> transform = node[0].node
            >>> shape = node[1].node
            >>> # transform carrying several shapes (rig / groom):
            >>> second_shape = node[2].node
        """
        return self.set_node(index)

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
        if attr in self.listAttr(attr=attr):
            return MAttr(self.node, attr)
        elif attr in self.__dict__:
            return self.__dict__[attr]
        try:
            return object.__getattribute__(self, attr)
        except AttributeError:
            logger.warning(f"'{attr}' doesn't exist on node '{self.node}'")
            return None

    def __setattr__(self, attr_name: str, value: Any):
        """Set attribute values directly.

        Args:
            attr_name: Attribute to set
            value: New value

        Example:
            >>> node.translateX = 10
        """
        # Handle internal attributes
        if attr_name.startswith('_'):
            super().__setattr__(attr_name, value)
            return

        # Handle Maya attributes
        if attr_name in self.listAttr(attr=attr_name):
            try:
                # Unwrap MAttr — happens with augmented assignment (node.tx += v):
                #   Python desugars  a.b += x  as  a.b = a.b.__iadd__(x)
                #   __iadd__ already applied the op in-place and returns self (the MAttr).
                #   Passing an MAttr object raw to cmds.setAttr raises TypeError.
                if isinstance(value, MAttr):
                    # Same node+attr → in-place op already wrote the value; skip.
                    if value._node == self.node and value.attr == attr_name:
                        return
                    # Different source → copy the value across.
                    value = value.getAttr()
                    # Normalize compound format: [(x,y,z)] → (x,y,z)
                    if (isinstance(value, list) and len(value) == 1
                            and isinstance(value[0], tuple)):
                        value = value[0]

                if isinstance(value, str):
                    cmds.setAttr(f'{self.node}.{attr_name}', value, type='string')
                else:
                    MAttr(self.node, attr_name).setAttr(value)
            except AttributeError:
                if isinstance(value, str):
                    cmds.setAttr(f'{self.node}.{attr_name}', value, type='string')
                else:
                    cmds.setAttr(f'{self.node}.{attr_name}', value)


    @classmethod
    def specialize(cls, node: str):
        from dw_maya.dw_node_registry import resolve
        return resolve(node)

    @property
    def __node(self) -> str:
        """
        This one is used to get the actual node from __dict__
        """
        return self.name()

    def set_node(self, index: int) -> 'MayaNode':
        """Update current node index (transform/shape selection).

        Args:
            index: 0 for transform, 1 for the first shape, N for the N-th
                shape (1-based over the shape list).

        Returns:
            Self for chaining
        """
        self.__dict__['item'] = index
        return self

    @property
    def node(self) -> str:
        """Returns the current node (transform or the selected shape).

        ``item == 0`` → transform, ``item == 1`` → first shape, and
        ``item >= 2`` → the N-th shape (1-based over :meth:`shapes`).  An
        out-of-range index falls back to the first shape (or transform).
        """
        id = self.__dict__['item']
        if id == 0:
            return self.tr or self.sh
        if id == 1:
            return self.sh or self.tr
        # id >= 2 → request the (id-1)-th shape (node[1] is the first shape).
        _shapes = self.shapes()
        shape_idx = id - 1
        if 0 <= shape_idx < len(_shapes):
            return _shapes[shape_idx]
        logger.warning(
            f"Shape index {id} out of range on '{self.tr}' "
            f"({len(_shapes)} shape(s)); falling back to the first shape.")
        return self.sh or self.tr

    @property
    def nodeType(self) -> str:
        """str: return the current node type, by default it always return the shape"""
        return cmds.nodeType(self.sh or self.__node)

    @property
    def sh(self) -> str:
        """Return the shape node, or the node itself if it is not a transform.

        Always uses ``fullPath=True`` on :func:`cmds.listRelatives` so the
        returned name is unambiguous when duplicate short names exist in the
        scene.

        Returns:
            str: Shape full/partial path, or fallback to transform name as shape might equal to transform
        """
        node = self.__node
        if cmds.nodeType(node) != 'transform':
            # Already a shape – partialPathName is usually sufficient, but
            # resolve to long if the name is ambiguous (contains duplicates).
            if "|" not in node and len(cmds.ls(node)) > 1:
                long = cmds.ls(node, long=True)
                return long[0] if long else node
            return node
        # Use shapes() so intermediate (orig) shapes are reliably excluded —
        # Maya's ni flag alone leaks them on referenced / namespaced nodes.
        _sh = self.shapes()
        if not _sh:
            return self.tr
        # A transform can own several shapes (rig / groom). ``.sh`` keeps its
        # historical meaning — the first shape — but warns once so callers know
        # to reach for shapes()/list_shapes() or node[2], node[3]…
        if len(_sh) > 1 and not self.__dict__.get('_multi_shape_warned'):
            self.__dict__['_multi_shape_warned'] = True
            logger.warning(
                f"'{node}' has {len(_sh)} shapes; '.sh' returns the first "
                f"('{_sh[0].split('|')[-1]}'). Use .shapes()/.list_shapes() "
                f"or node[2..{len(_sh)}] to reach the others.")
        return _sh[0]

    def shapes(self, intermediate: bool = False) -> List[str]:
        """Return every shape under this node's transform.

        Resolves the transform first (via :attr:`tr`), so the result is the
        same regardless of whether the wrapper currently points at the
        transform or one of the shapes.  ``shapes()[0]`` matches :attr:`sh`
        and ``shapes()[N-1]`` matches ``node[N].node``.

        Args:
            intermediate: When ``True``, include intermediate shapes
                (orig / construction history shapes). Defaults to ``False``.

        Returns:
            list[str]: Full DAG paths of the shapes, in Maya order (empty when
            the node has no shape).

        Example:
            >>> node = MayaNode('hairSystem_grp')   # transform with N shapes
            >>> node.shapes()
            ['|hairSystem_grp|curveShape1', '|hairSystem_grp|curveShape2', ...]
        """
        tr = self.tr
        if not tr:
            return []
        all_shapes = cmds.listRelatives(tr, type='shape', fullPath=True) or []
        if intermediate:
            return all_shapes
        # Maya's noIntermediate / ni flag is unreliable on referenced or
        # namespaced nodes (it can still return orig shapes), so filter the
        # intermediate shapes explicitly on the intermediateObject attribute.
        result = []
        for shape in all_shapes:
            try:
                if cmds.getAttr(f'{shape}.intermediateObject'):
                    continue
            except Exception:
                pass
            result.append(shape)
        return result

    #: Alias for :meth:`shapes` (Maya-style snake_case name).
    list_shapes = shapes

    @property
    def tr(self) -> str:
        """Return the transform node, or shape if no transform exists.

        Fixes the previous implementation where ``cmds.listRelatives(p=True)``
        was called *without* ``fullPath=True``, making the ``"|" in _tr[0]``
        guard always ``False`` (listRelatives returns short names by default).

        Returns:
            str: Transform full/partial path, or ``self.sh`` as fallback.
        """
        node = self.__node
        # Joints (and other transform-derived types such as locators, cameras…)
        # have nodeType 'joint' / 'locator' / etc., NOT 'transform', but they ARE
        # transforms.  Check the full inheritance chain so all of them are handled
        # the same way as a plain transform — returning themselves rather than
        # falling into the shape-walking code path below.
        _inherited = cmds.nodeType(node, inherited=True) or []
        if 'transform' in _inherited:
            if "|" in node:
                # Already a long/partial long path – ensure it resolves uniquely.
                # Do NOT filter by type='transform': joints won't match that filter.
                _tr = cmds.ls(node, long=True)
                return _tr[0] if _tr else None
            return node
        # node is a shape → walk up with fullPath=True so the result is usable
        _parents = cmds.listRelatives(node, p=True, fullPath=True)
        if _parents:
            # Sanity-check: parent must actually own a shape (avoids returning
            # an intermediate group that happens to be named identically).
            _sh = cmds.listRelatives(_parents[0], type='shape', ni=True)
            if _sh:
                return _parents[0]
        return self.sh

    def getFullPath(self, node_index: int = None) -> str:
        """Return the unambiguous full DAG path (always starting with ``|``).

        Unlike :attr:`tr` / :attr:`sh` which may return a partial path when
        the node name is already unique, this method *always* resolves to the
        full path via ``cmds.ls(..., long=True)``.

        This is equivalent to calling ``ancestor[0].name(long=True)`` on
        :class:`ObjPointer`, but respects the current ``node_index`` switch
        (transform vs. shape) and works even after the internal node pointer
        has been swapped via :meth:`set_node`.

        Args:
            node_index (int, optional):
                ``None``  – use the currently active node (default).
                ``0``     – force the transform.
                ``1``     – force the shape.

        Returns:
            str: Full DAG path, or ``None`` if the target does not exist.

        Example:
            >>> node = MayaNode('pCube1')
            >>> node.getFullPath()    # '|pCube1|pCubeShape1'  (shape is default)
            >>> node.getFullPath(0)   # '|pCube1'
            >>> node.getFullPath(1)   # '|pCube1|pCubeShape1'

            # Nested hierarchy with duplicate names:
            >>> node = MayaNode('grpA|grpB|pSphere1')
            >>> node.getFullPath(0)   # '|grpA|grpB|pSphere1'
            >>> node.getFullPath(1)   # '|grpA|grpB|pSphere1|pSphereShape1'
        """
        if node_index == 0:
            target = self.tr
        elif node_index == 1:
            target = self.sh
        else:
            target = self.node

        if not target:
            return None
        result = cmds.ls(target, long=True)
        return result[0] if result else None

    def addAttr(self,
                long_name: str,
                value=None,
                attr_type: Optional[str] = None,
                **kwargs) -> 'MAttr':
        """Add a new attribute to the node.

        When ``attr_type`` is left as ``None`` the Maya type is inferred from
        ``value`` by :func:`dw_maya.dw_maya_utils.add_attr` /
        :func:`infer_attr_type`: ``float`` -> ``double``, ``int`` -> ``long``,
        ``bool`` -> ``bool``, ``str`` -> ``string`` (falling back to ``long``
        when ``value`` is ``None``). Pass ``attr_type`` explicitly to override
        the inference or for types that can't be inferred (e.g. ``enum``).

        Args:
            long_name: Name for the new attribute
            value: Initial value (drives type inference when ``attr_type`` is None)
            attr_type: Maya attribute type; inferred from ``value`` when None
            **kwargs: Additional Maya attribute flags

        Returns:
            MAttr wrapper for the new attribute

        Example:
            >>> node.addAttr('weightsSmooth', 0.0001)   # -> double
            >>> node.addAttr('iterations', 5)           # -> long
            >>> node.addAttr('label', 'hello')          # -> string
            >>> node.addAttr('myAttr', 1.0, 'double')   # explicit override
        """
        try:
            result = dwu.add_attr(
                self.node,
                long_name=long_name,
                value=value,
                attr_type=attr_type,
                **kwargs
            )
            return MAttr(self.node, result.split('.')[-1])
        except Exception as e:
            logger.error(f"Failed to add attribute {long_name}: {e}")
            raise

    def listAttr(self, *args, node_index=None, attr=None, **kwargs):
        """List all attributes of the node or check if a specific attribute exists.

        Mirrors Maya command style: listAttr("tx") and listAttr(attr="tx") are equivalent.

        Args:
            *args: Optional positional attribute name (e.g., listAttr("tx")).
            node_index (int, optional): 0=transform, 1=shape — forces a specific node.
            attr (str, optional): Attribute name to check existence for.
            **kwargs: Additional Maya flags for cmds.listAttr (e.g., shortNames=True).

        Returns:
            list: All attributes, or [attr] if the attribute was found (with auto index-switching).
        """
        # If a positional arg was given and attr wasn't set explicitly, treat it as attr
        if args and attr is None:
            attr = args[0]

        current = self.node
        tr = self.tr
        sh = self.sh

        # Base retrieval honoring kwargs cleanly, ensuring we grab both short/long
        def _get_attrs(n):
            if not n: return []
            res = cmds.listAttr(n, **kwargs) or []

            # Maya requires explicit flagging to grab short names.
            # If the user didn't explicitly forbid or define flags differently, append short names too.
            if 'shortNames' not in kwargs and not kwargs:
                res.extend(cmds.listAttr(n, shortNames=True) or [])
            return res

        attr_list_tr = set(_get_attrs(tr))
        attr_list_sh = set(_get_attrs(sh))

        # If checking for a specific attribute
        if attr is not None:
            # Check existence in transform and shape nodes
            exists_in_tr = attr in attr_list_tr
            exists_in_sh = attr in attr_list_sh

            # Return list containing attribute if it exists, otherwise empty list
            if current == tr:
                if exists_in_tr:
                    if exists_in_sh and sh != tr:
                        logger.warning(
                            f"Attribute `{attr}` exists in both shape and transform, using: {current}.{attr}")
                    return [attr]
                elif exists_in_sh:
                    self.__dict__['item'] = 1  # Switch to shape
                    return [attr]
                return []
            else:  # current == sh
                if exists_in_sh:
                    if exists_in_tr and sh != tr:
                        logger.warning(
                            f"Attribute `{attr}` exists in both shape and transform, using: {current}.{attr}")
                    return [attr]
                elif exists_in_tr:
                    self.__dict__['item'] = 0  # Switch to transform
                    return [attr]
                return []

        # No specific attribute requested, return all for current node
        if node_index is not None:
            if node_index == 0:
                return list(attr_list_tr)
            else:
                return list(attr_list_sh)
        else:
            all_attr = list(attr_list_tr | attr_list_sh)
            return all_attr

    def getAttr(self, attr) -> "MAttr":
        """Get attribute wrapper for given name.

        Args:
            attr_name: Name of attribute to access

        Returns:
            MAttr wrapper if attribute exists
        """
        if attr in self.listAttr(attr=attr):
            return MAttr(self.node, attr)

    def getNamespace(self) -> str:
        """Get node's namespace.

        Returns:
            Namespace string or ':' if in root namespace
        """
        short_name = self.node.split('|')[-1]
        return short_name.rsplit(':', 1)[0] if ":" in short_name else ':'

    def stripNamespace(self, node_index: int = None) -> str:
        """Strip namespace from node name.

        Args:
            node_index: Optional node index (0=transform, 1=shape)

        Returns:
            Node name without namespace
        """
        if node_index is None:  # Properly check for None instead of truthiness
            short_name = self.node.split('|')[-1]
        else:
            __current_index = self.__dict__['item']
            if node_index != __current_index:
                self.set_node(node_index)
                short_name = self.node.split('|')[-1]
                self.set_node(__current_index)
            else:
                short_name = self.node.split('|')[-1]

        return short_name.split(':')[-1]

    def attrPreset(self, node: Optional[int] = None,
                   filter_match: list = None,
                   filter_exclude: list = None,
                   in_channelbox: bool = False) -> dict:
        """Create attribute preset dictionary from node.

        Args:
            node: Optional index (0=transform, 1=shape) to specify node

        Returns:
            Dictionary of attribute values and settings
        """
        import dw_maya.dw_presets_io.dw_preset
        try:
            if node is not None:
                _node_preset = self.tr if node == 0 else self.sh
                preset = dw_maya.dw_presets_io.dw_preset.createAttrPreset(_node_preset,
                                                                                        filter_match=filter_match,
                                                                                        filter_exclude=filter_exclude,
                                                                                        in_channelbox=in_channelbox)
                return preset

            # Handle both transform and shape
            if self.tr == self.sh:
                preset = dw_maya.dw_presets_io.dw_preset.createAttrPreset(self.node,
                                                                                        filter_match=filter_match,
                                                                                        filter_exclude=filter_exclude,
                                                                                        in_channelbox=in_channelbox)
                return preset

            # Combine transform and shape presets
            tr_preset = dw_maya.dw_presets_io.dw_preset.createAttrPreset(self.tr,
                                                                                       filter_match=filter_match,
                                                                                       filter_exclude=filter_exclude,
                                                                                       in_channelbox=in_channelbox)
            sh_preset = dw_maya.dw_presets_io.dw_preset.createAttrPreset(self.sh,
                                                                                       filter_match=filter_match,
                                                                                       filter_exclude=filter_exclude,
                                                                                       in_channelbox=in_channelbox)
            combined_preset = dwu.merge_two_dicts(tr_preset, sh_preset)

            return combined_preset
        except Exception as e:
            logger.error(f"Failed to create preset: {e}")
            raise

    # ------------------------------------------------------------------ #
    # Preset with Component-based preset                                 #
    # ------------------------------------------------------------------ #

    def presetIdentity(self) -> str:
        """Return the logical, namespace-stripped identity used as preset key.

        The transform name when this is a DAG node, otherwise the node's own
        name (shape-less / DG nodes).
        """
        base = self.tr or self.sh or self.node
        return base.split('|')[-1].split(':')[-1]

    def _iter_components(self,
                         only: Optional[list] = None,
                         skip: Optional[list] = None):
        """Yield the components selected for this pass.

        ``only`` restricts to the given component keys (and overrides
        ``enabled_by_default``, so opt-in components like keyframes can be
        included explicitly). ``skip`` removes keys. With neither, every
        default-on component runs.
        """
        for comp in self.preset_components:
            if only is not None:
                if comp.key not in only:
                    continue
            elif not comp.enabled_by_default:
                continue
            if skip and comp.key in skip:
                continue
            yield comp

    def _pre_capture(self, body: dict) -> None:
        """Hook called before components capture. Override to inject data."""

    def _post_capture(self, body: dict) -> None:
        """Hook called after components capture. Override to post-process."""

    def createPreset(self,
                     only: Optional[list] = None,
                     skip: Optional[list] = None,
                     ctx: Optional['pcomp.PresetContext'] = None) -> dict:
        """Capture this node into a ``{identity: body}`` preset entry.

        Each selected component contributes one slice keyed by ``comp.key``
        (``attributes``, ``connections``, ...). See :meth:`_iter_components`
        for ``only`` / ``skip``.

        Returns:
            dict: ``{presetIdentity(): {"nodeType": ..., <component slices>}}``.
        """
        ctx = ctx or pcomp.PresetContext()
        body = {"nodeType": self.nodeType}
        self._pre_capture(body)
        for comp in self._iter_components(only, skip):
            try:
                data = comp.capture(self, ctx)
            except Exception as e:
                logger.warning(f"createPreset: component '{comp.key}' failed on "
                               f"'{self.node}': {e}")
                continue
            if data is not None:
                body[comp.key] = data
        self._post_capture(body)
        return {self.presetIdentity(): body}

    def _select_body(self, nodes: dict) -> dict:
        """Pick the entry in ``nodes`` that matches this node.

        Matches by identity, falls back to the sole entry when there is only
        one, else returns an empty dict.
        """
        identity = self.presetIdentity()
        if identity in nodes:
            return nodes[identity]
        if len(nodes) == 1:
            return next(iter(nodes.values()))
        return {}

    def applyPreset(self,
                    preset: dict,
                    ctx: Optional['pcomp.PresetContext'] = None,
                    only: Optional[list] = None,
                    skip: Optional[list] = None) -> None:
        """Apply a preset onto this node, component by component.

        Args:
            preset: Either a full envelope (``{"format", "nodes": {...}}``) or a
                bare ``{identity: body}`` mapping.
            ctx: Apply context (namespace / blend / create). Default blend 1.0.
            only / skip: Component-key filters (see :meth:`_iter_components`).
        """
        ctx = ctx or pcomp.PresetContext()
        nodes = preset.get("nodes", preset) if isinstance(preset, dict) else {}
        body = self._select_body(nodes)
        if not body:
            logger.warning(f"applyPreset: no matching entry for '{self.node}'")
            return
        for comp in self._iter_components(only, skip):
            if comp.key in body:
                try:
                    comp.apply(self, body[comp.key], ctx)
                except Exception as e:
                    logger.warning(f"applyPreset: component '{comp.key}' failed "
                                   f"on '{self.node}': {e}")

    def savePreset(self,
                   path: str,
                   only: Optional[list] = None,
                   skip: Optional[list] = None,
                   defer: bool = False) -> bool:
        """Save this node to ``path`` as a versioned ``dw_preset`` envelope."""
        data = {"format": pcomp.PRESET_FORMAT,
                "version": pcomp.PRESET_VERSION,
                "nodes": self.createPreset(only=only, skip=skip)}
        data["namespaces"] = pcomp.collect_preset_namespaces(data["nodes"])
        logger.info(f"Saving preset to {path}")
        return dw_maya.dw_presets_io.save_json(path, data, defer=defer)

    def loadPreset(self,
                   path: str,
                   blend: float = 1.0,
                   target_ns: str = ":",
                   only: Optional[list] = None,
                   skip: Optional[list] = None,
                   apply_external: bool = True,
                   ext_ns_map: Optional[Dict] = None) -> None:
        """Load a ``dw_preset`` file and apply it onto this node.

        ``apply_external`` / ``ext_ns_map`` control connections captured toward
        other namespaces (external assets): skip them wholesale, or remap their
        namespace (``{"alien_999": "alien01", ":": "man_01"}``) - see
        ``PresetContext``.
        """
        data = dw_maya.dw_presets_io.load_json(path)
        if not data:
            return
        if data.get("format") != pcomp.PRESET_FORMAT:
            logger.warning(f"loadPreset: '{path}' is not a {pcomp.PRESET_FORMAT} file.")
            return
        ctx = pcomp.PresetContext(target_ns=target_ns, blend=blend,
                                  apply_external=apply_external,
                                  ext_ns_map=dict(ext_ns_map or {}))
        self.applyPreset(data, ctx, only=only, skip=skip)

    def listConnections(self, **kwargs) -> list:
        connection_list = cmds.listConnections(self.node, **kwargs)
        return list(set(connection_list))

    def disconnectAttr(self,
                       attr: Optional[str] = None,
                       source: bool = True,
                       destination: bool = True) -> list:
        """Break connections on one attribute, or clean the whole node.

        Args:
            attr: Attribute name; resolved with the usual transform/shape
                duality. When None, every connected plug on the transform
                and shape is disconnected.
            source: Break incoming connections.
            destination: Break outgoing connections.

        Returns:
            list: The broken connections as (source_plug, destination_plug).

        Example:
            >>> node.disconnectAttr('translateX')  # both directions
            >>> node.disconnectAttr('inMesh', destination=False)
            >>> node.disconnectAttr()  # clean every plug on the node
        """
        if attr is not None:
            plug = getattr(self, attr)
            if not isinstance(plug, MAttr):
                logger.warning(f"disconnectAttr: no attribute '{attr}' "
                               f"on '{self.node}'")
                return []
            return plug.disconnectAttr(source=source,
                                       destination=destination)

        targets = [self.tr]
        if self.sh and self.sh != self.tr:
            targets.append(self.sh)
        targets = [t for t in targets if t] or [self.node]

        # Dedupe: a tr <-> sh link shows up from both sides of the query.
        pairs = []
        seen = set()
        for target in targets:
            found = []
            if source:
                raw = cmds.listConnections(target, plugs=True,
                                           connections=True,
                                           source=True,
                                           destination=False) or []
                found += [(src, dst) for dst, src in zip(raw[::2], raw[1::2])]
            if destination:
                raw = cmds.listConnections(target, plugs=True,
                                           connections=True,
                                           source=False,
                                           destination=True) or []
                found += list(zip(raw[::2], raw[1::2]))
            for pair in found:
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)

        broken = []
        for src, dst in pairs:
            try:
                cmds.disconnectAttr(src, dst)
                broken.append((src, dst))
            except RuntimeError as e:
                logger.warning(f"disconnectAttr: could not break "
                               f"{src} -> {dst}: {e}")
        return broken

    def listHistory(self, **kwargs) -> list:
        """List node history with optional filtering.

        Args:
            **kwargs: Maya listHistory command flags

        Returns:
            List of history nodes

        Example:
            >>> node.listHistory(type='mesh')
        """
        try:
            # Handle type separately for better filtering
            node_type = kwargs.pop('type', None)
            sel = cmds.listHistory(self.node, **kwargs)
            if sel and node_type:
                sel = [s for s in sel if cmds.ls(s, type=node_type)]
            return sel

        except Exception as e:
            logger.error(f"Failed to list history: {e}")
            return []

    def getParent(self, all_parents: bool = False):
        """Return the parent of this node's transform.

        Args:
            all_parents: When True, return the whole ancestor chain as full
                paths, immediate parent first, top-most last.

        Returns:
            str | None: Immediate parent full path (None at world level), or
            a list of ancestor paths when ``all_parents`` is True (empty at
            world level).

        Example:
            >>> node = MayaNode('collider')      # |grp_a|grp_b|collider
            >>> node.getParent()                 # '|grp_a|grp_b'
            >>> node.getParent(all_parents=True) # ['|grp_a|grp_b', '|grp_a']
        """
        tr = self.tr
        parents = cmds.listRelatives(tr, parent=True, fullPath=True) if tr else None
        if not parents:
            return [] if all_parents else None
        if not all_parents:
            return parents[0]
        parts = parents[0].split('|')  # ['', 'grp_a', 'grp_b']
        return ['|'.join(parts[:i + 1]) for i in range(len(parts) - 1, 0, -1)]

    def parentTo(self, target):
        """Parent this node to target.

        Args:
            target: Target node or MayaNode instance

        Example:
            >>> sphere.parentTo(group)
        """
        from dw_maya.dw_maya_utils.dw_maya_hierarchy import is_already_parented
        if isinstance(target, MayaNode):
            if not is_already_parented(self.tr, target.tr):
                cmds.parent(self.tr, target.tr)
            else:
                cmds.warning(f"Target node {target.tr} already has a parent")
        else:
            if not is_already_parented(self.tr, target):
                cmds.parent(self.tr, target)
            else:
                cmds.warning(f"Target node {target} already has a parent")

    def rename(self, name: str):
        """Rename node maintaining Maya naming conventions.

        Handles both transform and shape renaming, maintaining
        Maya's standard naming patterns.

        Args:
            name: New name for the node

        Returns:
            New node name

        Example:
            >>> sphere.rename('ball')
        """
        pattern = SHAPE_PATTERN
        p = re.compile(pattern)

        try:
            # Simple rename for single node
            if self.tr == self.sh:
                cmds.rename(self.tr, name)
            else:
                # Handle shape/transform pair
                if self.sh == name:
                    # Temporary rename to avoid conflicts
                    _tmp = cmds.rename(self.sh, 'dwTmpRename')

                    # Handle explicit shape naming
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
                    cmds.rename(self.sh, name + 'Shape')
            self.__dict__['node'] = name
            return self
        except Exception as e:
            logger.error(f"Failed to rename the node: {e}")
            raise

    def createNode(self, preset, targ_ns=':', name=""):
        """Create new node from preset or type.

        Args:
            preset: Node type string or preset dictionary
            namespace: Optional namespace for new node

        Returns:
            Name of created node

        Example:
            >>> MayaNode('sphere').createNode('mesh')
            >>> MayaNode('light').createNode(light_preset_dict)
        """

        if isinstance(preset, str):
            # If we give some string, it will conform the dictionnary
            _type = preset[:]
            if _type not in cmds.ls(nt=True):
                raise ValueError(f"Please provide a valid string nodeType or a key `nodeType`. Got: '{_type}'")
            preset = {f"{self.__dict__['node']}_nodeType": _type}

        # we try to determine if we create a node from scratch or if we load it
        # in case of loading, we need to remap the dictionnary keys with the correct namespace
        if targ_ns == ':' or targ_ns == '':
            # in this case we have created the node with a basestring type so we need to add the namespace
            _type = f"{self.__dict__['node']}_nodeType"
            if _type not in preset:
                _type = f"{targ_ns}:{self.__dict__['node']}_nodeType"
        else:
            # In this case we create a node with a namespace but the preset is namespace agnostic
            _type = self.__dict__['node'] + '_nodeType'
            if _type not in preset:
                _type = f"{self.__dict__['node'].rsplit(':', 1)[-1]}_nodeType"

        # this part is for creating a good node name, at the end of the proc it will rename
        flags = dwu.flags(preset, self.__dict__['node'], 'name', 'n', dic={})

        # Create and initialize node
        new_node = cmds.createNode(preset[_type])
        self.setDAG(new_node)
        self.__dict__['node'] = new_node

        if flags:
            new_name = self.rename(**flags)
            return self
        if name:
            new_name = self.rename(name)
            return self

    def iter_attrs(self,
                   attrs: List[str],
                   skip_missing: bool = True,
                   skip_duplicates: bool = True,):
        """Safely iterate over a list of attribute names, yielding MAttr objects.

        Handles case normalization, duplicates, and missing attributes
        so artists can pass raw lists without worrying about typos or
        duplicates causing silent failures.

        Args:
            attrs:           List of attribute names (short or long, any case).
            skip_missing:    If True, silently skip attrs that don't exist.
                             If False, raises AttributeError on first missing attr.
            skip_duplicates: If True, each attr is only yielded once.


        Yields:
            MAttr: One per valid, unique attribute in `attrs`.

        Example:
            >>> node = MayaNode('pCube1')
            >>> for mattr in node.iter_attrs(['tx', 'ty', 'tz']):
            ...     mattr.setAttr(0)
        """
        seen = set()
        all_attrs = self.listAttr()  # one call, cached for the loop

        for raw in attrs:
            # --- normalize case ---
            resolved = raw
            # --- duplicate guard ---
            if skip_duplicates:
                if resolved in seen:
                    continue
                seen.add(resolved)

            # --- existence check ---
            if resolved not in all_attrs:
                if skip_missing:
                    logger.warning(f"iter_attrs: '{raw}' not found on '{self.node}', skipping.")
                    continue
                else:
                    raise AttributeError(f"'{raw}' doesn't exist on node '{self.node}'")

            yield MAttr(self.node, resolved)

    def saveNode(self, path: str, file: str):
        """Save node preset to JSON file.

        Args:
            path: Directory path
            file_name: Name for JSON file

        Returns:
            Full path to saved file
        """
        import dw_maya.dw_presets_io.dw_preset
        try:
            if path.startswith('/'):
                if not path.endswith('/'):
                    path += '/'
                if '.' not in file:
                    file += '.json'
                fullpath = path + file

                logger.info(f'Saving node preset to {fullpath}')
                return dw_maya.dw_presets_io.save_json(fullpath, self.attrPreset(), defer=True)
        except Exception as e:
            logger.error(f"Failed to save node preset: {e}")
            raise

    def loadNode(self, preset: Union[str, dict],
                 blend: float = 1.0,
                 namespace: str = ':'):
        """Create (if missing) and apply a v2 component preset onto this node.

        Accepts either a bare node type string ("locator", "multiplyDivide",
        ...) for plain creation, or a v2 component preset - the full envelope
        (``{"format": "dw_preset", "nodes": {...}}``) or a bare
        ``{identity: body}`` mapping as returned by :meth:`createPreset`.

        When the wrapped node does not exist yet, it is created from the
        entry's stored ``nodeType`` first, then the component slices are
        applied through :meth:`applyPreset`. SPECIAL_TOKENS ($RFSTART /
        $RFEND / ...) and numeric blending are resolved per-attribute by
        ``preset_components.apply_attr``.

        Args:
            preset: Node type string, or v2 preset dict.
            blend: Blend factor threaded to the attribute apply (1.0 = set).
            namespace: Target namespace for created nodes (``:`` = root).
        """
        try:
            # Bare node type string -> plain creation, nothing to apply.
            if isinstance(preset, str):
                self.createNode(preset)
                return

            nodes = preset.get("nodes", preset)
            if not isinstance(nodes, dict) or not nodes:
                logger.warning(f"loadNode: empty or invalid preset for "
                               f"'{self.__dict__['node']}'")
                return

            identity, body = self._pick_preset_entry(nodes)
            node_type = body.get('nodeType') if isinstance(body, dict) else None

            # Specialize the wrapper from the stored nodeType so type-specific
            # components (constraint network, geometry, ...) participate in
            # the apply even when the caller built a plain MayaNode. Only
            # done when the subclass adds no custom __init__ state.
            if node_type and type(self) is MayaNode:
                import dw_maya.dw_node_registry as node_registry
                cls = (pcomp.resolve_preset_class(node_type)
                       or node_registry.resolve_type(node_type))
                if (cls is not MayaNode and issubclass(cls, MayaNode)
                        and cls.__init__ is MayaNode.__init__):
                    self.__class__ = cls

            # Create the node before any accessor that assumes it exists
            # (presetIdentity / .sh / .tr choke on a not-yet-created node).
            if not cmds.objExists(self.__dict__['node']):
                if not node_type:
                    logger.error(f"loadNode: no matching entry / nodeType to "
                                 f"create '{self.__dict__['node']}'")
                    return
                self.createNode(node_type, namespace, name=self.__dict__['node'])

            target_ns = namespace if namespace else ':'
            ctx = pcomp.PresetContext(target_ns=target_ns,
                                      blend=blend,
                                      create=True)
            # Map the stored identity to the live node so ConnectionComponent
            # replays plugs onto this node even when it was given a new name.
            # Identity is transform-based, so map it to the transform (falls
            # back to the node itself for shape-less / DG nodes).
            if identity:
                ctx.name_map[identity] = self.tr or self.node
            self.applyPreset(nodes, ctx)
        except Exception as e:
            logger.error(f"Failed to load node preset: {e}")
            raise

    def list_presets_type(self) -> list:
        """
        Returns: animation attributes connections
        """
        return [i.key for i in self.preset_components]

    def _pick_preset_entry(self, nodes: dict) -> tuple:
        """Select the ``(identity, body)`` entry matching this wrapper.

        Mirrors :meth:`_select_body`, but derives the identity from the stored
        node string (base name, path/namespace stripped) so it works before
        the node exists in the scene.
        """
        target = self.__dict__['node'].split('|')[-1].split(':')[-1]
        if target in nodes:
            return target, nodes[target]
        if len(nodes) == 1:
            return next(iter(nodes.items()))
        return None, {}