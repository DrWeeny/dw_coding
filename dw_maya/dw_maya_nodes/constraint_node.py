"""Constraint node wrapper with full-wiring preset capture.

Summary:
    A constraint node is meaningless without its outgoing plugs (the
    ``constraintTranslate / constraintRotate -> driven.translate / rotate``
    links that actually drive the constrained node). The base MayaNode
    ConnectionComponent captures incoming connections only, which is right
    for whole-graph rebuilds but leaves a single-constraint preset unable
    to rewire its driven node. This subclass captures both directions.

Classes:
    Constraint: MayaNode with a both-direction ConnectionComponent.

Example:
    >>> import dw_maya.dw_lsNode as dwls
    >>> con = dwls.lsNode('collider_parentConstraint1')[0]  # -> Constraint
    >>> preset = con.createPreset()
    >>> # other scene / new name: driver + driven must already exist
    >>> new_con = MayaNode('new_pc', preset=preset)

Author:
    DrWeeny
"""

import dw_maya.dw_presets_io.preset_components as pcomp
from dw_maya.dw_node_registry import register_type
from .maya_node import MayaNode


class Constraint(MayaNode):
    """Wrapper for Maya constraint nodes (parent / point / orient / ...).

    Registered on the abstract ``constraint`` type, so the registry's
    inherited-type walk resolves every concrete constraint type to it.
    Presets capture outgoing connections too, so a saved constraint can
    rewire the node it drives when rebuilt.
    """

    preset_components = (pcomp.AttributeComponent(),
                         pcomp.ConnectionComponent(directions=("in", "out")),
                         pcomp.AnimationComponent())


register_type('constraint', Constraint)