"""
chain_joint_guide.py - DynForge backend: a chain of joints along a curve.

Wraps dw_rigging.dw_chain_guide.ChainGuide as a DynForge GuideBackend so joint
chains plug into the guide registry alongside future guide types (wings, hair,
tentacles...).

A guide is an ordered list of guide points plus build parameters. Two ways to
fill it, mixable:
- one by one: each point lands on the centroid of whatever the artist selected
  (edges, faces, verts, an object) and remembers that selection as its source;
- from a strip: an edge column / loop or a face strip gives one point per edge
  midpoint / face centroid, ordered along the strip (e.g. a dress column in one
  click). The strip itself is kept as the guide's strip_source.
Either way the sources let points be re-placed after the model changes. Points
are locators or joints - an artist preference.

Everything lives in one guide group under the host's setup group:

    dwForge_GRP                     setup (see forge_host)
      <name>_guide_GRP              .dwForgeGuide = type_name, .dwForgeRecipe = JSON
        <name>_locGuide_GRP         guide points
        <name>_src_crv              source curve
        <name>_jnt_0_PIN ...        built chain (until installed under a bone)

The recipe is to_dict() as JSON, rewritten after every scene-changing action, so
reopening the tool rebuilds the list from the scene (discover()). Save JSON
exports the same dicts for versioning.
"""

from __future__ import annotations

import json
from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2

from dw_logger import get_logger
from dw_maya.dw_decorators import dw_undo
from dw_maya.dw_rigging import dw_chain_guide
from dw_maya.DynForge import forge_host
from dw_maya.DynForge import guide_registry
from dw_maya.DynForge.forge_cmds import skin_ops

logger = get_logger()

GUIDE_TAG   = "dwForgeGuide"    # string attr on a guide group: its type_name
RECIPE_ATTR = "dwForgeRecipe"   # string attr on a guide group: to_dict() JSON
SOURCE_ATTR = "dwForgeSource"   # string attr on a guide point: its selection source


def _bare(node: str) -> str:
    """Short name without path nor namespace."""
    return node.split("|")[-1].split(":")[-1]


