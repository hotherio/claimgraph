#!/usr/bin/env bash
# Render the pipeline diagram from D2 and strip d2's opaque background so the SVG
# sits transparently on whatever container it is placed in.
#   Requires: d2 (https://d2lang.com)
#   Usage: scripts/render-pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."

d2 docs/assets/pipeline.d2 docs/assets/pipeline.svg

# d2 paints a full-canvas background rectangle (class "fill-N7"). Its colour comes from an
# embedded CSS rule, which overrides any inline fill, so make the SVG transparent by editing
# the rule itself. fill-N7 is used only by the background rect.
perl -0pi -e 's/\.fill-N7\s*\{\s*fill:\s*#?[0-9A-Fa-f]{3,8};?\s*\}/.fill-N7{fill:none;}/g' docs/assets/pipeline.svg

echo "rendered docs/assets/pipeline.svg (transparent background)"
