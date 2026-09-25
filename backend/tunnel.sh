#!/bin/bash
# Public tunnel for the overlay backend: a Cloudflare "quick tunnel" (no account, anonymous *.trycloudflare.com URL).
# Keeps cloudflared running, and whenever the URL changes writes it to backend.json at the repo root and pushes it,
# so the GitHub Pages viewer finds the backend without anyone editing anything.
#   backend/tunnel.sh          -> nohup supervisor, log in _build/logs/tunnel.log, current URL in _build/tunnel_url
#   backend/tunnel.sh --fg     -> foreground
#   backend/tunnel.sh --stop
set -u
cd "$(dirname "$0")/.."
REPO=$(pwd)
CF=${CF:-$HOME/.local/bin/cloudflared}
PORT=${PORT:-19529}
LOG=_build/logs/tunnel.log
mkdir -p _build/logs

if [ "${1:-}" = "--stop" ]; then
  pkill -f "cloudflared tunnel --url http://127.0.0.1:$PORT" 2>/dev/null; pkill -f "tunnel.sh --supervise" 2>/dev/null; echo stopped; exit 0
fi
if [ "${1:-}" != "--supervise" ] && [ "${1:-}" != "--fg" ]; then
  pkill -f "tunnel.sh --supervise" 2>/dev/null; pkill -f "cloudflared tunnel --url http://127.0.0.1:$PORT" 2>/dev/null
  nohup "$0" --supervise > "$LOG" 2>&1 &
  for i in $(seq 1 40); do sleep 1; [ -s _build/tunnel_url ] && { echo "tunnel: $(cat _build/tunnel_url)"; exit 0; }; done
  echo "no tunnel URL yet; see $LOG" >&2; exit 1
fi

publish() {  # $1 = url
  local url=$1 now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf '{"url":"%s","updated":"%s","note":"current public address of the overlay backend (Cloudflare quick tunnel; changes when the tunnel restarts)"}\n' "$url" "$now" > backend.json
  echo "$url" > _build/tunnel_url
  git add -- backend.json
  if git diff --cached --quiet -- backend.json; then return; fi   # unchanged (e.g. same URL after a restart)
  git -c user.name=camx-anonymous -c user.email=camxanonymous@gmail.com commit -q -m "Update overlay backend tunnel URL" -- backend.json
  git push -q origin HEAD:main 2>>"$LOG" && echo "$(date) published $url" || echo "$(date) push failed (will retry on next change)"
}

while true; do
  echo "$(date) starting cloudflared -> http://127.0.0.1:$PORT"
  rm -f _build/tunnel_url
  "$CF" tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate 2>&1 | while IFS= read -r line; do
    echo "$line"
    u=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)
    if [ -n "$u" ] && [ "$u" != "$(cat _build/tunnel_url 2>/dev/null)" ]; then publish "$u"; fi
  done
  echo "$(date) cloudflared exited; restarting in 10 s"
  sleep 10
done
