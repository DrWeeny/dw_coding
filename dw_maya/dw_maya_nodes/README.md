# maya_nodes

Pythonic, PyMel-style wrappers for Maya nodes built on top of `maya.cmds`.  
Keeps the **performance of cmds** while giving you **attribute dot-access, connections, presets and a type registry**.

---

## Module layout

```
maya_nodes/
├── __init__.py          # re-exports ObjPointer, MAttr, MayaNode
├── obj_pointer.py       # ObjPointer — stable MObject / UUID-based node pointer
├── attr.py              # MAttr      — single attribute wrapper
├── maya_node.py         # MayaNode   — high-level node wrapper (inherits ObjPointer)
└── tests/
    └── test_maya_node.py
```

---

## ObjPointer — stable node identity

`ObjPointer` is the base class.  It stores a Maya **MObject** (OpenMaya 2) pointer
so that the wrapper survives node renames inside Maya — the Python object always
knows the current name.

```python
cube = MayaNode('pCube1')
cmds.rename('pCube1', 'myCube')
print(cube.node)   # → 'myCube'  (still valid)
```

`self.__dict__` is used **directly** throughout to set internal state
(`node`, `item`, `_geo_index` …).  This bypasses `__setattr__` / `__getattr__`
and prevents infinite recursion when the class itself is being set up.

---

## MayaNode — constructor signatures

### 1 — Wrap an existing node

```python
cube = MayaNode('pCube1')
```

Stores a pointer to the node.  Works with transforms, shapes, deformers,
joints — anything Maya considers a DAG or DG node.

---

### 2 — Create a new node

```python
loc = MayaNode('myLocator', 'locator')
```

When the second argument is a **string node-type**, the node is created
(`cmds.createNode`) and the wrapper points to it immediately.

---

### 3 — Apply / load a preset dict

```python
preset = {
    'pCube1': {
        'nodeType':   'transform',
        'translateX': 100,
        'rotateY':    1.0,
        'scaleX':     0.5,
    }
}
cube = MayaNode('pCube1', preset, blend_value=0.5)
```

| Field | Meaning |
|---|---|
| `nodeType` | **Required.** Maya node type. Node is created if it doesn't exist yet. |
| Any attr name | Set via `cmds.setAttr`. Supports `int`, `float`, `bool`, `str`. |
| `blend_value` | `1.0` = full replacement. `0.5` = blend 50 % toward the preset value. |

#### Special tokens

String values that start with `$` are evaluated at load time:

| Token | Expands to |
|---|---|
| `$RFSTART` | Current render frame start |
| `$RFEND` | Current render frame end |
| *(extensible)* | Add entries to `constants.SPECIAL_TOKENS` |

#### Connections in presets

*(Planned / partial)* — A value of the form `"nodeName.attr"` will be
interpreted as a `connectAttr` rather than a `setAttr`.

#### Animation curves

*(Planned)* — Preset dicts can carry `animCurve` sub-keys that are
reconstructed and connected on load.

---

## Transform / shape indexing

A Maya mesh has two nodes: a **transform** (`pCube1`) and a **shape**
(`pCubeShape1`).  `MayaNode` wraps both and selects the right one
automatically.

| Expression | Result |
|---|---|
| `cube.node` | Shape by default (`item = 1`) |
| `cube[0].node` | Force transform (`item = 0`) |
| `cube[1].node` | Force shape (`item = 1`) |
| `cube.tr` | Always the transform string |
| `cube.sh` | Always the shape string |

For nodes that have **no transform** (deformers, DG nodes) `tr` and `sh`
return the same value.

---

## Attribute access — `__getattr__` / `__setattr__`

```python
cube = MayaNode('pCube1')

# --- read ---
cube.tx              # → MAttr('pCube1', 'tx')   short name works
cube.translateX      # → MAttr('pCube1', 'translateX')  long name works
cube.tx.getAttr()    # → float value
repr(cube.tx)        # → "<<double>>\n    0.0"

# --- write ---
cube.tx = 5          # cmds.setAttr('pCube1.translateX', 5)
cube.tx.setAttr(5)   # identical

# --- shape-priority rule ---
# 'visibility' exists on both transform and shape.
# Default (item=1) → uses shape.
cube.visibility
# Force transform:
cube[0].visibility
```

**Auto index-switching** — if you access an attribute that only exists on the
*other* node, the wrapper silently switches `item` for you:

```python
cube = MayaNode('pCube1')   # item = 1 (shape)
cube.tx                     # 'tx' not on shape → switches item to 0 (transform)
                            # → MAttr('pCube1', 'tx')
```

A warning is logged when an attribute exists on **both** nodes so you always
know which one is being used.

---

## `listAttr` — query available attributes

