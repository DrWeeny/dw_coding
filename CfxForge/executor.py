"""Executor: run a recipe as a dependency-ordered task graph.

Summary:
    Topological order, one op at a time (task-graph semantics, not
    dataflow). Each node's backend runs once and its named outputs are
    recorded on the BuildContext for downstream nodes. ``dry_run=True``
    calls every backend's dry_run instead - full validation pass without
    touching a scene.

    A failing node stops execution of its downstream dependents but the
    error lands in ``ctx.report`` rather than raising, so a batch rebuild
    always produces a complete report.

Functions:
    execute_recipe

Author:
    DrWeeny
"""

import traceback

from .context import BuildContext
from .registry import get_backend
from dw_logger import get_logger

logger = get_logger()


def execute_recipe(recipe,
                   ctx: BuildContext = None,
                   dry_run: bool = False) -> BuildContext:
    """Execute (or dry-run) every node of a recipe in dependency order.

    Args:
        recipe: A Recipe instance.
        ctx: Existing context to continue into (default: a fresh one).
        dry_run: Validate through the backends without executing.

    Returns:
        BuildContext: outputs + report. Check ``ctx.ok`` / ``ctx.summary()``.
    """
    ctx = ctx or BuildContext(dry_run=dry_run)
    ctx.dry_run = dry_run

    structural = recipe.validate()
    if structural:
        for msg in structural:
            ctx.error('<recipe>', msg)
        return ctx

    failed = set()

    for node_id in recipe.topological_order():
        entry = recipe.nodes[node_id]
        op_type = entry['type']

        # Skip nodes whose upstream failed - report stays complete.
        bad_deps = [d for d in recipe.dependencies(node_id) if d in failed]
        if bad_deps:
            ctx.warning(node_id, f"skipped, upstream failed: "
                                 f"{', '.join(bad_deps)}")
            failed.add(node_id)
            continue

        backend = get_backend(op_type)
        if backend is None:
            ctx.error(node_id, f"no backend registered for op type "
                               f"'{op_type}'")
            failed.add(node_id)
            continue

        # Resolve input ports against upstream outputs.
        inputs = {}
        try:
            for port, ref in entry.get('inputs', {}).items():
                inputs[port] = ctx.resolve_ref(ref)
        except KeyError as e:
            ctx.error(node_id, f"unresolved input reference: {e}")
            failed.add(node_id)
            continue

        params = entry.get('params', {})
        try:
            if dry_run:
                outputs = backend.dry_run(node_id, params, inputs, ctx)
            else:
                outputs = backend.execute(node_id, params, inputs, ctx)
            ctx.outputs[node_id] = outputs or {}
        except Exception:
            ctx.error(node_id, f"{op_type} failed:\n{traceback.format_exc()}")
            failed.add(node_id)

    return ctx