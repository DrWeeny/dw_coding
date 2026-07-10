"""Op registry: op type -> backend class.

Summary:
    Same pattern as DynForge's guide_registry: backend classes register
    themselves, the executor instantiates one per node. All DCC calls live
    inside backends - the recipe and executor never import a DCC. A recipe
    stays semantic ("this group simulates as cloth"); which solver/DCC
    fulfils it is decided by whichever backend module the caller imported
    (e.g. a future ``CfxForge.maya_ops``).

Classes:
    OpBackend

Functions:
    register, get_backend, list_op_types

Author:
    DrWeeny
"""

_by_op_type = {}


class OpBackend(object):
    """One op implementation. Subclass, set ``op_type``, implement execute.

    Attributes:
        op_type: Recipe node type this backend fulfils (e.g. 'group').
        dcc: Implementation domain ('core' = DCC-agnostic pure python).
    """

    op_type = ''
    dcc = 'core'

    def execute(self, node_id: str, params: dict, inputs: dict, ctx) -> dict:
        """Run the op. Returns the node's named outputs.

        Args:
            node_id: Recipe node id (for naming / report entries).
            params: The node's params dict (pure data).
            inputs: Resolved upstream outputs, keyed by port name.
            ctx: BuildContext (outputs of previous nodes, report, dry_run).

        Returns:
            dict: Named outputs recorded under ``ctx.outputs[node_id]``.
        """
        raise NotImplementedError(f"'{self.op_type}': execute not implemented")

    def dry_run(self, node_id: str, params: dict, inputs: dict, ctx) -> dict:
        """Validate without touching the scene. Default: params check only.

        Backends override to resolve rules against the scene (e.g. a group
        op reporting what its pattern currently matches). Returns outputs
        placeholders so downstream dry-runs can resolve their inputs.
        """
        errors = self.validate_params(params)
        for msg in errors:
            ctx.error(node_id, msg)
        return {}

    def validate_params(self, params: dict) -> list:
        """Return a list of param error strings (empty = valid)."""
        return []


def register(backend_class):
    """Register a backend class. Usable as a decorator.

    First registration wins for an op type (mirrors sim_registry ordering
    semantics) so a studio can pre-register overrides before importing the
    default backends.
    """
    op_type = backend_class.op_type
    if not op_type:
        raise ValueError(f"{backend_class.__name__}: empty op_type")
    if op_type not in _by_op_type:
        _by_op_type[op_type] = backend_class
    return backend_class


def get_backend(op_type: str) -> OpBackend:
    """Instantiate the backend registered for an op type (or None)."""
    backend_class = _by_op_type.get(op_type)
    return backend_class() if backend_class else None


def list_op_types() -> list:
    """Return the registered op types, in registration order."""
    return list(_by_op_type)