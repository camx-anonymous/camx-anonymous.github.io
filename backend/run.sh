#!/bin/bash
# Start (or restart) the CAMX overlay backend on the data machine.
#   backend/run.sh            -> nohup on port 19529, log in _build/logs/server.log
#   backend/run.sh --fg       -> foreground
# Env: CAMX_ROOT (default /data/camx_480p), CAMX_VIZ_DIR (camera-cross-embodiment/camx/visualization),
#      CAMX_OVERLAY_CACHE (_build/overlay_cache), CAMX_OVERLAY_WORKERS (2 clip jobs at once), PORT (19529)
set -e
cd "$(dirname "$0")/.."
PY=${PY:-/data/venvs/camx-overlay/bin/python}   # venv: pyarrow>=23 (meta/episodes parquet), av, trimesh, yourdfpy, rerun-sdk, fastapi
PORT=${PORT:-19529}
if [ ! -x "$PY" ]; then
  echo "venv missing: python -m venv /data/venvs/camx-overlay && pip install 'pyarrow>=19' 'numpy<2.3' scipy opencv-python-headless av trimesh yourdfpy rerun-sdk fastapi 'uvicorn[standard]' pandas" >&2
  exit 1
fi
pkill -f "backend/server.py --port $PORT" 2>/dev/null || true
mkdir -p _build/logs
if [ "$1" = "--fg" ]; then exec "$PY" backend/server.py --port "$PORT"; fi
nohup "$PY" backend/server.py --port "$PORT" > _build/logs/server.log 2>&1 &
for i in $(seq 1 30); do sleep 1; curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && { echo "overlay backend up: http://127.0.0.1:$PORT/viewer/"; exit 0; }; done
echo "backend did not come up; see _build/logs/server.log" >&2; exit 1
