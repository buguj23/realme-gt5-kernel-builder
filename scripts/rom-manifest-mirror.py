#!/usr/bin/env python3
"""rom-manifest-mirror.py — point a checked-out manifest at domestic mirrors.

`repo init` leaves AOSP on android.googlesource.com and Lineage/Infinity on GitHub.
In this region those are the slow path (measured: GitHub 18-25 KB/s direct,
googlesource unreachable); TUNA serves the same objects at 60 MB/s and is a plain
git mirror, so repo's commit verification still applies.

What is rewritten:
  * remote "aosp"   (android.googlesource.com)      -> TUNA AOSP mirror
  * remotes with fetch=".." (Lineage on GitHub)     -> TUNA LineageOS mirror
  * optionally remotes pointing at github.com       -> a GitHub accel prefix

Usage:
  rom-manifest-mirror.py <src-dir> [--aosp URL] [--lineage URL]
                         [--github-proxy PREFIX] [--dry-run]

Run after `repo init`, before `repo sync`. Re-run is idempotent.
"""
import argparse
import glob
import os
import re
import sys

DEFAULTS = {
    "aosp": "https://mirrors.tuna.tsinghua.edu.cn/git/AOSP/",
    "lineage": "https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/",
}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="tree containing .repo/manifests")
    ap.add_argument("--aosp", default=DEFAULTS["aosp"])
    ap.add_argument("--lineage", default=DEFAULTS["lineage"])
    ap.add_argument("--github-proxy", default="",
                    help="prefix for github.com remotes, e.g. https://gh-proxy.com/")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    mdir = os.path.join(a.src, ".repo", "manifests")
    if not os.path.isdir(mdir):
        print(f"not a repo tree: {mdir} missing", file=sys.stderr)
        return 2

    files = [os.path.join(mdir, "default.xml")] + sorted(
        glob.glob(os.path.join(mdir, "snippets", "*.xml")))
    changed = 0
    for path in files:
        if not os.path.isfile(path):
            continue
        text = open(path).read()
        orig = text
        text = text.replace('fetch="https://android.googlesource.com"',
                            f'fetch="{a.aosp}"')
        text = text.replace('fetch=".."', f'fetch="{a.lineage}"')
        if a.github_proxy:
            # covers fetch="https://github.com" and fetch="https://github.com/Org[…]
            text = re.sub(r'fetch="(https://github\.com[^"]*)"',
                          lambda m: f'fetch="{a.github_proxy}{m.group(1)}"', text)
        if text != orig:
            changed += 1
            if a.dry_run:
                print(f"would rewrite {os.path.relpath(path, a.src)}")
            else:
                open(path, "w").write(text)
                print(f"rewrote {os.path.relpath(path, a.src)}")

    remotes = sorted({m.group(1) for p in files if os.path.isfile(p)
                      for m in re.finditer(r'<remote[^>]*fetch="([^"]+)"', open(p).read())})
    print(f"{changed} file(s) changed; remotes now: {remotes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
