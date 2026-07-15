"""Maya op backends for CfxForge recipes.

Summary:
    Registers the Maya/nucleus implementation of the recipe node taxonomy.
    Import this module inside Maya (interactive or mayapy) to populate the
    registry - mirroring how DynForge imports its backends package. The
    CfxForge core stays import-light; only this module touches maya.cmds
    and dw_maya.

Ops registered:
    file (read/write), group, hierarchy, solver, cloth, collider, step,
    preset, deformer

Example:
    import CfxForge
    import CfxForge.maya_ops   # populates the registry
    ctx = CfxForge.execute_recipe(CfxForge.load_recipe(path))

Author:
    DrWeeny
"""

import fnmatch
import os
import re

from maya import cmds

import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_deformers as dwdef
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_maya.dw_nucleus_utils.dw_create_hierarchy import create_hierarchy, build_sim_step
from dw_maya.dw_nucleus_utils.dw_make_collide import make_collide_ncloth, add_passive_to_nsystem
from dw_maya.dw_nucleus_utils.dw_add_active_to_nsystem import add_active_to_nsystem
from dw_maya.dw_nucleus_utils.dw_nx_mel import get_first_free_constraint_index
from dw_maya.dw_nucleus_utils.dw_create_nconstraint import createNConstraint
from dw_maya.dw_constants import SPECIAL_TOKENS

from .registry import OpBackend, register


def _expand_tokens(value):
    """Expand a SPECIAL_TOKENS string ($RFSTART, ...) to its scene value."""
    if isinstance(value, str) and value in SPECIAL_TOKENS:
        return SPECIAL_TOKENS[value]()
    return value


def _set_attrs(node: str, attrs: dict, ctx, node_id: str):
    """Apply a params attr dict onto a node, token-aware and fault-tolerant."""
    for attr, value in (attrs or {}).items():
        plug = f'{node}.{attr}'
        try:
            cmds.setAttr(plug, _expand_tokens(value))
        except Exception as e:
            ctx.warning(node_id, f"could not set {plug}: {e}")


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _name_match(name: str, patterns: list) -> bool:
    """Match a node's short name (namespace-stripped) against ls-style
    wildcards. fnmatch keeps the semantics DCC-independent."""
    short = str(name).split('|')[-1].split(':')[-1]
    return any(fnmatch.fnmatchcase(short, str(p)) for p in patterns)


def _filter_meshes(meshes: list, pattern) -> list:
    """Optional pattern narrowing shared by the mesh-consuming ops."""
    patterns = _as_list(pattern)
    if not patterns:
        return meshes
    return [m for m in meshes if _name_match(m, patterns)]


# ----------------------------------------------------------------------
# solver-as-sink support: cloth/collider/constraint ops run BEFORE the
# solver node (recipes read causally: cloth -> constraint -> solver), so
# they build on a shared staging nucleus; the solver op then moves every
# collected object onto the real solver and deletes the staging node.
# ----------------------------------------------------------------------

def _staging_solver(ctx) -> str:
    name = ctx.shared.get('staging_nucleus')
    if name and cmds.objExists(name):
        return name
    name = dwnx.create_nucleus(name='cfxforge_staging_nucleus')
    ctx.shared['staging_nucleus'] = name
    return name


def _disconnect_destinations(plug: str):
    for target in cmds.listConnections(plug, plugs=True, source=False,
                                       destination=True) or []:
        cmds.disconnectAttr(plug, target)


def _move_nobject(shape: str, nucleus: str, active: bool):
    """Rewire an nCloth/nRigid from its current solver onto ``nucleus``."""
    _disconnect_destinations(f'{shape}.currentState')
    _disconnect_destinations(f'{shape}.startState')
    for source in cmds.listConnections(f'{shape}.nextState', plugs=True,
                                       source=True,
                                       destination=False) or []:
        cmds.disconnectAttr(source, f'{shape}.nextState')
    if active:
        add_active_to_nsystem(shape, nucleus)
    else:
        add_passive_to_nsystem(shape, nucleus)
    cmds.connectAttr(f'{nucleus}.startFrame', f'{shape}.startFrame',
                     force=True)


