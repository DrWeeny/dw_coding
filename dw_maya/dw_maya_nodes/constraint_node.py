"""Constraint node wrapper with network-aware preset capture.

Summary:
    A constraint node cannot be rebuilt with ``createNode`` + plug surgery:
    the native commands (``cmds.parentConstraint`` & co) build the target
    array, the dynamic weight attributes (``...W0``) and the rest offsets.
    So, like the nConstraint network component, a constraint preset stores
    the *relationship* (which drivers constrain which driven node, by name)
    and the apply rebuilds it through the native command. Attribute /
    connection components then run on the real node to restore settings.

Classes:
    ConstraintNetworkComponent: capture / rebuild of the constraint
        relationship (command, driven, targets, weights, offsets).
    Constraint: MayaNode subclass owning the network component, registered
        on the abstract ``constraint`` type.

Example:
    >>> import dw_maya.dw_lsNode as dwls
    >>> con = dwls.lsNode('collider_parentConstraint1')[0]  # -> Constraint
    >>> preset = con.createPreset()
    >>> # other scene / new name: driver + driven must already exist
    >>> new_con = MayaNode('new_pc', preset=preset)

Author:
    DrWeeny
"""

from maya import cmds

import dw_maya.dw_presets_io.preset_components as pcomp
from dw_maya.dw_node_registry import register_type
from dw_logger import get_logger
from .maya_node import MayaNode

logger = get_logger()


def _short(name: str) -> str:
    """Strip DAG path and namespace from a node name."""
    return name.split('|')[-1].split(':')[-1]


