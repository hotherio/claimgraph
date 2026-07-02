# L4 -- the ClaimGraph as an agent blackboard (injected refutation, self-audit, re-proof)

## Idea

L1-L3 use the ClaimGraph as a *reward* and a *curriculum*. L4 uses it as a **shared blackboard** between
agents. Builder agents post claims -- `Depends-On` edges and optimistic statuses. A **self-audit / refuter
agent** posts *findings*: what the kernel actually reads (`#print axioms` out of module), not what a build
or a green CI reports. The graph then turns each finding into its **blast radius** -- the dependents whose
*effective* status silently degrades because a prerequisite broke -- and a **scheduler** reads the
regression set back as the re-proof curriculum. The graph is the medium through which one agent's
refutation reaches the claims another agent thought were finished.

This is not a new algorithm. It is the coordination protocol assembled from the L3 primitives (`compute`,
`affected`, `reproof_order`) in `claimgraph.blackboard`. The value L4 demonstrates is that a claim graph
makes cross-agent blast radius *computable and honest*: the collateral damage of a refutation is derived,
not guessed.

## The worked event: WeakPFR silent contamination

The fixture (`weak-pfr.commits`, `claims.toml`) is the T4 / L2 event. Twelve builder commits assert the
entropy-route WeakPFR strand machine-checked, **including a downstream corollary `pfr-int-strong`** that
rests on `weak-pfr-int`. Then a module-system migration silently regresses seven of those results to
`sorryAx` behind a green build -- the exact 7 decls kernel-verified in the prooftrace L2 experiment
(`app_ent_PFR`, `PFR_projection`, `torsion_dist_shrinking`, `torsion_free_doubling`, `weak_PFR_asymm`,
`weak_PFR_int`, `weak_PFR`).

The demo builds the *pre-audit* blackboard (the builders' optimistic graph, everything machine-checked),
then the refuter posts the seven kernel findings and the graph propagates:

```
python -m claimgraph.blackboard              # examples/weak-pfr is the default
```

```
refuter posted 7 findings: app-ent-pfr, pfr-projection, torsion-dist-shrinking,
  torsion-free-doubling, weak-pfr-asymm, weak-pfr-int, weak-pfr-symm
blast radius: 8 claims (1 collateral, never audited: pfr-int-strong)

claim                                     before                 after  refuted?
--------------------------------------------------------------------------
app-ent-pfr                 math.machine-checked             math.open  yes
pfr-int-strong              math.machine-checked             math.open  COLLATERAL
pfr-projection              math.machine-checked             math.open  yes
...
weak-pfr-int                math.machine-checked             math.open  yes

re-proof curriculum (prerequisites first): pfr-projection -> app-ent-pfr ->
  torsion-dist-shrinking -> torsion-free-doubling -> weak-pfr-asymm ->
  weak-pfr-symm -> weak-pfr-int -> pfr-int-strong
```

**The point is `pfr-int-strong`.** The refuter never audited it -- no finding names it -- yet its effective
status drops from `machine-checked` to `open`, because the graph knows it rests (transitively) on
`weak-pfr-int`. That is the collateral a reviewer never sees from the green build: a corollary that is now
unproven and does not know it. The scheduler puts it last in the re-proof curriculum (it depends on
everything else in the set), so a re-proof loop repairs prerequisites first and the corollary last.

## Two propagation modes

Silent contamination regresses to `math.open` -- a *weaker* ladder status, not a terminal `BROKEN` one --
so the blast radius shows up as **effective-status demotion** via `weakest_dep` (the corollary inherits the
hole). A genuine **refutation** (a `BROKEN` status like `math.disproved`, e.g. a counterexample) instead
raises `in_question` on every dependent while leaving their asserted status intact -- "this rests on
something now known false." `claimgraph.blackboard` handles both; `tests/test_blackboard.py` covers the
`BROKEN`/`in_question` path on a synthetic chain and the `open`/demotion path on this WeakPFR fixture.

## What this establishes, and what it does not

- **Establishes.** With the graph as a shared blackboard, a refuter agent's kernel finding propagates to
  the exact set of other agents' claims it invalidates -- directly-refuted *and* collateral -- and the
  scheduler hands that set back in dependency order as the re-proof plan. The collateral is derived from
  the `Depends-On` closure, so it cannot be missed the way a green CI misses it.
- **Does not establish.** The "agents" here are the recorded commit history plus one kernel audit; this is
  the coordination *mechanism*, not a live multi-agent prover run. Wiring an actual prover fleet (builders
  proposing, a refuter auditing with `#print axioms`, the scheduler dispatching the re-proof set) onto this
  blackboard is the next step; the primitives and this demo are what it would be built on.
