#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_dir/.." && pwd)"
horizon="${FPLAGENT_FORECAST_HORIZON:-8}"

cd "$repository_root"

printf 'Refreshing official FPL players, teams, events and fixtures...\n'
uv run fpl-data build --source fpl_current --force

printf 'Rebuilding the current feature horizon (GW1-%s)...\n' "$horizon"
uv run fplagent prepare --horizon "$horizon"

printf 'Applying the promoted player outcome models to the new snapshot...\n'
uv run fplagent forecast

printf 'Applying the promoted component models to the new snapshot...\n'
uv run fplagent forecast-components

printf 'Current FPL forecasts refreshed. Reload the workspace to consume the new artifacts.\n'
