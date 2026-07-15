"""Core (DCC-agnostic) op backends.

Summary:
    Ops that need no DCC to run. 'script' is the escape hatch for choke
    points no taxonomy anticipates (multi-wrap chunking, cvWrap input
    limits, alembic delay loops...) and the migration path for porting old
    imperative rigs (start as one big script node, peel ops off over time).
    'merge' combines several upstream streams into one node list so a
    single consumer (cloth, constraint, export...) can take many sources.

Classes:
    ScriptOp, MergeOp

Author:
    DrWeeny
"""

from .registry import OpBackend, register


@register
class ScriptOp(OpBackend):
    """Run an arbitrary python snippet.

    Params:
        source (str): Python source. Runs with ``ctx``, ``inputs``,
            ``params`` and ``outputs`` in scope; assign into ``outputs``
            to expose results to downstream nodes.

    Example params:
        {"source": "outputs['meshes'] = inputs['group']['nodes'][:50]"}
    """

    op_type = 'script'
    dcc = 'core'

    def validate_params(self, params: dict) -> list:
        source = params.get('source')
        if not source or not isinstance(source, str):
            return ["'source' (str) is required"]
        try:
            compile(source, '<script-op>', 'exec')
        except SyntaxError as e:
            return [f"source does not compile: {e}"]
        return []

    def execute(self, node_id: str, params: dict, inputs: dict, ctx) -> dict:
        outputs = {}
        scope = {'ctx': ctx,
                 'inputs': inputs,
                 'params': params,
                 'outputs': outputs}
        exec(compile(params['source'], f'<script-op:{node_id}>', 'exec'), scope)
        return outputs


@register
class MergeOp(OpBackend):
    """Combine several upstream streams into one 'nodes' list.

    Wire any number of input ports (in0, in1, in2, ...); they merge in
    port-name order, duplicates keep their first occurrence. Dict inputs
    contribute their 'nodes' key (falling back to every list value),
    plain lists/values pass through.

    Outputs:
        {'nodes': merged list}
    """

    op_type = 'merge'
    dcc = 'core'

    @staticmethod
    def _flatten(value) -> list:
        if isinstance(value, dict):
            nodes = value.get('nodes')
            if nodes is not None:
                return list(nodes)
            flat = []
            for sub in value.values():
                if isinstance(sub, (list, tuple)):
                    flat.extend(sub)
            return flat
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value] if value is not None else []

    def execute(self, node_id: str, params: dict, inputs: dict, ctx) -> dict:
        merged = []
        for port in sorted(inputs):
            for node in self._flatten(inputs[port]):
                if node not in merged:
                    merged.append(node)
        ctx.info(node_id, f'{len(merged)} node(s) merged from '
                          f'{len(inputs)} stream(s)')
        return {'nodes': merged}

    def dry_run(self, node_id, params, inputs, ctx):
        return self.execute(node_id, params, inputs, ctx)