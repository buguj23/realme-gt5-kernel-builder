#!/usr/bin/env python3
"""40-verify-crc.py — can these ROM modules load on the built kernel?

Every .ko records, per imported symbol, the CRC it was built against (__versions).
The kernel compares each of those against its own Module.symvers; one mismatch and
the module is rejected ("disagrees about version of symbol X"). The classic first
casualty is `module_layout`, which covers struct module itself.

usage: 40-verify-crc.py <Module.symvers> <dir-with-stock-.ko> [--list N]
exit:  0 compatible, 1 incompatible
"""
import argparse
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import kmi  # noqa: E402

ap = argparse.ArgumentParser(description="Verify Module.symvers CRCs against stock .ko modules")
ap.add_argument("symvers", help="Path to kernel Module.symvers")
ap.add_argument("moddir", help="Directory containing stock .ko files")
ap.add_argument("--list", type=int, default=10, help="Max mismatched symbols to print")
ap.add_argument("--recursive", action="store_true", help="Walk subdirectories under moddir")
ap.add_argument(
    "--allow-ko-providers",
    action="store_true",
    help="Treat symbols exported by sibling stock .ko modules as satisfied when absent from Module.symvers",
)
args = ap.parse_args()

symvers, moddir, show = args.symvers, args.moddir, args.list

kernel = {}
for line in open(symvers):
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 2:
        kernel[parts[1]] = parts[0].lower()

modules = []
if args.recursive:
    for root, _, files in os.walk(moddir):
        for f in sorted(files):
            if f.endswith(".ko"):
                modules.append(os.path.join(root, f))
else:
    modules = [os.path.join(moddir, f) for f in sorted(os.listdir(moddir)) if f.endswith(".ko")]

if not modules:
    print(f"no .ko files in {moddir}")
    raise SystemExit(2)

ko_exports = {}
if args.allow_ko_providers:
    for path in modules:
        try:
            for sym, crc in kmi.module_exports(path).items():
                ko_exports.setdefault(sym, set()).add(f"0x{crc:08x}")
        except Exception:
            continue

total = 0
bad = Counter()          # symbol -> times seen mismatched
bad_modules = set()
layout = None
for path in modules:
    mod = os.path.relpath(path, moddir)
    mod_bad = False
    vers_map = None
    try:
        vers_map = {sym: f"0x{crc:08x}" for sym, crc in (kmi.module_versions(path) or {}).items()}
    except Exception:
        vers_map = None
    if not vers_map:
        try:
            out = subprocess.run(["modprobe", "--dump-modversions", path],
                                 capture_output=True, text=True, timeout=120).stdout
            vers_map = {}
            for line in out.splitlines():
                if "\t" not in line:
                    continue
                crc, sym = line.split("\t", 1)
                vers_map[sym.strip()] = crc.lower()
        except Exception:
            continue
    for sym, crc in vers_map.items():
        total += 1
        if sym == "module_layout" and layout is None:
            layout = (crc, mod)
        have = kernel.get(sym)
        if have == crc:
            continue
        if args.allow_ko_providers and have is None and crc in ko_exports.get(sym, ()):
            continue
        n, sample_crc = bad.get(sym, (0, crc))
        bad[sym] = (n + 1, sample_crc)
        mod_bad = True
    if mod_bad:
        bad_modules.add(mod)

print(f"modules checked : {len(modules)}")
print(f"imported refs   : {total}")
print(f"modules with ≥1 mismatch: {len(bad_modules)}")
if layout:
    stock_crc, sample = layout
    ours = kernel.get("module_layout")
    state = "MATCH" if ours == stock_crc else "MISMATCH"
    print(f"module_layout   : stock={stock_crc} ours={ours or '(absent)'} -> {state}")
print(f"distinct mismatched symbols: {len(bad)}")
for sym, (n, stock_crc) in sorted(bad.items(), key=lambda kv: -kv[1][0])[:show]:
    print(f"  {sym:40} stock={stock_crc} ours={kernel.get(sym, '(absent)')} refs={n}")
print("RESULT:", "COMPATIBLE" if not bad else "INCOMPATIBLE")
raise SystemExit(0 if not bad else 1)
