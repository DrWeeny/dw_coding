"""
Node naming convention for the nucleus tools.

Summary:
    Derives the name of a created node (nCloth, nRigid, output mesh, ...)
    from the mesh it is built on, so a multi-mesh call never falls back to
    Maya auto-numbering. The rules live in one swappable object: a studio
    whose meshes end in `_geo` and whose colliders end in `_rigid` sets its
    own instance once at startup instead of patching every tool.

Features:
    - Suffix roles held in a dict, not in branching code: add a role by
      adding a key.
    - Handles the transform/shape pair: `body_msh` and `body_mshShape`
        both reduce to the same base, and `shape=True` re-adds `Shape`.
    - DAG path and namespace are stripped: created nodes are local, they
        should not be pushed into a referenced namespace.

Classes:
    NucleusNaming: The convention itself.

Functions:
    get_naming: Return the active convention.
    set_naming: Replace the active convention (studio override).

Example:
    >>> from dw_maya.dw_nucleus_utils import _naming_convention
    >>> naming = _naming_convention.get_naming()
    >>> naming.name('|grp|ns:tissus_sim_msh', 'ncloth')
    'tissus_sim_ncloth'
    >>> naming.name('tissus_sim_msh', 'output', shape=True)
    'tissus_sim_outputcloth_mshShape'

    Studio override, once at startup:
    >>> _naming_convention.set_naming(_naming_convention.NucleusNaming(
    ...     source_suffixes=['_geo'],
    ...     collider='_rigid'))

TODO:
    Hook onto dw_pipe_project.Project so the convention ships with the
    studio adapter instead of being set by hand.

Author:
    DrWeeny
"""

import re
from typing import List


class NucleusNaming(object):
    """
    Suffix convention used to name nodes after the mesh they belong to.

    Args:
        source_suffixes (list): Mesh suffixes stripped to get the base name,
            longest match wins. Defaults to ['_msh'].
        shape_suffix (str): Suffix Maya appends to a shape. Defaults to
            'Shape'.
        **roles: Suffix per role, overriding the defaults (ncloth, output,
            collider, nucleus, constraint, polyunite).
    """

    DEFAULT_ROLES = {'ncloth': '_ncloth',
                     'output': '_outputcloth_msh',
                     'collider': '_collider',
                     'nucleus': '_nucleus',
                     'constraint': '_nconstraint',
                     'polyunite': '_polyunite'}

    def __init__(self,
                 source_suffixes: List[str] = None,
                 shape_suffix: str = 'Shape',
                 **roles):
        self.source_suffixes = list(source_suffixes or ['_msh'])
        self.shape_suffix = shape_suffix
        self.roles = dict(self.DEFAULT_ROLES)
        self.roles.update(roles)
        self._shape_pattern = re.compile(f'{re.escape(shape_suffix)}(?=\\d*$)')

    def base(self, node: str) -> str:
        """
        Reduce a node name to the part shared by every node built on it.

        Strips the DAG path, the namespace, a trailing shape suffix and a
        trailing mesh suffix, in that order. A name carrying none of them
        is returned unchanged, so the caller always gets something usable.

        Args:
            node (str): Mesh shape or transform, short name or full path.

        Returns:
            str: Base name.

        Example:
            >>> NucleusNaming().base('|grp|ns:body_mshShape')
            'body'
            >>> NucleusNaming().base('pSphereShape1')
            'pSphere1'
        """
        short = node.split('|')[-1].split(':')[-1]
        short = self._shape_pattern.sub('', short)
        for suffix in sorted(self.source_suffixes, key=len, reverse=True):
            if short.lower().endswith(suffix.lower()):
                return short[:-len(suffix)]
        return short

    def name(self, node: str, role: str, shape: bool = False) -> str:
        """
        Name a node created from `node` for a given role.

        Args:
            node (str): Mesh the new node is built on.
            role (str): Key of `self.roles` ('ncloth', 'collider', ...).
            shape (bool): Append the shape suffix.

        Returns:
            str: New node name.

        Raises:
            KeyError: If the role is unknown.
        """
        if role not in self.roles:
            cmds_roles = sorted(self.roles)
            raise KeyError(f'Unknown naming role {role!r}, known: {cmds_roles}')
        out = f'{self.base(node)}{self.roles[role]}'
        if shape:
            out = f'{out}{self.shape_suffix}'
        return out


NAMING = NucleusNaming()


def get_naming() -> NucleusNaming:
    """Return the active naming convention."""
    return NAMING


def set_naming(naming: NucleusNaming):
    """
    Replace the active naming convention.

    Args:
        naming (NucleusNaming): The studio convention.
    """
    global NAMING
    NAMING = naming