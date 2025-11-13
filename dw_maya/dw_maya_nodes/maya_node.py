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
import dw_maya.dw_presets_io as dwpreset
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
        - Index 0 returns transform, 1 returns shape by default
        - Attributes are accessed directly using Python attribute syntax
        - Shape attributes take priority when duplicated with transform
    """

    def __init__(self, name: str,
                 preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        """Initialize MayaNode with optional preset loading."""
        super().__init__(name)

        # this dict method is used to avoid calling __getattr __
        _input = self.name()
        if _input:
            self.__dict__['node'] = _input #: str: current priority node evaluated
        else:
            self.__dict__['node'] = name
        self.__dict__['item'] = 1  #: int: can be either 0 or 1 and should be exented with Mesh or Cluster


        # Handle preset if provided
        if preset:
            namespace = name.rsplit(':', 1)[0] if ':' in name else ''
            self.loadNode(preset, blend_value, namespace)

    def __getitem__(self, index: int):
        """Access transform (0) or shape (1) nodes.

        Args:
            index: 0 for transform, 1 for shape

        Returns:
            Self with updated node index

        Example:
            >>> node = MayaNode('pCube1')
            >>> transform = node[0].node
            >>> shape = node[1].node
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
        if attr in self.listAttr(attr):
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
        if attr_name in self.listAttr(attr_name):
            try:
                if not isinstance(value, str):
                    MAttr(self.node, attr_name).setAttr(value)
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

    def set_node(self, index: int) -> 'MayaNode':
        """Update current node index (transform/shape selection).

        Args:
            index: 0 for transform, 1 for shape

        Returns:
            Self for chaining
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
        return cmds.nodeType(self.sh or self.__node)

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

    def addAttr(self,
                long_name: str,
                value=None,
                attr_type='long',
                **kwargs) -> 'MAttr':
        """Add a new attribute to the node.

        Args:
            long_name: Name for the new attribute
            value: Initial value
            attr_type: Maya attribute type
            **kwargs: Additional Maya attribute flags

        Returns:
            MAttr wrapper for the new attribute

        Example:
            >>> node.addAttr('myAttr', 1.0, 'double')
        """
        try:
            result = dwu.add_attr(
                self._node,
                long_name=long_name,
                value=value,
                attr_type=attr_type,
                **kwargs
            )
            return MAttr(self.node, result.split('.')[-1])
        except Exception as e:
            logger.error(f"Failed to add attribute {long_name}: {e}")
            raise

    def listAttr(self, node_index=None, attr=None):
        """List all attributes of the node or check if a specific attribute exists.

        Args:
            attr (str, optional): name of an attribute to check

        Returns:
            list: list of attributes, or list containing the attribute if it exists
        """
        current = self.node
        tr = self.tr
        sh = self.sh

        attr_list_tr = []
        if tr:
            attr_list_tr += cmds.listAttr(tr) or []
            attr_list_tr += cmds.listAttr(tr, shortNames=True) or []
            attr_list_tr = list(set(attr_list_tr))  # Remove duplicates

        attr_list_sh = []
        if sh:
            attr_list_sh += cmds.listAttr(sh) or []
            attr_list_sh += cmds.listAttr(sh, shortNames=True) or []
            attr_list_sh = list(set(attr_list_sh))  # Remove duplicates

        # If checking for a specific attribute
        if attr is not None:
            # Check existence in transform and shape nodes
            exists_in_tr = attr in attr_list_tr
            exists_in_sh = attr in attr_list_sh

            # Return list containing attribute if it exists, otherwise empty list
            if current == tr:
                if exists_in_tr:
                    if exists_in_sh and sh != tr:
                        cmds.warning(f"attribute `{attr}` exists in both shape and transform, using: {current}.{attr}")
                    return [attr]
                elif exists_in_sh:
                    self.__dict__['item'] = 1  # Switch to shape
                    return [attr]
                return []
            else:  # current == sh
                if exists_in_sh:
                    if exists_in_tr and sh != tr:
                        cmds.warning(f"attribute `{attr}` exists in both shape and transform, using: {current}.{attr}")
                    return [attr]
                elif exists_in_tr:
                    self.__dict__['item'] = 0  # Switch to transform
                    return [attr]
                return []

        # No specific attribute requested, return all for current node
        if node_index is not None:
            if node_index == 0:
                return attr_list_tr
            else:
                return attr_list_sh
        else:
            all_attr = attr_list_tr + attr_list_sh
            all_attr = list(set(all_attr))
            return all_attr

    def getAttr(self, attr) -> "MAttr":
        """Get attribute wrapper for given name.

        Args:
            attr_name: Name of attribute to access

        Returns:
            MAttr wrapper if attribute exists
        """
        if attr in self.listAttr(attr):
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
                   filter_match:list=None,
                   filter_exclude:list=None,
                   in_channelbox:bool=False) -> dict:
        """Create attribute preset dictionary from node.

        Args:
            node: Optional index (0=transform, 1=shape) to specify node

        Returns:
            Dictionary of attribute values and settings
        """
        try:
            if node is not None:
                _node_preset = self.tr if node == 0 else self.sh
                preset = dwpreset.dw_preset.createAttrPreset(_node_preset,
                                                              filter_match=filter_match,
                                                              filter_exclude=filter_exclude,
                                                              in_channelbox=in_channelbox)
                return preset

            # Handle both transform and shape
            if self.tr == self.sh:
                preset = dwpreset.dw_preset.createAttrPreset(self.node,
                                                            filter_match=filter_match,
                                                            filter_exclude=filter_exclude,
                                                              in_channelbox=in_channelbox)
                return preset

            # Combine transform and shape presets
            tr_preset = dwpreset.dw_preset.createAttrPreset(self.tr,
                                                            filter_match=filter_match,
                                                            filter_exclude=filter_exclude,
                                                             in_channelbox=in_channelbox)
            sh_preset = dwpreset.dw_preset.createAttrPreset(self.sh,
                                                            filter_match=filter_match,
                                                            filter_exclude=filter_exclude,
                                                             in_channelbox=in_channelbox)
            combined_preset = dwu.merge_two_dicts(tr_preset, sh_preset)

            return combined_preset
        except Exception as e:
            logger.error(f"Failed to create preset: {e}")
            raise

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

    def parentTo(self, target):
        """Parent this node to target.

        Args:
            target: Target node or MayaNode instance

        Example:
            >>> sphere.parentTo(group)
        """
        if isinstance(target, MayaNode):
            cmds.parent(self.tr, target.tr)
        else:
            cmds.parent(self.tr, target)

    def rename(self, name: str) -> str:
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
                    cmds.rename(self.sh, name+'Shape')
            self.__dict__['node'] = name
            return self.tr
        except Exception as e:
            print(f"Failed to rename the node: {e}")

    def createNode(self, preset, targ_ns=':'):
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
                cmds.error('Please provide a valid : string nodeType or a key `nodeType`')
            preset = {f"{self.__dict__['node']}_nodeType": _type}

        # we try to determine if we create a node from scratch or if we load it
        # in case of loading, we need to remap the dictionnary keys with the correct namespace
        if targ_ns == ':'  or targ_ns == '':
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
            return new_name

    def saveNode(self, path: str, file: str):
        """Save node preset to JSON file.

        Args:
            path: Directory path
            file_name: Name for JSON file

        Returns:
            Full path to saved file
        """
        try:
            if path.startswith('/'):
                if not path.endswith('/'):
                    path += '/'
                if '.' not in file:
                    file += '.json'
                fullpath = path + file

                logger.info(f'Saving node preset to {fullpath}')
                return dwpreset.save_json(fullpath, self.attrPreset(), defer=True)
        except Exception as e:
            logger.error(f"Failed to save node preset: {e}")
            raise

    def loadNode(self, preset: Union[str, dict],
                 blend: float = 1.0,
                 namespace: str = ':'):
        """Load node from preset, optionally blending attributes.

        Args:
            preset: Node type or preset dictionary
            blend: Blend factor for attribute values
            namespace: Target namespace

        Example:
            {'pCube1': {'rotateX': 0.0,
               'nodeType': 'transform',
               'rotateY': 1.0,
               'translateX': 100,
               'translateY': 0.0,
               'translateZ': 0.0},
            'pSphere1': {'nodeType': 'transform',
                       'scaleX': 0.5,
                       'translateX': 1,
                       'translateY': 0,
                       'rotateY': 50}}

        """
        try:
            # Handle string preset
            if isinstance(preset, str):
                self.createNode(preset)
                return

            # Process dictionary preset
            for node_name, attributes in preset.items():
                # Skip if no nodeType attribute
                if 'nodeType' not in attributes:
                    logger.warning(f"No nodeType found for {node_name}, skipping")
                    continue

                # Handle namespace
                full_node_name = (f"{namespace}:{node_name}" if namespace not in [':', '']
                                  else node_name)
                node_type = attributes['nodeType']

                # Check if this is the node we're looking for, handling namespace correctly
                self_node_basenames = []
                # Get transform node basename if it exists
                if self.tr:
                    self_node_basenames.append(self.stripNamespace(0))  # 0 for transform
                # Get shape node basename if it exists and is different from transform
                if self.sh and self.sh != self.tr:
                    self_node_basenames.append(self.stripNamespace(1))  # 1 for shape

                current_node_basename = node_name

                # Check using full names or base names
                if full_node_name == self.__dict__['node'] or current_node_basename in self_node_basenames:
                    print(f"debug : it should process the node: {full_node_name}")
                    # Create or use existing node
                    if not cmds.objExists(self.__dict__['node']):
                        # Create new node with the specified node type
                        self.createNode(node_type, namespace, name=full_node_name)

                    # Create a copy of attributes without the nodeType for blending
                    attrs_to_apply = attributes.copy()
                    attrs_to_apply.pop('nodeType', None)

                    # Apply attributes
                    for attr, value in attrs_to_apply.items():
                        try:
                            # With this type-specific targeting:
                            if node_type == "transform":
                                target_attr = f"{self.tr}.{attr}"
                            else:
                                target_attr = f"{self.sh}.{attr}"

                            if not cmds.ls(target_attr):
                                print(f"skipping attribute {attr} for node {full_node_name}")
                                continue

                            # Check if value is a special token that needs evaluation
                            from dw_maya.dw_constants import SPECIAL_TOKENS
                            if isinstance(value, str) and value in SPECIAL_TOKENS:
                                value = SPECIAL_TOKENS[value]()

                            # Check for and delete any existing animation keys
                            if cmds.keyframe(target_attr, query=True, keyframeCount=True):
                                cmds.cutKey(target_attr)

                            current_value = cmds.getAttr(target_attr)

                            # Apply blending if needed
                            if blend < 0.999 and isinstance(value, (int, float, bool)):
                                blended_value = value * blend + current_value * (1 - blend)
                                cmds.setAttr(target_attr, blended_value)
                            else:
                                if isinstance(value, str):
                                    cmds.setAttr(target_attr, value, type='string')
                                else:
                                    cmds.setAttr(target_attr, value)
                        except Exception as e:
                            logger.warning(f"Failed to set attribute {attr}: {e}")

                    break
        except Exception as e:
            logger.error(f"Failed to load node preset: {e}")
            raise
