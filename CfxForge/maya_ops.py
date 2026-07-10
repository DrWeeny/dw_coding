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

import os

from maya import cmds

import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_deformers as dwdef
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_maya.dw_nucleus_utils.dw_create_hierarchy import create_hierarchy, build_sim_step
from dw_maya.dw_nucleus_utils.dw_make_collide import make_collide_ncloth
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


@register
class FileOp(OpBackend):
    """Read or write a file (Houdini File-SOP style).

    Params:
        mode (str): 'read' (default) or 'write'.
        path (str): File path (.abc / .ma / .mb for read; .abc for write).
        namespace (str): Optional namespace for read.
        parent (str): Optional group the imported roots are parented under.
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
        return {'nodes': new_nodes, 'transforms': cmds.ls(transforms)}


@register
class GroupOp(OpBackend):
    """Resolve a selection *rule* to scene nodes.

    Params:
        pattern (str or list): ls-style name pattern(s).
        node_type (str): Optional type filter (e.g. 'mesh' - resolves to
            the transforms of matched shapes).
        mode (str): object / face / edge / point (default 'object') -
            consumed by component-level ops (constraint).

    Inputs:
        source: Optional upstream output restricting candidates.

    Outputs:
        {'nodes': [...], 'mode': mode}
    """

    op_type = 'group'
    dcc = 'maya'

    MODES = ('object', 'face', 'edge', 'point')

    def validate_params(self, params: dict) -> list:
        errors = []
        if not params.get('pattern'):
            errors.append("'pattern' is required")
        mode = params.get('mode', 'object')
        if mode not in self.MODES:
            errors.append(f"mode must be one of {self.MODES}, got '{mode}'")
        return errors

    def _resolve(self, params, inputs):
        patterns = _as_list(params['pattern'])
        kwargs = {}
        if params.get('node_type'):
            kwargs['type'] = params['node_type']
            kwargs['dag'] = True
        matched = cmds.ls(patterns, **kwargs) or []
        if params.get('node_type'):
            # resolve shapes back to their transforms
            shapes = cmds.ls(matched, shapes=True)
            if shapes:
                transforms = cmds.listRelatives(shapes, parent=True) or []
                matched = sorted(set(transforms)
                                 | (set(matched) - set(shapes)))
        source = inputs.get('source')
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
            short = {str(c).split('|')[-1] for c in candidates}
            matched = [m for m in matched if m.split('|')[-1] in short]
        return sorted(set(matched))

    def dry_run(self, node_id, params, inputs, ctx):
        errors = self.validate_params(params)
        for msg in errors:
            ctx.error(node_id, msg)
            return {'nodes': [], 'mode': params.get('mode', 'object')}
        nodes = self._resolve(params, inputs)
        level = ctx.info if nodes else ctx.warning
        level(node_id, f"pattern {params['pattern']!r} currently matches "
                       f"{len(nodes)} node(s)")
        return {'nodes': nodes, 'mode': params.get('mode', 'object')}

    def execute(self, node_id, params, inputs, ctx):
        nodes = self._resolve(params, inputs)
        if not nodes:
            raise ValueError(f"pattern {params['pattern']!r} matched nothing")
        ctx.info(node_id, f'{len(nodes)} node(s) matched')
        return {'nodes': nodes, 'mode': params.get('mode', 'object')}


@register
class HierarchyOp(OpBackend):
    """Create the standard sim hierarchy (create_hierarchy backend).

    Params:
        asset (str), rig (str)

    Outputs:
        {'asset_grp', 'rig_grp', 'presim', 'utils', 'collider', 'sim',
         'postsim', 'exp'}
    """

    op_type = 'hierarchy'
    dcc = 'maya'

    KEYS = ('presim', 'utils', 'collider', 'sim', 'postsim', 'exp')

    def validate_params(self, params: dict) -> list:
        return [f"'{k}' is required" for k in ('asset', 'rig')
                if not params.get(k)]

    def execute(self, node_id, params, inputs, ctx):
        result = create_hierarchy(asset=params['asset'],
                                  rigname=params['rig'])
        outputs = {'asset_grp': result[0][0], 'rig_grp': result[1][0]}
        outputs.update(dict(zip(self.KEYS, result[2:])))
        return outputs


@register
class SolverOp(OpBackend):
    """Create (or reuse) a nucleus solver.

    Params:
        name (str): Solver node name.
        parent (str): Optional parent (literal name).
        attrs (dict): Attributes to set, token-aware
            (e.g. {"startFrame": "$RFSTART", "spaceScale": 0.1}).

    Inputs:
        parent: Optional upstream group (overrides params parent).

    Outputs:
        {'solver': nucleus_node}
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
        return {'solver': nucleus}


