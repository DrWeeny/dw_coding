# dw_paint — guide contributeur

Ce document explique comment le module est structuré et comment ajouter
un nouveau type de source de weights.

---

## Pourquoi deux hiérarchies parallèles ?

Maya a deux façons de stocker des poids par vertex :

**1. Les déformers** (`cluster`, `blendShape`, `wire`…)
Sont de vrais noeuds Maya. On peut faire `cmds.ls('cluster1')`,
`cmds.nodeType('cluster1')`, `cmds.rename(...)`. Ils héritent donc
de `MayaNode` (qui wraps l'API OpenMaya) ET de `WeightSource` (le
contrat de peinture).

```
ObjPointer          WeightSource (ABC)
    │                     │
MayaNode                  │
    │                     │
    └──── Deformer ────────┘
              │
         ┌───┴───────┬──────────┬───────┐
      Cluster  BlendShape    Wire   SkinCluster
```

**2. Les attributs nucleus** (`nClothShape.thicknessPerVertex`…)
Ne sont PAS des noeuds indépendants. Ce sont des attributs sur un noeud
`nCloth` ou `nRigid`. `cmds.createNode`, `cmds.rename` n'ont aucun sens
ici. `NClothMap` hérite donc UNIQUEMENT de `WeightSource` — sans `MayaNode`.

```
WeightSource (ABC)
      │
  NClothMap        ← wraps un noeud nCloth, expose ses attributs *PerVertex
```

**Règle :** si ce que tu veux wrapper est un noeud Maya à part entière
→ hérite de `Deformer`. Sinon → hérite directement de `WeightSource`.

---

## Le contrat WeightSource

Tout ce qui veut être paintable doit implémenter ces 4 éléments :

```python
class WeightSource(ABC):

    @property
    @abstractmethod
    def vtx_count(self) -> int:
        """Nombre de vertices du mesh affecté."""

    @abstractmethod
    def available_maps(self) -> List[str]:
        """Noms des maps disponibles sur ce noeud.
        Cluster → ['weightList']
        BlendShape → ['weightList', 'smile', 'frown']
        NClothMap → ['thickness', 'stretchMap', ...]
        """

    @abstractmethod
    def _resolve_attr(self, map_name: str) -> str:
        """Retourne le chemin Maya complet pour un map donné.
        Ex: 'cluster1.weightList[0].weights[0:381]'
        """

    @abstractmethod
    def paint(self) -> None:
        """Ouvre artisan pour le map actif."""
```

`get_weights` et `set_weights` sont implémentés dans la base à partir de
`_resolve_attr`. Tu n'as à les surcharger que si le format de stockage
est inhabituel (ex: SkinCluster per-influence).

---

## Ajouter un nouveau déformer standard

Exemple : support de `deltaMush`.

```python
# Dans dw_deformer_class.py

class DeltaMush(Deformer):
    """DeltaMush deformer."""

    def __init__(self, name, preset=None, blend_value=1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'deltaMush':
            raise ValueError(f"'{name}' is not a deltaMush deformer")

    # available_maps et _resolve_attr hérités de Deformer → rien à faire
    # si le format weightList standard convient.

    # Optionnel : méthodes spécifiques au deltaMush
    def set_smoothing_iterations(self, n: int) -> None:
        cmds.setAttr(f'{self.node_name}.smoothingIterations', n)


# Enregistrer dans la factory en bas du fichier :
_DEFORMER_CLASSES: Dict[str, type] = {
    'cluster':     Cluster,
    'softMod':     SoftMod,
    'blendShape':  BlendShape,
    'wire':        Wire,
    'skinCluster': SkinCluster,
    'deltaMush':   DeltaMush,   # ← ajouter ici
}

# Enregistrer dans _ARTISAN_ATTRS dans weight_source.py :
_ARTISAN_ATTRS: Dict[str, str] = {
    ...
    'deltaMush': 'deltaMush.{node}.weights',   # ← ajouter ici
}
```

C'est tout. `make_deformer('deltaMush1')` retournera automatiquement
un `DeltaMush`. `resolve_weight_sources` le trouvera via l'historique.

---

## Ajouter une nouvelle source non-déformer

Exemple : un noeud custom avec des attributs `*PerVertex` maison.

```python
# Nouveau fichier : dw_maya/dw_custom/dw_mynode_class.py

from dw_maya.dw_paint.protocol import WeightSource, WeightList
from maya import cmds

class MyNodeMap(WeightSource):
    """Maps per-vertex d'un noeud custom."""

    def __init__(self, node_name: str, mesh_name: str):
        if cmds.nodeType(node_name) != 'myCustomNode':
            raise ValueError(...)
        super().__init__(node_name, mesh_name)

    @property
    def vtx_count(self) -> int:
        return cmds.polyEvaluate(self._mesh_name, vertex=True)

    def available_maps(self) -> list:
        return ['densityMap', 'rigidnessMap']

    def _resolve_attr(self, map_name: str) -> str:
        return f'{self._node_name}.{map_name}PerVertex'

    def paint(self) -> None:
        # ouvrir artisan via MEL ou laisser non supporté
        from maya import mel
        mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "...'  )
```

Puis brancher dans `resolve_weight_sources` :

```python
# Dans weight_source.py, dans resolve_weight_sources()

if mode in ('all', 'custom'):
    from dw_maya.dw_custom.dw_mynode_class import MyNodeMap
    custom_nodes = cmds.ls(type='myCustomNode') or []
    for n in custom_nodes:
        if cmds.isConnected(...):   # vérifier que c'est lié au mesh
            sources.append(MyNodeMap(n, mesh))
```

---

## Fichiers clés et leurs rôles

```
dw_paint/
  protocol.py          ← WeightSource ABC — lire en premier
  weight_source.py     ← resolve_weight_sources, apply_operation (API publique)
  core.py              ← fonctions pures : smooth, modify, remap
  operations.py        ← mirror, vector, radial

dw_deformers/
  dw_deformer_class.py ← Deformer + sous-classes + make_deformer()

dw_nucleus_utils/
  dw_ncloth_class.py   ← NClothMap

dw_maya_nodes/
  obj_pointer.py       ← ObjPointer (wraps MObject/MDagPath)
  maya_node.py         ← MayaNode (attributs Pythoniques)
  attr.py              ← MAttr (get/set/connect un attribut)
```

---

## Points d'attention connus

**SkinCluster** : `available_maps()` retourne les influences, mais
`_resolve_attr` pour un nom d'influence retourne le même path que
`weightList`. Le support per-influence est à compléter.

**NClothMap et MayaNode** : `NClothMap` n'hérite pas de `MayaNode`,
donc `sources[n].translateX` plantera si la source est un `NClothMap`.
Si tu as besoin du noeud Maya sous-jacent : `cmds.ls(src.node_name)`.

**mesh_name dans Deformer** : passé comme `''` au `WeightSource.__init__`
puis résolu via property. C'est voulu (la résolution nécessite Maya),
mais surprenant à la lecture.
