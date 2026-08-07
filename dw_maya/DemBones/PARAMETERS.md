# DemBones parameters - what they do and what to set them to

Reference for the solve parameters exposed by the DemBones tool (`wgt_params.py`
-> `dem_cmds.build_args`). Flag names are the ones passed to `DemBones.exe`;
every argument is emitted as a single `flag=value` token because the Windows
parser requires the `=` form.

The advice below separates two things on purpose:

- **What the flag does** - the solver's own semantics.
- **What to set it to** - what was measured on this pipeline (cloth sim and
  costume solves), which is a narrower claim.

---

## 1. The mental model (read this first, the values make no sense without it)

DemBones runs an **alternating least-squares** loop. One global iteration
(`nIters`) does two sub-solves in turn:

1. **Transform solve** (`nTransIters` sub-iterations) - for each bone, fit the
   rigid/affine transform that best explains the motion of the vertices it
   currently influences.
2. **Weight solve** (`nWeightsIters` sub-iterations) - for each vertex, pick the
   `nnz` bones whose *current* transforms best explain that vertex's motion, and
   fit their weights.

Two consequences drive almost every parameter choice:

- **The two sub-solves feed each other.** Bad weights give bad transforms, which
  give worse weights. Convergence is about the *alternation*, not about either
  sub-solve being run harder.
- **Weights are the only coupling between a joint and the solver.** A bone with
  no weights gets no data in the transform solve, so it stays at bind; a bone
  frozen at bind explains nothing that moves, so the weight solve never picks
  it. It is dead for the whole solve. This is the mechanism behind "half my
  joints came back static" - see `bind_mesh_to_joints` and
  `removeUnusedInfluence`.

Total sub-solve work is roughly `nIters * (nTransIters + nWeightsIters)`. Push
`nIters` before pushing the sub-iterations.

---

## 2. Input / output flags (set by the tool, listed for log reading)

| Flag | Meaning |
|---|---|
| `-a=<path.abc>` | The **animated** cache - the deformation being decomposed. |
| `-i=<path.fbx>` | The **rest** geometry, optionally carrying bones + skin (the seed). |
| `-o=<path.fbx>` | Output FBX: solved skeleton, skinCluster weights, animation. |

The first line of every generation `.log` is the exact command, so a failed
solve can be replayed by hand from a shell.

---

## 3. Common parameters

### `nBones` (`-b`) - number of bones to solve for

Default **30**. Range 1-4096.

How many rigid segments the deformation is decomposed into. This is the single
biggest quality/cost dial: more bones fit better, produce a heavier skinCluster,
and take longer.

**Advice**

- Cloth / curtain / cape from scratch: start at **20-40**. Judge on playback,
  not on RMSE.
- Doubling bones does not halve error - returns fall off fast once the bone
  count exceeds the number of genuinely independent moving regions in the
  motion. If 60 bones look like 30, the motion is the limit, not the budget.
- Downstream cost is real: every bone is a joint in the scene, a column in the
  skinCluster, and an animation curve set. A 200-bone solve on a hero costume is
  a publishing problem, not a solving problem.
- **Ignored when "Use existing rig" is on** - `build_args` drops `-b` entirely so
  DemBones takes the bone count from the supplied skeleton. The spinbox is
  greyed out in that mode for exactly this reason.

### `nnz` (`--nnz`) - max influences per vertex

Default **8**. Range 1-32.

The number of non-zero weights allowed per vertex - the sparsity budget of the
weight solve.

**Advice**

- Leave at **8**. Maya's skinCluster and most game engines cap there anyway, and
  going above it means the weights get pruned later by something that does not
  know what it is throwing away.
- **4** if the target is a game engine with a 4-influence budget. Solve at the
  budget, do not solve at 8 and prune afterwards - the solver will distribute
  differently if you tell it the truth up front.
- When seeding with your own skin, `maximumInfluences` on the seed bind must
  match `nnz`. Maya's default of 5 against `nnz=8` hands the solve a seed
  narrower than its own budget. `bind_mesh_to_joints` enforces this.

### `nIters` (`-n`) - global iterations

Default **30**. Range 1-10000.

How many times the transform/weight alternation runs.

**Advice**

- From scratch (no rig): **30** is a reasonable default; **50-100** for a hard
  cloth solve where the first result still swims.
- **Use existing rig: keep it low (10-20).** Your joint placement has already
  done the work the alternation would otherwise have to discover. A high
  `nIters` here mostly buys solve time.
- **Animation only: keep it low (5-10).** With weights frozen there is no
  alternation left to converge - only the transform solve runs, and it converges
  in a handful of passes.
