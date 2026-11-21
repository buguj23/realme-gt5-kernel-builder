#!/usr/bin/env python3
"""Keep an interrupted initial repo fetch shallow on its internal retry."""
from pathlib import Path
import sys

OLD = "        if depth and not is_new and not self._HasShallow():\n"
NEW = """        # ossi: a failed initial fetch has no refs and was never unshallowed.
        if depth and not is_new and not self._HasShallow() and self.bare_ref.all:
"""


def patch(path: Path) -> str:
    if not path.is_file():
        return "repo not installed; skipped"
    text = path.read_text()
    if NEW in text:
        return "already applied"
    if text.count(OLD) != 1:
        return "guard differs from affected version; unchanged"
    updated = text.replace(OLD, NEW, 1)
    compile(updated, str(path), "exec")
    temp = path.with_name(path.name + ".ossi-depth.tmp")
    temp.write_text(updated)
    temp.chmod(path.stat().st_mode & 0o777)
    temp.replace(path)
    return "fixed initial-fetch retry depth"


if __name__ == "__main__":
    print("[repo-depth] " + patch(Path(sys.argv[1]) / ".repo/repo/project.py"))
