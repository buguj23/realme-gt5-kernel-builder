#!/usr/bin/env bash
# Package Image, Module.symvers, and modules.order from one Kbuild output.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 "$HERE/rom_kernel_package.py" assemble "$@"
