#!/usr/bin/env bash
# Build the static web folder for the frostpine pixel body (game_pixel.py) with
# pygbag (pygame -> WASM). Produces build/web/, a self-contained static site you
# can host anywhere (see DEPLOY-WEB.md). Nothing here touches the sim.
#
#   ./build_web.sh            # build into build/web/
#   ./build_web.sh --serve    # build AND serve locally at http://localhost:8000
#
# Requires: python3 with pygbag installed ->  python -m pip install pygbag
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

if ! python -m pygbag --help >/dev/null 2>&1; then
  echo "pygbag is not installed. Install it with:" >&2
  echo "    python -m pip install pygbag" >&2
  exit 1
fi

# pygbag bundles the folder of the entry script (the stdlib-only sim comes along),
# emits a static site under build/web/, and pins the canvas to the game's size.
COMMON=(--app_name frostpine --title "Frostpine" --width 928 --height 640)

if [[ "${1:-}" == "--serve" ]]; then
  echo ">>> pygbag build + local server at http://localhost:8000 (Ctrl-C to stop)"
  python -m pygbag "${COMMON[@]}" game_pixel.py
else
  echo ">>> pygbag build -> build/web/"
  python -m pygbag --build "${COMMON[@]}" game_pixel.py
  echo
  echo "Done. Static site is in:  build/web/"
  echo "Preview locally:  python -m http.server -d build/web 8000  ->  http://localhost:8000"
  echo "Publish:          see DEPLOY-WEB.md"
fi