- `tolerance`/`patience` will stop the solve early anyway, so an over-large
  `nIters` is a ceiling rather than a cost. Watch the log: if it exits on
  patience well before `nIters`, raising `nIters` changes nothing.

### `nTransIters` - transform sub-iterations per global iteration

Default **5**. Range 0-1000.

**Advice**

- **5** is fine for nearly everything. **0** is a special value: it means *do not
  solve transforms at all* - a weights-only solve against the transforms you
  supplied.
- Animation-only mode is the case where this deserves room: **5-10**, since it
  is the only solve left running.
- Raising it above ~10 in a normal solve is usually the wrong knob - it
  over-fits the transforms to weights that are still wrong. Raise `nIters`
  instead.

### `nWeightsIters` - weight sub-iterations per global iteration

Default **3**. Range 0-1000.

**Advice**

- **3** is the working default. **0** means *keep the weights you were given* -
  a transforms-only solve.
- With a custom rig, keep this **> 0** unless you explicitly want anim-only:
  your skin is the *seed*, not the answer. The validated custom-joint workflow
  is `nWeightsIters > 0` with `bindUpdate = 0`.
- Set it to **0** deliberately when the weights are authored and must survive -
  a hand-painted costume skin you are only re-animating.

---

## 4. Advanced parameters

### `nInitIters` - initialization iterations

Default **10**. Range 0-1000.

Iterations of the initial bone clustering, before the main loop starts. This is
where bones get *placed* when you did not supply any.

**Advice**

- From scratch: **10-20**. This is cheap relative to the main solve and a bad
  init is very hard to recover from later - if bones land in the wrong regions,
  the alternation tends to keep them there.
- **Use existing rig: 0.** The bones already exist and are placed where you want
  them; re-clustering is at best wasted and at worst moves them.
- Forced to 0 (and locked) by animation-only mode.

### `weightsSmooth` - Laplacian smoothing on the weights

Default **1e-4**. Range 0.0-1.0.

Pulls each vertex's weights toward its neighbours'. Fights the speckle the
sparse weight solve produces on dense meshes.

**Advice**

- **1e-4** is the shipped default and a good starting point.
- Raise to **1e-3 .. 1e-2** when the solved skin shows isolated vertices jumping
  to a different dominant influence (visible as sparkle or crumpling on a smooth
  region). Cloth on a dense mesh is the usual case.
- Too high smears weights across bones that should be independent, and the fit
  goes soft - detail disappears, folds round off. If raising it makes the result
  look "lazy", you have gone too far.
- This value is not scale-free in a friendly way. Change it by an order of
  magnitude at a time, not by increments.

### `weightsSmoothStep` - step size of the smoothing solve

Default **1.0**. Range 0.0-100.0.

**Advice**

- Leave at **1.0**. This is a numerical stability knob, not a look knob.
- Lower it (**0.5**, **0.1**) only if a high `weightsSmooth` makes the solve
  diverge or the log shows the error climbing. Slower, more stable.

### `transAffine` - bone **translation** affinity soft constraint

Default **10.0**. Range 0.0-1000.0.

Upstream doc string: *"Translations affinity soft constraint"*. This is **not**
about rigid-vs-affine bone transforms - DemBones bones are rigid by
construction (rotation + translation via SVD, see section 8). It is a
regularization on where a bone's **translation** is allowed to sit: it anchors
each bone to the region of skin it actually influences.

The reason it exists: a bone whose weights are few, weak, or spread thin has an
ill-conditioned translation - many translations explain the data about equally
well, so it can drift or jitter frame to frame. The soft constraint pulls it
back toward the vertices that justify it. **Higher = more strongly anchored.**

**Advice**

- **10.0** (the default) is the right setting for nearly everything. This is a
  stability knob, not a look knob.
- **Raise it (50-100)** if solved joints wander, pop, or jitter - particularly
  low-weight bones out at the edge of the mesh, or on a solve with a high
  `nBones` where each bone owns few vertices.
- **Lower it** only if bones seem unable to follow large translations they
  clearly should be following. Note this pipeline's cloth solves translate
  bones hard (203 units on the validated curtain), and the default handled it.
- Do not reach for this to fix joint scale or shear. It cannot - see the note
  in section 8.

### `transAffineNorm` - p-norm on that constraint

Default **4.0**. Range 0.0-100.0.

The p-norm used to weight the translation-affinity constraint per vertex.
Higher p concentrates the constraint on the vertices a bone influences *most
strongly* and effectively ignores its weakly-weighted ones.

**Advice**

