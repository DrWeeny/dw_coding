"""Mesh node wrapper carrying geometry in its preset.

A thin :class:`MayaNode` subclass whose preset also captures per-vertex
positions via :class:`GeometryComponent`, on top of the inherited attribute +
connection components.

Deliberately NOT registered for the ``mesh`` node type: an exact-type registry
entry would short-circuit the condition-based resolution in ``lsNode()`` (mesh +
nCloth -> NClothMap, mesh + nRigid -> ...). Instantiate ``Mesh(name)`` directly
when you want geometry in the snapshot. It IS registered in the preset-only
class map, so ``node_from_preset`` / ``load_preset_file`` rebuild ``mesh``
entries (and their geometry slice) through this class.

Classes:
    Mesh: MayaNode + GeometryComponent.

Author:
    DrWeeny
"""

from dw_maya.dw_maya_nodes import MayaNode
import dw_maya.dw_presets_io.preset_components as pcomp


class Mesh(MayaNode):
    """MayaNode whose preset also includes per-vertex geometry.

    Example:
        >>> m = Mesh('pSphere1')
        >>> m.savePreset('C:/tmp/sphere.json')   # attrs + connections + points
        >>> m.loadPreset('C:/tmp/sphere.json')   # deform back onto same topology
    """

    preset_components = MayaNode.preset_components + (pcomp.GeometryComponent(),)


pcomp.register_preset_class('mesh', Mesh)