# claimgraph

Build and visualize the **[Conventional Knowledge Commits (CKC)](https://conventional-knowledge-commits.org/) ClaimGraph** from git history.

CKC records knowledge claims (theorems, lemmas, definitions, conjectures, empirical findings) and
the relations between them as git-trailer footers in commit messages. `claimgraph` rebuilds the
graph those footers describe and answers the questions the spec is built around:

- **What is proved vs. assumed vs. open?** The *effective status* of each claim: the minimum over
  its transitive `Depends-On` / `Assumes` closure (the same thing Lean's `#print axioms` reports).
- **What breaks if a claim falls?** The *affected claims*: every dependent a refutation or retraction
  would put *in question*.

It reuses the CKC commit parser and the single-source-of-truth vocabulary from
[`ckc-tools`](https://github.com/hotherio/ckc-tools), so the graph stays in step with the spec.

## Install

```bash
pip install git+https://github.com/hotherio/claimgraph.git
```

Requires Python 3.13+. The CKC parser (`ckc-lint`) is pulled in automatically.

## Use

```bash
# Build the graph from a repo's history and write claimgraph.json
claimgraph build /path/to/repo --claims claims.toml -o claimgraph.json

# Claims grouped by effective status
claimgraph status --claims claims.toml

# What a refutation of a claim would put in question (its dependents)
claimgraph affected kempe

# A claim's effective status and the weakest dependency behind it
claimgraph effective four-color
```

Every command accepts `--from-fixture FILE` to read commit messages from a file instead of git,
which is handy for demos and tests.

The showcase example is [`examples/four-color/`](examples/four-color/): a hand-authored CKC history
of the Four Colour Theorem, from Guthrie's 1852 conjecture, through Kempe's refuted proof and the
1976 computer-assisted proof, to Gonthier's 2005 machine-checked Coq formalization. It exercises
every status the graph tracks. Four more classical proofs, each shaped to show off a different
feature of the graph, ship alongside it (and are selectable in the live viewer):

- [`examples/fermat/`](examples/fermat/), Fermat's Last Theorem: the gap in Wiles's 1993 proof,
  repaired by Taylor and Wiles, plus a Lean formalization still in progress.
- [`examples/kepler/`](examples/kepler/), the Kepler conjecture: a refuted attempt, then the
  computer-assisted proof promoted to machine-checked by the Flyspeck formalization.
- [`examples/fundamental-algebra/`](examples/fundamental-algebra/), the fundamental theorem of
  algebra: several independent proofs of one theorem, and two historical gaps.
- [`examples/prime-number-theorem/`](examples/prime-number-theorem/), the prime number theorem:
  parallel proofs over a shared lemma, and a sharper error term resting on the open Riemann hypothesis.

[`examples/paper-igl/`](examples/paper-igl/) is a graph built from a real repository
([hotherio/paper-igl](https://github.com/hotherio/paper-igl)), and
[`examples/igl/`](examples/igl/) is a small synthetic fixture for the unit tests.

```bash
claimgraph status -f examples/four-color/four-color.commits -c examples/four-color/claims.toml
```

## Ground Depends-On edges against Lean

The `Depends-On` / `Assumes` footers are author-asserted: a human (or an agent) writes down which
claims a result rests on. Lean already knows the truth, since every elaborated proof term records the
declarations it references. `claimgraph depcheck` extracts that real dependency graph from a built
project (a small metaprogram run via `lake env lean`, the same bridge idea as `axiom-report`),
collapses it onto the claim nodes, and compares it to the asserted edges:

- **confirmed**: an asserted `Depends-On` that Lean witnesses;
- **missing**: a real Lean dependency between two claims that no commit ever recorded;
- **spurious**: an asserted `Depends-On` with no real Lean path (over-claimed, or an expository
  link miscategorised as a logical dependency).

Only edges whose *source* node has a Lean reading are judged, so a paper-only claim's edges are never
called spurious. Helper lemmas that are not themselves claim nodes are passed through, so an
`A → helper → B` chain collapses to the node edge `A → B`.

```bash
# ground against a built project (runs `lake env lean`)
claimgraph depcheck blueprint/src/content.tex . --project lean/

# --populate prints the real edges as ready-to-paste Depends-On trailers;
# --strict exits nonzero when an asserted edge has no Lean path (a CI drift gate)
claimgraph depcheck blueprint/src/content.tex . --project lean/ --populate --strict
```

Pass `--lean-deps FILE` to ground against a saved dep-report instead of a live build. The bundled
example runs fully offline against the real [paper-igl](https://github.com/hotherio/paper-igl)
history, where the hand-authored edges turn out to be both incomplete (real dependencies never
recorded) and over-claimed (asserted edges with no Lean path):

```bash
claimgraph depcheck examples/blueprint-igl/content.tex \
  --from-fixture examples/paper-igl/paper-igl.commits \
  --claims examples/paper-igl/claims.toml \
  --lean-deps examples/blueprint-igl/leandeps.txt
```

## The web viewer

[`docs/`](docs/) is a static, dependency-free viewer (vendored
[Cytoscape.js](https://js.cytoscape.org/)) served at
**https://claimgraph.conventional-knowledge-commits.org/**. Node colour is effective status; edge style is the
relation. Click a claim to trace what it rests on; click a broken claim to highlight the claims it affects.

The viewer defaults to the Four Colour Theorem and offers a dropdown to switch between the bundled
examples. Each example's graph is a JSON under `docs/assets/` (four-color is `claimgraph.json`).
Regenerate one from its fixture:

```bash
claimgraph build -f examples/four-color/four-color.commits -c examples/four-color/claims.toml -o docs/assets/claimgraph.json
claimgraph build -f examples/kepler/kepler.commits -c examples/kepler/claims.toml -o docs/assets/kepler.json
```

The 1200×630 social cards under `docs/assets/og/` are generated by `scripts/gen_og.py`
(Pillow; fonts bundled under `scripts/fonts/`). Re-run it after editing a page title:

```bash
.venv/bin/python scripts/gen_og.py
```

## Export a standalone viewer

`claimgraph export` bundles the graph, the commit-history timeline, the viewer (CSS/JS + Cytoscape),
and the data into **one self-contained HTML file** — no build step, no external assets, works offline
(`file://`) and embeds anywhere. The data rides in an inline `<script type="application/json">` island
the viewer reads instead of fetching, so the page draws with zero network requests.

```bash
# a complete, self-contained page (timeline replay is on by default)
claimgraph export /path/to/repo -o claimgraph.html

# from a fixture, with a custom title
claimgraph export -f examples/four-color/four-color.commits -c examples/four-color/claims.toml \
  --title "Four Colour Theorem" -o four-color.html
```

`--shape` chooses the embed form:

| shape | what you get |
| --- | --- |
| `page` (default) | a full standalone `.html` document |
| `fragment` | a single `<iframe srcdoc>` snippet to paste into another page (fully style/script isolated) |
| `branded` | the page plus CKC chrome (logo, nav, footer) |

Other flags: `--no-timeline` omits the commit replay (graph + final state only); with no `-o` the HTML
goes to stdout. The bundled viewer assets under `src/claimgraph/viewer/` are copies of the canonical
`docs/assets/` files kept in sync by `scripts/sync-viewer.sh`; `tests/test_export.py` fails if they drift.

## Output

`claimgraph build` emits JSON conforming to
[`schema/claimgraph.schema.json`](schema/claimgraph.schema.json): `nodes[]` (id, kind, statement,
asserted `status`, computed `effective_status`, `in_question`, `weakest_dep`) and `edges[]` (source,
target, relation, breaking).

## Develop

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT.
