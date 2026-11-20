#!/usr/bin/env python3
"""branch-compare.py — diff one deliverable or kernel package against the stock OTA.

First-stage module counts (145 entries / 144 unique on RMX3820_15.0.0.320), security
patch levels and module sets must align with the target OTA measured by branch-facts.py.

Two modes:
  --deliver DIR   full ROM images (boot/vendor_boot/vendor_dlkm/system_dlkm)
  --package DIR   kernel package (Image + modules/ + Module.symvers)

Checks in package mode:
  * Image embeds the stock module_layout CRC
  * every packaged module carries that CRC
  * first-stage list of the stock OTA is fully covered

Checks in deliver mode add:
  * kernel release matches the stock one for this branch
  * first-stage count and metadata fstab line match
  * dlkm filesystem types match
  * boot header version matches

exit: 0 aligned, 1 differences found, 2 usage/IO
"""
import argparse
import json
import os
import sys
from pathlib import Path

from rom_inputs import BASE_PARTITIONS
from rom_modules import check_vendor_boot

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmi  # noqa: E402
import importlib.util


def load_facts_module():
    path = os.path.join(HERE, "branch-facts.py")
    spec = importlib.util.spec_from_file_location("branch_facts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = load_facts_module()


def stock_crc(facts):
    for key in ("vendor_dlkm_crc", "system_dlkm_crc"):
        census = facts.get(key) or {}
        if len(census) == 1:
            (crc, _), = census.items()
            if crc != "none":
                return int(crc, 16)
    return None


def package_mode(facts, pkg, stock_dir=None):
    rows = []
    ok = True
    want = stock_crc(facts)
    if want is None:
        rows.append(("stock CRC", "unknown", "known", False))
        return rows, False
    crc_hex = f"0x{want:08x}"

    symvers = os.path.join(pkg, "Module.symvers")
    if not os.path.isfile(symvers):
        rows.append(("Module.symvers", "missing", "present", False))
        return rows, False
    table = kmi.read_symvers(symvers)
    got = table.get(kmi.LAYOUT)
    rows.append((f"kernel {kmi.LAYOUT}", f"0x{got:08x}" if got else "none", crc_hex, got == want))
    ok = ok and got == want

    mods = os.path.join(pkg, "modules")
    files = sorted(f for f in os.listdir(mods) if f.endswith(".ko")) if os.path.isdir(mods) else []
    bad = []
    for name in files:
        crc = (kmi.module_versions(os.path.join(mods, name)) or {}).get(kmi.LAYOUT)
        if crc != want:
            bad.append(name)
    rows.append(("packaged modules", f"{len(files)} ({len(bad)} off-CRC)", crc_hex, bool(files) and not bad))
    ok = ok and bool(files) and not bad

    image = os.path.join(pkg, "Image")
    if os.path.isfile(image):
        hits = open(image, "rb").read().count(want.to_bytes(4, "little"))
        rows.append(("Image embeds CRC", f"{hits} hit(s)", ">=1", hits >= 1))
        ok = ok and hits >= 1
    else:
        rows.append(("Image", "missing", "present", False))
        ok = False

    first = facts.get("first_stage_modules") or []
    if not first:
        rows.append(("first-stage module list", "empty", "present", False))
        return rows, False
    have = set(files)
    missing = [m for m in first if m not in have]

    # A module absent from the package may be borrowed from the stock pool only
    # when its CRCs match the kernel — same rule rom-stage-kernel.py enforces.
    unsatisfied = list(missing)
    borrowed = []
    if missing and stock_dir:
        unsatisfied = []
        for name in missing:
            cand = os.path.join(stock_dir, name)
            if not os.path.isfile(cand):
                unsatisfied.append(name)
                continue
            crc = (kmi.module_versions(cand) or {}).get(kmi.LAYOUT)
            if crc != want:
                unsatisfied.append(name)
            else:
                borrowed.append(name)
        rows.append(("borrowed from stock", str(len(borrowed)), "CRC-checked", True))

    rows.append(("first-stage coverage",
                 f"{len(first) - len(unsatisfied)}/{len(first)}", "all", not unsatisfied))
    ok = ok and not unsatisfied
    for name in unsatisfied[:5]:
        rows.append(("  missing", name, "present", False))
    return rows, ok


def deliver_mode(facts, deliver):
    rows = []
    ok = True

    expected = BASE_PARTITIONS | {"boot", "vendor_boot", "init_boot", "dtbo", "recovery",
                                  "vbmeta", "vbmeta_system", "vbmeta_vendor"}
    for name in sorted(expected):
        if not os.path.isfile(os.path.join(deliver, f"{name}.img")):
            rows.append((f"{name}.img", "missing", "present", False))
            ok = False

    boot = os.path.join(deliver, "boot.img")
    if os.path.isfile(boot):
        rel = bf.kernel_release(boot)
        want = facts.get("kernel_release")
        stock_branch = (want or "").split("-", 1)[0]
        match = bool(stock_branch and rel and rel.split("-", 1)[0] == stock_branch)
        rows.append(("kernel branch", rel or "?", stock_branch or "?", match))
        ok = ok and match
        hdr = bf.boot_header(boot)
        w_hdr = facts.get("boot_header") or {}
        for k in ("header_version", "os_version"):
            if w_hdr.get(k):
                rows.append((f"boot {k}", hdr.get(k) or "?", w_hdr[k], hdr.get(k) == w_hdr[k]))
                ok = ok and hdr.get(k) == w_hdr[k]

    vb = os.path.join(deliver, "vendor_boot.img")
    if os.path.isfile(vb):
        lists = bf.vendor_ramdisk_list(vb)
        first = lists.get("modules.load", [])
        want_first = facts.get("first_stage_modules") or []
        match = bool(want_first) and first == want_first
        stock = Path(facts.get("stock", deliver)) / "vendor_boot.img"
        if match:
            try:
                check_vendor_boot(Path(vb), stock)
            except (OSError, ValueError):
                match = False
        rows.append(("first-stage and Recovery", str(len(first)), str(len(want_first)), match))
        ok = ok and match
        line = lists.get("metadata_line")
        rows.append(("/metadata", (line or "?").split()[2] if line else "?",
                     (facts.get("metadata_line") or "? ? ?").split()[2],
                     line == facts.get("metadata_line")))
        ok = ok and line == facts.get("metadata_line")

    for part in ("vendor_dlkm", "system_dlkm"):
        img = os.path.join(deliver, f"{part}.img")
        if not os.path.isfile(img):
            continue
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix=f"cmp_{part}_") as dest:
            mods = bf.extract_modules(img, dest)
            census = bf.crc_census(mods)
        want = stock_crc(facts)
        layout = f"0x{want:08x}" if want is not None else "unknown"
        match = set(census) == {layout}
        rows.append((f"{part} CRC", json.dumps(census), layout, match))
        ok = ok and match
        got_fs = bf.fs_type(img)
        want_fs = (facts.get("fs_types") or {}).get(part)
        rows.append((f"{part} fs", got_fs or "?", want_fs or "?", want_fs is None or got_fs == want_fs))
        ok = ok and (want_fs is None or got_fs == want_fs)

    return rows, ok


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--facts", required=True)
    ap.add_argument("--package")
    ap.add_argument("--stock-modules", help="stock module pool allowed as CRC-checked fallback")
    ap.add_argument("--deliver")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    facts = json.load(open(a.facts))

    rows, ok = [], True
    if a.package:
        r, o = package_mode(facts, a.package, a.stock_modules); rows += r; ok = ok and o
    if a.deliver:
        r, o = deliver_mode(facts, a.deliver); rows += r; ok = ok and o
    if not a.package and not a.deliver:
        ap.error("give --package and/or --deliver")

    print(f"branch {facts.get('label')} ({facts.get('kernel_release')})")
    width = max(len(r[0]) for r in rows)
    for name, got, want, good in rows:
        print(f"  {name:<{width}}  got={got}  want={want}  {'ok' if good else 'DIFF'}")
    print("ALIGNED" if ok else "MISALIGNED")
    if a.json:
        json.dump({"branch": facts.get("label"), "aligned": ok,
                   "rows": [dict(check=n, got=g, want=w, ok=b) for n, g, w, b in rows]},
                  open(a.json, "w"), indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
