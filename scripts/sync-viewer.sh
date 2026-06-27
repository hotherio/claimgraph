#!/usr/bin/env bash
# Copy the canonical viewer assets (served from docs/assets/ on the site) into the Python package,
# so `claimgraph export` can emit a self-contained HTML offline. Run this whenever the viewer
# (claimgraph.js / claimgraph.css / cytoscape) changes. tests/test_export.py guards against drift.
set -euo pipefail
cd "$(dirname "$0")/.."
dest="src/claimgraph/viewer"
mkdir -p "$dest"
cp docs/assets/claimgraph.css        "$dest/claimgraph.css"
cp docs/assets/claimgraph.js         "$dest/claimgraph.js"
cp docs/assets/vendor/cytoscape.min.js "$dest/cytoscape.min.js"
cp docs/assets/logo.png              "$dest/logo.png"   # for --shape branded
echo "synced viewer assets -> $dest"
