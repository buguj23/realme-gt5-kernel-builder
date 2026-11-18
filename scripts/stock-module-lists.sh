#!/usr/bin/env bash
# Extract all three verified stock module groups.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/rom_modules.py" stock "$@"