def _move_constraint(shape: str, nucleus: str):
    """Rewire a dynamicConstraint onto ``nucleus``."""
    _disconnect_destinations(f'{shape}.evalStart[0]')
    _disconnect_destinations(f'{shape}.evalCurrent[0]')
    index = get_first_free_constraint_index(nucleus)
    cmds.connectAttr(f'{shape}.evalStart[0]',
                     f'{nucleus}.inputStart[{index}]', force=True)
    cmds.connectAttr(f'{shape}.evalCurrent[0]',
                     f'{nucleus}.inputCurrent[{index}]', force=True)


def _collect_strings(value) -> list:
    """Flatten an input tree (dicts/lists/strings) to node name strings."""
    if isinstance(value, dict):
        flat = []
        for sub in value.values():
            flat.extend(_collect_strings(sub))
        return flat
    if isinstance(value, (list, tuple)):
        flat = []
        for sub in value:
            flat.extend(_collect_strings(sub))
        return flat
    return [str(value)] if value else []


@register
class FileOp(OpBackend):
    """Read or write a file (Houdini File-SOP style).

    Params:
        mode (str): 'read' (default) or 'write'.
        path (str): File path (.abc / .ma / .mb for read; .abc for write).
        namespace (str): Optional namespace for read.
        parent (str): Optional group the imported roots are parented under.
        filter (str or list): Read only - wildcard pattern(s) curating the
            imported transforms ('wing_*_msh'); what this node publishes
            downstream.
        frame_range (list): Write only - [start, end], token-aware.

    Inputs:
        roots: Write only - nodes (or an upstream 'nodes' output) to export.

    Outputs:
        read  -> {'nodes': all new nodes, 'transforms': new transforms}
        write -> {'path': written file}
    """

    op_type = 'file'
    dcc = 'maya'

    def validate_params(self, params: dict) -> list:
        errors = []
        mode = params.get('mode', 'read')
        if mode not in ('read', 'write'):
            errors.append(f"mode must be 'read' or 'write', got '{mode}'")
        if not params.get('path'):
            errors.append("'path' is required")
        elif mode == 'read' and not os.path.isfile(str(params['path'])):
            errors.append(f"file not found: {params['path']}")
        return errors

    def dry_run(self, node_id, params, inputs, ctx):
        for msg in self.validate_params(params):
            # a read wired below a write consumes a file that only exists
            # after the upstream barrier ran - not a dry-run error
            if inputs and msg.startswith('file not found'):
                ctx.warning(node_id, f'{msg} (produced upstream?)')
            else:
                ctx.error(node_id, msg)
        return {'nodes': [], 'transforms': [], 'path': params.get('path', '')}

    def execute(self, node_id, params, inputs, ctx):
        mode = params.get('mode', 'read')
        path = str(params['path'])

        if mode == 'write':
            roots = _as_list(inputs.get('roots'))
            if isinstance(inputs.get('roots'), dict):
                roots = _as_list(inputs['roots'].get('nodes'))
            if not roots:
                raise ValueError('file write: no roots to export')
            start, end = params.get('frame_range', ['$RFSTART', '$RFEND'])
            start = _expand_tokens(start)
            end = _expand_tokens(end)
            cmds.loadPlugin('AbcExport', quiet=True)
            root_flags = ' '.join(f'-root {cmds.ls(r, long=True)[0]}'
                                  for r in roots)
            job = (f'-frameRange {start} {end} -uvWrite -worldSpace '
                   f'{root_flags} -file {path}')
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            cmds.AbcExport(j=job)
            ctx.info(node_id, f'exported {len(roots)} root(s) to {path}')
            return {'path': path}

        # read
        if path.lower().endswith('.abc'):
            cmds.loadPlugin('AbcImport', quiet=True)
        import_kwargs = {'i': True, 'returnNewNodes': True}
        if params.get('namespace'):
            import_kwargs['namespace'] = params['namespace']
        new_nodes = cmds.file(path, **import_kwargs) or []
        transforms = cmds.ls(new_nodes, type='transform', long=True) or []
        roots = [t for t in transforms if t.count('|') == 1]
        if params.get('parent') and roots:
            cmds.parent(roots, params['parent'])
        ctx.info(node_id, f'imported {len(new_nodes)} node(s) from {path}')
        if params.get('filter'):
            patterns = _as_list(params['filter'])
            transforms = [t for t in transforms if _name_match(t, patterns)]
            ctx.info(node_id, f'filter {params["filter"]!r} publishes '
                              f'{len(transforms)} transform(s)')
            # the curated transforms ARE what this node publishes
            return {'nodes': cmds.ls(transforms),
                    'transforms': cmds.ls(transforms)}
        return {'nodes': new_nodes, 'transforms': cmds.ls(transforms)}


