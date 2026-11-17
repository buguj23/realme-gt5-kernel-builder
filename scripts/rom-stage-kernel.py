#!/usr/bin/env python3
"""rom-stage-kernel.py — stage one kernel package into the GT5 device tree.

Input : a package produced by scripts/kernel-package.sh (Image, dtbo.img,
        Module.symvers, modules/*.ko, manifest.json) and the *stock* module
        ordering taken from the official vendor_boot.

Output: device/realme/ossi/prebuilt/{Image,dtbo.img,vendor_ramdisk,vendor_dlkm,
        system_dlkm,kernel-modules.mk,stage-report.json}

Policy that makes the ROM bootable (see docs/AUDIT_16.0.3.500.md):
  * first-stage set and load order come from STOCK modules.load, never from the
    ROM's own generated list — a 50-entry list where stock has 146 means no UFS,
    no FBE key module, no boot;
  * a module missing from the package may be taken from the stock vendor_dlkm
    only when the CRC of every imported symbol matches this kernel's
    Module.symvers; anything else aborts the stage.

usage:
  rom-stage-kernel.py --package DIR --device-tree DIR --stock-modules-load FILE
                      [--stock-modules DIR] [--system-modules zram.ko,zsmalloc.ko]
                      [--no-stock-fallback] [--dry-run]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kmi  # noqa: E402


def read_list(path):
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def verify(pkg):
    symvers = os.path.join(pkg, "Module.symvers")
    mods = os.path.join(pkg, "modules")
    image = os.path.join(pkg, "Image")
    res = subprocess.run(
        [sys.executable, os.path.join(HERE, "kmi.py"), "verify",
         "--symvers", symvers, "--modules", mods, "--image", image],
        capture_output=True, text=True)
    return res.returncode == 0, (res.stdout + res.stderr).strip()


def kernel_symvers(pkg):
    return kmi.read_symvers(os.path.join(pkg, "Module.symvers"))


def compatible(module_path, table):
    """Every symbol the module imports must carry the kernel's CRC."""
    vers = kmi.module_versions(module_path)
    if not vers:
        return False, "no __versions"
    wrong = [s for s, crc in vers.items() if s in table and table[s] != crc]
    if wrong:
        return False, f"{len(wrong)} symbol mismatches e.g. {wrong[:3]}"
    return True, "ok"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--package", required=True)
    ap.add_argument("--device-tree", required=True)
    ap.add_argument("--stock-modules-load", required=True,
                    help="modules.load extracted from the official vendor_boot")
    ap.add_argument("--stock-modules", help="stock vendor_dlkm lib/modules for fallback")
    ap.add_argument("--system-modules", default="zram.ko,zsmalloc.ko")
    ap.add_argument("--no-stock-fallback", action="store_true")
    ap.add_argument("--no-vendor-fill", action="store_true",
                    help="do not complete vendor_dlkm from the stock pool")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    ok, report = verify(a.package)
    print(report)
    if not ok:
        print("ABORT: package is not internally aligned", file=sys.stderr)
        return 1

    table = kernel_symvers(a.package)
    kernel_layout = table.get(kmi.LAYOUT)
    pkg_mods = os.path.join(a.package, "modules")
    have = {f: os.path.join(pkg_mods, f) for f in os.listdir(pkg_mods) if f.endswith(".ko")}

    stock_order = read_list(a.stock_modules_load)
    system_names = {s.strip() for s in a.system_modules.split(",") if s.strip()}

    first_stage, vendor, system, borrowed, missing = [], [], [], [], []
    for name in stock_order:
        path = have.get(name)
        if path is None:
            cand = os.path.join(a.stock_modules, name) if a.stock_modules else None
            if cand and os.path.isfile(cand) and not a.no_stock_fallback:
                good, why = compatible(cand, table)
                if not good:
                    missing.append((name, f"stock fallback rejected: {why}"))
                    continue
                borrowed.append(name)
                path = cand
            else:
                missing.append((name, "absent from package"))
                continue
        first_stage.append((name, path))

    used = {n for n, _ in first_stage}
    for name, path in sorted(have.items()):
        if name in used:
            continue
        (system if name in system_names else vendor).append((name, path))

    # A kernel build only emits a few modules; the rest of vendor_dlkm is the
    # OEM's, which is usable only after the same per-symbol check. Without this
    # fill the ROM would ship a vendor_dlkm holding a single module.
    vendor_filled = 0
    if a.stock_modules and not a.no_vendor_fill:
        placed = {n for n, _ in vendor} | {n for n, _ in first_stage} | {n for n, _ in system}
        for name in sorted(os.listdir(a.stock_modules)):
            if not name.endswith(".ko") or name in placed:
                continue
            src = os.path.join(a.stock_modules, name)
            good, _why = compatible(src, table)
            if not good:
                continue
            vendor.append((name, src))
            vendor_filled += 1

    if missing:
        print(f"ABORT: {len(missing)} first-stage module(s) unavailable:", file=sys.stderr)
        for n, why in missing[:10]:
            print(f"  {n}: {why}", file=sys.stderr)
        return 1

    print(f"kernel module_layout=0x{kernel_layout:08x}" if kernel_layout else "kernel module_layout=UNKNOWN")
    print(f"first-stage {len(first_stage)} (stock order) | vendor_dlkm {len(vendor)} "
          f"(+{vendor_filled} OEM) | system_dlkm {len(system)} | "
          f"borrowed-from-stock {len(borrowed)}")

    dt = a.device_tree
    pre = os.path.join(dt, "prebuilt")
    layout = {
        "Image": os.path.join(a.package, "Image"),
        "dtbo.img": os.path.join(a.package, "dtbo.img"),
    }
    if a.dry_run:
        print("dry-run: no files written")
        return 0

    shutil.rmtree(os.path.join(pre, "vendor_ramdisk"), ignore_errors=True)
    shutil.rmtree(os.path.join(pre, "vendor_dlkm"), ignore_errors=True)
    shutil.rmtree(os.path.join(pre, "system_dlkm"), ignore_errors=True)
    for name, src in layout.items():
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(pre, name))

    def place(base, items):
        d = os.path.join(pre, base, "lib", "modules")
        os.makedirs(d, exist_ok=True)
        for name, src in items:
            shutil.copy2(src, os.path.join(d, name))
        return d

    stage_dir = place("vendor_ramdisk", first_stage)
    vendor_dir = place("vendor_dlkm", vendor)
    system_dir = place("system_dlkm", system)
    with open(os.path.join(stage_dir, "modules.load"), "w") as f:
        f.write("\n".join(n for n, _ in first_stage) + "\n")

    mk = []
    mk.append("# Generated by scripts/rom-stage-kernel.py — do not edit.")
    mk.append(f"# module_layout CRC 0x{kernel_layout:08x}" if kernel_layout else "# module_layout CRC unknown")
    mk.append("BOARD_USES_SYSTEM_DLKMIMAGE := true")
    mk.append("BOARD_VENDOR_RAMDISK_KERNEL_MODULES := \\")
    mk += [f"    $(DEVICE_PATH)/prebuilt/vendor_ramdisk/lib/modules/{n} \\" for n, _ in first_stage]
    mk.append("")
    mk.append("BOARD_VENDOR_RAMDISK_KERNEL_MODULES_LOAD := "
              + " ".join(n for n, _ in first_stage))
    mk.append("BOARD_VENDOR_KERNEL_MODULES := \\")
    mk += [f"    $(DEVICE_PATH)/prebuilt/vendor_dlkm/lib/modules/{n} \\" for n, _ in vendor]
    mk.append("")
    # _LOAD is a name list, not a file: build/make reads it as a variable.
    mk.append("BOARD_VENDOR_KERNEL_MODULES_LOAD := " + " ".join(n for n, _ in vendor))
    if system:
        mk.append("BOARD_SYSTEM_KERNEL_MODULES := \\")
        mk += [f"    $(DEVICE_PATH)/prebuilt/system_dlkm/lib/modules/{n} \\" for n, _ in system]
        mk.append("")
        mk.append("BOARD_SYSTEM_KERNEL_MODULES_LOAD := " + " ".join(n for n, _ in system))
    mk.append("TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilt/Image")
    if os.path.isfile(os.path.join(pre, "dtbo.img")):
        mk.append("BOARD_PREBUILT_DTBOIMAGE := $(DEVICE_PATH)/prebuilt/dtbo.img")
    with open(os.path.join(pre, "kernel-modules.mk"), "w") as f:
        f.write("\n".join(mk) + "\n")

    summary = {
        "module_layout_crc": f"0x{kernel_layout:08x}" if kernel_layout else None,
        "first_stage": len(first_stage),
        "vendor_dlkm": len(vendor),
        "system_dlkm": len(system),
        "borrowed_from_stock": borrowed,
        "vendor_from_stock": vendor_filled,
    }
    with open(os.path.join(pre, "stage-report.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(f"staged into {pre}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
