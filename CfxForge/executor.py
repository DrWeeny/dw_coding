"""Executor: run a recipe as a dependency-ordered task graph.

Summary:
    Topological order, one op at a time (task-graph semantics, not
    dataflow). Each node's backend runs once and its named outputs are
    recorded on the BuildContext for downstream nodes. ``dry_run=True``
    calls every backend's dry_run instead - full validation pass without
    touching a scene.

    A failing node stops execution of its downstream dependents but the
    error lands in ``ctx.report`` rather than raising, so a batch rebuild
    always produces a complete report. Interactive callers that want the
    build to halt on the first failure pass ``stop_on_error=True``.

    ``until`` builds only a node and its ancestors. A build is always
    meant to run from scratch into a fresh scene - the executor never
    resumes into a partly built one, so "build to here" gives the same
    result whatever was run before it.

    ``iter_execute`` is the same run as a generator, yielding after each
    node, so a UI can step through a build and let the artist inspect the
    scene between two ops without the executor knowing anything about it.

    Hand edits close the loop: an op declaring an ``edit_kind`` gets its
    sidecar re-applied straight after it executes, whenever the file
    exists. ``capture_node`` writes that file from a built scene.

Functions:
    execute_recipe, iter_execute, capture_node

Author:
    DrWeeny
"""

import os
import traceback

from .context import BuildContext
from .registry import get_backend
from .recipe import RecipeError
from dw_logger import get_logger

logger = get_logger()


def _handle_edit(backend,
                 node_id: str,
                 params: dict,
                 inputs: dict,
                 ctx,
                 dry_run: bool):
    """Re-apply a node's hand-edit sidecar, if the op has one and it exists.

    Raises whatever ``apply_edit`` raises: the caller turns it into a node
    failure. A build that quietly skipped a captured edit would hand back
    the un-edited version of the asset, which is worse than stopping.
    """
    if not backend.edit_kind:
        return

    path = ctx.edit_path(node_id, params)
    if not path:
        return

    if not os.path.isfile(path):
        # Not an error: the node has simply never been hand-edited.
        if dry_run:
            ctx.info(node_id, f'no {backend.edit_kind} edit saved yet')
        return

    if dry_run:
        ctx.info(node_id, f'would re-apply {backend.edit_kind} edit: {path}')
        return

    backend.apply_edit(node_id, params, inputs, ctx, path)
    ctx.info(node_id, f're-applied {backend.edit_kind} edit: {path}')


def capture_node(recipe,
                 node_id: str,
                 ctx) -> str:
    """Save the artist's hand edits on one node to its sidecar.

    Called after a build (usually a partial one, ``until=node_id``) once
    the artist has edited the result by hand. The written file is picked
    up automatically by every later build of that recipe.

    Args:
        recipe: The Recipe the node belongs to.
        node_id: Node to capture from.
        ctx: The BuildContext of the build being captured from - its
            outputs say what the node created.

    Returns:
        str: The written path, or None when there was nothing to save.

    Raises:
        RecipeError: On an unknown node.
        ValueError: When the op has no editable state, or edits are
            disabled (no ``edit_dir`` on the context).
    """
    if node_id not in recipe.nodes:
        raise RecipeError(f"Unknown node '{node_id}'")

    entry = recipe.nodes[node_id]
    op_type = entry['type']
    backend = get_backend(op_type)
    if backend is None:
        raise ValueError(f"no backend registered for op type '{op_type}'")
    if not backend.edit_kind:
        raise ValueError(f"'{op_type}' has no editable state to capture")

    params = entry.get('params', {})
    path = ctx.edit_path(node_id, params)
    if not path:
        raise ValueError('no edit_dir on the context, edits are disabled')

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    inputs = {}
    for port, ref in entry.get('inputs', {}).items():
        inputs[port] = ctx.resolve_ref(ref)

    written = backend.capture(node_id, params, inputs, ctx, path)
    if written:
        ctx.info(node_id, f'{backend.edit_kind} edit captured: {written}')
    else:
        ctx.warning(node_id, f'nothing to capture for {node_id}')
    return written


