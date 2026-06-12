"""
dw_chain_guide.py  –  Phase 1
==============================
Build a joint chain along an edge loop via a NurbsCurve intermediate.

Workflow :
    # 1. Sélectionner un edge loop dans Maya
    guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A")
    guide.build()

    # 2. Rebuild avec plus de joints (la curve source est conservée)
    guide.rebuild(n_joints=20)

    # 3. Depuis une curve existante
    guide = ChainGuide.from_existing_curve("my_crv", n_joints=15, name="rope_B")
    guide.build()
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2


# ─────────────────────────────────────────────────────────────────────────────
# Edge Extraction
# ─────────────────────────────────────────────────────────────────────────────

def get_selected_edges() -> tuple[om2.MDagPath, list[int]]:
    """
    Retourne (mesh_dag, [edge_ids]) depuis la sélection active.
    Lève ValueError si la sélection n'est pas des edges.
    """
    sel = om2.MGlobal.getActiveSelectionList()
    if sel.isEmpty():
        raise ValueError("Rien de sélectionné. Sélectionner un edge loop.")

    dag, component = sel.getComponent(0)

    if component.apiType() != om2.MFn.kMeshEdgeComponent:
        raise ValueError(
            "La sélection doit être des edges (MeshEdgeComponent)."
        )

    dag.extendToShape()
    edge_comp = om2.MFnSingleIndexedComponent(component)
    edge_ids  = list(edge_comp.getElements())  # MIntArray → list

    if len(edge_ids) < 2:
        raise ValueError(f"Au moins 2 edges requis, {len(edge_ids)} trouvé(s).")

    return dag, edge_ids


def _build_edge_vert_map(
    mesh_dag: om2.MDagPath,
    edge_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """
    Construit {edge_id: (v0, v1)} en une seule passe sur l'itérateur.
    Complexité O(total_edges), acceptable pour des meshes normaux.
    """
    target = set(edge_ids)
    result: dict[int, tuple[int, int]] = {}
    it = om2.MItMeshEdge(mesh_dag)
    while not it.isDone():
        idx = it.index()
        if idx in target:
            result[idx] = (it.vertexId(0), it.vertexId(1))
            if len(result) == len(edge_ids):
                break
        it.next()
    return result


def order_edge_loop(
    mesh_dag: om2.MDagPath,
    edge_ids: list[int]
) -> tuple[list[int], bool]:
    """
    Réordonne les edges en une séquence connectée.

    Returns
    -------
    ordered_edges : list[int]
    is_closed     : bool  – True si le loop se referme sur lui-même
    """
    e2v = _build_edge_vert_map(mesh_dag, edge_ids)

    # Adjacence : vertex → [edge_ids]
    v2e: dict[int, list[int]] = defaultdict(list)
    for eid, (v0, v1) in e2v.items():
        v2e[v0].append(eid)
        v2e[v1].append(eid)

    # Point de départ : vertex terminal (apparaît dans 1 seul edge)
    # → chaîne ouverte.  S'il n'y en a pas → boucle fermée.
    start_edge = edge_ids[0]
    is_closed  = True
    for eid, (v0, v1) in e2v.items():
        if len(v2e[v0]) == 1 or len(v2e[v1]) == 1:
            start_edge = eid
            is_closed  = False
            break

    # Traversée style linked-list
    ordered: list[int] = [start_edge]
    visited: set[int]  = {start_edge}

    current_vert = e2v[start_edge][1]  # on part du 2e vertex du 1er edge

    while len(ordered) < len(edge_ids):
        advanced = False
        for eid in v2e[current_vert]:
            if eid not in visited:
                ordered.append(eid)
                visited.add(eid)
                v0, v1     = e2v[eid]
                current_vert = v1 if v0 == current_vert else v0
                advanced   = True
                break
        if not advanced:
            break  # chaîne incomplète / edges non connexes

    if len(ordered) != len(edge_ids):
        import warnings
        warnings.warn(
            f"order_edge_loop : {len(ordered)}/{len(edge_ids)} edges ordonnés. "
            "Vérifier que les edges sont bien connectés.",
            RuntimeWarning
        )

    return ordered, is_closed


def extract_edge_midpoints(
    mesh_dag: om2.MDagPath,
    ordered_edges: list[int]
) -> list[om2.MPoint]:
    """
    Retourne le point médian world-space de chaque edge, dans l'ordre.
    """
    e2v    = _build_edge_vert_map(mesh_dag, ordered_edges)
    mesh   = om2.MFnMesh(mesh_dag)
    points = []
    for eid in ordered_edges:
        v0, v1 = e2v[eid]
        p0 = mesh.getPoint(v0, om2.MSpace.kWorld)
        p1 = mesh.getPoint(v1, om2.MSpace.kWorld)
        points.append(om2.MPoint(
            (p0.x + p1.x) * 0.5,
            (p0.y + p1.y) * 0.5,
            (p0.z + p1.z) * 0.5,
        ))
    return points


# ─────────────────────────────────────────────────────────────────────────────
# Face Extraction
# ─────────────────────────────────────────────────────────────────────────────

def get_selected_faces() -> tuple[om2.MDagPath, list[int]]:
    """
    Retourne (mesh_dag, [face_ids]) depuis la sélection active.
    Lève ValueError si la sélection n'est pas des faces.
    """
    sel = om2.MGlobal.getActiveSelectionList()
    if sel.isEmpty():
        raise ValueError("Rien de sélectionné. Sélectionner des faces.")

    dag, component = sel.getComponent(0)

    if component.apiType() != om2.MFn.kMeshPolygonComponent:
        raise ValueError(
            "La sélection doit être des faces (MeshPolygonComponent)."
        )

    dag.extendToShape()
    face_comp = om2.MFnSingleIndexedComponent(component)
    face_ids  = list(face_comp.getElements())

    if len(face_ids) < 2:
        raise ValueError(f"Au moins 2 faces requises, {len(face_ids)} trouvée(s).")

    return dag, face_ids


def _collect_face_data(
    mesh_dag: om2.MDagPath,
    face_ids: list[int],
) -> dict[int, tuple[om2.MPoint, list[int]]]:
    """
    Passe unique sur MItMeshPolygon.
    Retourne {face_id: (centroid_world, [adjacent_selected_face_ids])}

    Utilisé par order_face_strip() et extract_face_centroids()
    pour éviter de parcourir le mesh deux fois.
    """
    face_set = set(face_ids)
    data: dict[int, tuple[om2.MPoint, list[int]]] = {}

    it = om2.MItMeshPolygon(mesh_dag)
    while not it.isDone():
        fid = it.index()
        if fid in face_set:
            centroid  = it.center(om2.MSpace.kWorld)
            neighbors = [f for f in it.getConnectedFaces() if f in face_set]
            data[fid] = (centroid, neighbors)
        it.next()

    return data


def order_face_strip(
    mesh_dag: om2.MDagPath,
    face_ids: list[int],
) -> tuple[list[int], bool]:
    """
    Réordonne les faces en une bande connectée (strip).

    Attend un strip linéaire : chaque face a au plus 2 voisines sélectionnées.
    Si la bande forme un anneau (jupe), is_closed est True.

    Returns
    -------
    ordered_faces : list[int]
    is_closed     : bool
    """
    face_data = _collect_face_data(mesh_dag, face_ids)

    # Face terminale = 0 ou 1 voisine sélectionnée → chaîne ouverte
    # Pas de terminal → boucle fermée
    start     = face_ids[0]
    is_closed = True
    for fid, (_, neighbors) in face_data.items():
        if len(neighbors) <= 1:
            start     = fid
            is_closed = False
            break

    ordered: list[int] = [start]
    visited: set[int]  = {start}
    current = start

    while len(ordered) < len(face_ids):
        _, neighbors = face_data[current]
        advanced = False
        for nb in neighbors:
            if nb not in visited:
                ordered.append(nb)
                visited.add(nb)
                current = nb
                advanced = True
                break
        if not advanced:
            break

    if len(ordered) != len(face_ids):
        import warnings
        warnings.warn(
            f"order_face_strip : {len(ordered)}/{len(face_ids)} faces ordonnées. "
            "Le strip doit être connexe et sans branchement.",
            RuntimeWarning,
        )

    return ordered, is_closed


def extract_face_centroids(
    mesh_dag: om2.MDagPath,
    ordered_faces: list[int],
) -> list[om2.MPoint]:
    """
    Retourne le centroïde world-space de chaque face, dans l'ordre.
    """
    face_data = _collect_face_data(mesh_dag, ordered_faces)
    return [face_data[fid][0] for fid in ordered_faces]


# ─────────────────────────────────────────────────────────────────────────────
# Curve Creation
# ─────────────────────────────────────────────────────────────────────────────

def build_curve_from_positions(
    positions: list[om2.MPoint],
    name: str  = "chainGuide_crv",
    degree: int = 3,
    closed: bool = False,
) -> str:
    """
    Crée une NurbsCurve à travers les positions données.
    Pour un loop fermé, on duplique les premiers CVs pour assurer
    la continuité tangentielle.

    Returns
    -------
    curve_transform : str  – nom du nœud transform Maya
    """
    pts = [(p.x, p.y, p.z) for p in positions]
    n   = len(pts)
    d   = min(degree, n - 1)  # degree ne peut pas dépasser nPoints-1

    if closed and n >= d + 1:
        # Wrapping : on ajoute les d premiers points à la fin
        wrapped = pts + pts[:d]
        crv = cmds.curve(point=wrapped, degree=d)
        # closeCurve pour avoir un vrai curve périodique
        crv = cmds.closeCurve(crv, preserveShape=False,
                               replaceOriginal=True)[0]
    else:
        crv = cmds.curve(point=pts, degree=d)

    crv = cmds.rename(crv, name)
    return crv


def reverse_curve_direction(curve_name: str) -> str:
    """
    Inverse la direction d'une curve en place (reverseCurve -replaceOriginal).
    Tous les rebuilds suivants partiront de l'autre extrémité.

    Returns
    -------
    curve_name : str  – même nom (la curve est modifiée in-place)
    """
    result = cmds.reverseCurve(curve_name, replaceOriginal=True)
    # reverseCurve retourne [shape] ou [transform, shape] selon la version
    return curve_name


# ─────────────────────────────────────────────────────────────────────────────
# Joint Distribution
# ─────────────────────────────────────────────────────────────────────────────

_UP_REMAP = {
    "x": "xup", "y": "yup", "z": "zup",
    "-x": "xdown", "-y": "ydown", "-z": "zdown",
}


def distribute_joints(
    curve_name: str,
    n_joints:   int,
    chain_name: str = "chain",
    up_axis:    str = "y",
) -> list[str]:
    """
    Distribue n_joints uniformément le long de la curve
    (paramétrage en arc-length).

    Convention d'orientation (via orientJoint Maya) :
        X → le long du bone (tangente)
        Y → up_axis (world)
        Z → cross product

    Parameters
    ----------
    up_axis : "x" | "y" | "z" | "-x" | "-y" | "-z"

    Returns
    -------
    joints : list[str]  (root en [0], tip en [-1])
    """
    # ── Récupérer la curve OM2 ───────────────────────────────────────────
    sel = om2.MSelectionList()
    sel.add(curve_name)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    curve_fn     = om2.MFnNurbsCurve(dag)
    total_length = curve_fn.length()

    if total_length < 1e-6:
        raise ValueError(f"La curve '{curve_name}' a une longueur nulle.")

    # ── Calculer les positions en arc-length ─────────────────────────────
    positions: list[om2.MPoint] = []
    for i in range(n_joints):
        t       = i / max(n_joints - 1, 1)
        arc_len = t * total_length
        # Clamp pour éviter les erreurs floating-point aux extrémités
        arc_len = max(0.0, min(arc_len, total_length * (1.0 - 1e-7)))
        param   = curve_fn.findParamFromLength(arc_len)
        pos     = curve_fn.getPointAtParam(param, om2.MSpace.kWorld)
        positions.append(pos)

    # ── Créer la hiérarchie de joints ────────────────────────────────────
    joints: list[str] = []
    cmds.select(clear=True)

    for i, pos in enumerate(positions):
        # Sélectionner le joint précédent → nouveau joint devient son enfant
        if joints:
            cmds.select(joints[-1])
        jnt = cmds.joint(
            name=f"{chain_name}_jnt_{i:02d}",
            position=(pos.x, pos.y, pos.z),
        )
        joints.append(jnt)

    # ── Orienter la chaîne ───────────────────────────────────────────────
    sec_axis = _UP_REMAP.get(up_axis.lower(), "yup")
    cmds.joint(
        joints[0],
        edit=True,
        orientJoint="xyz",
        secondaryAxisOrient=sec_axis,
        children=True,
        zeroScaleOrient=True,
    )
    # Le dernier joint hérite de l'orientation du parent : on zero ses orients
    for attr in ("jointOrientX", "jointOrientY", "jointOrientZ"):
        cmds.setAttr(f"{joints[-1]}.{attr}", 0.0)

    cmds.select(clear=True)
    return joints


# ─────────────────────────────────────────────────────────────────────────────
# ChainGuide
# ─────────────────────────────────────────────────────────────────────────────

class ChainGuide:
    """
    Représente une chaîne de joints construite à partir d'une NurbsCurve source.

    La curve est la « source de vérité » : elle peut être éditée à la main
    dans Maya, puis rebuild() recrée la chaîne sans toucher à la curve.

    Metadata stockée comme attributs sur la curve :
        .cgName     (string)  – nom logique du guide
        .cgJoints   (int)     – nombre de joints
        .cgUpAxis   (string)  – axe up utilisé
    """

    GRP_NAME = "chainGuides_GRP"

    # ── Constructeur ──────────────────────────────────────────────────────

    def __init__(
        self,
        curve_name: str,
        n_joints:   int = 10,
        name:       str = "chain",
        up_axis:    str = "y",
    ) -> None:
        self.curve_name = curve_name
        self.n_joints   = n_joints
        self.name       = name
        self.up_axis    = up_axis
        self.joints:   list[str]       = []

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    def from_edge_selection(
        cls,
        n_joints: int  = 10,
        name:     str  = "chain",
        degree:   int  = 3,
        up_axis:  str  = "y",
        reverse:  bool = False,
    ) -> "ChainGuide":
        """
        Crée un ChainGuide depuis la sélection d'edges courante dans Maya.

        Parameters
        ----------
        reverse : bool
            Inverse le sens de la chaîne (root ↔ tip).
            Peut aussi être changé après coup via guide.flip().

        Exemple
        -------
        # Sélectionner un edge loop dans le viewport, puis :
        guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A")
        guide.build()

        # Si la chaîne part dans le mauvais sens :
        guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A", reverse=True)
        guide.build()
        """
        mesh_dag, edge_ids = get_selected_edges()
        ordered, is_closed = order_edge_loop(mesh_dag, edge_ids)
        positions          = extract_edge_midpoints(mesh_dag, ordered)

        if reverse:
            positions = positions[::-1]

        crv = build_curve_from_positions(
            positions,
            name   = f"{name}_src_crv",
            degree = degree,
            closed = is_closed,
        )

        # Ranger dans le groupe guides
        cls._ensure_guide_group()
        cmds.parent(crv, cls.GRP_NAME)

        # Stocker les métadonnées sur la curve pour pouvoir reconstruire
        cls._tag_curve(crv, name, n_joints, up_axis)

        return cls(curve_name=crv, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_face_selection(
        cls,
        n_joints: int  = 10,
        name:     str  = "chain",
        degree:   int  = 3,
        up_axis:  str  = "y",
        reverse:  bool = False,
    ) -> "ChainGuide":
        """
        Crée un ChainGuide depuis une sélection de faces dans Maya.

        Le centroïde de chaque face est utilisé comme point de passage
        de la curve — adapté aux strips de faces le long d'un vêtement.

        Notes
        -----
        - Le strip doit être linéaire (pas de bifurcation).
        - Pour un anneau de faces (ourlet de jupe), is_closed est détecté
          automatiquement et la curve sera périodique.

        Exemple
        -------
        # Sélectionner un strip de faces le long d'une écharpe, puis :
        guide = ChainGuide.from_face_selection(n_joints=14, name="scarf_A")
        guide.build()
        """
        mesh_dag, face_ids = get_selected_faces()
        ordered, is_closed = order_face_strip(mesh_dag, face_ids)
        positions          = extract_face_centroids(mesh_dag, ordered)

        if reverse:
            positions = positions[::-1]

        crv = build_curve_from_positions(
            positions,
            name   = f"{name}_src_crv",
            degree = degree,
            closed = is_closed,
        )

        cls._ensure_guide_group()
        cmds.parent(crv, cls.GRP_NAME)
        cls._tag_curve(crv, name, n_joints, up_axis)

        return cls(curve_name=crv, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_existing_curve(
        cls,
        curve_name: str,
        n_joints:   int = 10,
        name:       str = "chain",
        up_axis:    str = "y",
    ) -> "ChainGuide":
        """
        Utilise une curve déjà présente dans la scène comme source.
        Permet de dessiner / sculpter la curve à la main avant de builder.
        """
        if not cmds.objExists(curve_name):
            raise ValueError(f"Curve introuvable : '{curve_name}'.")
        cls._tag_curve(curve_name, name, n_joints, up_axis)
        return cls(curve_name=curve_name, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_scene_curve(cls, curve_name: str) -> "ChainGuide":
        """
        Reconstruit un ChainGuide depuis une curve déjà taguée dans la scène
        (après réouverture de fichier, par exemple).
        """
        if not cmds.objExists(f"{curve_name}.cgName"):
            raise ValueError(
                f"'{curve_name}' ne semble pas être une curve ChainGuide "
                "(attribut .cgName absent)."
            )
        name     = cmds.getAttr(f"{curve_name}.cgName")
        n_joints = cmds.getAttr(f"{curve_name}.cgJoints")
        up_axis  = cmds.getAttr(f"{curve_name}.cgUpAxis")
        return cls(curve_name=curve_name, n_joints=n_joints, name=name, up_axis=up_axis)

    # ── Build / Rebuild ───────────────────────────────────────────────────

    def build(self) -> list[str]:
        """
        Construit la chaîne de joints depuis la curve source.
        Supprime l'ancienne chaîne si elle existe.
        """
        self._cleanup_joints()
        self.joints = distribute_joints(
            curve_name = self.curve_name,
            n_joints   = self.n_joints,
            chain_name = self.name,
            up_axis    = self.up_axis,
        )
        self._organize_joints()
        return self.joints

    def rebuild(
        self,
        n_joints: Optional[int] = None,
        up_axis:  Optional[str] = None,
    ) -> list[str]:
        """
        Rebuild la chaîne.  La curve source est intacte.
        Paramètres passés remplacent ceux du guide et sont persistés.
        """
        if n_joints is not None:
            self.n_joints = n_joints
        if up_axis is not None:
            self.up_axis = up_axis

        # Mettre à jour les métadonnées sur la curve
        self._tag_curve(self.curve_name, self.name, self.n_joints, self.up_axis)

        return self.build()

    def flip(self) -> list[str]:
        """
        Inverse le sens de la curve source et rebuild la chaîne.

        Utile quand la direction est mauvaise après un from_edge_selection()
        sans avoir à tout recréer.  La curve est modifiée in-place :
        tous les rebuilds suivants partiront du bon côté.

        Exemple
        -------
        guide = ChainGuide.from_edge_selection(n_joints=12, name="scarf")
        guide.build()
        # → root en bas, mauvais sens
        guide.flip()
        # → root en haut, c'est bon
        """
        reverse_curve_direction(self.curve_name)
        return self.build()

    # ── Helpers internes ──────────────────────────────────────────────────

    def _cleanup_joints(self) -> None:
        """Supprime la chaîne existante (par la racine, cascade automatique)."""
        alive = [j for j in self.joints if cmds.objExists(j)]
        if alive:
            root = alive[0]
            # Remonter à la vraie racine si jamais elle a été reparentée
            parents = cmds.listRelatives(root, allParents=True, type="joint") or []
            root = parents[-1] if parents else root
            cmds.delete(root)
        self.joints = []

    def _organize_joints(self) -> None:
        """Place la racine sous le groupe guide."""
        if not self.joints:
            return
        root = self.joints[0]
        self._ensure_guide_group()
        current_parent = cmds.listRelatives(root, parent=True) or []
        if current_parent != [self.GRP_NAME]:
            cmds.parent(root, self.GRP_NAME)

    @classmethod
    def _ensure_guide_group(cls) -> None:
        if not cmds.objExists(cls.GRP_NAME):
            cmds.group(empty=True, name=cls.GRP_NAME)

    @staticmethod
    def _tag_curve(curve: str, name: str, n_joints: int, up_axis: str) -> None:
        """Ajoute / met à jour les attributs de métadonnées sur la curve."""
        def _ensure_attr(node, ln, typ, **kw):
            if not cmds.attributeQuery(ln, node=node, exists=True):
                cmds.addAttr(node, longName=ln, **kw)

        _ensure_attr(curve, "cgName",   "string", dataType="string")
        _ensure_attr(curve, "cgJoints", "long",   attributeType="long")
        _ensure_attr(curve, "cgUpAxis", "string", dataType="string")

        cmds.setAttr(f"{curve}.cgName",   name,     type="string")
        cmds.setAttr(f"{curve}.cgJoints", n_joints)
        cmds.setAttr(f"{curve}.cgUpAxis", up_axis,  type="string")

    # ── Propriétés ────────────────────────────────────────────────────────

    @property
    def root_joint(self) -> Optional[str]:
        return self.joints[0] if self.joints else None

    @property
    def tip_joint(self) -> Optional[str]:
        return self.joints[-1] if self.joints else None

    @property
    def is_built(self) -> bool:
        return bool(self.joints) and cmds.objExists(self.joints[0])

    def __repr__(self) -> str:
        status = f"joints={len(self.joints)}" if self.is_built else "not built"
        return (
            f"ChainGuide(name={self.name!r}, "
            f"n_joints={self.n_joints}, "
            f"up='{self.up_axis}', "
            f"curve={self.curve_name!r}, "
            f"{status})"
        )