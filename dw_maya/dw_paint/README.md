# dw_paint — guide utilisateur

Ce module donne accès aux poids par vertex (weights) de tous les déformers
et noeuds nucleus d'un mesh, avec une interface identique quel que soit le
type de noeud.

## Point d'entrée unique

```python
from dw_maya.dw_paint.weight_source import resolve_weight_sources, apply_operation
```

`resolve_weight_sources(mesh)` retourne la liste de tout ce qui peut être
peint sur un mesh. Tu n'as pas besoin de connaître les classes internes.

---

## Cas d'usage courants

### Lister ce qui est paintable sur un mesh

```python
sources = resolve_weight_sources('pSphere1')
for s in sources:
    print(s)
# <Cluster   node='cluster1'    mesh='pSphere1' map=None>
# <BlendShape node='blendShape1' mesh='pSphere1' map=None>
# <NClothMap  node='nClothShape1' mesh='pSphere1' map=None>
```

### Lire / écrire des weights

```python
src = sources[0]          # Cluster dans cet exemple

# Cluster n'a qu'un seul map → auto-résolu, pas besoin de use_map()
weights = src.get_weights()
src.set_weights([1.0] * src.vtx_count)
```

### Choisir un map quand il y en a plusieurs

Certains noeuds exposent plusieurs maps : `BlendShape` (une par target),
`SkinCluster` (une par influence), `NClothMap` (thickness, stretchMap…).

```python
bs = sources[1]                    # BlendShape
bs.available_maps()
# ['weightList', 'smile', 'frown']

bs.use_map('smile').get_weights()  # chainable
bs.use_map('weightList').set_weights([1.0] * bs.vtx_count)

nc = sources[2]                    # NClothMap
nc.available_maps()
# ['thickness', 'stretchMap', 'bendResistance', ...]
nc.use_map('thickness')
nc.get_weights()
```

### Appliquer une opération

Toutes les opérations fonctionnent de la même façon quelle que soit la
source (Cluster, BlendShape, NClothMap…).

```python
apply_operation(src, 'flood',  value=0.5)
apply_operation(src, 'smooth', iterations=3, factor=0.5)
apply_operation(src, 'mirror', axis='x')
apply_operation(src, 'vector', direction='y+')
apply_operation(src, 'radial', radius=5.0, falloff='smooth')
```

### Ouvrir l'outil de peinture Maya

```python
src.use_map('smile')
src.paint()   # ouvre artisan pour le map actif
```

### Filtrer par type de backend

```python
resolve_weight_sources('pSphere1', mode='deformer')  # cluster, blendShape…
resolve_weight_sources('pSphere1', mode='nucleus')   # nCloth, nRigid
resolve_weight_sources('pSphere1', mode='vtxColor')  # vertex color alpha
```

### Accéder directement à un déformer connu

Si tu connais déjà le nom du noeud, tu n'as pas besoin de `resolve_weight_sources`.

```python
from dw_maya.dw_deformers.dw_deformer_class import make_deformer

cluster = make_deformer('cluster1')
cluster.smooth_weights(iterations=2)
cluster.mirror_weights(axis='x')
cluster.paint()
```

---

## Deux backends, une même interface

| Ce que tu vois dans Maya | Classe Python   | Ce que c'est vraiment |
|--------------------------|-----------------|----------------------|
| `cluster1`, `blendShape1`… | `Deformer` (et sous-classes) | Un **noeud Maya** (`cmds.ls`, `cmds.nodeType` fonctionnent) |
| `nClothShape1` | `NClothMap` | Un groupe d'**attributs** sur un noeud nCloth — pas un noeud indépendant |

Cette distinction explique pourquoi `NClothMap` n'a pas de `translateX` ou
de `rename()` : ce n'est pas un noeud, c'est une vue sur des attributs.

---

## Ce que ce module ne fait PAS

- `SkinCluster` est disponible via `make_deformer` mais le support
  per-influence est partiel. Pour les workflows skinning complexes,
  utiliser `dw_skincluster` directement.
- Pas de support des noeuds `hairSystem` comme source de weights.
- Les vertex colors (mode `vtxColor`) sont en lecture seule pour l'instant.
