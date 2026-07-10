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
    - Core ops: 'script' (arbitrary python escape hatch).

Classes:
    Recipe, OpBackend, BuildContext

Functions:
    load_recipe, execute_recipe, register, get_backend

Example:
    import CfxForge
    recipe = CfxForge.load_recipe(path)
    ctx = CfxForge.execute_recipe(recipe, dry_run=True)   # validate only
    ctx = CfxForge.execute_recipe(recipe)                 # build

TODO:
    - Maya op backends (file/group/solver/cloth/collider/constraint/...).
    - das schema per op type for param validation.
    - file-write barrier semantics for distributed execution.

Author:
    DrWeeny
"""

from .recipe import Recipe, load_recipe, save_recipe, RECIPE_FORMAT, RECIPE_VERSION
from .registry import OpBackend, register, get_backend, list_op_types
from .context import BuildContext
from .executor import execute_recipe

# Core (DCC-agnostic) ops self-register on import.
from . import core_ops