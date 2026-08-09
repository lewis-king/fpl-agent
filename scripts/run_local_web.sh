#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
api_pid=""
model_pid=""
client_pid=""
shutdown_started=0

cleanup() {
  local exit_code=$?
  local process_id
  local still_running

  if (( shutdown_started )); then
    return
  fi
  shutdown_started=1
  trap - EXIT INT TERM

  for process_id in "$client_pid" "$api_pid" "$model_pid"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill -TERM "$process_id" 2>/dev/null || true
    fi
  done

  # Give Uvicorn, CUDA and Vite a bounded grace period, then ensure the launcher can
  # never leave the terminal waiting forever on a child that ignored SIGTERM.
  for _ in {1..80}; do
    still_running=0
    for process_id in "$client_pid" "$api_pid" "$model_pid"; do
      if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
        still_running=1
      fi
    done
    if (( ! still_running )); then
      break
    fi
    sleep 0.1
  done

  for process_id in "$client_pid" "$api_pid" "$model_pid"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill -KILL "$process_id" 2>/dev/null || true
    fi
  done
  for process_id in "$client_pid" "$api_pid" "$model_pid"; do
    if [[ -n "$process_id" ]]; then
      wait "$process_id" 2>/dev/null || true
    fi
  done

  return "$exit_code"
}

handle_interrupt() { exit 130; }
handle_terminate() { exit 143; }

trap cleanup EXIT
trap handle_interrupt INT
trap handle_terminate TERM

cd "$repository_root"

if [[ -x "$repository_root/.venv/bin/fplagent-web" ]]; then
  "$repository_root/.venv/bin/fplagent-web" --host 127.0.0.1 --port 8000 &
else
  uv run fplagent-web --host 127.0.0.1 --port 8000 &
fi
api_pid="$!"

model_arguments=(
  "$repository_root/llm/serve_chat_qwen35.py"
  --host 127.0.0.1
  --port 8011
)
if [[ -n "${FPLAGENT_WEB_ADAPTER:-}" ]]; then
  model_arguments+=(--adapter "$FPLAGENT_WEB_ADAPTER")
fi
"$repository_root/llm/.venv/bin/python" "${model_arguments[@]}" &
model_pid="$!"

if [[ -x "$repository_root/web/node_modules/.bin/vite" ]]; then
  "$repository_root/web/node_modules/.bin/vite" "$repository_root/web" --host 127.0.0.1 &
else
  (
    cd "$repository_root/web"
    exec npm run dev -- --host 127.0.0.1
  ) &
fi
client_pid="$!"

printf '\nFPLAgent is starting locally.\n'
printf 'Web:   http://127.0.0.1:5173\n'
printf 'API:   http://127.0.0.1:8000/docs\n'
printf 'Model: http://127.0.0.1:8011/health\n\n'
printf 'Optional authenticated sync expects the separately running MCP endpoint:\n'
printf 'MCP:   http://127.0.0.1:8021/mcp (login UI on port 8020)\n\n'
printf 'The web and API become available first; Qwen reports ready after its weights load.\n'
printf 'Press Ctrl+C to stop all three processes.\n\n'

wait -n "$api_pid" "$model_pid" "$client_pid"