@register
class ClothOp(OpBackend):
    """Turn a group of meshes into nCloth objects on a solver.

    Params:
        name (str): Base name for the nCloth nodes.
        world_space (int): 0 local (default) / 1 world.

    Inputs:
        meshes: Upstream group output (or list) of mesh transforms.
        solver: Upstream solver output.

    Outputs:
        {'cloth': [nCloth nodes], 'meshes': input meshes}
    """

    op_type = 'cloth'
    dcc = 'maya'

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _as_list(meshes)
        if not meshes:
            raise ValueError('no input meshes')
        solver = inputs.get('solver')
        if isinstance(solver, dict):
            solver = solver.get('solver')
        kwargs = {}
        if params.get('name'):
            kwargs['name'] = params['name']
        cloth = dwnx.create_ncloth(meshes,
                                   nucleus_node=solver,
                                   world_space=params.get('world_space', 0),
                                   **kwargs)
        ctx.info(node_id, f'{len(cloth)} nCloth created on {solver}')
        return {'cloth': cloth, 'meshes': meshes}


@register
class ColliderOp(OpBackend):
    """Make a group of meshes passive colliders on a solver.

    Params:
        preset (int): set_collider_preset index (default 2 = collide).
        thickness (float): Optional fixed thickness (else auto-computed).

    Inputs:
        meshes: Upstream group output (or list) of mesh transforms.
        solver: Upstream solver output.

    Outputs:
        {'rigids': [nRigid nodes]}
    """

    op_type = 'collider'
    dcc = 'maya'

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _as_list(meshes)
        if not meshes:
            raise ValueError('no input meshes')
        solver = inputs.get('solver')
        if isinstance(solver, dict):
            solver = solver.get('solver')

        rigids = []
        for mesh in meshes:
            kwargs = {'preset': params.get('preset', 2)}
            if params.get('thickness') is not None:
                kwargs['thickness'] = params['thickness']
            kwargs['name'] = f"{mesh.split('|')[-1].split(':')[-1]}_collider"
            rigids += make_collide_ncloth(sel_mesh=mesh,
                                          nucleus=solver,
                                          **kwargs)
        ctx.info(node_id, f'{len(rigids)} collider(s) on {solver}')
        return {'rigids': rigids}


@register
class StepOp(OpBackend):
    """Duplicate meshes into a pipeline stage (build_sim_step backend).

    Params:
        stage (str): Step name injected in the mesh names (sim, postsim...).
        index (int): Name-part index replaced/inserted (default -2).
        insert (bool): Insert instead of replace (default False).
        connection (bool): Connect original -> duplicate (default True).

    Inputs:
        meshes: Upstream group/step output (or list) of transforms.
        parent: Optional group the new meshes are parented under.

    Outputs:
        {'nodes': created transforms}
    """

    op_type = 'step'
    dcc = 'maya'

    def validate_params(self, params: dict) -> list:
        return [] if params.get('stage') else ["'stage' is required"]

    def execute(self, node_id, params, inputs, ctx):
        meshes = inputs.get('meshes')
        if isinstance(meshes, dict):
            meshes = meshes.get('nodes')
        meshes = _as_list(meshes)
        if not meshes:
            raise ValueError('no input meshes')
        parent = inputs.get('parent')
        if isinstance(parent, dict):
            parent = parent.get(params['stage']) or parent.get('nodes', [None])[0]
        created = build_sim_step(step_name=params['stage'],
                                 step_ind=params.get('index', -2),
                                 obj=meshes,
                                 insert=params.get('insert', False),
                                 parent=parent,
                                 connection=params.get('connection', True))
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
    """Create a deformer between upstream results. v1: wrap.

    Params:
        kind (str): 'wrap' (default; more kinds later).
        name (str): Optional deformer name.
        exclusive_bind (bool): Wrap exclusiveBind flag (default False).

    Inputs:
        driven: The deformed mesh (first node of an upstream output).
        driver: The influence mesh.

    Outputs:
        {'deformer': node, 'base': wrap base shape}
    """

    op_type = 'deformer'
    dcc = 'maya'

    KINDS = ('wrap',)

    def validate_params(self, params: dict) -> list:
        kind = params.get('kind', 'wrap')
        if kind not in self.KINDS:
            return [f"kind must be one of {self.KINDS}, got '{kind}'"]
        return []

    @staticmethod
    def _first(value):
        if isinstance(value, dict):
            value = value.get('nodes') or value.get('meshes')
        value = _as_list(value)
        return value[0] if value else None

    def execute(self, node_id, params, inputs, ctx):
        driven = self._first(inputs.get('driven'))
        driver = self._first(inputs.get('driver'))
        if not driven or not driver:
            raise ValueError("both 'driven' and 'driver' inputs are required")
        kwargs = {'exclusiveBind': params.get('exclusive_bind', False)}
        if params.get('name'):
            kwargs['name'] = params['name']
        wrap = dwdef.createWrap(driven, driver, **kwargs)
        return {'deformer': wrap[0], 'base': wrap[1]}