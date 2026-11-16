#!/usr/bin/env bash
# import-official.sh — stage GT5 150W official images locally (not committed).
set -euo pipefail
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
ZIP=${1:-${OFFICIAL_ZIP:-$REPO_DIR/../GT5 150W.zip}}
DEST=$REPO_DIR/official/stock
[ -f "$ZIP" ] || { echo "missing $ZIP" >&2; exit 1; }
mkdir -p "$DEST"
python3 - "$ZIP" "$DEST" <<'PY'
import sys, zipfile, io
from pathlib import Path
outer, dest = Path(sys.argv[1]), Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(outer) as z:
    for name in z.namelist():
        if not name.endswith('.zip') or name.endswith('/'):
            continue
        ver = Path(name).stem
        d = dest / ver
        d.mkdir(exist_ok=True)
        print('inner', ver)
        with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:
            inner.extractall(d)
print('staged', dest)
PY
ls -lh "$DEST"/*/boot.img
