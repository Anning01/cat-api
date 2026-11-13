#!/bin/bash
set -eu

cd "$(dirname "$0")/.."
mkdir -p logs
pid_file="$PWD/logs/local-dev.pid"

if [ "${1:-}" = stop ]; then
  if [ -f "$pid_file" ]; then
    kill -TERM "$(cat "$pid_file")" 2>/dev/null || true
    echo "Stopping local Cat API."
  else
    echo "Local Cat API is not running through this script."
  fi
  exit 0
fi

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "Cat API is already running: http://127.0.0.1:3001/"
  exit 0
fi

if [ ! -f .env ]; then
  echo "Create .env from .env.example and set the administrator account first." >&2
  exit 1
fi
if [ ! -d web/node_modules ] || [ ! -d .venv ]; then
  echo "Install the documented project dependencies first: uv sync --frozen; cd web && npm ci" >&2
  exit 1
fi

uv run --no-sync python scripts/local_postgres.py start

python3 - <<'PY'
import socket
for port in (9000, 3001):
    with socket.socket() as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            connection.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is in use. Stop the previous local service first.')
PY

api_pid=
web_pid=
cleanup() {
  trap - EXIT INT TERM
  [ -z "$web_pid" ] || kill -TERM "$web_pid" 2>/dev/null || true
  [ -z "$api_pid" ] || kill -TERM "$api_pid" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -f "$pid_file"
}
trap cleanup EXIT
trap 'exit 0' INT TERM
echo "$$" > "$pid_file"

uv run --no-sync uvicorn main:app --host 127.0.0.1 --port 9000 &
api_pid=$!
CAT_API_DEV_BACKEND=http://127.0.0.1:9000 npm --prefix web run dev -- --host 127.0.0.1 --port 3001 --strictPort &
web_pid=$!

echo "Cat API: http://127.0.0.1:3001/"
echo "API documentation: http://127.0.0.1:9000/console-docs"
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
echo "A local service exited; stopping the remaining service." >&2
exit 1
