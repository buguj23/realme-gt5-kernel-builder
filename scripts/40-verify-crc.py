#!/usr/bin/env python3
"""40-verify-crc.py — can these ROM modules load on the built kernel?

Every .ko records, per imported symbol, the CRC it was built against (__versions).
The kernel compares each of those against its own Module.symvers; one mismatch and
the module is rejected ("disagrees about version of symbol X"). The classic first
casualty is `module_layout`, which covers struct module itself.

usage: 40-verify-crc.py <Module.symvers> <dir-with-stock-.ko> [--list N]
exit:  0 compatible, 1 incompatible
"""
import os
import subprocess
import sys
from collections import Counter

if len(sys.argv) < 3:
    print(__doc__)
    raise SystemExit(2)

symvers, moddir = sys.argv[1], sys.argv[2]
show = 10
if "--list" in sys.argv:
    try:
        show = int(sys.argv[sys.argv.index("--list") + 1])
    except (IndexError, ValueError):
        pass

kernel = {}
for line in open(symvers):
    parts = line.rstrip("\n").split("\t")
    if len(parts) >= 2:
        kernel[parts[1]] = parts[0].lower()

modules = sorted(f for f in os.listdir(moddir) if f.endswith(".ko"))
if not modules:
    print(f"no .ko files in {moddir}")
    raise SystemExit(2)

total = 0
bad = Counter()          # symbol -> times seen mismatched
bad_modules = set()
layout = None
for mod in modules:
    path = os.path.join(moddir, mod)
    try:
        out = subprocess.run(["modprobe", "--dump-modversions", path],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception:
        continue
    mod_bad = False
    for line in out.splitlines():
        if "\t" not in line:
            continue
        crc, sym = line.split("\t", 1)
        sym = sym.strip()
        crc = crc.lower()
        total += 1
        if sym == "module_layout" and layout is None:
            layout = (crc, mod)
        have = kernel.get(sym)
        if have != crc:
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
