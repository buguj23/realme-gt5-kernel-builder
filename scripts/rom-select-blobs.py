#!/usr/bin/env python3
"""rom-select-blobs.py — turn a platform blob list into one branch's real list.

A blob list is only usable if every path exists in *that* branch's OTA. This
mounts each partition image read-only (loop, erofs or ext4) and keeps the entries
that are actually present, preserving extract-utils annotations (`;SYMLINK=`,
`;MODULE_SUFFIX=`, `;REQUIRED=`) verbatim.

Files that the platform list does not mention but that this device ships — the
Oplus HAL services and their libraries — are appended in a clearly marked section
only when they match a fixed pattern and exist. Nothing is invented: every emitted
line was stat()ed inside the mounted image.

usage:
  rom-select-blobs.py --base-list upstream.txt --images DIR --out proprietary-files.txt
                      [--report JSON] [--no-extras] [--mount /tmp/mnt]

DIR must contain <partition>.img for the partitions the list references.
Requires passwordless sudo for `mount -o loop,ro`.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# Oplus-specific payload the platform list has no reason to carry.
EXTRA_PATTERNS = [
    (re.compile(r'^(odm|vendor)/bin/hw/.*oplus'), 'service'),
    (re.compile(r'^(odm|vendor)/lib(64)?/hw/.*oplus'), 'hal library'),
    (re.compile(r'^(odm|vendor)/lib(64)?/.*oplus[^/]*\.so$'), 'library'),
    (re.compile(r'^(odm|vendor)/etc/vintf/manifest/.*\.xml$'), 'vintf manifest'),
    (re.compile(r'^(odm|vendor)/etc/init/.*oplus.*\.rc$'), 'init script'),
    (re.compile(r'^(odm|vendor)/etc/permissions/.*oplus.*\.xml$'), 'permission xml'),
]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def parse_entry(line):
    """-> (path, original_line) with the annotation preserved on the line."""
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return None
    body = raw.lstrip('-+ ')
    # extract-utils syntax: "<src>[:<dst>][;ANNOTATION=...]" — the source is
    # what must exist in the dump.
    path = body.split(";", 1)[0].split(":", 1)[0].strip()
    if not path or "/" not in path:
        return None
    return path, raw


class Mounts:
    def __init__(self, image_dir, mnt, sudo=True):
        self.image_dir = image_dir
        self.mnt = mnt
        self.sudo = ["sudo", "-n"] if sudo else []
        self.mounted = None

    def _mount(self, image):
        cmd = [*self.sudo, "mount", "-o", "loop,ro", image, self.mnt]
        res = run(cmd)
        if res.returncode != 0:
            res = run([*self.sudo, "mount", "-o", "loop,ro", "-t", "ext4", image, self.mnt])
        return res.returncode == 0

    def _umount(self):
        run([*self.sudo, "umount", self.mnt])
        self.mounted = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        if self.mounted:
            self._umount()

    def open(self, partition):
        if self.mounted == partition:
            return True
        if self.mounted:
            self._umount()
        image = os.path.join(self.image_dir, f"{partition}.img")
        if not os.path.isfile(image):
            return False
        if not self._mount(image):
            return False
        self.mounted = partition
        return True

    def exists(self, partition, rel):
        return self.open(partition) and os.path.isfile(os.path.join(self.mnt, rel))

    def walk(self, partition):
        if not self.open(partition):
            return []
        root = self.mnt
        out = []
        for dirpath, _dirs, files in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    # runtime-generated entries (e.g. odm vintf manifests pointing
                    # at /proc/oplusManifest) are not files we can ship
                    continue
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                out.append(rel)
        return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-list", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    ap.add_argument("--mount", default=None)
    ap.add_argument("--no-extras", action="store_true")
    ap.add_argument("--materialize", help="copy the selected files into this dump dir")
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)

    mnt = a.mount or tempfile.mkdtemp(prefix="blobmnt-")
    os.makedirs(mnt, exist_ok=True)
    sudo = bool(os.environ.get("SUDO_MOUNT", "1") == "1")

    kept, dropped, seen = [], [], set()
    per_part = {}
    with Mounts(a.images, mnt, sudo=sudo) as mounts:
        for line in open(a.base_list):
            parsed = parse_entry(line)
            if not parsed:
                continue
            path, original = parsed
            part = path.split("/", 1)[0]
            rel = path.split("/", 1)[1]
            per_part.setdefault(part, [0, 0])
            per_part[part][1] += 1
            if mounts.exists(part, rel):
                kept.append(original)
                seen.add(path)
                per_part[part][0] += 1
            else:
                dropped.append(path)

        extras = []
        if not a.no_extras:
            for part in ("odm", "vendor"):
                for rel in mounts.walk(part):
                    path = f"{part}/{rel}"
                    if path in seen:
                        continue
                    for pattern, why in EXTRA_PATTERNS:
                        if pattern.match(path):
                            extras.append((path, why))
                            seen.add(path)
                            break
            extras.sort()

        if a.materialize:
            os.makedirs(a.materialize, exist_ok=True)
            copied = 0
            targets = [l.lstrip('-+ ').split(";", 1)[0].split(":", 1)[0].strip() for l in kept]
            targets += [p for p, _ in extras]
            for src in targets:
                part, rel = src.split("/", 1)
                if not mounts.open(part):
                    continue
                s_path = os.path.join(mnt, rel)
                if not os.path.isfile(s_path):
                    continue
                d_path = os.path.join(a.materialize, src)
                os.makedirs(os.path.dirname(d_path), exist_ok=True)
                subprocess.run(["cp", "-a", s_path, d_path], check=False)
                copied += 1
            print(f"materialized {copied} files into {a.materialize}")

    header = [
        "## Generated by scripts/rom-select-blobs.py — every line below was stat()ed",
        "## inside this branch's own OTA images; nothing is hand-invented.",
    ]
    if a.label:
        header.append(f"## branch: {a.label}")
    header.append("## Platform base: LineageOS device/oneplus/sm8550-common proprietary-files.txt")
    header.append("")

    with open(a.out, "w") as f:
        f.write("\n".join(header) + "\n")
        f.write("\n".join(kept) + "\n")
        if extras:
            f.write("\n# ---- Oplus HAL payload present on this device (auto-included) ----\n")
            for path, _why in extras:
                # No trailing comment: extract-utils would treat it as part of the path.
                f.write(path + "\n")

    report = {
        "label": a.label,
        "kept": len(kept),
        "dropped": len(dropped),
        "extras": len(extras),
        "per_partition": {k: {"present": v[0], "listed": v[1]} for k, v in sorted(per_part.items())},
        "dropped_samples": dropped[:20],
        "extras_samples": [p for p, _ in extras[:20]],
    }
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