@register
class GroupOp(OpBackend):
    """Resolve a selection *rule* to scene nodes or components.

    Two flavors, decided by the presence of 'ids':

        object group: pattern/items resolve to a node list.
        component group: the rule must resolve to exactly ONE node; ids +
            mode expand to component strings ('mesh.vtx[0:3]'). With an
            empty rule, a single-node upstream source is inherited
            (cloth -> component group flows).

    A brand-new group is valid while empty (UI default state): dry-run
    only warns, execute fails.

    Params:
        pattern (str or list): ls-style name pattern(s).
        items (list): Explicit node names (exact-match rules, UI picks).
        node_type (str): Optional type filter (e.g. 'mesh' - resolves to
            the transforms of matched shapes).
        mode (str): object / face / edge / point (default 'object') -
            component type, maps to nComponent.componentType downstream.
        ids (list): Component group - component ids, ints or 'start:end'
            strings (e.g. [0, "2:5"]).

    Inputs:
        source: Optional upstream output restricting candidates.

    Outputs:
        object group    -> {'nodes': [...], 'mode': mode}
        component group -> {'nodes': ['mesh.vtx[0]', 'mesh.vtx[2:5]'],
                            'components': [{'node', 'mode', 'ids'}],
                            'mode': mode}
    """

    op_type = 'group'
    dcc = 'maya'

    MODES = ('object', 'face', 'edge', 'point')
    COMPONENT_ATTR = {'point': 'vtx', 'edge': 'e', 'face': 'f'}
    _ID_RANGE = re.compile(r'^\d+:\d+$')

    def validate_params(self, params: dict) -> list:
        errors = []
        mode = params.get('mode', 'object')
        if mode not in self.MODES:
            errors.append(f"mode must be one of {self.MODES}, got '{mode}'")
        ids = _as_list(params.get('ids'))
        if ids and mode not in self.COMPONENT_ATTR:
            errors.append("'ids' requires mode point, edge or face")
        for entry in ids:
            if isinstance(entry, int):
                continue
            if isinstance(entry, str) and self._ID_RANGE.match(entry):
                continue
            errors.append(f"invalid id entry {entry!r} "
                          f"(int or 'start:end' string)")
        return errors

    @staticmethod
    def _rule(params) -> list:
        return _as_list(params.get('pattern')) + _as_list(params.get('items'))

    def _resolve(self, params, inputs):
        source = inputs.get('source')
        candidates = None
        if source:
            if isinstance(source, dict):
                # A 'nodes' key wins; otherwise flatten every list output
                candidates = source.get('nodes')
                if candidates is None:
                    candidates = []
                    for value in source.values():
                        candidates.extend(_as_list(value))
            else:
                candidates = _as_list(source)

        rule = self._rule(params)
        if not rule:
            # empty rule inherits the upstream source wholesale
            return sorted(set(_as_list(candidates)))

        kwargs = {}
        if params.get('node_type'):
            kwargs['type'] = params['node_type']
            kwargs['dag'] = True
        matched = cmds.ls(rule, **kwargs) or []
        if params.get('node_type'):
            # resolve shapes back to their transforms
            shapes = cmds.ls(matched, shapes=True)
            if shapes:
                transforms = cmds.listRelatives(shapes, parent=True) or []
                matched = sorted(set(transforms)
                                 | (set(matched) - set(shapes)))
        if candidates is not None:
            # compare on the node part so components ('mesh.vtx[0:3]')
            # survive a source restriction
            short = {str(c).split('|')[-1].split('.')[0] for c in candidates}
            matched = [m for m in matched
                       if m.split('|')[-1].split('.')[0] in short]
        return sorted(set(matched))

    def _outputs(self, params, nodes) -> dict:
        """Shape the outputs; expands ids on the (single) resolved node."""
        mode = params.get('mode', 'object')
        ids = _as_list(params.get('ids'))
        if not ids:
            return {'nodes': nodes, 'mode': mode}
        if len(nodes) != 1:
            raise ValueError(f'component group needs exactly one node, '
                             f'rule resolved {len(nodes)}: {nodes}')
        attr = self.COMPONENT_ATTR[mode]
        comps = [f'{nodes[0]}.{attr}[{i}]' for i in ids]
        return {'nodes': comps,
                'components': [{'node': nodes[0], 'mode': mode, 'ids': ids}],
                'mode': mode}

    def dry_run(self, node_id, params, inputs, ctx):
        errors = self.validate_params(params)
        if errors:
            for msg in errors:
                ctx.error(node_id, msg)
            return {'nodes': [], 'mode': params.get('mode', 'object')}
        if not self._rule(params) and not inputs.get('source'):
            ctx.warning(node_id, 'empty group (no rule, no source)')
            return {'nodes': [], 'mode': params.get('mode', 'object')}
        nodes = self._resolve(params, inputs)
        level = ctx.info if nodes else ctx.warning
        level(node_id, f'rule currently resolves {len(nodes)} node(s)')
        try:
            return self._outputs(params, nodes)
        except ValueError as e:
            ctx.warning(node_id, str(e))
            return {'nodes': [], 'mode': params.get('mode', 'object')}

    def execute(self, node_id, params, inputs, ctx):
        nodes = self._resolve(params, inputs)
        if not nodes:
            raise ValueError(f'group rule resolved nothing '
                             f'(rule={self._rule(params)!r})')
        outputs = self._outputs(params, nodes)
        ctx.info(node_id, f"{len(outputs['nodes'])} member(s) resolved")
        return outputs


