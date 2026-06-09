#!/usr/bin/env bash
# Start the remote desktop server and expose it over an HTTPS Cloudflare tunnel.
# Run from this directory:  bash start.sh
set -euo pipefail
cd "$(dirname "$0")"

# --- required ---
: "${RD_PASSWORD:?Set RD_PASSWORD first, e.g. export RD_PASSWORD='your-strong-password'}"

PORT="${RD_PORT:-8080}"
PYTHON="${PYTHON:-python3}"

# server listens on localhost only; the tunnel is the only way in
export RD_HOST="127.0.0.1"

echo "Starting server on 127.0.0.1:$PORT ..."
"$PYTHON" server.py &
SERVER_PID=$!

sleep 2

# locate cloudflared (either on PATH or ./cloudflared)
CF="$(command -v cloudflared || true)"
[ -z "$CF" ] && [ -x ./cloudflared ] && CF="./cloudflared"
if [ -z "$CF" ]; then
  echo "cloudflared not found. See README for install, or reach the server"
  echo "on your LAN at http://<this-machine-ip>:$PORT"
else
  echo "Starting Cloudflare tunnel ..."
  "$CF" tunnel --url "http://localhost:$PORT" 2>&1 | tee tunnel.log &
  TUNNEL_PID=$!
  echo "Waiting for tunnel URL ..."
  for _ in $(seq 1 30); do
    grep -q "trycloudflare.com" tunnel.log 2>/dev/null && break
    sleep 1
  done
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' tunnel.log | head -1 || true)"
  echo
  echo "================================================="
  echo "  Open this on your phone or any browser:"
  echo "  ${URL:-"(check tunnel.log)"}"
  echo "================================================="
  echo
fi

cleanup(){ kill "${SERVER_PID:-}" "${TUNNEL_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait
