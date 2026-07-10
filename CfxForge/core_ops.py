"""Core (DCC-agnostic) op backends.

Summary:
    Ops that need no DCC to run. Today: 'script', the escape hatch for
    choke points no taxonomy anticipates (multi-wrap chunking, cvWrap input
    limits, alembic delay loops...) and the migration path for porting old
    imperative rigs (start as one big script node, peel ops off over time).

Classes:
    ScriptOp

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