"""CfxForge - declarative CFX rig build recipes.

Summary:
    Nodal representation of a CFX rig build as plain data (a "recipe"),
    executed as a dependency-ordered task graph. The core is DCC-agnostic
    and import-light: op backends (Maya/nucleus today, others later) are
    registered separately and do all DCC work behind the registry boundary.

Features:
    - Recipe document: json envelope, validation, topological ordering.
    - Op registry: op type -> backend class (same pattern as guide_registry).
    - Executor: run / dry-run a recipe, outputs flow through a BuildContext.
      Partial builds (``until=``), first-failure halt, and step-by-step
      iteration for debugging.
    - Hand edits: build to a node, edit by hand, capture the edit to a
      sidecar, and every later build re-applies it.
    - Core ops: 'script' (arbitrary python escape hatch).

Classes:
    Recipe, OpBackend, BuildContext

Functions:
    load_recipe, execute_recipe, iter_execute, capture_node, register,
    get_backend

Example:
    import CfxForge
    recipe = CfxForge.load_recipe(path)
    ctx = CfxForge.execute_recipe(recipe, dry_run=True)   # validate only
    ctx = CfxForge.execute_recipe(recipe)                 # build

    # build to a node, hand-edit the scene, capture the edit
    ctx = CfxForge.BuildContext(edit_dir=edits_folder)
    CfxForge.execute_recipe(recipe, ctx=ctx, until='cloth_preset')
    # ... artist retunes the cloth in the scene ...
    CfxForge.capture_node(recipe, 'cloth_preset', ctx)

TODO:
    - Maya op backends (file/group/solver/cloth/collider/constraint/...).
    - das schema per op type for param validation.
    - file-write barrier semantics for distributed execution.
    - edit_kind on the deformer/skin ops (weights), then paint maps.

Author:
    DrWeeny
"""

from .recipe import Recipe, load_recipe, save_recipe, RECIPE_FORMAT, RECIPE_VERSION
from .registry import OpBackend, register, get_backend, list_op_types
from .context import BuildContext
from .executor import execute_recipe, iter_execute, capture_node

# Core (DCC-agnostic) ops self-register on import.
from . import core_ops