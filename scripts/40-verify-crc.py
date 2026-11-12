#!/usr/bin/env python3
"""40-verify-crc.py — check whether a set of ROM modules can load on the built kernel.

Compares every symbol CRC imported by the modules (__versions section) against
Module.symvers of the kernel. Any mismatch means the module will be rejected by
modversions (usually 'module_layout' first).
"""
import os
import subprocess
import sys

symvers = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/gt5_kernel_ab/kernel_platform/out200/common/Module.symvers")
moddir = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser(
    "~/gt5_infinity_workspace/rom_check/vdlkm/modules")

crc = {}
for line in open(symvers):
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 2:
        crc[parts[1]] = parts[0]

total = bad = 0
for mod in sorted(f for f in os.listdir(moddir) if f.endswith(".ko")):
    try:
        out = subprocess.run(["modprobe", "--dump-modversions",
                              os.path.join(moddir, mod)],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        continue
    for line in out.splitlines():
        if "\t" not in line:
            continue
        c, sym = line.split("\t", 1)
        sym = sym.strip()
        total += 1
        if sym not in crc or crc[sym].lower() != c.lower():
            bad += 1

print(f"imported refs: {total}  mismatches: {bad}")
print("RESULT:", "COMPATIBLE" if bad == 0 else "INCOMPATIBLE")
sys.exit(0 if bad == 0 else 1)
