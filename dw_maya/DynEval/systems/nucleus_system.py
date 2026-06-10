import maya.cmds as cmds
from ..sim_registry import register, SimSystem
from ..dendrology.nucleus_leaf import make_nucleus_item
from ..sim_cmds.cache_management import NucleusCacheOps

register(SimSystem(
    name           = 'nucleus',
    solver_types   = ['nucleus'],
    sim_node_types = ['nCloth', 'hairSystem', 'nRigid'],
    discover       = lambda: cmds.ls(type='nucleus') or [],
    make_item      = make_nucleus_item,     # dispatches by node type internally
    cache_ops      = NucleusCacheOps,
))