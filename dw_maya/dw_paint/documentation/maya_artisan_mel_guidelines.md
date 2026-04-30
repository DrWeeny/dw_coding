# Maya Artisan MEL — Guide de référence (Maya 2022)

> Produit à partir de la lecture directe des scripts MEL de Maya 2022.  
> Chemin source : `C:/Program Files/Autodesk/Maya2022/scripts/others/artAttr*.mel`

---

## 1. Architecture générale

L'Artisan est composé de **quatre couches** pour chaque type d'outil :

```
ToolScript   →  setToolTo(context)  →  Properties / Values callbacks
     ↓                                         ↑
artSetToolAndSelectAttr                 invoqués implicitement
     ↓
artAttrSelected  →  artAttrCtx -e -pas "attr" `currentCtx`
```

| Couche | Rôle |
|--------|------|
| **ToolScript** | Crée le contexte si nécessaire, configure `makePaintable`, appelle `setToolTo` |
| **Properties** | Construit l'UI de la Tool Settings window |
| **Values** | Lit les valeurs courantes du contexte pour remplir l'UI |
| **Callback** | Réagit aux changements UI (opération, valeur, clamp, attribut sélectionné…) |

---

## 2. Commandes MEL principales

### `artAttrCtx`
La commande MEL **fondamentale** — crée et édite les contextes artisan de type "paint attribute".  
⚠️ Ne pas confondre avec `artAttrContext` qui est le **nom d'instance** par défaut, pas une commande.

```mel
// Créer un contexte
artAttrCtx -i1 "attrPaint.png" -whichTool "general" "artAttrContext";

// Vérifier l'existence
artAttrCtx -exists "artAttrContext";

// Éditer : changer l'attribut peint (pas = paintAttributeString)
artAttrCtx -e -pas "mesh.pSphereShape1.myAttr" "artAttrContext";

// Éditer : changer l'opération
artAttrCtx -e -selectedattroper "absolute"  "artAttrContext";  // Replace
artAttrCtx -e -selectedattroper "additive"  "artAttrContext";  // Add
artAttrCtx -e -selectedattroper "scale"     "artAttrContext";  // Scale
artAttrCtx -e -selectedattroper "smooth"    "artAttrContext";  // Smooth

// Flood (appliquer sur tous les vertices)
artAttrCtx -e -clear "artAttrContext";

// Valeur du brush
artAttrCtx -e -value 0.5 "artAttrContext";
artAttrCtx -e -minvalue 0.0 -maxvalue 1.0 "artAttrContext";

// Clamp
artAttrCtx -e -clamp "both" "artAttrContext";
artAttrCtx -e -clamplower 0.0 -clampupper 1.0 "artAttrContext";

// Query
artAttrCtx -q -attrSelected "artAttrContext";  // → "mesh.node.attr"
artAttrCtx -q -objattrArray "artAttrContext";  // → liste d'attributs paintables
artAttrCtx -q -value "artAttrContext";
artAttrCtx -q -whichTool "artAttrContext";     // → "general" / "blendShapeWeights" / etc.
```

### `makePaintable`
Enregistre un attribut dans le registre global de Maya comme "paintable".  
**Obligatoire** pour tout attribut custom avant d'utiliser l'Artisan dessus.

```mel
// Enregistrer un attribut custom
makePaintable -activate true "mesh" "myCustomAttr";

// Enregistrer un deformer standard
makePaintable -activate true "cluster" "weights";

// Activer TOUT (sauf vertex colors et skinCluster — gérés séparément)
makePaintable -activateAll true;
makePaintable -activate false "mesh" "vertexColorRGB";
makePaintable -activate false "mesh" "vertexFaceColorRGB";
makePaintable -activate false "skinCluster" "*";

// Désactiver TOUT puis activer un seul type
makePaintable -activateAll false;
makePaintable -activate true "blendShape" "baseWeights";

// Query : vérifier si un attribut est paintable
int $ok[] = `makePaintable -q "mesh" "myCustomAttr"`;
// $ok[0] == 1 si paintable
```

### `artSetToolAndSelectAttr`
Point d'entrée principal depuis l'UI. Choisit le bon tool selon le type de nœud puis appelle `artAttrSelected`.

```mel
// Signature
artSetToolAndSelectAttr(string $artCommand, string $attribute)

// Exemples
artSetToolAndSelectAttr "artAttrCtx" "cluster.cluster1.weights";
artSetToolAndSelectAttr "artAttrCtx" "blendShape.blendShape1.baseWeights";
artSetToolAndSelectAttr "artAttrCtx" "mesh.pSphereShape1.myCustomAttr";
```

**Routing interne selon `$buf[0]` (nodeType)** :
| `$buf[0]` | Action |
|-----------|--------|
| `skinCluster` | `artAttrSkinToolScript(4)` |
| `blendShape` | `artAttrBlendShapeToolScript(4)` |
| `mesh` + `vertexColorRGB` | `artAttrColorPerVertexToolScript(5)` |
| `mesh` + `vertexFaceColorRGB` | `artAttrColorPerVertexToolScript(6)` |
| tout le reste | `artAttrToolScript(4, "")` |

Termine toujours par : `artAttrSelected($artCommand, $attribute)`

### `artAttrSelected`  *(dans artAttrCallback.mel)*
Notifie le contexte du nouvel attribut sélectionné. **C'est là que se produit l'erreur "Cannot find procedure 'artAttrContext'"** si l'attribut n'est pas enregistré via `makePaintable`.

```mel
// Signature
artAttrSelected(string $artCommand, string $attribute)

// Ce que ça fait en interne (ligne 543-544) :
string $cmd = $artCommand + " -e -pas \"" + $attribute + "\" `currentCtx`";
eval($cmd);
// → artAttrCtx -e -pas "mesh.shape.attr" artAttrContext
```