@register
class HierarchyOp(OpBackend):
    """Create the standard sim hierarchy (create_hierarchy backend).

    Params:
        asset (str), rig (str)
        groups (list): Stage group names (default: presim, utils,
            collider, sim, postsim, exp). Each becomes a named output a
            step can wire its parent to ('hierarchy.presim').

    Outputs:
        {'asset_grp', 'rig_grp', <one key per group>}
    """

    op_type = 'hierarchy'
    dcc = 'maya'

    KEYS = ('presim', 'utils', 'collider', 'sim', 'postsim', 'exp')

    def validate_params(self, params: dict) -> list:
        return [f"'{k}' is required" for k in ('asset', 'rig')
                if not params.get(k)]

    def execute(self, node_id, params, inputs, ctx):
        groups = _as_list(params.get('groups')) or list(self.KEYS)
        result = create_hierarchy(asset=params['asset'],
                                  rigname=params['rig'],
                                  groups=groups)
        outputs = {'asset_grp': result[0][0], 'rig_grp': result[1][0]}
        outputs.update(dict(zip(groups, result[2:])))
        return outputs


@register
class SolverOp(OpBackend):
    """Create a nucleus solver and adopt the upstream sim objects.

    The solver is the SINK of a sim setup: cloth/collider/constraint
    nodes flow into it (recipes read causally, Houdini/Vellum style -
    a future vellum backend evaluates the same shape natively). The
    upstream ops built on a staging nucleus; this op moves every
    collected nCloth/nRigid/dynamicConstraint onto the real solver and
    deletes the staging node.

    Params:
        name (str): Solver node name.
        parent (str): Optional parent (literal name).
        attrs (dict): Attributes to set, token-aware
            (e.g. {"startFrame": "$RFSTART", "spaceScale": 0.1}).

    Inputs:
        objects: Upstream cloth/collider/constraint outputs (wire a
            merge node to combine several setups).
        parent: Optional upstream group (overrides params parent).

    Outputs:
        {'solver': nucleus_node, 'objects': adopted nodes}
    """

    op_type = 'solver'
    dcc = 'maya'

    def validate_params(self, params: dict) -> list:
        return [] if params.get('name') else ["'name' is required"]

    def execute(self, node_id, params, inputs, ctx):
        parent = inputs.get('parent') or params.get('parent')
        if isinstance(parent, dict):
            parent = parent.get('rig_grp') or parent.get('nodes', [None])[0]
        nucleus = dwnx.create_nucleus(name=params['name'], parent=parent)
        _set_attrs(nucleus, params.get('attrs'), ctx, node_id)

        collected = _collect_strings(inputs.get('objects'))
        shapes = cmds.ls(collected,
                         dag=True,
                         type=('nCloth', 'nRigid', 'dynamicConstraint'),
                         long=False) or []
        adopted = []
        # constraints last: their solver index wiring expects the
        # members to already live on the target nucleus
        for shape in sorted(set(shapes),
                            key=lambda s: cmds.nodeType(s)
                            == 'dynamicConstraint'):
            node_type = cmds.nodeType(shape)
            if node_type == 'dynamicConstraint':
                _move_constraint(shape, nucleus)
            else:
                _move_nobject(shape, nucleus, active=node_type == 'nCloth')
            adopted.append(shape)
        if adopted:
            cmds.getAttr(f'{nucleus}.forceDynamics')
            ctx.info(node_id, f'{len(adopted)} object(s) adopted by '
                              f'{nucleus}')

        staging = ctx.shared.pop('staging_nucleus', None)
        if staging and cmds.objExists(staging):
            leftovers = cmds.listConnections(staging, source=True,
                                             destination=False,
                                             type='nBase') or []
            if leftovers:
                ctx.warning(node_id, f'staging nucleus kept: '
                                     f'{sorted(set(leftovers))} not '
                                     f'wired into any solver')
                ctx.shared['staging_nucleus'] = staging
            else:
                cmds.delete(staging)
        return {'solver': nucleus, 'objects': adopted}


