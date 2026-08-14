#!/usr/bin/env bash
# Runs the backend for local development.
#
# Binds to 0.0.0.0 so a real iPhone on the same Wi-Fi can reach it. A physical
# device cannot use "localhost" — that resolves to the phone itself — so it must
# point at this machine's LAN address, printed below.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"

echo "Backend starting on ${HOST}:${PORT}"
echo
echo "  Simulator      →  http://localhost:${PORT}"
if [ -n "$LAN_IP" ]; then
  echo "  Real device    →  http://${LAN_IP}:${PORT}"
  echo
  echo "  On the iPhone: Settings (gear icon) → Backend address → http://${LAN_IP}:${PORT}"
  echo "  The phone must be on the same Wi-Fi network (not cellular)."
else
  echo "  Real device    →  no Wi-Fi address detected; connect this Mac to Wi-Fi"
fi
echo

exec ./.venv/bin/uvicorn app.main:app --reload --host "$HOST" --port "$PORT"