> ⚠️ `$artCommand` doit TOUJOURS être `"artAttrCtx"` (le nom de commande MEL),  
> jamais `"artAttrContext"` (le nom d'instance du contexte).

---

## 3. Contextes et leurs noms

| Outil | Contexte (instance name) | `-whichTool` | ToolScript | Properties proc |
|-------|--------------------------|--------------|------------|-----------------|
| General Attribute Paint | `artAttrContext` | `"general"` | `artAttrToolScript(4, "")` | `artAttrProperties` |
| Blend Shape | `artAttrBlendShapeContext` | `"blendShapeWeights"` | `artAttrBlendShapeToolScript(4)` | `artAttrBlendShapeProperties` |
| Skin | `artAttrSkinPaintCtx` | `"skinWeights"` | `artAttrSkinToolScript(4)` | `artAttrSkinProperties` |
| nCloth | `artAttrNClothContext` | `"nClothWeights"` | `artAttrNClothToolScript(4)` | `artAttrNClothProperties` |
| Vertex Color | `artAttrColorPerVertexContext` | `"colorPerVertex"` | `artAttrColorPerVertexToolScript(5)` | `artAttrColorPerVertexProperties` |
| Custom tool | `{toolName}Context` | `"{toolName}"` | user-defined | `{toolName}Properties` + `{toolName}Values` |

> **Règle de nommage** : quand `setToolTo "myContext"` est appelé, Maya cherche implicitement les procs `{ctxName}Properties()` et `{ctxName}Values()`. Pour le General tool, c'est `artAttrContext` → `artAttrProperties` + `artAttrValues` (les "Context" est retiré).

---

## 4. Format de l'attribut paintable

Toujours sous la forme : **`"nodeType.nodeName.attributeName"`**

```
cluster.cluster1.weights
blendShape.blendShape1.paintTargetWeights
blendShape.blendShape1.baseWeights
deltaMush.deltaMush1.weights
wire.wire1.weights
mesh.pSphereShape1.vertexColorRGB          ← vertex color (outil dédié)
mesh.pSphereShape1.myCustomAttr            ← attribut custom → makePaintable obligatoire
skinCluster.skinCluster1.weightList[0].weights  ← skin (outil dédié)
```

---

## 5. Fichiers MEL et leurs rôles

```
artAttrCallback.mel
├── artAttrPaintOperation()     → change l'opération (Replace/Add/Scale/Smooth)
├── artAttrSetFiler()           → filtre par type de déformer
├── artAttrSyncCurrentAttribute()→ valide $gArtAttrCurrentAttr
├── artAttrUpdatePaintValueSlider()→ met à jour le slider de valeur
├── artAttrUpdateClamp*()       → met à jour les options de clamp
├── artAttrSelected()           → notifie le contexte du nouvel attr (ligne 543-544 !)
├── artAttrPaintCallback()      → callbacks UI pour le General paint tool
└── artAttrCallback()           → callback principal (appelle artisanBrushCallback etc.)

artAttrCreateMenuItems.mel
├── artAttrCreateMenuItems()    → construit le menu des attributs paintables
└── artSetToolAndSelectAttr()   → POINT D'ENTRÉE PRINCIPAL — route vers le bon tool

artAttrToolScript.mel
└── artAttrToolScript(int, string) → crée/active le General Attribute Paint tool

artAttrInitPaintableAttr.mel
├── artAttrValidateAttr()       → vérifie si un attr est enregistré comme paintable
├── artAttrFindFirstPaintableAttr() → trouve le 1er attr paintable sur l'objet sélectionné
├── artAttrSetPaintableNode()   → utilisé par les callbacks de changement de sélection
└── artAttrInitPaintableAttr()  → init appelée par artAttrToolScript après setToolTo

artAttrProperties.mel           → définit l'UI de la Tool Settings window (General tool)
artAttrValues.mel               → lit et affiche les valeurs courantes du contexte

artAttrBlendShape*.mel          → même structure pour blendShape
artAttrSkin*.mel                → même structure pour skinCluster
artAttrNCloth*.mel              → même structure pour nCloth
artAttrColorPerVertex*.mel      → même structure pour vertex color
```

---

## 6. Variable globale critique

```mel
global string $gArtAttrCurrentAttr;
// Exemple : "blendShape.blendShape1.paintTargetWeights"
// Persiste entre les changements de sélection.
// Mis à jour par artAttrSelected().
// Validé par artAttrSyncCurrentAttribute() et artAttrValidateAttr().
```

C'est cette variable qui explique pourquoi Maya "se souvient" du dernier attribut peint et y revient lors d'un `setToolTo "artAttrContext"` : `artAttrInitPaintableAttr()` la relit et rappelle `artAttrSelected()` avec son contenu.

---

## 7. Patterns Python / `cmds` recommandés

### Peindre un attribut de déformer standard (cluster, deltaMush…)
```python
from maya import cmds, mel

mel.eval('artSetToolAndSelectAttr "artAttrCtx" "cluster.cluster1.weights"')
```

### Peindre un attribut custom sur un mesh shape
```python
from maya import cmds, mel

map_name = "qdWearMap"
shape    = "pSphereShape1"
attr_str = f"mesh.{shape}.{map_name}"

# 1. OBLIGATOIRE : enregistrer l'attribut comme paintable
mel.eval(f'makePaintable -activate true "mesh" "{map_name}"')

# 2. Créer le contexte si besoin
if not cmds.artAttrCtx("artAttrContext", exists=True):
    cmds.artAttrCtx("artAttrContext")

# 3. Activer
mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "{attr_str}"')
```

### Flood (appliquer la valeur courante sur tous les vertices)
```python
cmds.artAttrCtx("artAttrContext", edit=True, clear=True)
```

### Changer l'opération
```python
cmds.artAttrCtx("artAttrContext", edit=True, selectedattroper="absolute")  # Replace
cmds.artAttrCtx("artAttrContext", edit=True, selectedattroper="smooth")    # Smooth
```

### Query : quel attribut est en cours de peinture
```python
attr = cmds.artAttrCtx("artAttrContext", query=True, attrSelected=True)
# → "mesh.pSphereShape1.qdWearMap"
node_type, node_name, attr_name = attr.split(".")
```

### Smooth puis revenir en Replace
```python
mel.eval('artAttrPaintOperation artAttrCtx Smooth')
cmds.artAttrCtx(cmds.currentCtx(), edit=True, clear=True)  # flood
mel.eval('artAttrPaintOperation artAttrCtx Replace')
```

---

## 8. Erreurs fréquentes et solutions

### `Cannot find procedure "artAttrContext"`
**Cause** : L'attribut n'est pas enregistré via `makePaintable`. Le pipeline MEL tente un fallback qui cherche `artAttrContext()` comme procédure MEL — elle n'existe pas.  
**Fix** : `mel.eval('makePaintable -activate true "mesh" "myAttr"')` avant `artSetToolAndSelectAttr`.

### L'artisan switch sur le dernier deformer (ex : blendShape) après un `cmds.select()`
**Cause** : `$gArtAttrCurrentAttr` contient encore l'attribut blendShape. Quand Maya recontextualise l'outil après un select, `artAttrInitPaintableAttr()` retrouve cet attribut et le rappelle.  
**Fix** : Rappeler `paint()` (qui appelle `artSetToolAndSelectAttr`) **après** le select pour écraser `$gArtAttrCurrentAttr` avec le bon attribut.

### `Cannot find procedure "artAttrContextProperties"` / `"artAttrContextValues"`
**Cause** : `setToolTo "myContext"` cherche `{ctxName}Properties()` et `{ctxName}Values()`.  
**Fix** : Utiliser `artSetToolAndSelectAttr` plutôt que `setToolTo` directement. Ou nommer son contexte selon la convention (`{toolName}Context`) et définir les procs correspondantes.

### Flood ne fait rien / artisan non actif
**Cause** : `artAttrCtx -e -clear` nécessite que l'outil artisan soit le tool actif (`currentCtx()`).  
**Fix** : S'assurer d'avoir appelé `artSetToolAndSelectAttr` avant le flood.

---

## 9. Flux complet : entrée en peinture sur un attribut custom

```
Python : mel.eval('makePaintable -activate true "mesh" "myAttr"')
    ↓
Python : mel.eval('artSetToolAndSelectAttr "artAttrCtx" "mesh.shape.myAttr"')
    ↓
artSetToolAndSelectAttr() [artAttrCreateMenuItems.mel]
    → nodeType == "mesh" → branche else (ni skinCluster, ni blendShape, ni vertexColor)
    → artAttrToolScript(4, "")
        → makePaintable -activateAll true  (+ exclusions)
        → artAttrCtx -exists "artAttrContext" ? sinon crée
        → setToolTo "artAttrContext"
            → Maya cherche "artAttrContextProperties" → trouve "artAttrProperties" ✓
            → Maya cherche "artAttrContextValues"     → trouve "artAttrValues"     ✓
        → artAttrInitPaintableAttr()
            → "mesh.shape.myAttr" dans la liste des paintables ? ← dépend de makePaintable
    → artAttrSelected("artAttrCtx", "mesh.shape.myAttr")
        → $gArtAttrCurrentAttr = "mesh.shape.myAttr"
        → eval("artAttrCtx -e -pas \"mesh.shape.myAttr\" artAttrContext")  ← ligne 543-544
        → update UI (bouton label, liste)
```

---

## 10. 🔬 Tâche future — Ramp de couleur (false coloring)

> **Objectif** : Comprendre comment le BlendShape installe sa ramp de couleur pour reproduire le même
> système sur d'autres contextes (General Attribute Paint, SoftWear…).

### Ce que fait le BlendShape

La ramp de couleur est gérée par **`artisanRampCallback.mel`**, un module générique partageable.  
Le BlendShape l'intègre en trois lignes dans sa Properties proc :

```mel
// artAttrBlendShapeProperties.mel
source "artisanRampCallback.mel";                    // 1. charger le module
// ... dans le frameLayout "Paint Weights" :
artisanCreateRamp($artCommonOpFrame, 0);             // 2. créer le widget UI
// ... à la fin de artAttrBlendShapeProperties() :
artisanRampCallback("artAttrCtx");                   // 3. brancher les callbacks
```

### Flags `artAttrCtx` liés à la ramp

Tous les états de la ramp sont stockés **directement dans le contexte** (`artAttrCtx`), pas dans une variable globale.

| Flag | Mode | Description |
|------|------|-------------|
| `-useColorRamp` | edit/query | Active/désactive la ramp (`true`/`false`) |
| `-colorRamp` | edit/query | La courbe de couleur encodée en string `"pos,r,g,b,interp; ..."` |
| `-rampMinColor` | edit/query | Couleur pour valeur 0 (bouton noir, si `$addColorTabs == 1`) |
| `-rampMaxColor` | edit/query | Couleur pour valeur 1 (bouton blanc, si `$addColorTabs == 1`) |
| `-useMaxMinColor` | edit | Active les boutons min/max color (automatique si les boutons existent) |

```mel
// Exemples de query
artAttrCtx -q -useColorRamp "artAttrContext";
artAttrCtx -q -colorRamp    "artAttrContext";
// → "1,0,0,0.5,1,1,1,0,1,1,0,0,0,0,1"
//    pos,r,g,b,interp répété pour chaque clé
```

### Format de la ramp string

```
"pos,r,g,b,interp  pos,r,g,b,interp  ..."
```

| Champ | Valeur |
|-------|--------|
| `pos` | Position sur la ramp (0.0 → 1.0) |
| `r,g,b` | Couleur RGB (0.0 → 1.0) |
| `interp` | `0` = aucune, `1` = linéaire, `2` = smooth, `3` = spline |

Presets existants dans `artisanRampCallback.mel` :
```mel
// Hot (noir → rouge → jaune → blanc)
"1,0,0,0.5,1,1,1,0,1,1,0,0,0,0,1"

// Full spectrum (arc-en-ciel)
"1,0,0,1,1,1,0.5,0,0.75,1,1,1,0,0.5,1,0,1,0,0.25,1,0,0,1,0,1"

// Greyscale
"0.5,0.5,0.5,0.5,1,1,1,1,1,1,0,0,0,0,1"
```

### Anatomie de `artisanCreateRamp(string $parent, int $addColorTabs)`

```
artisanCreateRamp($parent, 0)   → widget simplifié (pas de boutons min/max)
artisanCreateRamp($parent, 1)   → widget complet (+ boutons couleur min et max)
```

Widgets créés (noms fixes, utilisés par les callbacks) :
- `artisanRampUseRamp`      — `checkBoxGrp` enable/disable
- `artisanColorRamp`        — `gradientControlNoAttr` (la courbe visuelle)
- `artisanColorRampSlider`  — `colorSliderGrp` (couleur de la clé sélectionnée)
- `artisanColorPresetsGrid` — les 3 icônes de presets
- `artRampMinColorButton`   — bouton couleur min (si `$addColorTabs == 1`)
- `artRampMaxColorButton`   — bouton couleur max (si `$addColorTabs == 1`)

### Ce qu'il faut faire pour ajouter la ramp à un outil custom

**Dans la Properties proc** (ex: `myToolProperties()`):
```mel
source "artisanRampCallback.mel";

// À l'intérieur du frameLayout voulu :
artisanCreateRamp($myFrame, 0);   // crée l'UI

// À la fin de la proc :
artisanRampCallback("artAttrCtx");   // branche les callbacks
```

**Dans la Values proc** (ex: `myToolValues(string $toolName)`):
```mel
// La ramp est automatiquement relue par artisanRampCallback()
// si on la rappelle depuis Values — pas de proc dédiée nécessaire.
artisanRampCallback("artAttrCtx");
```

**Depuis Python pour lire/écrire la ramp directement** :
```python
from maya import cmds

ctx = cmds.currentCtx()  # ou "artAttrContext"

# Lire
enabled = cmds.artAttrCtx(ctx, query=True, useColorRamp=True)
ramp_str = cmds.artAttrCtx(ctx, query=True, colorRamp=True)

# Écrire
cmds.artAttrCtx(ctx, edit=True, useColorRamp=True)
cmds.artAttrCtx(ctx, edit=True, colorRamp="1,0,0,0.5,1,1,1,0,1,1,0,0,0,0,1")
```

---

## Section 10 — Color Ramp : Analyse complète et comparaison BlendShape vs General

### Pourquoi la ramp n'existe que dans BlendShape (et Skin/Nucleus) ?

La différence est architecturale et entièrement dans les fichiers **Properties** de chaque outil.

| Outil | Fichier Properties | `artisanCreateRamp` appelé ? | `artisanRampCallback` appelé ? |
|---|---|---|---|
| General Attribute Paint | `artAttrProperties.mel` | ❌ Non | ❌ Non |
| BlendShape Paint Weights | `artAttrBlendShapeProperties.mel` | ✅ Oui (ligne 106) | ✅ Oui (ligne 156) |
| Paint Skin Weights | `artAttrSkinProperties.mel` | ✅ Oui | ✅ Oui |
| Nucleus | `artAttrNucleusProperties.mel` | ✅ Oui | ✅ Oui |

**La ramp n'est pas une feature du contexte artisan lui-même — c'est une feature de l'UI Properties** ajoutée manuellement dans chaque outil spécialisé. Le General tool (`artAttrProperties.mel`) n'en a tout simplement pas.

---

### Anatomie de `artAttrBlendShapeProperties.mel`

```mel
global proc artAttrBlendShapeProperties()
{
    source "artisanProperties.mel";   // Base Artisan UI
    source "artisanCallback.mel";
    source "artAttrProperties.mel";   // Common Attribute Paint UI (partagé)
    source "artAttrBlendShapeCallback.mel";
    source "artisanRampCallback.mel"; // Chargement OBLIGATOIRE pour la ramp

    // ... Brush frame (artisanCreateBrushFrame) ...
    // ... Target object frame (liste des blendShape targets) ...

    // Frame "Paint Weights" — contient les contrôles communs + la ramp
    string $artCommonOpFrame = `frameLayout ... artCommonOperationFrame`;
        artAttrCreateCommonProperties();    // sliders value/opacity/etc.
        artisanCreateRamp($artCommonOpFrame, 0); // ← RAMP injectée ici avec $addColorTabs=0

    // ... Stroke, Pressure, AttrMaps, Display frames ...

    artAttrBlendShapeTargetMenu("blendShapeTargetList", "artAttrCtx");
    artAttrBlendShapeCallback("artAttrCtx");    // callbacks BlendShape-spécifiques
    artisanRampCallback("artAttrCtx");          // ← câble la ramp sur le contexte
}
```

**Points clés :**
1. `artisanCreateRamp($artCommonOpFrame, 0)` — Le `0` = `$addColorTabs`. Signifie : injecter les widgets ramp dans le frame existant, sans créer de tabs couleur additionnels.
2. `artisanRampCallback("artAttrCtx")` est appelé **après** toute la création UI — il lit les widgets créés par `artisanCreateRamp` et les synchronise avec le contexte.
3. `artAttrBlendShapeValues.mel` **ne rappelle pas** `artisanRampCallback` au refresh — la ramp est initialisée une seule fois à l'ouverture Properties, pas à chaque changement de target.

---

### `artAttrBlendShapeValues.mel` — Refresh de la Tool Settings

Le fichier Values est appelé à chaque fois que la Tool Settings window se rafraîchit (changement de contexte, ré-ouverture). Il ne contient **aucune référence à la ramp** :

```mel
global proc artAttrBlendShapeValues(string $toolName)
{
    // source des callbacks communs...
    artisanBrushValues($artCommand, $currTool);
    artBlendShapePaintValues($artCommand, $currTool);  // targets + paintable node
    artisanStrokeValues($artCommand, $currTool);
    artisanPressureValues($artCommand, $currTool);
    artisanAttrMapValues($artCommand, $currTool);
    artisanDisplayValues($artCommand, $currTool);
    // ← Pas de artisanRampValues() ni artisanRampCallback()
}
```

→ La ramp UI est donc **persistante** une fois créée (les widgets MEL survivent). Elle n'a pas besoin d'être reconstruite au refresh.

---

### Stratégie pour ajouter la ramp à un outil custom (SoftWear)

Il n'existe pas de raccourci : pour avoir la ramp dans Tool Settings sur un outil custom, il faut **créer son propre Properties proc** sur le pattern BlendShape.

**Prérequis :**
- Un contexte nommé (ex: `artSoftWearCtx`) créé via `artAttrCtx`
- Un ToolScript enregistré via `scriptCtx` (ou via `artSetToolAndSelectAttr` si on reste sur `artAttrCtx`)

**Structure minimale :**

```mel
// artSoftWearProperties.mel
global proc artSoftWearProperties()
{
    source "artisanProperties.mel";
    source "artisanCallback.mel";
    source "artAttrProperties.mel";
    source "artisanRampCallback.mel";  // obligatoire pour artisanCreateRamp

    string $currContext = `currentCtx`;
    string $currTool    = `contextInfo -c $currContext`;
    string $parent      = `toolPropertyWindow -q -location`;
    setParent $parent;

    columnLayout -adj true artSoftWear;

    frameLayout -label "Brush" -collapsable true artSoftWearBrushFrame;
        artisanCreateBrushFrame("artSoftWearBrushFrame", $currTool);
    setParent ..;

    string $opFrame = `frameLayout -label "Paint Weights" -collapsable true artSoftWearOpFrame`;
        setUITemplate -pushTemplate OptionsTemplate;
        columnLayout;
            artAttrCreateCommonProperties();
            artisanCreateRamp($opFrame, 0);  // ← la ramp
        setParent ..;
        setUITemplate -popTemplate;
    setParent ..;

    setParent ..;
    artisanCallback("artAttrCtx");
    artisanRampCallback("artAttrCtx");  // ← câblage ramp
}
```

**Enregistrement du ToolScript :**
```mel
// Enregistrer Properties + Values dans le ToolScript BlendShape existant n'est pas possible.
// Il faut passer par scriptCtx OU redéfinir les procs globales avant appel de artSetToolAndSelectAttr.
// Option la plus simple : injecter artisanCreateRamp dans artAttrCreateCommonProperties()
// via override de la proc — risqué car global.
```

---

### Alternative Python pure (sans UI Tool Settings)

Si l'objectif est uniquement d'**activer la coloration par ramp dans le viewport** sans modifier la Tool Settings, les flags `-useColorRamp` et `-colorRamp` suffisent directement sur le contexte :

```python
from maya import cmds

ctx = cmds.currentCtx()  # ou nom explicite "artAttrContext"

# Activer la color ramp
cmds.artAttrCtx(ctx, edit=True, useColorRamp=True)

# Définir une ramp (format : position,r,g,b répété)
# Exemple : noir (0) → rouge (0.5) → blanc (1)
cmds.artAttrCtx(ctx, edit=True, colorRamp="0,0,0,0, 0.5,1,0,0, 1,1,1,1")
```

⚠️ **Ces flags font partie de `artAttrCtx` (commande Maya)** — ils fonctionnent sur tout contexte artAttrCtx, qu'il soit BlendShape, General ou custom. Ils ne nécessitent **pas** l'ouverture de la Tool Settings window.

---

### Points d'investigation restants

- [ ] **Confirmer que `-useColorRamp` / `-colorRamp` fonctionnent sur `artAttrContext` (General tool) après `makePaintable`.**  
  Les flags sont documentés sur `artAttrCtx` sans restriction — à valider en pratique sur un attribut custom paintable.

- [ ] **Cycle de vie de la ramp sans Tool Settings.**  
  Quand on passe d'un attribut à l'autre via `artSetToolAndSelectAttr`, la ramp est-elle réinitialisée ? À tester.

- [ ] **Créer un `artSoftWearProperties.mel` complet pour avoir la ramp dans Tool Settings.**  
  Nécessite d'enregistrer un ToolScript custom qui pointe vers cette proc, ce qui sort du pattern `artSetToolAndSelectAttr` standard.