@register
class ClothOp(OpBackend):
    """Turn a group of meshes into nCloth objects on a solver.

    Params:
        name (str): Base name for the nCloth nodes.
        pattern (str or list): Optional wildcard(s) narrowing the input
            meshes ('wing_*_sim_msh').
        world_space (int): 0 local (default) / 1 world.

    Inputs:
        meshes: Upstream file/group/step output (or list) of transforms.

    Outputs:
        {'cloth': [nCloth nodes], 'meshes': input meshes}
    """

    op_type = 'cloth'
    dcc = 'maya'

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _filter_meshes(_as_list(meshes), params.get('pattern'))
        if not meshes:
            raise ValueError('no input meshes')
        kwargs = {}
        if params.get('name'):
            kwargs['name'] = params['name']
        cloth = dwnx.create_ncloth(meshes,
                                   nucleus_node=_staging_solver(ctx),
                                   world_space=params.get('world_space', 0),
                                   **kwargs)
        ctx.info(node_id, f'{len(cloth)} nCloth created (awaiting solver)')
        return {'cloth': cloth, 'meshes': meshes}


@register
class ColliderOp(OpBackend):
    """Make a group of meshes passive colliders on a solver.

    Params:
        preset (int): set_collider_preset index (default 2 = collide).
        pattern (str or list): Optional wildcard(s) narrowing the input
            meshes.
        thickness (float): Optional fixed thickness (else auto-computed).

    Inputs:
        meshes: Upstream file/group output (or list) of mesh transforms.

    Outputs:
        {'rigids': [nRigid nodes]}
    """

    op_type = 'collider'
    dcc = 'maya'

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _filter_meshes(_as_list(meshes), params.get('pattern'))
        if not meshes:
            raise ValueError('no input meshes')

        staging = _staging_solver(ctx)
        rigids = []
        for mesh in meshes:
            kwargs = {'preset': params.get('preset', 2)}
            if params.get('thickness') is not None:
                kwargs['thickness'] = params['thickness']
            kwargs['name'] = f"{mesh.split('|')[-1].split(':')[-1]}_collider"
            rigids += make_collide_ncloth(sel_mesh=mesh,
                                          nucleus=staging,
                                          **kwargs)
        ctx.info(node_id, f'{len(rigids)} collider(s) created '
                          f'(awaiting solver)')
        return {'rigids': rigids}


@register
class StepOp(OpBackend):
    """Duplicate meshes into a pipeline stage (build_sim_step backend).

    Params:
        stage (str): Step name injected in the mesh names (sim, postsim...).
        index (int): Name-part index replaced/inserted (default -2).
        insert (bool): Insert instead of replace (default False).
        method (str): 'outmesh' (default, live connected copy) or
            'duplicate' (static copy - nucleus presim meshes).
        connection (bool): Connect original -> duplicate (defaults to True
            for outmesh, False for duplicate).
        pattern (str or list): Optional wildcard(s) narrowing the input
            meshes.

    Inputs:
        meshes: Upstream group/step output (or list) of transforms.
        parent: Optional group the new meshes are parented under.

    Outputs:
        {'nodes': created transforms}
    """

    op_type = 'step'
    dcc = 'maya'

    METHODS = ('outmesh', 'duplicate')

    def validate_params(self, params: dict) -> list:
        errors = [] if params.get('stage') else ["'stage' is required"]
        method = params.get('method', 'outmesh')
        if method not in self.METHODS:
            errors.append(f"method must be one of {self.METHODS}, "
                          f"got '{method}'")
        return errors

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _filter_meshes(_as_list(meshes), params.get('pattern'))
        if not meshes:
            raise ValueError('no input meshes')
        parent = inputs.get('parent')
        if isinstance(parent, dict):
            parent = parent.get(params['stage']) or parent.get('nodes', [None])[0]
        method = params.get('method', 'outmesh')
        created = build_sim_step(step_name=params['stage'],
                                 step_ind=params.get('index', -2),
                                 obj=meshes,
                                 insert=params.get('insert', False),
                                 parent=parent,
                                 connection=params.get('connection',
                                                       method == 'outmesh'),
                                 method=method)
        ctx.info(node_id, f'{len(created)} {params["stage"]} mesh(es) created')
        return {'nodes': created}