def iter_execute(recipe,
                 ctx: BuildContext,
                 dry_run: bool = False,
                 until=None,
                 stop_on_error: bool = False):
    """Execute a recipe node by node, yielding after each one.

    The caller owns the context, so it still holds the report when it
    abandons the generator half way (a UI pausing on a step, an artist
    closing the panel).

    Args:
        recipe: A Recipe instance.
        ctx: The BuildContext to fill in.
        dry_run: Validate through the backends without executing.
        until: Node id (or list) to build up to. None builds everything.
        stop_on_error: End the run at the first failing node instead of
            carrying on with the branches that do not depend on it.

    Yields:
        str: The node id that just ran (or was skipped).
    """
    ctx.dry_run = dry_run

    structural = recipe.validate()
    if structural:
        for msg in structural:
            ctx.error('<recipe>', msg)
        return

    try:
        order = recipe.build_order(until)
    except RecipeError as e:
        ctx.error('<recipe>', str(e))
        return

    if until is not None:
        ctx.info('<recipe>', f'building {len(order)} of '
                             f'{len(recipe.nodes)} node(s), up to {until}')

    failed = set()

    for node_id in order:
        entry = recipe.nodes[node_id]
        op_type = entry['type']

        # Skip nodes whose upstream failed - report stays complete.
        bad_deps = [d for d in recipe.dependencies(node_id) if d in failed]
        if bad_deps:
            ctx.warning(node_id, f"skipped, upstream failed: "
                                 f"{', '.join(bad_deps)}")
            failed.add(node_id)
            yield node_id
            continue

        backend = get_backend(op_type)
        if backend is None:
            ctx.error(node_id, f"no backend registered for op type "
                               f"'{op_type}'")
            failed.add(node_id)
            if stop_on_error:
                return
            yield node_id
            continue

        # Resolve input ports against upstream outputs.
        inputs = {}
        try:
            for port, ref in entry.get('inputs', {}).items():
                inputs[port] = ctx.resolve_ref(ref)
        except KeyError as e:
            ctx.error(node_id, f"unresolved input reference: {e}")
            failed.add(node_id)
            if stop_on_error:
                return
            yield node_id
            continue

        params = entry.get('params', {})
        try:
            if dry_run:
                outputs = backend.dry_run(node_id, params, inputs, ctx)
            else:
                outputs = backend.execute(node_id, params, inputs, ctx)
            ctx.outputs[node_id] = outputs or {}
            _handle_edit(backend, node_id, params, inputs, ctx, dry_run)
        except Exception:
            ctx.error(node_id, f"{op_type} failed:\n{traceback.format_exc()}")
            failed.add(node_id)
            if stop_on_error:
                return

        yield node_id


def execute_recipe(recipe,
                   ctx: BuildContext = None,
                   dry_run: bool = False,
                   until=None,
                   stop_on_error: bool = False) -> BuildContext:
    """Execute (or dry-run) a recipe in dependency order.

    Args:
        recipe: A Recipe instance.
        ctx: Existing context to run into (default: a fresh one). Note
            this does not resume a build - a recipe is always executed
            from its first node into a fresh scene.
        dry_run: Validate through the backends without executing.
        until: Node id (or list) to build up to, for debugging or for
            stopping where an artist wants to edit by hand.
        stop_on_error: End the run at the first failing node.

    Returns:
        BuildContext: outputs + report. Check ``ctx.ok`` / ``ctx.summary()``.
    """
    ctx = ctx or BuildContext(dry_run=dry_run)
    for _ in iter_execute(recipe,
                          ctx,
                          dry_run=dry_run,
                          until=until,
                          stop_on_error=stop_on_error):
        pass
    return ctx