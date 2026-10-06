"""
forge_host.py - DynForge studio seam: where guide setups live and install.

Summary:
    DynForge never hardcodes a studio hierarchy. It asks the active ForgeHost
    where a guide setup group lives, which setups exist in the scene, and how a
    built chain's _PIN is installed into the rig. The default host is plain
    Maya: setup groups at the world root, _PIN parented straight to the picked
    parent bone. A studio ports the tool by subclassing ForgeHost in one file
    and pointing the DW_FORGE_HOST env var at it (same contract as
    dw_pipe_project / DW_PIPE_PROJECT).

Features:
    - One setup group per guide system, tagged with SETUP_TAG. Each guide
      inside it owns a group carrying its JSON recipe (see chain_joint_guide).
    - get_host() lazy-loads the external host; a broken host logs a traceback
      and falls back to ForgeHost - it must never prevent the tool from opening.

Classes:
    ForgeHost

Functions:
    get_host, set_host

Example:
    # my_studio_forge.py, then set DW_FORGE_HOST=D:/pipe/my_studio_forge.py
    from dw_maya.DynForge import forge_host

    class StudioForgeHost(forge_host.ForgeHost):
        label = "Studio"
        def install_pin(self, pin, parent_bone):
            ...

Author:
    DrWeeny
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import traceback
from typing import Optional

import maya.cmds as cmds

from dw_logger import get_logger
from dw_maya.dw_rigging import dw_chain_guide

logger = get_logger()


class ForgeHost(object):
    """Plain-Maya host: setup groups at world, _PIN parented to the parent bone."""

    label     = "Maya"
    SETUP_GRP = "dwForge_GRP"
    SETUP_TAG = "dwForgeSetup"   # bool attr marking a setup group
    # Install options shown next to the Install button: {name: default text}.
    # main_ui persists them and pushes them back with set_option().
    options: dict = {}
    # True when the host stores setups in a studio home (setup_for); guides
    # left without one are then offered a JSON save after install.
    has_setup_home = False

    def __init__(self) -> None:
        self.values = dict(self.options)

    def set_option(self,
                   name:  str,
                   value: str,) -> None:
        self.values[name] = value

    # -- Naming -----------------------------------------------------------

    def naming_defaults(self) -> dict:
        """Defaults for the naming panel: {"prefix": str, "sides": (str, ...)}."""
        return {"prefix": "", "sides": ("", "L", "R", "C", "M")}

    def joint_names(self,
                    guide_name: str,
                    count:      int,) -> Optional[list]:
        """
        Names given to an installed chain's joints, root first, or None to keep
        the build names (<guide>_jnt_0_PIN, <guide>_jnt_1, ...).
        """
        return None

    # -- Setups -----------------------------------------------------------

    def list_setups(self) -> list:
        """Long paths of every setup group in the scene."""
        return [node for node in cmds.ls(type="transform", long=True) or []
                if cmds.attributeQuery(self.SETUP_TAG, node=node, exists=True)]

    def ensure_setup(self,
                     name: Optional[str] = None,) -> str:
        """
        Return the setup group `name` (default SETUP_GRP), creating + tagging it.

        A long path is taken as is. A bare name means the WORLD-level group of
        that name: once a studio host has moved a setup into its own home there
        are several groups called dwForge_GRP, and asking Maya by bare name is
        then ambiguous (it crashed adding a point to a new guide after a studio
        install). Studio homes are reached through setup_for, never by name.
        """
        name = name or self.SETUP_GRP
        if "|" in name and cmds.objExists(name):
            group = cmds.ls(name, long=True)[0]
        else:
            bare = name.split("|")[-1]
            at_world = [n for n in cmds.ls(bare, long=True) or [] if n.count("|") == 1]
            group = at_world[0] if at_world else cmds.ls(cmds.group(empty=True, name=bare, world=True),
                                                         long=True)[0]
        if not cmds.attributeQuery(self.SETUP_TAG, node=group, exists=True):
            cmds.addAttr(group, longName=self.SETUP_TAG, attributeType="bool")
            cmds.setAttr(f"{group}.{self.SETUP_TAG}", True)
        return group

    def setup_for(self,
                  guide,) -> Optional[str]:
        """
        The setup group a guide should live in once installed (created if
        needed), or None to leave it where it is. Default: None.
        """
        return None

    # -- Install tab ------------------------------------------------------

    def install_unit(self,
                     guide,) -> tuple:
        """
        (key, label) of the unit a guide installs with - what the Install tab
        groups by and saves one JSON per. Default: the top-level group of the
        registered mesh; ("", "unassigned") without a mesh.
        """
        meshes = [m for m in (getattr(guide, "skin_meshes", None) or []) if cmds.objExists(m)]
        if not meshes:
            return "", "unassigned"
        top = cmds.ls(meshes[0], long=True)[0].split("|")[1]
        return f"|{top}", top.split(":")[-1]

    def describe_target(self,
                        guide,) -> str:
        """Where install_chain would put the chain, for display only (never creates anything)."""
        bone = getattr(guide, "parent_bone", None)
        return bone.split("|")[-1] if bone else "-"

    def extra_tabs(self,
                   context,) -> list:
        """
        Studio tabs added to the right-hand tab widget: [(title, QWidget)]. The
        `context` (wgt_base.ForgeContext) gives the listed guides, the selected
        one and a guides_changed signal. Default: none.
        """
        return []

    # -- Install ----------------------------------------------------------

    def install_chain(self,
                      guide,) -> list:
        """
        Move a built chain into the rig and return its joints (root first) as
        they are named afterwards. Default: parent the root (_PIN) under the
        guide's parent bone, keep the names. `guide` exposes chain_joints,
        parent_bone, name and skin_meshes.
        """
        joints = list(guide.chain_joints)
        parent_bone = guide.parent_bone
        if joints and parent_bone and cmds.objExists(parent_bone):
            current = cmds.listRelatives(joints[0], parent=True, fullPath=True) or []
            if current != cmds.ls(parent_bone, long=True):
                cmds.parent(joints[0], parent_bone)
        return self.rename_chain(guide, joints)

    def uninstall_chain(self,
                        guide,) -> list:
        """
        Undo install_chain: put the chain root back under the guide group and
        give the joints their build names again (<guide>_jnt_0_PIN, ...), in the
        root namespace - a studio tool may have namespaced them in the rig.
        Returns the joints, root first.
        """
        joints = list(guide.chain_joints)
        if not joints:
            return joints
        group = guide.guide_group()
        uuids = [cmds.ls(j, uuid=True)[0] for j in joints]
        current = cmds.listRelatives(joints[0], parent=True, fullPath=True) or []
        if current != [group]:
            cmds.parent(joints[0], group)
        for uuid, name in zip(uuids, dw_chain_guide.chain_joint_names(guide.name, len(uuids))):
            node = cmds.ls(uuid, long=True)[0]
            if node.split("|")[-1] != name:
                cmds.rename(node, f":{name}")
        return [cmds.ls(uuid)[0] for uuid in uuids]

    def rename_chain(self,
                     guide,
                     joints: list,) -> list:
        """Apply joint_names() to `joints` (no-op when it returns None)."""
        names = self.joint_names(guide.name, len(joints))
        if not names:
            return joints
        uuids = [cmds.ls(j, uuid=True)[0] for j in joints]
        for uuid, name in zip(uuids, names):
            node = cmds.ls(uuid, long=True)[0]
            short = node.split("|")[-1]
            namespace = short.rsplit(":", 1)[0] + ":" if ":" in short else ""   # keep it
            if short.split(":")[-1] != name:
                cmds.rename(node, f"{namespace}{name}")
        return [cmds.ls(uuid)[0] for uuid in uuids]


# ============================================================================
# ACTIVE HOST
# ============================================================================

_current_host = None


def set_host(host: ForgeHost) -> None:
    """Register the active host (e.g. from a studio userSetup)."""
    global _current_host
    _current_host = host


def get_host() -> ForgeHost:
    """
    Return the active host, loading it on first call. Resolution: set_host()
    -> file or module named by DW_FORGE_HOST -> the package's own host/ folder
    (gitignored, absent outside a studio) -> ForgeHost.
    """
    global _current_host
    if _current_host is None:
        _current_host = _load_external_host() or _load_package_host() or ForgeHost()
    return _current_host


def _load_package_host() -> Optional[ForgeHost]:
    """
    The studio host shipped beside this module in host/ (gitignored, so it is
    only there on a studio machine): its get_host() factory. Absent = None,
    broken = logged traceback and None - never a reason the tool cannot open.
    """
    try:
        module = importlib.import_module("dw_maya.DynForge.host")
    except ModuleNotFoundError as e:
        if e.name in ("dw_maya.DynForge.host", "dw_maya.DynForge"):
            return None
        logger.error(f"DynForge host/ failed to import, falling back to ForgeHost:\n{traceback.format_exc()}")
        return None
    except Exception:
        logger.error(f"DynForge host/ failed to import, falling back to ForgeHost:\n{traceback.format_exc()}")
        return None
    factory = getattr(module, "get_host", None)
    if not callable(factory):
        return None
    try:
        host = factory()
    except Exception:
        logger.error(f"DynForge host/ get_host() failed, falling back to ForgeHost:\n{traceback.format_exc()}")
        return None
    return host if isinstance(host, ForgeHost) else None


def _load_external_host() -> Optional[ForgeHost]:
    """
    Load a host from DW_FORGE_HOST (file path or module name). The module may
    expose a get_host() factory or define a ForgeHost subclass (first one found
    is instantiated). Errors are logged and None returned, so callers fall back.
    """
    target = os.environ.get("DW_FORGE_HOST")
    if not target:
        return None
    try:
        if os.path.isfile(target):
            spec = importlib.util.spec_from_file_location("dw_forge_host_ext", target)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(target)

        factory = getattr(module, "get_host", None)
        if callable(factory):
            host = factory()
            if isinstance(host, ForgeHost):
                return host
            logger.warning(f"DW_FORGE_HOST '{target}': get_host() did not return a ForgeHost, ignoring it")

        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, ForgeHost) and obj is not ForgeHost:
                return obj()

        logger.warning(f"DW_FORGE_HOST '{target}' defines no get_host() factory nor ForgeHost subclass")
    except Exception:
        logger.error(f"Failed to load DW_FORGE_HOST '{target}', falling back to ForgeHost:\n"
                     f"{traceback.format_exc()}")
    return None