@register
class PresetOp(OpBackend):
    """Apply a saved dw_preset envelope (v2 component presets).

    Params:
        path (str): Preset json path.
        target_ns (str): Namespace lookups resolve against (default ':').
        create (bool): Allow creating missing nodes (default True).

    Outputs:
        {'nodes': names of the nodes the preset touched}
    """

    op_type = 'preset'
    dcc = 'maya'

    def validate_params(self, params: dict) -> list:
        path = params.get('path')
        if not path:
            return ["'path' is required"]
        if not os.path.isfile(str(path)):
            return [f'preset file not found: {path}']
        return []

    def execute(self, node_id, params, inputs, ctx):
        nodes = pcomp.load_preset_file(str(params['path']),
                                       target_ns=params.get('target_ns', ':'),
                                       create=params.get('create', True))
        names = [n.node for n in nodes]
        ctx.info(node_id, f'preset applied to {len(names)} node(s)')
        return {'nodes': names}


@register
class ConstraintOp(OpBackend):
    """Create a dynamicConstraint, or rebuild constraints from a preset.

    Two modes:
        create (default): feed the input members (objects or components,
            order matters: constrained members first, target last) to the
            createNConstraint python port. The solver is inferred from the
            members' nucleus objects.
        preset: params['preset_path'] switches to rebuilding a saved
            nConstraint dw_preset envelope (createAllConstraintPresets).

    Params:
        method (str): transform, pointToSurface (default), slideOnSurface,
            weldBorders, force, match, tearableSurface, collisionExclusion,
            disableCollision, pointToPoint.
        name (str): Constraint node name.
        preset_path (str): Preset mode - envelope json path.
        target_ns (str): Preset mode - namespace (default ':').

    Inputs:
        first: Group output (or list) - constrained members/components.
        second: Optional group output - target surface/object.

    Outputs:
        {'constraints': [transforms], 'shapes': [dynamicConstraint shapes]}
    """

    op_type = 'constraint'
    dcc = 'maya'

    METHODS = ('transform', 'pointToSurface', 'slideOnSurface',
               'weldBorders', 'force', 'match', 'tearableSurface',
               'collisionExclusion', 'disableCollision', 'pointToPoint')

    def validate_params(self, params: dict) -> list:
        if params.get('preset_path'):
            if not os.path.isfile(str(params['preset_path'])):
                return [f"preset file not found: {params['preset_path']}"]
            return []
        method = params.get('method', 'pointToSurface')
        if method not in self.METHODS:
            return [f"method must be one of {self.METHODS}, got '{method}'"]
        return []

    @staticmethod
    def _members(value) -> list:
        if isinstance(value, dict):
            value = value.get('nodes')
        return _as_list(value)

    def execute(self, node_id, params, inputs, ctx):
        # Preset mode: rebuild saved constraint networks
        if params.get('preset_path'):
            transforms = dwnx.createAllConstraintPresets(
                str(params['preset_path']),
                targ_ns=params.get('target_ns', ':'))
            shapes = cmds.ls(transforms, dag=True, type='dynamicConstraint')
            ctx.info(node_id, f'{len(transforms)} constraint(s) rebuilt '
                              f'from preset')
            return {'constraints': transforms, 'shapes': shapes}

        # Create mode: constrained members first, target last
        members = (self._members(inputs.get('first'))
                   + self._members(inputs.get('second')))
        if not members:
            raise ValueError("no input members ('first' / 'second')")
        created = createNConstraint(selection=members,
                                    constraintType=params.get('method',
                                                              'pointToSurface')) or []
        shapes = cmds.ls(created, dag=True, type='dynamicConstraint')
        if not shapes:
            raise ValueError(f'createNConstraint created no constraint from '
                             f'{len(members)} member(s)')
        transforms = list(dict.fromkeys(
            cmds.listRelatives(shapes, parent=True) or []))
        # createNConstraint's own name kwarg only names the shape; rename
        # the transform/shape pair explicitly
        if params.get('name') and len(shapes) == 1:
            new_shape = cmds.rename(shapes[0], params['name'] + 'Shape')
            new_tr = cmds.rename(cmds.listRelatives(new_shape, parent=True)[0],
                                 params['name'])
            transforms = [new_tr]
            shapes = cmds.listRelatives(new_tr, shapes=True)
        ctx.info(node_id, f'{len(shapes)} constraint(s) created on '
                          f'{len(members)} member(s)')
        return {'constraints': transforms, 'shapes': shapes}


