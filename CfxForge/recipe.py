"""Recipe document: a CFX build as plain data.

Summary:
    A recipe is a json envelope holding a task graph: node id -> entry with
    an op ``type``, a ``params`` dict (pure data, das-friendly) and an
    ``inputs`` dict wiring the node to upstream results. Deliberately plain
    nested dicts, same philosophy as the dw_preset envelope, so a das schema
    can be attached later without changing the format.

Envelope:
    {
        "format": "dw_recipe",
        "version": 1,
        "name": "wings",
        "nodes": {
            "<node_id>": {
                "type": "group",
                "params": {...},
                "inputs": {"<port>": "<node_id>" | "<node_id>.<key>"}
            }
        }
    }

Classes:
    Recipe

Functions:
    load_recipe, save_recipe

Author:
    DrWeeny
"""

import json
import os

RECIPE_FORMAT = 'dw_recipe'
RECIPE_VERSION = 1


class RecipeError(ValueError):
    """Raised when a recipe document is structurally invalid."""


class Recipe(object):
    """In-memory recipe: node entries + graph queries.

    Args:
        nodes: ``{node_id: {"type": str, "params": dict, "inputs": dict}}``
        name: Recipe label (asset / rig name).
    """

    def __init__(self, nodes: dict = None, name: str = ''):
        self.name = name
        self.nodes = nodes or {}

    # ------------------------------------------------------------------
    # Document I/O
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> 'Recipe':
        if data.get('format') != RECIPE_FORMAT:
            raise RecipeError(f"Not a {RECIPE_FORMAT} document "
                              f"(format={data.get('format')!r})")
        return cls(nodes=data.get('nodes', {}), name=data.get('name', ''))

    def to_dict(self) -> dict:
        return {'format': RECIPE_FORMAT,
                'version': RECIPE_VERSION,
                'name': self.name,
                'nodes': self.nodes}

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def add_node(self,
                 node_id: str,
                 op_type: str,
                 params: dict = None,
                 inputs: dict = None) -> dict:
        """Add a node entry and return it (builder-style authoring)."""
        if node_id in self.nodes:
            raise RecipeError(f"Duplicate node id '{node_id}'")
        entry = {'type': op_type,
                 'params': params or {},
                 'inputs': inputs or {}}
        self.nodes[node_id] = entry
        return entry

    def dependencies(self, node_id: str) -> list:
        """Return upstream node ids referenced by a node's inputs."""
        entry = self.nodes[node_id]
        deps = []
        for ref in entry.get('inputs', {}).values():
            deps.append(str(ref).split('.')[0])
        return deps

    def ancestors(self, node_id: str, include_self: bool = True) -> set:
        """Return every node a node transitively depends on.

        Args:
            node_id: The node to walk up from.
            include_self: Include ``node_id`` in the result.

        Returns:
            set: Node ids. Unknown references are ignored here - that is
                ``validate``'s job, and slicing must stay usable on a
                half-authored recipe.

        Raises:
            RecipeError: When the node is not in the recipe.
        """
        if node_id not in self.nodes:
            raise RecipeError(f"Unknown node '{node_id}'")

        seen = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen or current not in self.nodes:
                continue
            seen.add(current)
            stack.extend(self.dependencies(current))

        if not include_self:
            seen.discard(node_id)
        return seen

    def build_order(self, until=None) -> list:
        """Return the execution order, optionally cut at a node.

        ``until`` keeps only the target(s) and what they depend on - the
        rest of the graph is not merely stopped at, it is never visited,
        so a sibling branch that has nothing to do with the target does
        not run either. That is what makes "build to here" reproducible:
        the same slice always builds the same scene.

        Args:
            until: Node id, or list of node ids, to build up to. None
                builds everything.

        Returns:
            list: Node ids in dependency order.

        Raises:
            RecipeError: On a cycle, or an unknown target node.
        """
        order = self.topological_order()
        if until is None:
            return order

        targets = [until] if isinstance(until, str) else list(until)
        keep = set()
        for target in targets:
            keep.update(self.ancestors(target))
        return [node_id for node_id in order if node_id in keep]

    # ------------------------------------------------------------------
    # Validation / ordering
    # ------------------------------------------------------------------

    def validate(self) -> list:
        """Structural validation. Returns a list of error strings.

        Checks input references point to existing nodes and the graph is
        acyclic. Op-type existence is the registry's concern (a recipe may
        be validated on a machine without the DCC backends installed).
        """
        errors = []
        for node_id, entry in self.nodes.items():
            if not isinstance(entry, dict) or 'type' not in entry:
                errors.append(f"'{node_id}': entry must be a dict with a 'type'")
                continue
            for port, ref in entry.get('inputs', {}).items():
                dep = str(ref).split('.')[0]
                if dep not in self.nodes:
                    errors.append(f"'{node_id}' input '{port}' references "
                                  f"unknown node '{dep}'")
        try:
            self.topological_order()
        except RecipeError as e:
            errors.append(str(e))
        return errors

    def topological_order(self) -> list:
        """Return node ids in dependency order (Kahn's algorithm).

        Deterministic: ties resolve in insertion order (python 3.7 dicts).

        Raises:
            RecipeError: When the graph has a cycle.
        """
        pending = {node_id: set(d for d in self.dependencies(node_id)
                                if d in self.nodes)
                   for node_id in self.nodes}
        order = []
        while pending:
            ready = [n for n, deps in pending.items() if not deps]
            if not ready:
                cycle = ', '.join(sorted(pending))
                raise RecipeError(f"Cycle detected among nodes: {cycle}")
            for n in ready:
                order.append(n)
                del pending[n]
            for deps in pending.values():
                deps.difference_update(ready)
        return order


def load_recipe(path: str) -> Recipe:
    """Read a recipe json file."""
    with open(path, 'r') as f:
        return Recipe.from_dict(json.load(f))


def save_recipe(recipe: Recipe, path: str) -> str:
    """Write a recipe as json. Returns the written path."""
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, 'w') as f:
        json.dump(recipe.to_dict(), f, indent=4)
    return path