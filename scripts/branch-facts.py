#!/usr/bin/env python3
"""branch-facts.py — measure one stock OTA baseline so a branch is not guessed.

For every 5.15.* branch the ROM must match *that branch's* OTA, not a sibling's.
This emits the facts that differ between branches and that decide compatibility:

  kernel_release      uname -r string found inside the stock boot image
  module_layout_crc   CRC shared by every stock vendor_dlkm module
  first_stage         modules.load entries in vendor_boot (order source)
  recovery_stage      modules.load.recovery entries
  metadata_fs         fstab line for /metadata (ext4 vs f2fs changes the ROM)
  boot_header         header version + os_version/patch level
  fs_types            filesystem of vendor/vendor_dlkm/system_dlkm/odm images

usage: branch-facts.py --stock DIR [--label NAME] [--json OUT]
       DIR holds boot.img vendor_boot.img vendor_dlkm.img system_dlkm.img
       (missing files are reported, not fatal)
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmi  # noqa: E402


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def kernel_release(boot_img):
    data = open(boot_img, "rb").read()
    m = re.search(rb"Linux version (\d+\.\d+\.\d+[^\s\x00]*)", data)
    return m.group(1).decode() if m else None


def boot_header(boot_img):
    out = run(["unpack_bootimg", "--boot_img", boot_img]).stdout
    info = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return {
        "header_version": info.get("boot image header version"),
        "os_version": info.get("os version"),
        "os_patch_level": info.get("os patch level"),
        "page_size": info.get("page size"),
        "kernel_load": info.get("kernel load address"),
        "ramdisk_load": info.get("ramdisk load address"),
        "tags_load": info.get("kernel tags load address"),
    }


def vendor_ramdisk_list(vendor_boot):
    tmp = tempfile.mkdtemp()
    try:
        run(["unpack_bootimg", "--boot_img", vendor_boot, "--out", tmp])
        frag = os.path.join(tmp, "vendor_ramdisk00")
        if not os.path.isfile(frag):
            return {}
        cpio = os.path.join(tmp, "rd.cpio")
        with open(cpio, "wb") as out:
            if run(["file", "-b", frag]).stdout.strip().startswith("LZ4"):
                subprocess.run(["lz4", "-dc", frag], stdout=out)
            else:
                out.write(open(frag, "rb").read())
        rd = os.path.join(tmp, "rd")
        os.makedirs(rd)
        with open(cpio, "rb") as f:
            subprocess.run(["cpio", "-idm", "--quiet"], cwd=rd, stdin=f,
                           capture_output=True)
        base = os.path.join(rd, "lib", "modules")
        lists = {}
        for name in ("modules.load", "modules.load.recovery"):
            p = os.path.join(base, name)
            if os.path.isfile(p):
                lists[name] = [l.strip() for l in open(p) if l.strip()]
        fstab = os.path.join(rd, "first_stage_ramdisk", "fstab.qcom")
        if os.path.isfile(fstab):
            for line in open(fstab):
                if "/metadata" in line and not line.lstrip().startswith("#"):
                    lists["metadata_line"] = " ".join(line.split())
                    break
        return lists
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_modules(img, dest):
    os.makedirs(dest, exist_ok=True)
    kind = run(["file", "-b", img]).stdout
    if "erofs" in kind:
        run(["fsck.erofs", f"--extract={dest}", img])
    else:
        run(["debugfs", "-R", f"rdump / {dest}", img])
    found = []
    for root, _, files in os.walk(dest):
        for f in files:
            if f.endswith(".ko"):
                found.append(os.path.join(root, f))
    return found


def crc_census(mods):
    census = {}
    for m in mods:
        vers = kmi.module_versions(m) or {}
        crc = vers.get(kmi.LAYOUT)
        key = f"0x{crc:08x}" if crc is not None else "none"
        census[key] = census.get(key, 0) + 1
    return census


def fs_type(img):
    if not os.path.isfile(img):
        return None
    img = os.path.realpath(img)
    kind = run(["file", "-b", img]).stdout.strip()
    for tag in ("erofs", "ext2", "ext4", "f2fs"):
        if tag in kind:
            return "erofs" if tag == "erofs" else ("ext4" if tag.startswith("ext2") else tag)
    return kind.split(",")[0]


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stock", required=True)
    ap.add_argument("--label", default=os.path.basename(os.path.abspath(argv[-1])))
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    s = a.stock
    facts = {"label": a.label, "stock": os.path.abspath(s)}

    boot = os.path.join(s, "boot.img")
    if os.path.isfile(boot):
        facts["kernel_release"] = kernel_release(boot)
        facts["boot_header"] = boot_header(boot)

    vb = os.path.join(s, "vendor_boot.img")
    if os.path.isfile(vb):
        lists = vendor_ramdisk_list(vb)
        facts["first_stage"] = len(lists.get("modules.load", []))
        facts["recovery_stage"] = len(lists.get("modules.load.recovery", []))
        facts["metadata_line"] = lists.get("metadata_line")
        facts["first_stage_modules"] = lists.get("modules.load", [])

    tmp = tempfile.mkdtemp()
    try:
        for name in ("vendor_dlkm", "system_dlkm"):
            img = os.path.join(s, f"{name}.img")
            if not os.path.isfile(img):
                continue
            mods = extract_modules(img, os.path.join(tmp, name))
            facts[f"{name}_modules"] = len(mods)
            facts[f"{name}_crc"] = crc_census(mods)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    facts["fs_types"] = {n: fs_type(os.path.join(s, f"{n}.img"))
                         for n in ("vendor", "vendor_dlkm", "system_dlkm", "odm")}

    text = json.dumps(facts, indent=1)
    if a.json:
        open(a.json, "w").write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