@register
class DeformerOp(OpBackend):
    """Make driven geometry follow driver geometry.

    One semantic intent, three mechanisms:
        wrap: different topology (model -> sim proxy).
        blendShape: same topology, weight 1, world origin (anim -> model).
        connect: same topology, direct outMesh -> inMesh plug wire -
            cheapest, no deformer node, no envelope to blend.

    Params:
        kind (str): 'wrap' (default), 'blendShape' or 'connect'.
        name (str): Optional deformer name (wrap / blendShape).
        pattern (str or list): Optional wildcard(s) picking the driven /
            driver mesh out of multi-mesh inputs (same wildcard applies
            to both; use group nodes for asymmetric picks).
        exclusive_bind (bool): Wrap exclusiveBind flag (default False).

    Inputs:
        driven: The deformed mesh(es) - every mesh of the upstream output
            (pattern-narrowed) gets its own deformer.
        driver: The influence mesh (first of its upstream output).

    Outputs:
        {'deformer': first, 'deformers': all, 'driven': driven meshes}
        (+ 'bases' for wrap, 'plugs' for connect)
    """

    op_type = 'deformer'
    dcc = 'maya'

    KINDS = ('wrap', 'blendShape', 'connect')

    def validate_params(self, params: dict) -> list:
        kind = params.get('kind', 'wrap')
        if kind not in self.KINDS:
            return [f"kind must be one of {self.KINDS}, got '{kind}'"]
        return []

    @staticmethod
    def _meshes(value, pattern=None) -> list:
        if isinstance(value, dict):
            value = value.get('nodes') or value.get('meshes')
        return _filter_meshes(_as_list(value), pattern)

    @staticmethod
    def _shape(node):
        shapes = cmds.ls(node, dag=True, type='shape', noIntermediate=True)
        if not shapes:
            raise ValueError(f'no shape under {node}')
        return shapes[0]

    def execute(self, node_id, params, inputs, ctx):
        pattern = params.get('pattern')
        driven_list = self._meshes(inputs.get('driven'), pattern)
        drivers = self._meshes(inputs.get('driver'), pattern)
        if not driven_list or not drivers:
            raise ValueError("both 'driven' and 'driver' inputs are required")
        driver = drivers[0]
        kind = params.get('kind', 'wrap')

        outputs = {'deformers': [], 'driven': driven_list}
        for driven in driven_list:
            if kind == 'blendShape':
                kwargs = {'origin': 'world', 'weight': (0, 1)}
                if params.get('name'):
                    kwargs['name'] = params['name']
                outputs['deformers'].append(
                    cmds.blendShape(driver, driven, **kwargs)[0])
            elif kind == 'connect':
                source = dwu.get_type_io(self._shape(driver), io=1)
                target = dwu.get_type_io(self._shape(driven), io=0)
                if not cmds.listConnections(target, source=True,
                                            destination=False):
                    cmds.connectAttr(source, target, force=True)
                outputs['deformers'].append(driven)
                outputs.setdefault('plugs', []).append([source, target])
            else:
                kwargs = {'exclusiveBind': params.get('exclusive_bind',
                                                      False)}
                if params.get('name'):
                    kwargs['name'] = params['name']
                wrap = dwdef.createWrap(driven, driver, **kwargs)
                outputs['deformers'].append(wrap[0])
                outputs.setdefault('bases', []).append(wrap[1])
        outputs['deformer'] = outputs['deformers'][0]
        ctx.info(node_id, f'{len(driven_list)} mesh(es) follow {driver} '
                          f'({kind})')
        return outputs