- Leave at **4.0**. Change it only after `transAffine` has failed, and only if
  the instability is localised to a few bones (raise it, so each bone is judged
  by its core vertices) rather than spread across all of them (raise
  `transAffine` instead).

> **Correction note.** The tooltip in `wgt_params.py` describes `transAffine` as
> "Allowed affine (non-rigid) bone transformation. 0 = pure rigid bones". That
> is wrong on both counts - the flag concerns translations, and the bones are
> always rigid. The tooltip needs fixing.

### `bindUpdate` - how the bind pose is updated

Default **0**. Values: `0` keep bind, `1` update bind, `2` regroup root.

**Advice**

- **0 - keep bind.** This is the correct value for every workflow in this tool,
  and the only one validated here. It preserves your joint placement, which is
  the whole point of feeding a rig in.
- **1 - update bind** lets the solver move the rest-pose joint positions to
  better fit the motion. It gives a tighter fit and it *invalidates your rig*:
  the joints come back somewhere else, so anything relying on their bind
  placement (a control layer, an existing skin, a published skeleton) no longer
  lines up. Only defensible for a throwaway from-scratch solve where the joint
  cloud has no meaning outside the solve.
- **2 - regroup root** is untested here.
- Forced to 0 (and locked) by animation-only mode.

### `tolerance` - convergence threshold

Default **0.001**. Range 0.0-1.0.

The solve stops early once the RMSE improvement per iteration drops below this.

**Advice**

- **0.001** is fine. This is a *relative improvement* threshold, so it does not
  need retuning per asset scale.
- Lower it (**1e-4**, **1e-5**) to squeeze out the last of the fit on a hero
  solve where you have time to spend, and raise `nIters` at the same time -
  otherwise the iteration cap stops you first and the tolerance never applies.
- Raise it (**0.01**) for a fast look-see pass while dialling `nBones`.

### `patience` - stalled iterations tolerated

Default **3**. Range 0-100.

How many consecutive iterations may fail to beat `tolerance` before the solve
gives up.

**Advice**

- **3** is a good default: it rides out the occasional flat iteration without
  burning the whole budget on a solve that has plateaued.
- Raise to **5-10** if the log shows solves stopping early on a result you can
  see is still improving - alternating solves do sometimes stall for an
  iteration or two before dropping again.
- **0** means stop at the first stalled iteration. Fast and usually premature.

---

## 5. Presets by workflow

### A. From scratch - no rig, solve everything

The classic SSDR case: a cloth sim cache in, a joint cloud + skin out.

```
nBones            30      (20-40; dial on playback)
nnz               8
nIters            30
nTransIters       5
nWeightsIters     3
nInitIters        10
weightsSmooth     1e-4
weightsSmoothStep 1.0
transAffine       10
transAffineNorm   4
bindUpdate        0
tolerance         0.001
patience          3
```

### B. Use existing rig - your joints, solved weights and animation

Static rig in, animated rig out. `-b` is dropped automatically.

```
nBones            (ignored - comes from the skeleton)
nnz               8       (and maximumInfluences=8 on the seed bind)
nIters            10-20   (placement already did the work)
nTransIters       5
nWeightsIters     3       (must be > 0; your skin is the seed, not the answer)
nInitIters        0       (do not re-cluster placed bones)
bindUpdate        0       (keep your placement)
```

Preconditions that are not parameters but fail like parameters:

- The init FBX must contain **exactly** the influence joints. `export_target_fbx`
  handles this (`FBXExportIncludeChildren` off, non-influence ancestors bound at
  weight 0) - a mismatch is the `"Scene has more joints than skinCluster has"`
  exit 1.
- The seed bind must use `removeUnusedInfluence=False`, or Maya prunes joints at
  bind time and they come back static.

### C. Animation only - keep the weights, solve the transforms

Ticked in the source panel; `ParamsPanel.set_anim_only` forces and locks the
three zeros.

```
nWeightsIters     0       (locked - freeze the supplied weights)
nInitIters        0       (locked)
bindUpdate        0       (locked)
nTransIters       5-10    (the only solve left - give it room)
nIters            5-10    (no alternation left to converge)
nBones / nnz / weightsSmooth*   unused
```

### D. Weights only - keep the transforms, solve the weights

The mirror case, not a UI mode - just set it:

```
nTransIters       0
nWeightsIters     3-5
nIters            10-20
```

Useful for re-solving weights against a skeleton whose animation you already
trust.

---

## 6. Symptom -> parameter