Mirrors the Maya command style — positional **or** keyword argument:

```python
cube.listAttr()              # all attrs from both tr + sh (union, deduplicated)
cube.listAttr('tx')          # ['tx'] if found, [] if not — also switches item
cube.listAttr(attr='tx')     # identical (keyword form)
cube.listAttr(node_index=0)  # all transform attrs only
cube.listAttr(node_index=1)  # all shape attrs only

# Pass-through to cmds.listAttr flags:
cube.listAttr(keyable=True)
cube.listAttr(shortNames=True)
```

Both long **and** short names are always included in the internal cache,
so `'tx'` and `'translateX'` are equally discoverable.

---

## MAttr — attribute wrapper

`MAttr` is returned by every attribute access on `MayaNode`.

```python
tx = cube.tx          # MAttr('pCube1', 'translateX')

tx.getAttr()          # cmds.getAttr equivalent
tx.setAttr(5)         # cmds.setAttr equivalent
repr(tx)              # "<<double>>\n    5.0"
str(tx)               # "5.0"

# Operators
tx == 5.0             # True / False  (value comparison)
tx > 3.0              # True
bool(tx)              # False if value is 0, True otherwise

# Connections
cube.tx >> sphere.tx  # connectAttr (rshift)
cube.tx << sphere.tx  # connectAttr reversed (lshift)

# Compound / array attributes
cluster = MayaNode('cluster1')
cluster.weightList[0].weights.getAttr()
# equivalent to: cmds.getAttr('cluster1.weightList[0].weights[:]')

# Slicing
cluster.weightList[0].weights[0:10].getAttr()
```

---

## Inheritance and the type registry

`MayaNode` is designed to be **subclassed**.  Specialised classes
(`Cluster`, `SkinCluster`, `BlendShape` …) inherit it and add domain-
specific methods.  They register themselves so `lsNode()` and
`make_deformer()` can return the richest available class automatically:

```python
# deformer_class.py
class Cluster(Deformer):   # Deformer inherits MayaNode
    ...

node_registry.register_type('cluster', Cluster)
```

```python
# usage
from dw_maya.dw_lsNode import lsNode

lsNode('cluster1')          # → Cluster instance
lsNode(type='blendShape')   # → [BlendShape, BlendShape, …]
lsNode('pCube1')            # → MayaNode  (fallback)
```

The registry lookup order is:
1. Exact Maya node-type match (`'cluster'` → `Cluster`)
2. Inherited type walk (most-specific first)
3. Condition-based match (e.g. mesh with nCloth connection → `NClothMap`)
4. Fallback → `MayaNode`

---

## Quick-reference cheat sheet

```python
from dw_maya.dw_maya_nodes import MayaNode

n = MayaNode('pCube1')

n.node          # current node string (shape by default)
n[0].node       # transform
n[1].node       # shape
n.tr            # transform string
n.sh            # shape string
n.nodeType      # Maya node type of the shape

n.tx            # MAttr — short name
n.translateX    # MAttr — long name
n.tx.getAttr()  # read value
n.tx = 5        # write value
n.tx.setAttr(5) # write value (MAttr style)
n.tx >> n.ty    # connect tx → ty
n.tx.listConnections()          # list connections on this attr
n.tx.disconnectAttr()           # disconnect all

n.listAttr()                    # all attrs (tr + sh)
n.listAttr('tx')                # ['tx'] or []
n.listAttr(node_index=0)        # transform attrs only
n.listAttr(keyable=True)        # pass-through to cmds.listAttr

n.addAttr('myFloat', 1.0, 'double')   # add custom attr → MAttr
n.getAttr('tx')                        # same as n.tx
n.attrPreset()                         # dict snapshot of all attr values
n.attrPreset(node=0)                   # transform only
n.attrPreset(in_channelbox=True)       # channelbox attrs only

n.listHistory(type='skinCluster')      # filtered history
n.parentTo(other_node)                 # parent transform
n.rename('newName')                    # rename tr + sh correctly
n.getNamespace()                       # 'myNS' or ':'
n.stripNamespace()                     # name without namespace

n.saveNode('/path/', 'preset')         # save attr preset to JSON
n.loadNode(preset_dict, blend=0.5)     # load / blend preset
```

---

## Running the test suite (inside Maya)

```python
import importlib
import dw_maya.dw_maya_nodes.tests.test_maya_node as t
importlib.reload(t)
t.run()
```

All tests create and clean up their own temporary nodes.  
Expected output:

```
============================================================
  MayaNode / MAttr Test Suite
============================================================
  [PASS]  tr/sh resolution
  [PASS]  short name attr access (tx)
  ...
============================================================
  Result: 19/19 passed  |  All good!
============================================================
```

