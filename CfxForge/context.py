"""BuildContext: state threaded through one recipe execution.

Summary:
    Holds the outputs every executed node produced, the report (info /
    warning / error entries with their node id), and the dry_run flag.
    Backends read upstream results through resolved inputs and may stash
    shared state (e.g. a localisation in/out pair) in ``ctx.shared``.

    It also resolves where a node's hand-edit sidecar lives (``edit_dir``
    + ``edit_path``): the file an artist captures after editing a build by
    hand, re-applied on every later build. The context only says *where*;
    reading and writing it is the op backend's job, so a captured edit
    stays a document other tools already understand (a dw_preset stays a
    dw_preset) instead of a CfxForge-only envelope.

Classes:
    BuildContext

Author:
    DrWeeny
"""

import os


class BuildContext(object):
    """Execution state for one recipe run.

    Args:
        dry_run: Validate through the backends without executing.
        edit_dir: Folder holding the per-node hand-edit sidecars, normally
            next to the recipe json. None disables edits entirely.
    """

    def __init__(self, dry_run: bool = False, edit_dir: str = None):
        self.dry_run = dry_run
        self.edit_dir = edit_dir
        #: {node_id: {output_key: value}} recorded after each node runs.
        self.outputs = {}
        #: Cross-node scratch space (e.g. paired localisation state).
        self.shared = {}
        #: [{'node': id, 'level': 'info'|'warning'|'error', 'message': str}]
        self.report = []

    # ------------------------------------------------------------------
    # Hand-edit sidecars
    # ------------------------------------------------------------------

    def edit_path(self, node_id: str, params: dict = None) -> str:
        """Where a node's hand-edit sidecar lives.

        A node names its own file through the ``edit_file`` param (taken
        as-is when absolute, else relative to ``edit_dir``); without one
        it falls back to ``<edit_dir>/<node_id>.json``.

        Args:
            node_id: Recipe node id.
            params: The node's params dict.

        Returns:
            str: The path, or None when edits are disabled (no edit_dir
                and no absolute ``edit_file``).
        """
        name = (params or {}).get('edit_file')
        if name and os.path.isabs(str(name)):
            return str(name)
        if not self.edit_dir:
            return None
        return os.path.join(self.edit_dir, str(name or f'{node_id}.json'))

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