| What you see | Look at |
|---|---|
| Fit is loose everywhere, motion is mushy | `nBones` up, then `nIters` up |
| More bones changed nothing | The motion has fewer independent regions than bones - stop raising it |
| Solve stops way before `nIters` | Working as intended; `tolerance` down / `patience` up only if still improving |
| Speckled weights, single vertices on the wrong bone | `weightsSmooth` up an order of magnitude |
| Result went soft and detail disappeared | `weightsSmooth` back down |
| Bones jitter, pop, or wander (usually low-weight ones) | `transAffine` up (50-100); if only a few bones, `transAffineNorm` up |
| Joints come back with scale or shear | Not from the solve - DemBones bones are rigid. Look at the FBX round trip or the seed rig |
| Half the joints have no animation | Not a parameter - unweighted joints are dead to the solve. Check `removeUnusedInfluence=False` and `maximumInfluences == nnz` on the seed bind |
| Joints came back in the wrong place | `bindUpdate` is not 0 |
| Exit 1, "Scene has more joints than skinCluster has: N/M" | Not a parameter - the init FBX carries non-influence joints |
| Exit 1, no obvious cause | Read the `.log` beside the generation; line 1 is the exact command |

---

## 7. Practical workflow

1. **Dial `nBones` first, cheap.** `tolerance=0.01`, `nIters=10`, everything else
   default. Three or four solves at different bone counts, judged on playback.
2. **Then quality.** Put `tolerance` and `nIters` back, solve once properly.
3. **Then artefacts.** Only now touch `weightsSmooth` / `transAffine`, one at a
   time, an order of magnitude at a time.
4. **Judge across the range, never at the rest frame.** At the bind pose every
   weighting reproduces the rest shape - a rest-frame comparison validates the
   bind matrices and says nothing at all about the weights.
5. Every generation writes its params to a sidecar `.json`; "Restore params" in
   the generations panel puts them back in the UI. Use it instead of keeping
   notes - a generation you cannot reproduce is a generation you cannot iterate
   on.

---

## 8. What the solver actually does (bone repartition)

Source of truth: `include/DemBones/DemBones.h` upstream. DemBones implements
*Smooth Skinning Decomposition with Rigid Bones* (Le & Deng, SIGGRAPH Asia 2012),
with the weight-smoothing refinement from *Robust and Accurate Skeletal Rigging
from Mesh Sequences* (Le & Deng, SIGGRAPH 2014).

### Initialization - how bones get distributed (`init()`, `nInitIters`)

**LBG-VQ** - Linde-Buzo-Gray vector quantization, i.e. k-means with iterative
cluster splitting. When neither weights nor transforms are supplied:

1. Start from a single cluster covering the mesh.
2. **Split** the cluster with the worst reconstruction error into two.
3. Run `nInitIters` refinement rounds: compute each bone's transform from its
   current label set, then **reassign every vertex to the bone whose rigid
   transform best explains that vertex's motion across the whole sequence**.
4. Prune bones that ended up with too few vertices.
5. Repeat from 2 until the cluster count reaches `nBones`.

Two things follow from this. The clustering metric is **motion similarity over
the full cache, not proximity** - vertices land on the same bone because they
move alike, not because they are near each other, so a bone can legitimately own
disconnected patches. And init produces a **hard labelling**: one bone per
vertex, rigid. The smooth, sparse, `nnz`-influence weights only appear once the
main loop starts relaxing that labelling.

This is also why `nInitIters` is the right thing to zero out when you supply
your own rig: the whole splitting/labelling stage exists to invent a bone
distribution you have already decided.

### Main loop

- **Transform update** (`nTransIters`) - per bone, per frame: build a 4x4
  covariance matrix from the influenced vertex positions and take its **SVD** to
  extract the optimal rotation + translation. This is weighted Procrustes /
  Kabsch. It yields a **rigid** transform - which is the "Rigid Bones" in the
  paper title, and why no parameter can make the solver emit scale or shear.
- **Weight update** (`nWeightsIters`) - per vertex, an independent **convex
  least-squares** solve for that vertex's weights, subject to the `nnz` sparsity
  cap and regularized by the Laplacian smoothness term (`weightsSmooth`,
  `weightsSmoothStep`). Locked weights are respected.

The alternation between those two is what `nIters` counts, and `tolerance` /
`patience` watch for it flattening out.

---

## See also

- `CLAUDE.md` (this folder) - the tool's architecture, the two exit-1 causes,
  and the skin/animation transfer directions.
- `dw_maya/dw_deformers/ssdr_dembones_cloth_baking.md` - background theory on
  SSDR cloth baking (research notes, no implementation).
- `DemBonesRnD/rnd_diary.md` - the measured failures behind several of the
  cautions above.
- Upstream: https://github.com/electronicarts/dem-bones (BSD-3).