class ChainJointGuide(guide_registry.GuideBackend):
    """A chain of joints distributed along a curve through the guide points."""

    type_name = "chain_joint"
    label     = "Joint Chain"

    def __init__(self,
                 name:         str = "chain",
                 n_joints:     int = 10,
                 up_axis:      str = "y",
                 degree:       int = 3,
                 flip:         bool = False,
                 point_type:   str = "locator",
                 cv_count:     int = 6,
                 exact_points: bool = False,) -> None:
        super().__init__(name=name)
        self.n_joints     = n_joints
        self.up_axis      = up_axis
        self.degree       = degree
        self.flip         = flip
        # Guide-point node type: "locator" or "joint" (artist preference).
        self.point_type   = point_type
        # CV count the curve through the points is resampled to (editable resolution).
        self.cv_count     = cv_count
        # Exact mode: one joint per guide point, placed exactly on it; the curve
        # is kept only as data. Joint count follows the points.
        self.exact_points = exact_points
        # -- Skinning params (filled in the Skinning tab, used on Install) -----
        self.skin_cluster:      Optional[str] = None   # target skinCluster
        self.skin_meshes:       list          = []     # meshes it deforms
        self.gizmo:             Optional[str] = None   # optional clip gizmo transform
        self.gizmo_shape:       str           = "box"  # box / sphere / capsule
        # Optional vertex mask: the only verts the chain may take weight on,
        # {mesh transform: [[first, last], ...]} (ranges, see skin_ops.to_ranges).
        self.skin_mask:         dict          = {}
        # Vertex count of each masked mesh when the mask was set: a different
        # count now means the topology changed and the indices may be wrong.
        self.skin_mask_counts:  dict          = {}
        self.source_influences: list          = []     # picked donor bones
        self.parent_bone:       Optional[str] = None   # _PIN parent (donor bone)
        self.power:             float         = 1.0    # spatial-cascade falloff
        # Tube / attachment radius = (_PIN -> nearest skin joint) * radius_scale.
        self.radius_scale:      float         = 1.0
        # Live guide point nodes, root -> tip.
        self.points:        list = []
        # Snapshot of the points: [{"name", "position", "source"}], so the guide
        # survives its point nodes (joint markers are consumed on build, a loaded
        # file has no nodes yet).
        self.point_records: list = []
        # Edge column / face strip the points were generated from (None when
        # placed one by one): {"kind", "mesh", "ids", "closed"}.
        self.strip_source:  Optional[dict] = None
        # How many of a strip's points get a locator (handle): first / middle /
        # last for 3, spread by index; 0 = every point.
        self.strip_handles: int = 3
        # Snapshot of the source curve CVs [(x, y, z)], keeps hand-edited curves.
        self.positions:     list = []
        self.source_curve:  Optional[str] = None
        # Setup group this guide belongs to (None = the host's default setup).
        self.setup:         Optional[str] = None
        # Studio home the host moved the setup to on the last install (None = none found).
        self.setup_home:    Optional[str] = None
        # Install state: the chain sits in the rig / its weights are on the skin.
        self.installed:      bool = False
        self.skin_installed: bool = False
        # Install with the skin weights or only place the chain - per guide (the
        # Install tab's Skin column; new guides take the tab's default).
        self.with_skin:      bool = True
        # An install setting (skin flag, target, home) changed after the install
        # and the reinstall was declined: the rig does not match the tab yet.
        self.reinstall_pending: bool = False
        # Free slot owned by the ForgeHost, persisted in the recipe: what the
        # studio side made for this guide (e.g. the uuid of its solver node), so
        # it is found again after an uninstall, a rename or a relaunch.
        self.host_data:      dict = {}
        self._group:        Optional[str] = None
        self._chain:        Optional[dw_chain_guide.ChainGuide] = None
        # Flip direction currently baked into the source curve, so rebuild() can
        # tell when the artist toggled Flip and reverse the curve to match.
        self._curve_flip:   bool = flip

    @classmethod
    def create(cls,
               **params,) -> "ChainJointGuide":
        """
        Create a blank PENDING guide carrying the build parameters but no scene
        nodes. Points are added from the editor, the per-row Build materializes it.
        """
        guide = cls(name         = params.get("name", "chain"),
                    n_joints     = params.get("n_joints", 10),
                    up_axis      = params.get("up_axis", "y"),
                    degree       = params.get("degree", 3),
                    flip         = params.get("flip", False),
                    point_type   = params.get("point_type", "locator"),
                    cv_count     = params.get("cv_count", 6),
                    exact_points = params.get("exact_points", False),)
        guide.strip_handles = int(params.get("strip_handles", 3))
        guide.with_skin = bool(params.get("with_skin", True))
        return guide

    # -- Groups -----------------------------------------------------------

    def guide_group(self) -> str:
        """Return this guide's group (long path), creating it under its setup."""
        if self._group and cmds.objExists(self._group):
            return self._group
        setup = forge_host.get_host().ensure_setup(self.setup)
        self.setup = setup
        short = f"{self.name}_guide_GRP"
        found = [node for node in cmds.listRelatives(setup, children=True, fullPath=True) or []
                 if node.split("|")[-1] == short]
        group = found[0] if found else cmds.parent(cmds.group(empty=True, name=short), setup)[0]
        if not cmds.attributeQuery(GUIDE_TAG, node=group, exists=True):
            cmds.addAttr(group, longName=GUIDE_TAG, dataType="string")
        cmds.setAttr(f"{group}.{GUIDE_TAG}", self.type_name, type="string")
        self._group = cmds.ls(group, long=True)[0]
        return self._group

    def _points_group(self) -> str:
        return dw_chain_guide.ensure_locator_group(self.name, parent=self.guide_group())

    def refresh_references(self) -> list:
        """
        Re-resolve every scene name the recipe stores - parent bone, donors,
        skinCluster, meshes, vertex-mask keys - to what it is called NOW
        (skin_ops.resolve_node, namespace-agnostic). A studio pipeline
        namespaces its containers' content on save / reload (an artist's
        BB_M_0_Hips comes back as _SKL_X_:BB_M_0_Hips), which left every stored
        long path dangling and made install / uninstall fail after a reopen.
        Writes the recipe back when something was renamed. Returns the names
        that could not be resolved (gone, or ambiguous) - kept as they were.
        """
        lost, changed = [], [False]

        def fix(stored):
            if not stored:
                return stored
            if cmds.objExists(stored) and len(cmds.ls(stored) or []) == 1:
                return stored   # still names one node: nothing to do (and no recipe write - it is undoable)
            now = skin_ops.resolve_node(stored)
            if now is None:
                lost.append(stored)
                return stored
            changed[0] = True
            return now

        self.parent_bone = fix(self.parent_bone)
        self.source_influences = [fix(d) for d in self.source_influences]
        self.skin_meshes = [fix(m) for m in self.skin_meshes]
        if self.skin_cluster and not cmds.objExists(self.skin_cluster):
            found = cmds.ls(_bare(self.skin_cluster), recursive=True, type="skinCluster") or []
            if len(found) == 1:
                self.skin_cluster, changed[0] = found[0], True
            else:
                lost.append(self.skin_cluster)
        if self.skin_mask:
            renamed = {mesh: fix(mesh) for mesh in self.skin_mask}
            self.skin_mask = {renamed[m]: r for m, r in self.skin_mask.items()}
            self.skin_mask_counts = {renamed.get(m, m): c for m, c in self.skin_mask_counts.items()}
        if lost:
            logger.warning(f"DynForge: {self.name} - cannot find {', '.join(_bare(n) for n in lost)} "
                           f"in the scene (deleted, or several nodes now share that name).")
        if changed[0]:
            self.store_recipe()
        return lost

    def store_recipe(self) -> None:
        """Write to_dict() onto the guide group (no-op until the group exists)."""
        if not (self._group and cmds.objExists(self._group)):
            return
        if not cmds.attributeQuery(RECIPE_ATTR, node=self._group, exists=True):
            cmds.addAttr(self._group, longName=RECIPE_ATTR, dataType="string")
        cmds.setAttr(f"{self._group}.{RECIPE_ATTR}", json.dumps(self.to_dict()), type="string")

    # -- Guide points -----------------------------------------------------

    def set_point_type(self,
                       point_type: str,) -> None:
        """Change the guide-point node type ('locator' / 'joint') for new points."""
        self.point_type = point_type

    @dw_undo.singleUndoChunk
    def add_point(self) -> str:
        """
        Add one guide point at the centroid of the current selection (world
        origin when nothing is selected) and return its node name. The selection
        is stored on the point as its source. The node type follows point_type.

        With the 'joint' point type the placed joints ARE the chain joints, so
        each one bumps n_joints.
        """
        # Read the selection BEFORE creating any group: cmds.group / cmds.parent
        # change the active selection and would clobber the artist's components.
        center = dw_chain_guide.get_selection_center()
        source = dw_chain_guide.get_selection_source()
        node = dw_chain_guide.create_guide_point(
            node_type = self.point_type,
            name      = self.name,
            index     = len(self.points),
            position  = center,
            group     = self._points_group(),
        )
        self._set_source(node, source)
        self._auto_register(source)
        self._sync_point_records()   # settle the existing records before appending
        self.points.append(node)
        self.point_records.append(self._node_record(node))
        if self.point_type == "joint":
            self.n_joints = max(len(self.points), 2)
        self.store_recipe()
        return node

    @dw_undo.singleUndoChunk
    def snap_point(self,
                   node: str,) -> None:
        """
        Snap one of this guide's points to the current selection centroid and
        record the selection as its new source. Once an exact joint chain is
        built the points are parented to each other, so the children's world
        positions are held - snapping one point must not drag the chain along.
        """
        if node not in self.points:
            return
        source = dw_chain_guide.get_selection_source()
        children = cmds.listRelatives(node, children=True, type="joint", fullPath=True) or []
        held = [(child, cmds.xform(child, query=True, worldSpace=True, translation=True))
                for child in children]
        dw_chain_guide.snap_node_to_selection_center(node)
        for child, pos in held:
            cmds.xform(child, worldSpace=True, translation=pos)
        self._set_source(node, source)
        self._auto_register(source)
        self._sync_point_records()
        self.store_recipe()

    @dw_undo.singleUndoChunk
    def delete_point(self,
                     node: str,) -> None:
        """
        Delete one guide point (node + list entry); keep joint-count in sync.
        A built exact joint chain has its points parented to each other, so the
        children are handed to the deleted point's parent first - cmds.delete
        would otherwise take the whole tail of the chain with it.
        """
        if node not in self.points:
            return
        if cmds.objExists(node):
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            for child in cmds.listRelatives(node, children=True, type="joint", fullPath=True) or []:
                if parents:
                    cmds.parent(child, parents[0])
                else:
                    cmds.parent(child, world=True)
            cmds.delete(node)
        handles = self._handle_records()
        k = self.points.index(node)
        if len(handles) == len(self.points):
            del self.point_records[handles[k]]
        self.points.remove(node)
        if self.point_type == "joint":
            self.n_joints = max(len(self.points), 2)
        self._sync_point_records()
        self.store_recipe()

    @dw_undo.singleUndoChunk
    def points_from_strip(self) -> list:
        """
        Replace the guide points with one point per edge midpoint / face
        centroid of the selected edge column / loop or face strip, ordered along
        it. Every point is recorded, but only `strip_handles` of them get a
        locator (first / middle / last for 3): moving a handle drags the hidden
        points between it and its neighbour handles (see _sync_point_records).
        Starts the guide over: the previous points, curve and chain are removed
        (-> PENDING), since the curve would otherwise stay the source of truth
        on rebuild. Joint count is left alone - the joints are spread over the
        curve through all the points (Exact: one joint per point).
        """
        strip = dw_chain_guide.ordered_strip_from_selection()
        if strip["closed"]:
            logger.warning(f"'{self.name}': closed {strip['kind']} loop - the chain is built open, "
                           "from the first element around.")
        self._reset_build()
        for node in self.points:
            if cmds.objExists(node):
                cmds.delete(node)
        self.points = []
        self.point_records = []
        suffix = "e" if strip["kind"] == "edges" else "f"
        group = self._points_group()
        handles = set(self._handle_indices(len(strip["ids"]), self.strip_handles))
        for index, (cid, pos) in enumerate(zip(strip["ids"], strip["positions"])):
            position = [pos.x, pos.y, pos.z]
            source = {"kind": "components", "items": [f"{strip['mesh']}.{suffix}[{cid}]"]}
            record = {"name": None, "position": position, "source": source,
                      "handle": index in handles, "origin": list(position)}
            if index in handles:
                node = dw_chain_guide.create_guide_point(
                    node_type = self.point_type,
                    name      = self.name,
                    index     = index,   # a handle keeps its strip index in its name
                    position  = tuple(position),
                    group     = group,
                )
                self._set_source(node, source)
                record["name"] = node.split("|")[-1]
                self.points.append(node)
            self.point_records.append(record)
        self.strip_source = {key: strip[key] for key in ("kind", "mesh", "ids", "closed")}
        self._auto_register({"kind": "objects", "items": [strip["mesh"]]})
        cmds.select(clear=True)
        self._sync_point_records()
        self.store_recipe()
        return self.points

    @dw_undo.singleUndoChunk
    def rename(self,
               new_name: str,) -> None:
        """
        Rename the guide and every node it owns whose name starts with the old
        guide name (guide / points groups, points, curve, joints - installed ones
        included - and gizmo), then refresh the tags and the recipe. Nodes are
        tracked by UUID since renaming a parent invalidates its children's paths.
        """
        old = self.name
        if new_name == old:
            return
        # Match the prefix the nodes really carry: a name Maya refused (leading
        # digit, e.g. "0_chain") made them "_chain_*", read it off the group.
        node_prefix = old
        if self._group and cmds.objExists(self._group):
            short = self._group.split("|")[-1]
            if short.endswith("_guide_GRP"):
                node_prefix = short[:-len("_guide_GRP")]
        owned = []
        if self._group and cmds.objExists(self._group):
            owned.append(self._group)
            owned += cmds.listRelatives(self._group, allDescendents=True, fullPath=True) or []
        owned += [n for n in (self._chain.joints if self._chain else []) if cmds.objExists(n)]
        if self.gizmo and cmds.objExists(self.gizmo):
            owned.append(self.gizmo)
        uuids = {cmds.ls(node, uuid=True)[0] for node in owned}

        def uuid_of(node: Optional[str]) -> Optional[str]:
            return cmds.ls(node, uuid=True)[0] if node and cmds.objExists(node) else None

        point_ids = [uuid_of(n) for n in self.points]
        joint_ids = [uuid_of(n) for n in (self._chain.joints if self._chain else [])]
        curve_id, gizmo_id, group_id = uuid_of(self.source_curve), uuid_of(self.gizmo), uuid_of(self._group)

        # An installed chain may carry the host's joint names instead of the
        # <guide>_ prefix: map those old -> new by position.
        host = forge_host.get_host()
        host_old = host.joint_names(old, len(joint_ids)) or []
        host_new = host.joint_names(new_name, len(joint_ids)) or []
        host_map = {u: (o, n) for u, o, n in zip(joint_ids, host_old, host_new) if u}

        prefix = f"{node_prefix}_"
        for uuid in uuids:
            short = cmds.ls(uuid)[0].split("|")[-1]
            namespace = short.rsplit(":", 1)[0] + ":" if ":" in short else ""   # keep it
            bare = short.split(":")[-1]
            if uuid in host_map and bare == host_map[uuid][0]:
                target = host_map[uuid][1]
            elif bare.startswith(prefix):
                target = f"{new_name}_{bare[len(prefix):]}"
            else:
                continue
            cmds.rename(cmds.ls(uuid, long=True)[0], f"{namespace}{target}")

        def resolve(uuid: Optional[str]) -> Optional[str]:
            return cmds.ls(uuid)[0] if uuid and cmds.ls(uuid) else None

        self.name = new_name
        self.points = [n for n in (resolve(u) for u in point_ids) if n]
        self.source_curve = resolve(curve_id)
        self.gizmo = resolve(gizmo_id)
        if group_id:
            self._group = cmds.ls(group_id, long=True)[0]
        if self._chain is not None:
            self._chain.name = new_name
            self._chain.joints = [n for n in (resolve(u) for u in joint_ids) if n]
            if self._group:
                self._chain.group_name = self._group   # still pointed at the old group path
            if self.source_curve:
                self._chain.curve_name = self.source_curve
                dw_chain_guide.ChainGuide._tag_curve(self.source_curve, new_name,
                                                     self._chain.n_joints, self._chain.up_axis)
            self._tag_chain()
        self._sync_point_records()
        self.store_recipe()

    def _reset_build(self) -> None:
        """Drop the built chain + source curve so the next build starts from the points."""
        if self._chain is not None:
            self._chain._cleanup_joints()
        if self.source_curve and cmds.objExists(self.source_curve):
            cmds.delete(self.source_curve)
        self._chain       = None
        self.source_curve = None
        self.positions    = []
        self._status      = guide_registry.GuideStatus.PENDING

    def reorder_points(self,
                       ordered: list,) -> None:
        """
        Set a new chain order; `ordered` must be a permutation of the points.
        Refused on a strip with hidden points - reordering handles would scramble
        the strip; redo it from the selection instead.
        """
        if not (set(ordered) == set(self.points) and len(ordered) == len(self.points)):
            return
        self._sync_point_records()
        if len(self.point_records) != len(self.points):
            raise ValueError(f"'{self.name}': the points come from a strip with hidden points - "
                             "reorder is off, redo the strip instead.")
        self.point_records = [self.point_records[self.points.index(n)] for n in ordered]
        self.points = list(ordered)
        self.store_recipe()

    def _auto_register(self,
                       source: Optional[dict],) -> None:
        """
        Pre-register the skinCluster of the mesh a point was placed on, when the
        guide has none yet (a mesh without skinCluster is silently ignored).
        """
        if self.skin_cluster or not source:
            return
        items = source.get("items") or []
        if not items:
            return
        node = items[0].split(".")[0]
        if not cmds.objExists(node):
            return
        try:
            if skin_ops.find_skin_cluster(node):
                self.register_skin(node)
        except Exception as e:
            logger.warning(f"DynForge: could not pre-register the skin of {node!r}: {e}")

    def _points_alive(self) -> bool:
        """True if this guide has point nodes and all of them still exist."""
        return bool(self.points) and all(cmds.objExists(node) for node in self.points)

    @staticmethod
    def _set_source(node:   str,
                    source: Optional[dict],) -> None:
        if not cmds.attributeQuery(SOURCE_ATTR, node=node, exists=True):
            cmds.addAttr(node, longName=SOURCE_ATTR, dataType="string")
        cmds.setAttr(f"{node}.{SOURCE_ATTR}", json.dumps(source), type="string")

    @staticmethod
    def _handle_indices(count:   int,
                        handles: int,) -> list:
        """Which of `count` strip points get a locator: `handles` spread by index (<= 0 = all)."""
        if handles <= 0 or handles >= count:
            return list(range(count))
        handles = max(handles, 2)
        return sorted({int(i * (count - 1) / (handles - 1) + 0.5) for i in range(handles)})

    def _handle_records(self) -> list:
        """Indices of the records that have a node (handles), in order - they pair with self.points."""
        return [i for i, rec in enumerate(self.point_records) if rec.get("handle", True)]

    @staticmethod
    def _node_record(node:     str,
                     previous: Optional[dict] = None,) -> dict:
        """Record of a live point node; keeps the previous record's origin (rest position)."""
        source = None
        if cmds.attributeQuery(SOURCE_ATTR, node=node, exists=True):
            source = json.loads(cmds.getAttr(f"{node}.{SOURCE_ATTR}") or "null")
        position = list(cmds.xform(node, query=True, worldSpace=True, translation=True))
        origin = (previous or {}).get("origin") or (previous or {}).get("position") or position
        return {"name": node.split("|")[-1], "position": position, "source": source,
                "handle": True, "origin": list(origin)}

    def _sync_point_records(self) -> None:
        """
        Refresh point_records from the live handle nodes (kept as-is when the
        nodes are gone). Hidden strip points follow their neighbour handles:
        each gets the handles' displacement from their origin, blended by index
        between the handle before and the handle after it.
        """
        if not self._points_alive():
            return
        handles = self._handle_records()
        if len(handles) != len(self.points):
            # Records out of step with the nodes: every node is a handle.
            self.point_records = [self._node_record(node) for node in self.points]
            return
        moved = {}
        for k, node in zip(handles, self.points):
            record = self._node_record(node, self.point_records[k])
            self.point_records[k] = record
            moved[k] = [p - o for p, o in zip(record["position"], record["origin"])]
        if len(moved) == len(self.point_records):
            return
        keys = sorted(moved)
        for i, record in enumerate(self.point_records):
            if record.get("handle", True):
                continue
            before = [k for k in keys if k < i]
            after = [k for k in keys if k > i]
            if before and after:
                a, b = before[-1], after[0]
                t = (i - a) / float(b - a)
                shift = [da + (db - da) * t for da, db in zip(moved[a], moved[b])]
            else:
                shift = moved[before[-1]] if before else moved[after[0]]
            origin = record.get("origin") or record["position"]
            record["position"] = [o + d for o, d in zip(origin, shift)]

    def _point_positions(self) -> list:
        """World MPoints of the guide points, root -> tip (live nodes, else records)."""
        self._sync_point_records()
        return [om2.MPoint(*rec["position"]) for rec in self.point_records]

    def _respawn_points(self) -> None:
        """Recreate locator points from the records (loaded file / consumed nodes)."""
        if self._points_alive() or not self.point_records or self.point_type != "locator":
            return
        group = self._points_group()
        self.points = []
        for index, rec in enumerate(self.point_records):
            if not rec.get("handle", True):
                continue
            node = dw_chain_guide.create_guide_point(
                node_type = "locator",
                name      = self.name,
                index     = index,
                position  = tuple(rec["position"]),
                group     = group,
            )
            self._set_source(node, rec.get("source"))
            rec["name"] = node.split("|")[-1]
            self.points.append(node)

    # -- Lifecycle --------------------------------------------------------

    def _tag_chain(self) -> None:
        """
        Tag the built joints with a 'dwForge' string attr (= guide name) so the
        install / skinning steps can recognise DynForge joints and group them by
        guide. The root keeps its _PIN suffix as its role marker.
        """
        if self._chain is None:
            return
        for jnt in (self._chain.joints or []):
            if not cmds.objExists(jnt):
                continue
            if not cmds.attributeQuery("dwForge", node=jnt, exists=True):
                cmds.addAttr(jnt, longName="dwForge", dataType="string")
            cmds.setAttr(f"{jnt}.dwForge", self.name, type="string")

    @property
    def chain_joints(self) -> list:
        """The built chain joints, root first (empty when not built)."""
        return list(self._chain.joints) if self._chain is not None else []

    @property
    def pin_joint(self) -> Optional[str]:
        """The root (_PIN) joint of the built chain, or None if not built."""
        if self._chain is not None and self._chain.joints:
            return self._chain.joints[0]
        return None

    def _finish_build(self) -> None:
        self.source_curve = self._chain.curve_name
        self.positions    = self._read_curve_points(self._chain.curve_name)
        self._curve_flip  = self.flip
        self._tag_chain()
        self._status = guide_registry.GuideStatus.BUILT
        self.store_recipe()

    @dw_undo.singleUndoChunk
    def build(self) -> None:
        """
        Materialize the guide (-> BUILT). Source resolution order:

        - exact mode: one joint per guide point (see _build_exact).
        - already has a curve: just (re)distribute the joints.
        - has a curve snapshot (loaded file): rebuild the curve from its CVs, so
          hand edits to the curve survive.
        - otherwise: build the curve through the guide points.
        """
        self._respawn_points()
        if self.exact_points:
            self._build_exact()
            return
        if self._chain is not None:
            self._chain.build()
        elif self.positions:
            self._chain = self._chain_from_curve_points(
                [om2.MPoint(*p) for p in self.positions], resample=False)
            self._chain.build()
        else:
            points = self._point_positions()
            if len(points) < 2:
                raise ValueError(f"'{self.name}': add at least 2 guide points before building.")
            if self.flip:
                points = points[::-1]
            self._chain = self._chain_from_curve_points(points, resample=True)
            if self.point_type == "joint" and self._points_alive():
                # The placed joints were markers seeding the curve; the records
                # keep them, the constructed chain replaces the nodes.
                cmds.delete(self.points)
                self.points = []
            self._chain.build()
        self._finish_build()

    def save_curve_positions(self) -> None:
        """
        Snapshot the live curve CV world positions into self.positions, so manual
        edits to the curve are preserved (used by the UI's 'Rebuild all').
        """
        if self.source_curve and cmds.objExists(self.source_curve):
            self.positions = self._read_curve_points(self.source_curve)

    @dw_undo.singleUndoChunk
    def rebuild(self) -> None:
        """
        Rebuild the joint chain, following any artist adjustments. Once a curve
        exists it is the source of truth: the artist edits its CVs and rebuild
        keeps the curve and only redistributes the joints.

        Exact mode is the exception: the points are the source of truth, so
        rebuild re-reads them and re-places the joints.
        """
        if self.exact_points or self._chain is None:
            self.build()
            return
        # Toggling Flip after the curve exists must reverse the curve in place
        # (rebuild alone only redistributes joints along it).
        if self.flip != self._curve_flip:
            dw_chain_guide.reverse_curve_direction(self.source_curve)
        self._chain.rebuild(n_joints=self.n_joints, up_axis=self.up_axis)
        self._finish_build()

    def _build_exact(self) -> None:
        """
        Exact build: one joint sitting precisely on each guide point. The curve
        is rebuilt as a data-only record passing exactly through the points. For
        the 'joint' point type the placed joints are REUSED as the chain; for the
        'locator' type fresh joints are created and the locators stay as scaffold.
        """
        group = self.guide_group()
        reuse_joints = (self.point_type == "joint" and self._points_alive()
                        and len(self.points) == len(self.point_records))
        if reuse_joints:
            self._sync_point_records()
            order  = self.points[::-1] if self.flip else self.points
            points = dw_chain_guide.get_locator_positions(order)
            joints = dw_chain_guide.chain_from_joints(order, self.name, self.up_axis)
            # Keep self.points in the original placement order so flip stays a
            # pure derived transform (no double-reverse on the next rebuild).
            self.points = joints[::-1] if self.flip else joints
        else:
            points = self._point_positions()
            if self.flip:
                points = points[::-1]
            if self._chain is not None:
                self._chain._cleanup_joints()   # drop the previous exact chain
            joints = dw_chain_guide.place_joint_chain(points, self.name, self.up_axis)
        if len(points) < 2:
            raise ValueError(f"'{self.name}': add at least 2 guide points before building.")

        # Data-only curve, passing exactly through the points.
        if self.source_curve and cmds.objExists(self.source_curve):
            cmds.delete(self.source_curve)
        curve = dw_chain_guide.build_curve_through_positions(
            points, name=f"{self.name}_src_crv", degree=self.degree,
        )
        curve = cmds.parent(curve, group)[0]
        chain = dw_chain_guide.ChainGuide.from_existing_curve(
            curve, n_joints=len(points), name=self.name, up_axis=self.up_axis, group=group,
        )
        chain.joints = joints
        root = joints[0]
        if (cmds.listRelatives(root, parent=True, fullPath=True) or []) != [group]:
            cmds.parent(root, group)

        self._chain   = chain
        self.n_joints = len(points)
        self._finish_build()

    @dw_undo.singleUndoChunk
    def destroy(self) -> None:
        """Delete the built joint chain, keeping points + curve (-> PENDING)."""
        if self._chain is not None:
            # TODO: expose a public delete on ChainGuide; using the internal
            # cleanup for now so destroy() does not rely on tracking joints here.
            self._chain._cleanup_joints()
        self._status = guide_registry.GuideStatus.PENDING
        self.store_recipe()

    @dw_undo.singleUndoChunk
    def delete(self) -> None:
        """Remove the guide from the scene entirely: chain, gizmo and guide group."""
        if self._chain is not None:
            self._chain._cleanup_joints()
        for node in (self.gizmo, self._group):
            if node and cmds.objExists(node):
                cmds.delete(node)
        self._group = None
        self._status = guide_registry.GuideStatus.PENDING

    # -- Editing ----------------------------------------------------------

    def set_build_params(self,
                         n_joints:     Optional[int]  = None,
                         up_axis:      Optional[str]  = None,
                         degree:       Optional[int]  = None,
                         flip:         Optional[bool] = None,
                         cv_count:     Optional[int]  = None,
                         exact_points: Optional[bool] = None,
                         strip_handles: Optional[int] = None,) -> None:
        """Update the build parameters of a (PENDING or BUILT) guide."""
        if n_joints is not None:
            self.n_joints = n_joints
        if up_axis is not None:
            self.up_axis = up_axis
        if degree is not None:
            self.degree = degree
        if flip is not None:
            self.flip = flip
        if cv_count is not None:
            self.cv_count = cv_count
        if exact_points is not None:
            self.exact_points = exact_points
        if strip_handles is not None:
            self.strip_handles = strip_handles

    # -- Skinning (phase 1: register / region / analyze - no weights) -----

    def register_skin(self,
                      mesh: Optional[str] = None,) -> str:
        """Register the skinCluster of `mesh` (or the selected mesh) + its meshes."""
        target = mesh or skin_ops.selected_mesh()
        if not target:
            raise ValueError("Select a skinned mesh to register.")
        skin = skin_ops.find_skin_cluster(target)
        if not skin:
            raise ValueError(f"No skinCluster found on {target.split('|')[-1]!r}.")
        self.skin_cluster = skin
        self.skin_meshes  = skin_ops.skin_cluster_meshes(skin)
        self.store_recipe()
        return skin

    def make_gizmo(self,
                   shape: Optional[str] = None,) -> str:
        """
        (Re)create the optional clip gizmo, fitted around the whole chain with
        the reach radius (see skin_ops.fit_gizmo) - it starts clipping nothing,
        the artist shrinks / moves it to cut something out. Falls back to a unit
        gizmo on the _PIN when the chain has no curve yet.
        """
        if shape:
            self.gizmo_shape = shape
        if self.gizmo and cmds.objExists(self.gizmo):
            cmds.delete(self.gizmo)
        name = f"{self.name}_skinGizmo"
        if self.source_curve and cmds.objExists(self.source_curve):
            _, _, radius = self.reach()
            self.gizmo = skin_ops.fit_gizmo(self.gizmo_shape, self.source_curve, radius, name=name)
        else:
            self.gizmo = skin_ops.create_gizmo(self.gizmo_shape, center=self.pin_joint, name=name)
        self.store_recipe()
        return self.gizmo

    def gizmo_coverage(self) -> Optional[float]:
        """Fraction of the chain's curve inside the clip gizmo (None without gizmo / curve)."""
        if not (self.gizmo and cmds.objExists(self.gizmo)
                and self.source_curve and cmds.objExists(self.source_curve)):
            return None
        return skin_ops.clip_coverage(self.gizmo, self.gizmo_shape, self.source_curve)

    def delete_gizmo(self) -> None:
        """Drop the clip gizmo: the region is the plain tube around the chain again."""
        if self.gizmo and cmds.objExists(self.gizmo):
            cmds.delete(self.gizmo)
        self.gizmo = None
        self.store_recipe()

    def gizmo_size(self) -> Optional[float]:
        """The clip gizmo's size in % of its fitted size (None without gizmo)."""
        if not (self.gizmo and cmds.objExists(self.gizmo)):
            return None
        return 100.0 * skin_ops.gizmo_size_factor(self.gizmo)

    @dw_undo.singleUndoChunk
    def set_gizmo_size(self,
                       percent: float,) -> None:
        """
        Grow / shrink the clip gizmo around its centre to `percent` of its
        fitted size. Relative to its current scale, so a viewport scale (even a
        non-uniform one) is kept in proportion rather than overwritten.
        """
        if self.gizmo and cmds.objExists(self.gizmo):
            skin_ops.set_gizmo_size_factor(self.gizmo, max(percent, 1.0) / 100.0)

    # -- Vertex mask ------------------------------------------------------

    def mask_count(self) -> int:
        """How many vertices the mask allows (0 = no mask: the whole tube)."""
        return sum(len(skin_ops.from_ranges(r)) for r in self.skin_mask.values())

    def set_mask_from_selection(self,
                                add: bool = False,) -> int:
        """
        Store the selected vertices (faces / edges / objects are converted) of
        the guide's registered meshes as its mask - replacing it, or added to it
        with `add`. Returns the mask's vertex count; raises when nothing
        selected is on a registered mesh.
        """
        registered = {cmds.ls(m, long=True)[0] for m in self.skin_meshes if cmds.objExists(m)}
        picked = {mesh: vids for mesh, vids in skin_ops.selected_vertices().items() if mesh in registered}
        if not picked:
            raise ValueError("Select vertices (or faces / edges) on the guide's registered mesh.")
        mask = {mesh: skin_ops.from_ranges(r) for mesh, r in self.skin_mask.items()} if add else {}
        for mesh, vids in picked.items():
            mask[mesh] = mask.get(mesh, set()) | vids
            self.skin_mask_counts[mesh] = cmds.polyEvaluate(mesh, vertex=True)
        self.skin_mask = {mesh: skin_ops.to_ranges(vids) for mesh, vids in mask.items()}
        self.skin_mask_counts = {m: c for m, c in self.skin_mask_counts.items() if m in self.skin_mask}
        self.store_recipe()
        return self.mask_count()

    def mask_count_changes(self) -> list:
        """
        [(mesh, count when the mask was set, count now)] for every masked mesh
        whose vertex count changed - the mask's indices may point at other
        vertices now. A mesh with no recorded count (older recipe) is not
        reported: there is nothing to compare against.
        """
        changes = []
        for mesh, then in self.skin_mask_counts.items():
            if mesh in self.skin_mask and cmds.objExists(mesh):
                now = cmds.polyEvaluate(mesh, vertex=True)
                if now != then:
                    changes.append((mesh, then, now))
        return changes

    def clear_mask(self) -> None:
        self.skin_mask = {}
        self.skin_mask_counts = {}
        self.store_recipe()

    def select_mask(self) -> None:
        """Select the mask's vertices in the viewport (to check or edit it)."""
        components = []
        for mesh, ranges in self.skin_mask.items():
            if cmds.objExists(mesh):
                components += [f"{mesh}.vtx[{first}:{last}]" for first, last in ranges]
        if components:
            cmds.select(components, replace=True)
        else:
            cmds.select(clear=True)

    def reach(self) -> tuple:
        """
        Return (nearest bone, base radius, radius): the base is the distance from
        the _PIN to the nearest skinCluster joint (DynForge chains excluded), the
        radius is base * radius_scale. It sizes both the attachment search around
        the _PIN and the tube around the chain. (None, 0.0, 0.0) if not ready.
        """
        pin = self.pin_joint
        if not (self.skin_cluster and pin and cmds.objExists(pin)):
            return None, 0.0, 0.0
        bone, base = skin_ops.nearest_influence(self.skin_cluster, pin,
                                                exclude=tuple(self._chain.joints))
        return bone, base, base * self.radius_scale

    def analyze(self) -> list:
        """
        Rank the skinCluster influences under the whole chain (within the reach
        radius of its curve; around the _PIN before there is a curve) - the
        bones it takes weight from. Reads the vanilla skin when it has a backup,
        so an installed chain is analysed against what it took from, and never
        lists DynForge chain joints. When nothing is picked yet, the top one is
        taken as the donor (more are the artist's pick), and the top one AT THE _PIN as parent bone (a strip
        hangs from its root, wherever most of its weight comes from).
        A donor that is a DynForge chain joint (picked from a list read on an
        installed skin before this was fixed) is dropped with a warning: the
        vanilla skin gives it no weight, so the chain would take nothing.
        """
        self.refresh_references()
        if not self.skin_cluster:
            raise ValueError("Register a skinned mesh first.")
        if not self.pin_joint:
            raise ValueError("Build the chain first: the analysis starts from its _PIN.")
        _, _, radius = self.reach()
        if radius <= 0.0:
            raise ValueError("No skin joint found around the _PIN to size the radius.")
        curve = self.source_curve if self.source_curve and cmds.objExists(self.source_curve) else None
        ranked = skin_ops.attachment_candidates(self.skin_cluster, self.pin_joint, radius, curve=curve)
        stale = [d for d in self.source_influences if skin_ops.is_chain_joint(d)]
        if stale:
            logger.warning(f"DynForge: {self.name} had DynForge chain joint(s) as donor - dropped: "
                           f"{', '.join(_bare(d) for d in stale)}")
            self.source_influences = [d for d in self.source_influences if d not in stale]
        weighted = [(name, pct) for name, pct in ranked if pct > 0.0]   # the list also shows 0% bones
        if weighted and not self.source_influences:
            # The top bone only (user, 2026-10-07): several donors are the
            # artist's call, made by selecting more rows in the list.
            self.source_influences = [weighted[0][0]]
        if not self.parent_bone or skin_ops.is_chain_joint(self.parent_bone):
            at_pin = skin_ops.attachment_candidates(self.skin_cluster, self.pin_joint, radius) if curve else ranked
            at_pin = [(name, pct) for name, pct in at_pin if pct > 0.0]
            if at_pin:
                self.parent_bone = cmds.ls(at_pin[0][0], long=True)[0]
        self.store_recipe()
        return ranked

    def skin_spec(self) -> dict:
        """The plain-dict description skin_ops.compute_split / install_chains use."""
        self.refresh_references()
        _, _, radius = self.reach()
        return {
            "name":        self.name,
            "joints":      list(self._chain.joints),
            "curve":       self.source_curve,
            # A chain never takes from a chain: a stale chain-joint donor would take nothing.
            "donors":      [d for d in self.source_influences if not skin_ops.is_chain_joint(d)],
            "radius":      radius,
            "power":       self.power,
            "gizmo":       self.gizmo if self.gizmo and cmds.objExists(self.gizmo) else None,
            "gizmo_shape": self.gizmo_shape,
            "mask":        {mesh: skin_ops.from_ranges(r) for mesh, r in self.skin_mask.items()} or None,
        }

    def inspect_influence(self,
                          influence: str,) -> None:
        """Open the paint tool focused on `influence` (first registered mesh)."""
        if self.skin_meshes:
            skin_ops.inspect_influence(self.skin_meshes[0], influence)

    def set_parent_from_selection(self) -> str:
        """Store the selected joint as the _PIN parent (donor) bone."""
        sel = cmds.ls(selection=True, type="joint", long=True) \
            or cmds.ls(selection=True, long=True)
        if not sel:
            raise ValueError("Select a joint to use as the parent bone.")
        self.parent_bone = sel[0]
        self.store_recipe()
        return self.parent_bone

    def skin_layer_info(self) -> dict:
        """
        The DynForge layer of the registered skinCluster, for display:
        {"chains": [...], "verts": n, "time": str, "legacy": [chain joints
        carrying weight that no layer records]}.
        """
        info = {"chains": [], "verts": 0, "time": "", "legacy": []}
        if not (self.skin_cluster and cmds.objExists(self.skin_cluster)):
            return info
        layer = skin_ops.load_layer(self.skin_cluster, skin_ops._part_of(self))
        if layer:
            info["chains"] = list(layer.get("chains") or [])
            info["verts"] = sum(len(rows) for rows in (layer.get("shapes") or {}).values())
            info["time"] = layer.get("time", "")
        elif not skin_ops.has_backup(self.skin_cluster):
            info["legacy"] = skin_ops.chain_weighted_influences(self.skin_cluster)
        return info

    @dw_undo.singleUndoChunk
    def remove_skin_layer(self,
                          skin_peers: tuple = (),) -> dict:
        """
        Take every DynForge weight off the registered skinCluster (all its
        chains), one undo step; the chains stay in the rig, reserved at weight
        0 and locked like an install without skin. Returns the removal report.
        """
        self.refresh_references()
        if not (self.skin_cluster and cmds.objExists(self.skin_cluster)):
            raise ValueError("Register a skinned mesh first.")
        same_skin = [g for g in tuple(skin_peers) + (self,)
                     if getattr(g, "skin_cluster", None) == self.skin_cluster]
        placed = [g for g in dict.fromkeys(same_skin) if getattr(g, "installed", False)]
        part = skin_ops._part_of(self)
        keep = [j for g in placed for j in g.chain_joints]
        report = skin_ops.strip_dynforge(self.skin_cluster, keep_joints=keep, part=part) or {}
        skin_ops.save_layer(self.skin_cluster, None, skin_ops.layer_home(self), part)
        for guide in dict.fromkeys(same_skin):
            if getattr(guide, "installed", False):
                skin_ops.reserve_influences(self.skin_cluster, guide.chain_joints)
            if getattr(guide, "skin_installed", False):
                guide.skin_installed = False
                guide.store_recipe()
        return report

    def is_installable(self,
                       with_skin: bool = True,) -> bool:
        """
        True if this guide can be installed: built with a parent bone, plus a
        skinCluster and donor bone(s) when the weights are installed too.
        """
        built = bool(self._chain is not None and self._chain.joints
                     and self.source_curve and cmds.objExists(self.source_curve))
        if not with_skin:
            return built and bool(self.parent_bone and cmds.objExists(self.parent_bone))
        return built and bool(self.skin_cluster and cmds.objExists(self.skin_cluster)
                              and self.source_influences)

    def is_installed(self) -> bool:
        """True if this guide's chain joints are already influences on the skin."""
        if not (self.skin_cluster and self._chain and self._chain.joints):
            return False
        infls = set(cmds.skinCluster(self.skin_cluster, query=True, influence=True) or [])
        short = {i.split("|")[-1] for i in infls}
        return all(j in infls or j.split("|")[-1] in short for j in self._chain.joints)

    @dw_undo.singleUndoChunk
    def install_pin(self) -> Optional[str]:
        """
        Hand the chain to the host to place it in the rig (default: _PIN under
        the parent bone; a studio host may also rename it), then move the guide
        group into the host's setup home when it has one. The weights are
        installed per skinCluster, for all its chains at once - see
        skin_ops.install_chains. Returns the setup home, or None when the guide
        stayed where it was.
        """
        self.refresh_references()
        host = forge_host.get_host()
        if self._chain is not None and self._chain.joints:
            joints = host.install_chain(self)
            if joints:
                self._chain.joints = list(joints)
            self._tag_chain()
        home = host.setup_for(self)
        if home:
            self.move_to_setup(home)
        self.setup_home = home   # read by the UI to offer a JSON copy when None
        self.installed = True
        self.reinstall_pending = False
        self.store_recipe()
        return home

    @dw_undo.singleUndoChunk
    def uninstall(self,
                  skin_peers: tuple = (),) -> None:
        """
        Revert the install, one undo step:
        - weights: when this guide's weights were installed, the skin's
          DynForge layer is taken off (the other departments' edits stay) and
          the other skin-installed guides in `skin_peers` are re-applied, or
          the skin is left without DynForge weight when none remains;
        - hierarchy: the host puts the chain back under the guide group with
          its build names (and drops what it created for it, e.g. a ghost).
        The guide group stays in its setup home.
        """
        self.refresh_references()
        has_skin = bool(self.skin_cluster and cmds.objExists(self.skin_cluster))
        if self.skin_installed and has_skin:
            same_skin = [g for g in skin_peers
                         if g is not self and getattr(g, "skin_cluster", None) == self.skin_cluster]
            remaining = [g for g in same_skin if getattr(g, "skin_installed", False)]
            # Peers installed without skin keep their 0-weight locked influences.
            reserved = tuple(g for g in same_skin
                             if getattr(g, "installed", False) and not getattr(g, "skin_installed", False))
            if remaining:
                skin_ops.install_skin(self.skin_cluster, remaining, reserved=reserved)
            else:
                # Raises before changing anything on a skin whose DynForge weight
                # no layer records (installed before the layer, record lost).
                part = skin_ops._part_of(self)
                keep = [j for g in reserved for j in g.chain_joints]
                skin_ops.strip_dynforge(self.skin_cluster, keep_joints=keep, part=part)
                skin_ops.save_layer(self.skin_cluster, None, skin_ops.layer_home(self), part)
                for guide in reserved:
                    skin_ops.reserve_influences(self.skin_cluster, guide.chain_joints)
        elif self.installed and has_skin:
            # Installed without skin: its joints were reserved at weight 0 - take them out again.
            painted = skin_ops.release_influences(self.skin_cluster, self.chain_joints)
            if painted:
                logger.warning(f"DynForge: {self.name} had weight painted on {len(painted)} joint(s) - "
                               f"removed with the chain, Maya gave it back to the other influences.")
        if self._chain is not None and self._chain.joints:
            joints = forge_host.get_host().uninstall_chain(self)
            if joints:
                self._chain.joints = list(joints)
            self._tag_chain()
        self.installed = False
        self.skin_installed = False
        self.reinstall_pending = False
        self.store_recipe()

    def move_to_setup(self,
                      setup: str,) -> None:
        """Re-parent the guide group under another setup group (e.g. a studio home)."""
        group = self.guide_group()
        current = cmds.listRelatives(group, parent=True, fullPath=True) or []
        if current != cmds.ls(setup, long=True):
            group = cmds.parent(group, setup)[0]
        self._group = cmds.ls(group, long=True)[0]
        self.setup = cmds.ls(setup, long=True)[0]
        if self._chain is not None:
            self._chain.group_name = self._group

    # -- Serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        """Return the JSON-serializable recipe (params + sources + node names)."""
        self._sync_point_records()
        return {
            "type_name":         self.type_name,
            "name":              self.name,
            "n_joints":          self.n_joints,
            "up_axis":           self.up_axis,
            "degree":            self.degree,
            "flip":              self.flip,
            "point_type":        self.point_type,
            "cv_count":          self.cv_count,
            "exact_points":      self.exact_points,
            "points":            self.point_records,
            "strip_source":      self.strip_source,
            "strip_handles":     self.strip_handles,
            "curve_points":      self.positions,
            "skin_cluster":      self.skin_cluster,
            "skin_meshes":       self.skin_meshes,
            "gizmo":             self.gizmo,
            "gizmo_shape":       self.gizmo_shape,
            "skin_mask":         self.skin_mask,
            "skin_mask_counts":  self.skin_mask_counts,
            "source_influences": self.source_influences,
            "parent_bone":       self.parent_bone,
            "power":             self.power,
            "radius_scale":      self.radius_scale,
            "installed":         self.installed,
            "skin_installed":    self.skin_installed,
            "with_skin":         self.with_skin,
            "reinstall_pending": self.reinstall_pending,
            "host_data":         self.host_data,
            # Scene node names without namespace (a studio tool may add one to
            # anything moved into a container), only used to reattach a guide.
            "nodes": {
                "points": [_bare(node) for node in self.points],
                "curve":  _bare(self.source_curve) if self.source_curve else None,
                "joints": [_bare(j) for j in (self._chain.joints if self._chain else [])],
            },
        }

    @classmethod
    def from_dict(cls,
                  data: dict,) -> "ChainJointGuide":
        """Rebuild a (PENDING) guide from a to_dict() payload - no scene nodes."""
        guide = cls(name         = data.get("name", "chain"),
                    n_joints     = data.get("n_joints", 10),
                    up_axis      = data.get("up_axis", "y"),
                    degree       = data.get("degree", 3),
                    flip         = data.get("flip", False),
                    point_type   = data.get("point_type", "locator"),
                    cv_count     = data.get("cv_count", 6),
                    exact_points = data.get("exact_points", False),)
        guide.point_records     = [dict(rec) for rec in data.get("points", [])]
        guide.positions         = [tuple(p) for p in data.get("curve_points", [])]
        guide.strip_source      = data.get("strip_source")
        guide.strip_handles     = int(data.get("strip_handles", 3))
        guide.skin_cluster      = data.get("skin_cluster")
        guide.skin_meshes       = list(data.get("skin_meshes", []))
        guide.gizmo_shape       = data.get("gizmo_shape", "box")
        guide.skin_mask         = dict(data.get("skin_mask") or {})
        guide.skin_mask_counts  = dict(data.get("skin_mask_counts") or {})
        guide.source_influences = list(data.get("source_influences", []))
        guide.parent_bone       = data.get("parent_bone")
        guide.power             = data.get("power", 1.0)
        guide.radius_scale      = data.get("radius_scale", 1.0)
        guide.installed         = bool(data.get("installed", False))
        guide.skin_installed    = bool(data.get("skin_installed", False))
        guide.with_skin         = bool(data.get("with_skin", True))
        guide.reinstall_pending = bool(data.get("reinstall_pending", False))
        guide.host_data         = dict(data.get("host_data") or {})
        return guide

    # -- Discovery --------------------------------------------------------

    @classmethod
    def discover(cls) -> list:
        """Rebuild the guides whose recipe group is in the scene, reattached to their nodes."""
        found: list = []
        for group in cmds.ls(type="transform", long=True) or []:
            if not cmds.attributeQuery(RECIPE_ATTR, node=group, exists=True):
                continue
            if cmds.getAttr(f"{group}.{GUIDE_TAG}") != cls.type_name:
                continue
            try:
                guide = cls._from_scene_group(group)
                guide.refresh_references()   # names may have changed since the recipe was written
                found.append(guide)
            except Exception as e:
                logger.warning(f"discover: could not restore {group!r}: {e}")
        return found

    @classmethod
    def _from_scene_group(cls,
                          group: str,) -> "ChainJointGuide":
        data  = json.loads(cmds.getAttr(f"{group}.{RECIPE_ATTR}"))
        guide = cls.from_dict(data)
        guide._group = group
        guide.setup  = (cmds.listRelatives(group, parent=True, fullPath=True) or [None])[0]
        nodes = data.get("nodes", {})

        # Shortest unique names, like every node the guide creates itself: a long
        # path goes stale as soon as a point is re-parented (exact chains).
        descendants = cmds.listRelatives(group, allDescendents=True, fullPath=True) or []
        by_short = {_bare(node): cmds.ls(node)[0] for node in descendants}
        guide.points = [by_short[n] for n in nodes.get("points", []) if n in by_short]
        curve = by_short.get(nodes.get("curve"))
        gizmo = data.get("gizmo")
        guide.gizmo = gizmo if gizmo and cmds.objExists(gizmo) else None
        if not curve:
            return guide

        # An installed chain has left the group for its parent bone: fall back
        # to the joints tagged with this guide's name.
        joints = []
        for short in nodes.get("joints", []):
            short = _bare(short)
            node = by_short.get(short)
            if node is None:
                tagged = [j for j in cmds.ls(short, long=True, type="joint", recursive=True) or []
                          if cmds.attributeQuery("dwForge", node=j, exists=True)
                          and cmds.getAttr(f"{j}.dwForge") == guide.name]
                node = cmds.ls(tagged[0])[0] if len(tagged) == 1 else None
            if node is None:
                joints = []
                break
            joints.append(node)

        guide.source_curve = curve
        guide._chain = dw_chain_guide.ChainGuide(
            curve_name=curve, n_joints=guide.n_joints, name=guide.name,
            up_axis=guide.up_axis, group=group,
        )
        guide._chain.joints = joints
        guide._curve_flip = guide.flip
        if joints:
            guide._status = guide_registry.GuideStatus.BUILT
            # A recipe written before the install flags existed: read the state
            # off the scene (the _PIN left the guide group / joints are influences).
            if "installed" not in data:
                pin_parent = cmds.listRelatives(joints[0], parent=True, fullPath=True) or []
                guide.installed = pin_parent != [group]
            if "skin_installed" not in data:
                try:
                    guide.skin_installed = bool(guide.skin_cluster and cmds.objExists(guide.skin_cluster)
                                                and guide.is_installed())
                except Exception:
                    guide.skin_installed = False
        return guide

    # -- Internal helpers -------------------------------------------------

    @staticmethod
    def _read_curve_points(curve: str) -> list:
        """Return the world-space CV positions of a curve as [(x, y, z), ...]."""
        cvs = cmds.ls(f"{curve}.cv[*]", flatten=True) or []
        return [tuple(cmds.pointPosition(cv, world=True)) for cv in cvs]

    def _chain_from_curve_points(self,
                                 points:   list,
                                 resample: bool,) -> dw_chain_guide.ChainGuide:
        """Build the source curve from `points` inside the guide group and wrap it."""
        if len(points) < 2:
            raise ValueError(f"'{self.name}': {len(points)} curve point(s), at least 2 are required.")
        group = self.guide_group()
        curve = dw_chain_guide.build_curve_from_positions(
            points, name=f"{self.name}_src_crv", degree=self.degree, closed=False,
        )
        # Resample only UP to cv_count: a few hand-placed points need extra CVs
        # to be editable, but a dense edge column must keep its shape.
        if resample and len(points) < self.cv_count:
            dw_chain_guide.resample_curve(curve, self.cv_count, degree=self.degree)
        curve = cmds.parent(curve, group)[0]
        return dw_chain_guide.ChainGuide.from_existing_curve(
            curve_name = curve,
            n_joints   = self.n_joints,
            name       = self.name,
            up_axis    = self.up_axis,
            group      = group,
        )


guide_registry.register(ChainJointGuide)
