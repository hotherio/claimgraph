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
claimgraph affected conjecture:naive-separable

# A claim's effective status and the weakest dependency behind it
claimgraph effective IGL.fubini_factorization
```

Every command accepts `--from-fixture FILE` to read commit messages from a file instead of git,
which is handy for demos and tests.

The main example is [`examples/paper-igl/`](examples/paper-igl/): the real ClaimGraph of
[hotherio/paper-igl](https://github.com/hotherio/paper-igl), the formalized Intrinsic Green's
Learning development, vendored as a commit fixture so it rebuilds without the upstream repo. A
smaller synthetic fixture lives in [`examples/igl/`](examples/igl/) for the unit tests.

```bash
claimgraph status -f examples/paper-igl/paper-igl.commits -c examples/paper-igl/claims.toml
```

## The web viewer

[`docs/`](docs/) is a static, dependency-free viewer (vendored
[Cytoscape.js](https://js.cytoscape.org/)) served at
**https://claimgraph.conventional-knowledge-commits.org/**. Node colour is effective status; edge style is the
relation. Click a claim to trace what it rests on; click a broken claim to highlight the claims it affects.

The viewer is seeded with the paper-igl graph. Regenerate it from the vendored fixture:

```bash
claimgraph build -f examples/paper-igl/paper-igl.commits -c examples/paper-igl/claims.toml -o docs/assets/claimgraph.json
```

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
