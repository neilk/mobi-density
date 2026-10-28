#!/bin/sh
# Serve the repository over HTTP so the maps under analysis/output/ can be
# opened in a browser at a stable localhost URL.
#
#   ./serve.sh          serves on http://localhost:8000
#   ./serve.sh 8080     picks a different port
cd "$(dirname "$0")" || exit 1
PORT="${1:-8000}"
echo "Map: http://localhost:$PORT/analysis/output/map.html  (Ctrl-C to stop)"
exec uv run --project analysis python -m http.server "$PORT" --bind 127.0.0.1
