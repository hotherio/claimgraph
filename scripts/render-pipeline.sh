#!/usr/bin/env bash
# Render the pipeline diagram from D2 and strip d2's opaque background so the SVG
# sits transparently on whatever container it is placed in.
#   Requires: d2 (https://d2lang.com)
#   Usage: scripts/render-pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."

d2 docs/assets/pipeline.d2 docs/assets/pipeline.svg

# d2 paints a full-canvas background rectangle (class "fill-N7", fill #FFFFFF).
# Drop its fill so the SVG background is transparent.
perl -0pi -e 's/fill="#FFFFFF"(\s+class=" fill-N7")/fill="none"$1/' docs/assets/pipeline.svg

echo "rendered docs/assets/pipeline.svg (transparent background)"
