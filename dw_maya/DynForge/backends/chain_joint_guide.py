"""
chain_joint_guide.py - DynForge backend: a chain of joints along a curve.

Wraps dw_rigging.dw_chain_guide.ChainGuide as a DynForge GuideBackend so joint
chains plug into the guide registry alongside future nHair / constraint guides.

The reproducibility snapshot stores world-space curve waypoints (preferred over
component ids, which break on retopo) plus the build parameters, so a guide can
be rebuilt after the source selection is gone.
"""

from __future__ import annotations

from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2

from dw_logger import get_logger
from dw_maya.dw_rigging import dw_chain_guide
from dw_maya.DynForge import guide_registry
from dw_maya.DynForge.forge_cmds import skin_ops

logger = get_logger()


class ChainJointGuide(guide_registry.GuideBackend):
    """A chain of joints distributed along a source NURBS curve."""

    type_name      = "chain_joint"
    label          = "Joint Chain"
    creation_modes = ("edge", "face", "locator")

    def __init__(self,
                 name:       str = "chain",
                 mode:       str = "edge",
                 n_joints:   int = 10,
                 up_axis:    str = "y",
                 degree:     int = 3,
                 flip:       bool = False,
                 n_locators: int = 4,
                 point_type:  str = "locator",
                 cv_count:    int = 6,
                 exact_points: bool = False,) -> None:
        super().__init__(name=name)
        self.mode       = mode
        self.n_joints   = n_joints
        self.up_axis    = up_axis
        self.degree     = degree
        self.flip       = flip
        self.n_locators = n_locators
        # Guide-point node type for the locator flow: "locator" or "joint".
        self.point_type = point_type
        # CV count the locator-flow curve is resampled to (editable resolution).
        self.cv_count   = cv_count
        # Exact mode (locator flow): one joint per guide point, placed exactly on
        # it; the curve is kept only as data. Joint count follows the points.
        self.exact_points = exact_points
        # -- Skinning params (filled in the Skinning tab, used on Install) -----
        self.skin_cluster:      Optional[str] = None   # target skinCluster
        self.skin_meshes:       list          = []     # meshes it deforms
        self.gizmo:             Optional[str] = None   # region gizmo transform
        self.gizmo_shape:       str           = "box"  # box / sphere / capsule
        self.source_influences: list          = []     # picked donor bones
        self.parent_bone:       Optional[str] = None   # _PIN parent (donor bone)
        self.power:             float         = 1.0    # spatial-cascade falloff
        # Locator-flow only: guide locator transforms set while PENDING.
        self.locators:     list                          = []
        # Reproducibility snapshot: world-space curve waypoints [(x, y, z), ...].
        self.positions:    list                          = []
        self.source_curve: Optional[str]                 = None
        self._chain:       Optional[dw_chain_guide.ChainGuide] = None
        # Flip direction currently baked into the source curve, so rebuild() can
        # tell when the artist toggled Flip and reverse the curve to match.
        self._curve_flip:  bool                          = flip
        # Override group for the built nodes (set when loading a version from a
        # file, so it lands in its own group instead of the shared working one).
        self.group_name:   Optional[str]                 = None

    # -- Creation factories -----------------------------------------------

    @classmethod
    def from_edge_selection(cls,
                            name:     str = "chain",
                            n_joints: int = 10,
                            up_axis:  str = "y",
                            degree:   int = 3,
                            flip:     bool = False,) -> "ChainJointGuide":
        """
        Create a PENDING guide from the current Maya edge selection.
        The source curve is built immediately; joints are built on build().
        """
        guide = cls(name     = name,
                    mode     = "edge",
                    n_joints = n_joints,
                    up_axis  = up_axis,
                    degree   = degree,
                    flip     = flip,)
        chain = dw_chain_guide.ChainGuide.from_edge_selection(
            n_joints = n_joints,
            name     = name,
            degree   = degree,
            up_axis  = up_axis,
            reverse  = flip,
        )
        guide._chain       = chain
        guide.source_curve = chain.curve_name
        guide.positions    = cls._read_curve_points(chain.curve_name)
        return guide

    @classmethod
    def from_face_selection(cls,
                            name:     str = "chain",
                            n_joints: int = 10,
                            up_axis:  str = "y",
                            degree:   int = 3,
                            flip:     bool = False,) -> "ChainJointGuide":
        """
        Create a PENDING guide from the current Maya face selection.
        The source curve is built immediately; joints are built on build().
        """
        guide = cls(name     = name,
                    mode     = "face",
                    n_joints = n_joints,
                    up_axis  = up_axis,
                    degree   = degree,
                    flip     = flip,)
        chain = dw_chain_guide.ChainGuide.from_face_selection(
            n_joints = n_joints,
            name     = name,
            degree   = degree,
            up_axis  = up_axis,
            reverse  = flip,
        )
        guide._chain       = chain
        guide.source_curve = chain.curve_name
        guide.positions    = cls._read_curve_points(chain.curve_name)
        return guide

    @classmethod
    def create_with_locators(cls,
                             name:       str = "chain",
                             n_locators: int = 3,
                             n_joints:   int = 10,
                             up_axis:    str = "y",
                             degree:     int = 3,
                             flip:       bool = False,) -> "ChainJointGuide":
        """
        Start a locator-flow guide: spawn n_locators guide locators (min 3) and
        return a PENDING instance. The artist positions the locators, then
        build() reads them, builds the source curve and distributes the joints.
        No curve exists yet at this point.
        """
        guide = cls(name     = name,
                    mode     = "locator",
                    n_joints = n_joints,
                    up_axis  = up_axis,
                    degree   = degree,
                    flip     = flip,)
        guide.locators = dw_chain_guide.create_guide_locators(
            n_locators = n_locators,
            name       = name,
        )
        return guide

    @classmethod
    def create(cls,
               **params,) -> "ChainJointGuide":
        """
        Create a blank PENDING guide carrying the build parameters but no scene
        nodes. The artist picks / confirms the creation mode in the UI, then the
        per-row Build button materializes it (see build()). Nothing is read from
        the current selection here, so [+] never depends on what is selected.
        """
        return cls(name       = params.get("name", "chain"),
                   mode       = params.get("mode", "edge"),
                   n_joints   = params.get("n_joints", 10),
                   up_axis    = params.get("up_axis", "y"),
                   degree     = params.get("degree", 3),
                   flip       = params.get("flip", False),
                   n_locators = params.get("n_locators", 4),
                   point_type = params.get("point_type", "locator"),
                   cv_count   = params.get("cv_count", 6),
                   exact_points = params.get("exact_points", False),)

    # -- Editing (while PENDING) ------------------------------------------

    def set_mode(self,
                 mode: str,) -> None:
        """Change the creation mode of a not-yet-built guide (ignored if BUILT)."""
        if self._status is guide_registry.GuideStatus.BUILT:
            return
        self.mode = mode

    def set_point_type(self,
                       point_type: str,) -> None:
        """Change the guide-point node type ('locator' / 'joint') for new points."""
        self.point_type = point_type

    def add_locator(self) -> str:
        """
        Add one guide point at the current selection center (or at the world
        origin / extrapolated past the last point when nothing is selected) and
        return its node name. The node type follows self.point_type.

        With the 'joint' point type the placed joints ARE the chain joints, so
        each one bumps n_joints; at build they seed the curve and are then
        removed and replaced by the constructed chain.
        """
        # Read the selection center BEFORE creating the group: cmds.group /
        # cmds.parent change the active selection, which would otherwise clobber
        # the artist's vertex selection on the very first add (-> world origin).
        center = dw_chain_guide.get_selection_center()
        group  = dw_chain_guide.ensure_locator_group(self.name)
        node = dw_chain_guide.create_guide_point(
            node_type = self.point_type,
            name      = self.name,
            index     = len(self.locators),
            position  = center,
            group     = group,
        )
        self.locators.append(node)
        if self.point_type == "joint":
            self.n_joints = max(len(self.locators), 2)
        return node

    def snap_locator(self,
                     node: str,) -> None:
        """Snap one of this guide's points to the current selection center."""
        if node not in self.locators:
            return
        dw_chain_guide.snap_node_to_selection_center(node)

    def delete_locator(self,
                       node: str,) -> None:
        """Delete one guide point (node + list entry); keep joint-count in sync."""
        if node not in self.locators:
            return
        if cmds.objExists(node):
            cmds.delete(node)
        self.locators.remove(node)
        if self.point_type == "joint":
            self.n_joints = max(len(self.locators), 2)

    def spawn_locators(self) -> list:
        """
        (Re)spawn the guide locators for a locator-flow guide so the artist can
        position them before building. Replaces any existing locators.
        """
        if self.locators:
            dw_chain_guide.delete_guide_locators(self.locators)
            self.locators = []
        self.locators = dw_chain_guide.create_guide_locators(
            n_locators = self.n_locators,
            name       = self.name,
        )
        return self.locators

    # -- Lifecycle --------------------------------------------------------

    def _locators_alive(self) -> bool:
        """True if this guide has locators and all of them still exist in scene."""
        return bool(self.locators) and all(cmds.objExists(loc) for loc in self.locators)

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
    def pin_joint(self) -> Optional[str]:
        """The root (_PIN) joint of the built chain, or None if not built."""
        if self._chain is not None and self._chain.joints:
            return self._chain.joints[0]
        return None

    def build(self) -> None:
        """
        Materialize the guide (-> BUILT). Source resolution order:

        - already has a curve: just (re)distribute the joints.
        - locator flow with live locators: build the curve from them.
        - has a snapshot (loaded from JSON / a previous build): rebuild the curve
          from the stored waypoints (so loaded guides do not need a live selection).
        - edge / face: read the current Maya selection and build the curve.
        """
        if self.exact_points and self.mode == "locator" and (self._locators_alive() or self.positions):
            self._build_exact()
            return
        if self._chain is not None:
            self._chain.build()
        elif self.mode == "locator" and self._locators_alive():
            self._chain = dw_chain_guide.ChainGuide.from_locators(
                self.locators,
                n_joints = self.n_joints,
                name     = self.name,
                degree   = self.degree,
                up_axis  = self.up_axis,
                reverse  = self.flip,
                cv_count = self.cv_count,
            )
            if self.point_type == "joint":
                # The placed joints were temporary markers seeding the curve;
                # remove them, the constructed chain replaces them.
                dw_chain_guide.delete_guide_locators(self.locators)
                self.locators = []
            self._chain.build()
        elif self.positions:
            self._chain = self._chain_from_snapshot()
            self._chain.build()
        elif self.mode == "edge":
            self._chain = dw_chain_guide.ChainGuide.from_edge_selection(
                n_joints = self.n_joints,
                name     = self.name,
                degree   = self.degree,
                up_axis  = self.up_axis,
                reverse  = self.flip,
            )
            self._chain.build()
        elif self.mode == "face":
            self._chain = dw_chain_guide.ChainGuide.from_face_selection(
                n_joints = self.n_joints,
                name     = self.name,
                degree   = self.degree,
                up_axis  = self.up_axis,
                reverse  = self.flip,
            )
            self._chain.build()
        else:
            raise ValueError(
                f"ChainJointGuide '{self.name}': nothing to build - select "
                "edges/faces (edge/face mode) or create locators first."
            )
        self.source_curve = self._chain.curve_name
        self.positions    = self._read_curve_points(self._chain.curve_name)
        self._curve_flip  = self.flip
        self._tag_chain()
        self._status = guide_registry.GuideStatus.BUILT

    def save_curve_positions(self) -> None:
        """
        Snapshot the live curve CV world positions into self.positions, so manual
        edits to the curve are preserved (used by the UI's 'Rebuild all').
        """
        if self.source_curve and cmds.objExists(self.source_curve):
            self.positions = self._read_curve_points(self.source_curve)

    def rebuild(self) -> None:
        """
        Rebuild the joint chain, following any artist adjustments. Once a curve
        exists (any mode, locators included), it is the source of truth: the
        artist edits its CVs and rebuild keeps the curve and only redistributes
        the joints. The locator-built curve is created with enough CVs to edit
        (see cv_count / build()), so there is no need to rebuild it from the
        locators here - that would discard the hand edits.

        Exact mode (one joint per guide point) is the exception: the points are
        the source of truth, so rebuild re-reads them and re-places the joints.
        """
        if self.exact_points and self.mode == "locator" and (self._locators_alive() or self.positions):
            self._build_exact()
            return
        if self._chain is not None:
            # Toggling Flip after the curve exists must reverse the curve in
            # place (rebuild alone only redistributes joints along it).
            if self.flip != self._curve_flip:
                dw_chain_guide.reverse_curve_direction(self.source_curve)
                self._curve_flip = self.flip
            self._chain.rebuild(n_joints=self.n_joints, up_axis=self.up_axis)
        else:
            # Never built: fall back to a fresh build.
            self.build()
            return
        self.source_curve = self._chain.curve_name
        self.positions    = self._read_curve_points(self._chain.curve_name)
        self._curve_flip  = self.flip
        self._tag_chain()
        self._status      = guide_registry.GuideStatus.BUILT

    # -- Exact mode (one joint per guide point) ---------------------------

    def _exact_positions(self) -> list:
        """World-space MPoints for the guide points (flip applied), live or snapshot."""
        if self._locators_alive():
            points = dw_chain_guide.get_locator_positions(self.locators)
        elif self.positions:
            points = [om2.MPoint(x, y, z) for (x, y, z) in self.positions]
        else:
            raise ValueError(
                f"ChainJointGuide '{self.name}': no guide points for an exact build."
            )
        if self.flip:
            points = points[::-1]
        return points

    def _build_exact(self) -> None:
        """
        Exact build: one joint sitting precisely on each guide point. The curve
        is rebuilt as a data-only record passing exactly through the points. For
        the 'joint' point type the placed joints are REUSED as the chain; for the
        'locator' type fresh joints are created and the locators stay as scaffold.
        """
        group = self.group_name or dw_chain_guide.ChainGuide.GRP_NAME

        reuse_joints = (self.point_type == "joint" and self._locators_alive())
        if reuse_joints:
            order  = self.locators[::-1] if self.flip else self.locators
            points = dw_chain_guide.get_locator_positions(order)
            joints = dw_chain_guide.chain_from_joints(order, self.name, self.up_axis)
            # Keep self.locators in the original placement order so flip stays a
            # pure derived transform (no double-reverse on the next rebuild).
            self.locators = joints[::-1] if self.flip else joints
        else:
            points = self._exact_positions()
            if self._chain is not None:
                self._chain._cleanup_joints()   # drop the previous exact chain
            joints = dw_chain_guide.place_joint_chain(points, self.name, self.up_axis)

        # Data-only curve, passing exactly through the points.
        if self.source_curve and cmds.objExists(self.source_curve):
            cmds.delete(self.source_curve)
        curve = dw_chain_guide.build_curve_through_positions(
            points, name=f"{self.name}_src_crv", degree=self.degree,
        )
        chain = dw_chain_guide.ChainGuide.from_existing_curve(
            curve, n_joints=len(points), name=self.name, up_axis=self.up_axis, group=group,
        )
        grp = chain.ensure_group()
        if (cmds.listRelatives(curve, parent=True) or []) != [grp]:
            cmds.parent(curve, grp)
        chain.joints = joints
        root = joints[0]
        if (cmds.listRelatives(root, parent=True) or []) != [grp]:
            cmds.parent(root, grp)

        self._chain       = chain
        self.source_curve = chain.curve_name
        self.positions    = [(p.x, p.y, p.z) for p in points]
        self.n_joints     = len(points)
        self._curve_flip  = self.flip
        self._tag_chain()
        self._status      = guide_registry.GuideStatus.BUILT

    def destroy(self) -> None:
        """Delete the built joint chain, keeping the source curve (-> PENDING)."""
        if self._chain is not None:
            # TODO: expose a public delete on ChainGuide; using the internal
            # cleanup for now so destroy() does not rely on tracking joints here.
            self._chain._cleanup_joints()
        self._status = guide_registry.GuideStatus.PENDING

    # -- Editing ----------------------------------------------------------

    def set_build_params(self,
                         n_joints:     Optional[int]  = None,
                         up_axis:      Optional[str]  = None,
                         degree:       Optional[int]  = None,
                         flip:         Optional[bool] = None,
                         cv_count:     Optional[int]  = None,
                         exact_points: Optional[bool] = None,) -> None:
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

    def reorder_locators(self,
                         ordered: list,) -> None:
        """
        Set a new chain order for the guide locators. `ordered` must be a
        permutation of the current locators; anything else is ignored.
        """
        if set(ordered) == set(self.locators) and len(ordered) == len(self.locators):
            self.locators = list(ordered)

    def snap_locators_to_mesh(self,
                              mesh: Optional[str] = None,) -> None:
        """
        Snap every guide locator to the nearest vertex of `mesh` (or the first
        selected mesh when `mesh` is None). Locator flow only.
        """
        if not self.locators:
            raise ValueError("This guide has no locators to snap.")
        target = mesh or dw_chain_guide.get_selected_mesh()
        if not target:
            raise ValueError("Select a mesh (or its vertices) to snap the locators to.")
        dw_chain_guide.snap_locators_to_mesh(self.locators, target)

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
        return skin

    def make_gizmo(self,
                   shape: Optional[str] = None,) -> str:
        """(Re)create the region gizmo, centered on the _PIN joint."""
        if shape:
            self.gizmo_shape = shape
        if self.gizmo and cmds.objExists(self.gizmo):
            cmds.delete(self.gizmo)
        self.gizmo = skin_ops.create_gizmo(
            self.gizmo_shape, center=self.pin_joint, name=f"{self.name}_skinGizmo",
        )
        return self.gizmo

    def analyze(self) -> list:
        """Rank the skinCluster influences by participation inside the gizmo."""
        if not self.skin_cluster:
            raise ValueError("Register a skinned mesh first.")
        if not (self.gizmo and cmds.objExists(self.gizmo)):
            raise ValueError("Create a gizmo first.")
        return skin_ops.analyze_participation(
            self.skin_cluster, self.skin_meshes, self.gizmo, self.gizmo_shape,
        )

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
        return self.parent_bone

    def has_skin_backup(self) -> bool:
        """True if the registered skinCluster carries a DynForge weight backup."""
        return bool(self.skin_cluster) and skin_ops.has_backup(self.skin_cluster)

    def backup_skin(self,
                    force: bool = False,) -> bool:
        """Back up the registered skinCluster's weights (no overwrite unless force)."""
        if not self.skin_cluster:
            raise ValueError("Register a skinned mesh first.")
        return skin_ops.backup_skin(self.skin_cluster, force=force)

    def restore_skin(self) -> None:
        """Restore the registered skinCluster to its DynForge backup."""
        if not self.skin_cluster:
            raise ValueError("Register a skinned mesh first.")
        skin_ops.restore_skin(self.skin_cluster)

    def is_installable(self) -> bool:
        """True if this guide is built and fully configured for a skin install."""
        return bool(self.skin_cluster
                    and self.source_influences
                    and self.gizmo and cmds.objExists(self.gizmo)
                    and self._chain is not None and self._chain.joints)

    def is_installed(self) -> bool:
        """True if this guide's chain joints are already influences on the skin."""
        if not (self.skin_cluster and self._chain and self._chain.joints):
            return False
        infls = set(cmds.skinCluster(self.skin_cluster, query=True, influence=True) or [])
        short = {i.split("|")[-1] for i in infls}
        return all(j in infls or j.split("|")[-1] in short for j in self._chain.joints)

    def install(self) -> int:
        """
        Transfer the donor weight onto this chain (spatial cascade) and parent the
        _PIN under the donor/parent bone. Returns the number of verts edited.
        """
        if not self.is_installable():
            raise ValueError(
                "Not ready to install: build the chain, register a skin, create a "
                "gizmo and pick donor bone(s) first.")
        edited = skin_ops.install_chain(
            self.skin_cluster,
            self.skin_meshes,
            self.gizmo,
            self.gizmo_shape,
            self.source_curve,
            list(self._chain.joints),
            self.source_influences,
            self.power,
        )
        # Hierarchy move: parent the _PIN under the donor / parent bone.
        if self.parent_bone and cmds.objExists(self.parent_bone):
            pin = self.pin_joint
            if pin and (cmds.listRelatives(pin, parent=True, fullPath=True) or []) != [self.parent_bone]:
                try:
                    cmds.parent(pin, self.parent_bone)
                except Exception as e:
                    logger.warning(f"DynForge install: parent _PIN failed: {e}")
        return edited

    # -- Serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        """Return the JSON-serializable reproducibility snapshot."""
        return {
            "type_name":    self.type_name,
            "name":         self.name,
            "mode":         self.mode,
            "n_joints":     self.n_joints,
            "up_axis":      self.up_axis,
            "degree":       self.degree,
            "flip":         self.flip,
            "n_locators":   self.n_locators,
            "point_type":   self.point_type,
            "cv_count":     self.cv_count,
            "exact_points": self.exact_points,
            "skin_cluster":      self.skin_cluster,
            "skin_meshes":       self.skin_meshes,
            "gizmo_shape":       self.gizmo_shape,
            "source_influences": self.source_influences,
            "parent_bone":       self.parent_bone,
            "power":             self.power,
            "positions":    self.positions,
            "source_curve": self.source_curve,
            "locators":     self.locators,
        }

    @classmethod
    def from_dict(cls,
                  data: dict,) -> "ChainJointGuide":
        """Rebuild a (PENDING) guide instance from a to_dict() payload."""
        guide = cls(name       = data.get("name", "chain"),
                    mode       = data.get("mode", "edge"),
                    n_joints   = data.get("n_joints", 10),
                    up_axis    = data.get("up_axis", "y"),
                    degree     = data.get("degree", 3),
                    flip       = data.get("flip", False),
                    n_locators = data.get("n_locators", 4),
                    point_type = data.get("point_type", "locator"),
                    cv_count   = data.get("cv_count", 6),
                    exact_points = data.get("exact_points", False),)
        guide.positions    = [tuple(p) for p in data.get("positions", [])]
        guide.source_curve = data.get("source_curve")
        guide.locators     = list(data.get("locators", []))
        guide.skin_cluster      = data.get("skin_cluster")
        guide.skin_meshes       = list(data.get("skin_meshes", []))
        guide.gizmo_shape       = data.get("gizmo_shape", "box")
        guide.source_influences = list(data.get("source_influences", []))
        guide.parent_bone       = data.get("parent_bone")
        guide.power             = data.get("power", 1.0)
        return guide

    # -- Discovery --------------------------------------------------------

    @classmethod
    def discover(cls) -> list:
        """Find tagged ChainGuide curves in the scene and wrap them as instances."""
        found: list = []
        for shape in cmds.ls(type="nurbsCurve", long=True) or []:
            parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
            if not parents:
                continue
            transform = parents[0]
            if not cmds.objExists(f"{transform}.cgName"):
                continue
            try:
                chain = dw_chain_guide.ChainGuide.from_scene_curve(transform)
            except Exception as e:
                logger.warning(f"discover: could not wrap {transform!r}: {e}")
                continue
            guide = cls(name     = chain.name,
                        n_joints = chain.n_joints,
                        up_axis  = chain.up_axis,)
            guide._chain       = chain
            guide.source_curve = chain.curve_name
            guide.positions    = cls._read_curve_points(chain.curve_name)
            guide._status      = guide_registry.GuideStatus.BUILT
            found.append(guide)
        return found

    # -- Internal helpers -------------------------------------------------

    @staticmethod
    def _read_curve_points(curve: str) -> list:
        """Return the world-space CV positions of a curve as [(x, y, z), ...]."""
        cvs = cmds.ls(f"{curve}.cv[*]", flatten=True) or []
        return [tuple(cmds.pointPosition(cv, world=True)) for cv in cvs]

    def _chain_from_snapshot(self) -> dw_chain_guide.ChainGuide:
        """Recreate the source curve from stored waypoints and wrap it."""
        if len(self.positions) < 2:
            raise ValueError(
                f"ChainJointGuide '{self.name}': snapshot has "
                f"{len(self.positions)} point(s), at least 2 are required."
            )
        points = [om2.MPoint(x, y, z) for (x, y, z) in self.positions]
        curve = dw_chain_guide.build_curve_from_positions(
            points,
            name   = f"{self.name}_src_crv",
            degree = self.degree,
            closed = False,
        )
        chain = dw_chain_guide.ChainGuide.from_existing_curve(
            curve_name = curve,
            n_joints   = self.n_joints,
            name       = self.name,
            up_axis    = self.up_axis,
            group      = self.group_name,
        )
        # Keep the regenerated curve inside the guide's group (build_curve_from_
        # positions leaves it at the scene root) so a loaded version stays tidy.
        group = chain.ensure_group()
        if (cmds.listRelatives(curve, parent=True) or []) != [group]:
            cmds.parent(curve, group)
        return chain


guide_registry.register(ChainJointGuide)