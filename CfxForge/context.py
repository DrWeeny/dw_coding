"""BuildContext: state threaded through one recipe execution.

Summary:
    Holds the outputs every executed node produced, the report (info /
    warning / error entries with their node id), and the dry_run flag.
    Backends read upstream results through resolved inputs and may stash
    shared state (e.g. a localisation in/out pair) in ``ctx.shared``.

Classes:
    BuildContext

Author:
    DrWeeny
"""


class BuildContext(object):
    """Execution state for one recipe run."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        #: {node_id: {output_key: value}} recorded after each node runs.
        self.outputs = {}
        #: Cross-node scratch space (e.g. paired localisation state).
        self.shared = {}
        #: [{'node': id, 'level': 'info'|'warning'|'error', 'message': str}]
        self.report = []

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def info(self, node_id: str, message: str):
        self.report.append({'node': node_id, 'level': 'info',
                            'message': message})

    def warning(self, node_id: str, message: str):
        self.report.append({'node': node_id, 'level': 'warning',
                            'message': message})

    def error(self, node_id: str, message: str):
        self.report.append({'node': node_id, 'level': 'error',
                            'message': message})

    @property
    def errors(self) -> list:
        return [e for e in self.report if e['level'] == 'error']

    @property
    def ok(self) -> bool:
        return not self.errors

    # ------------------------------------------------------------------
    # Input resolution
    # ------------------------------------------------------------------

    def resolve_ref(self, ref: str):
        """Resolve an input reference to an executed node's output.

        ``"node_id"`` returns that node's whole outputs dict;
        ``"node_id.key"`` returns one named output.

        Raises:
            KeyError: When the referenced node has not produced outputs.
        """
        parts = str(ref).split('.', 1)
        node_outputs = self.outputs[parts[0]]
        if len(parts) == 1:
            return node_outputs
        return node_outputs[parts[1]]

    def summary(self) -> str:
        lines = [f"{len(self.outputs)} node(s) executed, "
                 f"{len(self.errors)} error(s)"]
        for entry in self.report:
            lines.append(f"[{entry['level'].upper():7}] "
                         f"{entry['node']}: {entry['message']}")
        return '\n'.join(lines)