class ConstraintNetworkComponent(pcomp.PresetComponent):
    """Store and rebuild the constraint relationship through the native command.

    Capture reads the network with the constraint command's own query flags
    (``targetList`` / ``weightAliasList``), the driven node from the
    ``constraintParentInverseMatrix`` input, and the per-target rest offsets.
    Apply resolves driver / driven names through the :class:`PresetContext`
    (rename map -> target namespace -> bare name), replaces any bare
    ``createNode`` placeholder with a real command-built constraint, then
    restores weights and offsets.
    """

    key = "network"
    enabled_by_default = True

    # ------------------------------------------------------------------ #
    # capture
    # ------------------------------------------------------------------ #
    def capture(self, node: "MayaNode", ctx: pcomp.PresetContext):
        con = node.node
        command = cmds.nodeType(con)
        cmd = getattr(cmds, command, None)
        if cmd is None:
            logger.warning(f"ConstraintNetwork: no cmds.{command} command, "
                           f"skipping network capture on '{con}'")
            return None

        try:
            targets = cmd(con, query=True, targetList=True) or []
        except Exception as e:
            logger.warning(f"ConstraintNetwork: targetList query failed on "
                           f"'{con}': {e}")
            return None
        if not targets:
            return None

        try:
            aliases = cmd(con, query=True, weightAliasList=True) or []
            weights = [cmds.getAttr(f"{con}.{alias}") for alias in aliases]
        except Exception:
            weights = []

        driven = cmds.listConnections(f"{con}.constraintParentInverseMatrix",
                                      source=True,
                                      destination=False) or []
        if not driven:
            # The constraint node usually lives under the driven transform.
            driven = cmds.listRelatives(con, parent=True) or []
        if not driven:
            logger.warning(f"ConstraintNetwork: cannot resolve the driven "
                           f"node of '{con}'")
            return None

        data = {"command": command,
                "driven": _short(driven[0]),
                "targets": [_short(t) for t in targets],
                "weights": weights}

        offsets = self._capture_offsets(con, len(targets))
        if offsets:
            data["offsets"] = offsets
        return data

    def _capture_offsets(self, con: str, target_count: int):
        """Read rest offsets: per-target compounds, or the single offset attr."""
        offsets = {}
        for i in range(target_count):
            entry = {}
            for attr in ("targetOffsetTranslate", "targetOffsetRotate"):
                plug = f"{con}.target[{i}].{attr}"
                try:
                    if cmds.objExists(plug):
                        entry[attr] = list(cmds.getAttr(plug)[0])
                except Exception:
                    pass
            if entry:
                offsets[str(i)] = entry
        if offsets:
            return offsets
        # point / orient / scale constraints expose one offset compound.
        try:
            if cmds.attributeQuery("offset", node=con, exists=True):
                return {"offset": list(cmds.getAttr(f"{con}.offset")[0])}
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ #
    # apply
    # ------------------------------------------------------------------ #
    def _resolve_node(self, name: str, ctx: pcomp.PresetContext):
        """Shared stored-name resolution (see ``resolve_scene_node``)."""
        return pcomp.resolve_scene_node(name, ctx)

    def _to_transform(self, name):
        """Coerce a resolved node to a transform (constraints reject shapes)."""
        if not name:
            return name
        if 'transform' in (cmds.nodeType(name, inherited=True) or []):
            return name
        parents = cmds.listRelatives(name, parent=True) or []
        return parents[0] if parents else name

    def apply(self, node: "MayaNode", data: dict, ctx: pcomp.PresetContext) -> None:
        command = data.get("command")
        cmd = getattr(cmds, command, None) if command else None
        if cmd is None:
            logger.warning(f"ConstraintNetwork: unknown command '{command}'")
            return

        driven = self._to_transform(self._resolve_node(data.get("driven", ""), ctx))
        targets = [self._to_transform(self._resolve_node(t, ctx))
                   for t in data.get("targets", [])]
        missing = [s for s, r in zip(data.get("targets", []), targets) if not r]
        if not driven:
            logger.warning(f"ConstraintNetwork: cannot rebuild '{node.node}' - "
                           f"missing driven '{data.get('driven')}'")
            return
        if missing:
            logger.warning(f"ConstraintNetwork: cannot rebuild '{node.node}' - "
                           f"missing targets {missing}")
            return

        con = node.node if cmds.objExists(node.node) else None
        if con:
            try:
                already_wired = bool(cmd(con, query=True, targetList=True))
            except Exception:
                already_wired = False
            if not already_wired:
                # Bare createNode placeholder (loadNode / node_from_preset
                # made it before components ran) - the native command must
                # build the node itself to get the target array and dynamic
                # weight attrs, so replace it under the same name. Park the
                # placeholder aside first so a failed command leaves the
                # wrapper on a live node instead of a deleted one.
                name = _short(con)
                identity = node.presetIdentity()
                parked = cmds.rename(con, f"{name}_dwPresetTmp")
                new_con = self._create(cmd, targets, driven, name)
                if not new_con:
                    restored = cmds.rename(parked, name)
                    node.setDAG(restored)
                    node.__dict__['node'] = restored
                    return
                cmds.delete(parked)
                con = new_con
                node.setDAG(con)
                node.__dict__['node'] = con
                # Keep the rename map coherent for the connection replay.
                for key in (identity, name):
                    ctx.name_map[key] = con
        else:
            con = self._create(cmd, targets, driven, _short(node.node))
            if not con:
                return
            node.setDAG(con)
            node.__dict__['node'] = con

        self._apply_weights(cmd, con, data.get("weights", []))
        self._apply_offsets(con, data.get("offsets"))

    def _create(self, cmd, targets: list, driven: str, name: str):
        """Run the native constraint command (offset flag when supported)."""
        try:
            result = cmd(*targets, driven, maintainOffset=True, name=name)
        except TypeError:
            # poleVector / geometry / normal constraints have no offset flag.
            try:
                result = cmd(*targets, driven, name=name)
            except Exception as e:
                logger.error(f"ConstraintNetwork: {cmd.__name__} failed: {e}")
                return None
        except Exception as e:
            logger.error(f"ConstraintNetwork: {cmd.__name__} failed: {e}")
            return None
        return result[0] if result else None

    def _apply_weights(self, cmd, con: str, weights: list) -> None:
        if not weights:
            return
        try:
            aliases = cmd(con, query=True, weightAliasList=True) or []
        except Exception:
            return
        for alias, weight in zip(aliases, weights):
            try:
                cmds.setAttr(f"{con}.{alias}", weight)
            except Exception as e:
                logger.warning(f"ConstraintNetwork: weight '{alias}': {e}")

    def _apply_offsets(self, con: str, offsets) -> None:
        """Overwrite maintainOffset's computed rest offsets with the saved ones."""
        if not offsets:
            return
        if "offset" in offsets:
            try:
                cmds.setAttr(f"{con}.offset", *offsets["offset"])
            except Exception as e:
                logger.warning(f"ConstraintNetwork: offset: {e}")
            return
        for idx, entry in offsets.items():
            for attr, value in entry.items():
                plug = f"{con}.target[{idx}].{attr}"
                try:
                    cmds.setAttr(plug, *value)
                except Exception as e:
                    logger.warning(f"ConstraintNetwork: {plug}: {e}")


class Constraint(MayaNode):
    """Wrapper for Maya constraint nodes (parent / point / orient / ...).

    Registered on the abstract ``constraint`` type, so the registry's
    inherited-type walk resolves every concrete constraint type to it.
    The network component rebuilds the relationship first (native command),
    then attributes / connections restore the tuned settings on the result.
    """

    preset_components = (ConstraintNetworkComponent(),
                         pcomp.AttributeComponent(),
                         pcomp.ConnectionComponent(io=(True, True)),
                         pcomp.AnimationComponent())


register_type('constraint', Constraint)