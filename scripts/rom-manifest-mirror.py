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

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mirror_helper  # noqa: E402

DEFAULTS = {
    "aosp": "https://mirrors.tuna.tsinghua.edu.cn/git/AOSP/",
    "lineage": "https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/",
}


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="tree containing .repo/manifests")
    ap.add_argument("--aosp", default=DEFAULTS["aosp"],
                    help="AOSP mirror base URL or 'auto' to probe fastest live mirror")
    ap.add_argument("--lineage", default=DEFAULTS["lineage"],
                    help="LineageOS mirror base URL or 'auto' to probe fastest live mirror")
    ap.add_argument("--github-proxy", default="",
                    help="prefix for github.com remotes, e.g. https://ghfast.top/, 'auto', or 'direct'")
    ap.add_argument("--clo", default=None,
                    help="optional CodeLinaro mirror override")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.aosp == "auto":
        ranked_aosp = mirror_helper.rank_urls(
            [m.rstrip("/") + "/platform/manifest.git" for m in mirror_helper.DEFAULT_AOSP_MIRRORS if mirror_helper.is_domestic_url(m)],
            is_git=True,
        )
        a.aosp = ranked_aosp[0][0].removesuffix("platform/manifest.git") if ranked_aosp else DEFAULTS["aosp"]
    if a.lineage == "auto":
        ranked_lin = mirror_helper.rank_urls(
            [m.rstrip("/") + "/LineageOS/android.git" for m in mirror_helper.DEFAULT_LINEAGE_MIRRORS],
            is_git=True,
        )
        a.lineage = ranked_lin[0][0].removesuffix("LineageOS/android.git") if ranked_lin else DEFAULTS["lineage"]
    if a.github_proxy == "auto":
        ranked_gh = mirror_helper.rank_github_urls("https://github.com/ProjectInfinity-X/manifest.git", mode="cn", is_git=True)
        chosen = ranked_gh[0] if ranked_gh else ""
        a.github_proxy = "" if chosen.startswith("https://github.com/") else chosen.split("https://github.com/", 1)[0]

    mdir = os.path.join(a.src, ".repo", "manifests")
    if not os.path.isdir(mdir):
        print(f"not a repo tree: {mdir} missing", file=sys.stderr)
        return 2

    files = sorted({
        p for pattern in (
            os.path.join(mdir, "*.xml"),
            os.path.join(mdir, "snippets", "*.xml"),
        )
        for p in glob.glob(pattern)
    })
    changed = 0
    gh_prefix = a.github_proxy if a.github_proxy else None
    if a.github_proxy == "direct":
        gh_prefix = ""
    for path in files:
        if not os.path.isfile(path):
            continue
        text = open(path).read()
        orig = text
        text = mirror_helper.rewrite_manifest_text(
            text,
            aosp_mirror=a.aosp,
            lineage_mirror=a.lineage,
            github_prefix=gh_prefix,
            clo_mirror=a.clo,
        )
        text = text.replace('fetch=".."', f'fetch="{a.lineage}"')
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
