#!/usr/bin/env python3
"""Stage the kernel, stock device trees, and phase-specific module lists."""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

import kmi
from rom_inputs import baseline, require, sha256, stock_payload, verify_stock
from rom_kernel_package import verify_package
from rom_modules import dtb_for_ramdisk_fstab, load_pool, path_modules

FS_MAKE = {"vendor_dlkm": "BOARD_VENDOR_DLKMIMAGE_FILE_SYSTEM_TYPE",
           "system_dlkm": "BOARD_SYSTEM_DLKMIMAGE_FILE_SYSTEM_TYPE"}


def merged(*sets):
    result = {}
    for entries in sets:
        for name, path in entries.items():
            require(name not in result or sha256(result[name]) == sha256(path),
                    f"conflicting instances of module {name}")
            result[name] = path
    return result


def canonical_module(name):
    return Path(name).name.removesuffix(".ko").replace("-", "_")


def blocklisted_modules(path):
    """Parse modprobe blocklist/blacklist entries into canonical module names."""
    blocked = set()
    if not path.is_file():
        return blocked
    for line in path.read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and fields[0] in ("blocklist", "blacklist"):
            blocked.add(canonical_module(fields[1]))
    return blocked


def dependency_closure(names, pool, dep_file):
    """Select only the modules reachable from a stock ramdisk load list."""
    dependencies = {}
    if dep_file.is_file():
        for line in dep_file.read_text().splitlines():
            if not line.strip():
                continue
            source, sep, providers = line.partition(":")
            require(sep, f"{dep_file}: malformed dependency entry")
            dependencies[Path(source).name] = [Path(provider).name for provider in providers.split()]

    canonical = canonical_module

    softdep_file = dep_file.with_name("modules.softdep")
    if softdep_file.is_file():
        modules = {canonical(name): name for name in pool}
        require(len(modules) == len(pool), f"{dep_file.parent}: ambiguous kernel module names")
        for line in softdep_file.read_text().splitlines():
            parts = line.split("#", 1)[0].split(maxsplit=2)
            if not parts:
                continue
            require(len(parts) == 3 and parts[0] == "softdep", f"{softdep_file}: malformed soft dependency")
            name = modules.get(canonical(parts[1]))
            if name:
                references = re.sub(r"\b(?:pre|post):", " ", parts[2]).split()
                # A soft dependency may be absent in the original image.
                dependencies.setdefault(name, []).extend(
                    modules[canonical(ref)] for ref in references if canonical(ref) in modules)
    result = {}
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in result:
            continue
        require(name in pool, f"ramdisk module {name} or its dependency is missing")
        result[name] = pool[name]
        pending.extend(dependencies.get(name, ()))
    return result


def verify_symbols(symvers, phase, modules, providers=None):
    try:
        catalog = kmi.symbol_catalog(symvers, providers if providers is not None else modules)
    except ValueError as error:
        raise ValueError(f"{phase}: {error}") from error
    for name, path in modules.items():
        require(kmi.arm64_module(path), f"{phase}: {name} is not an AArch64 module")
        problems = kmi.module_problems(path, catalog)
        require(not problems, f"{phase}: {name}: {', '.join(problems[:6])}")


def select_modules(package, stock, lists):
    packaged = path_modules(package / "modules")

    def replace(modules):
        return {name: packaged.get(name, source) for name, source in modules.items()}

    shared = path_modules(stock / "ramdisk")
    recovery_pool = merged(shared, path_modules(stock / "recovery"))
    early = replace(dependency_closure(lists["first_stage"], shared, stock / "ramdisk/modules.dep"))
    deps = stock / "recovery/modules.dep"
    if not deps.is_file() and not deps.with_name("modules.softdep").is_file():
        deps = stock / "ramdisk/modules.dep"
    recovery = replace(dependency_closure(lists["recovery"], recovery_pool, deps))
    vendor = replace(path_modules(stock / "vendor_dlkm"))
    system = replace(path_modules(stock / "system_dlkm"))
    # New build modules are available in vendor_dlkm. Retain the stock load order.
    for name, path in packaged.items():
        if not any(name in modules for modules in (early, recovery, vendor, system)):
            vendor[name] = path

    blocked_system = (
        blocklisted_modules(stock / "vendor_dlkm/system_dlkm.modules.blocklist")
        | blocklisted_modules(stock / "system_dlkm/modules.blocklist")
    )
    active_system = {name: path for name, path in system.items() if canonical_module(name) not in blocked_system}

    symvers = package / "Module.symvers"
    verify_symbols(symvers, "normal first stage", early)
    verify_symbols(symvers, "Recovery", recovery)
    verify_symbols(symvers, "system_dlkm", system, merged(early, system))
    verify_symbols(symvers, "normal boot DLKM", vendor, merged(early, active_system, vendor))
    partitions = {"vendor_ramdisk": merged(early, recovery), "vendor_dlkm": vendor, "system_dlkm": system}
    if packaged:
        features = {tuple(kmi.vermagic(path).split()[1:]) for path in packaged.values()}
        require(len(features) == 1 and next(iter(features)), "inconsistent kernel package vermagic flags")
        for group, modules in partitions.items():
            for name, path in modules.items():
                require(tuple(kmi.vermagic(path).split()[1:]) in features,
                        f"{group}: {name}: vermagic flags differ from the packaged kernel modules")
    return partitions


def stage(a):
    payload = stock_payload(a.stock_images, a.branch, a.payload_metadata)
    package = verify_package(a.package, a.branch)
    pool = load_pool(a.stock_pool, payload["sha256"])
    verify_stock(a.stock_images, payload, ("vendor_boot", "dtbo"))
    lists = pool["lists"]
    partitions = select_modules(a.package, a.stock_pool, lists)
    with (a.stock_images / "dtbo.img").open("rb") as stream:
        require(stream.read(4) == b"\xd7\xb7\xab\x1e", "stock DTBO header has invalid magic")
    original_dtb = (a.stock_pool / "dtb.img").read_bytes()
    # The pool is locally generated from the same vendor_boot and tied to its hash
    # by the checker. Compare with the source image here as well.
    source_boot = a.stock_images / "vendor_boot.img"
    with source_boot.open("rb") as stream:
        header = stream.read(2128)
        _, page, kernel, ramdisk, ramdisk_size = struct.unpack_from("<5I", header, 8)
        tags, = struct.unpack_from("<I", header, 2076)
        hsize, dtb_size, dtb_addr = struct.unpack_from("<IIQ", header, 2096)
        stream.seek(((hsize + page - 1) // page + (ramdisk_size + page - 1) // page) * page)
        require(stream.read(dtb_size) == original_dtb, "stock pool DTB differs from vendor_boot")
    dtb, dtb_updates = dtb_for_ramdisk_fstab(original_dtb)
    print(f"Module order verified: normal {len(lists['first_stage'])}, Recovery {len(lists['recovery'])}, "
          f"vendor_dlkm {len(lists['vendor_dlkm'])}, system_dlkm {len(lists['system_dlkm'])}")
    print(f"Selected ramdisk fstab for {dtb_updates} stock DTBs with legacy vendor mounts")
    if a.dry_run:
        return
    pre = a.device_tree / "prebuilt"
    pre.mkdir(exist_ok=True)
    # The caller installs the overlay in a clean build tree. Refuse stale
    # staging files whenever the direct CLI is used in an existing overlay.
    require(not (pre / "kernel-modules.mk").exists(), f"{pre}: remove the previous kernel staging output first")
    shutil.copyfile(a.package / "Image", pre / "Image")
    shutil.copyfile(a.stock_images / "dtbo.img", pre / "dtbo.img")
    (pre / "dtb").mkdir(exist_ok=True)
    (pre / "dtb" / "ossi.dtb").write_bytes(dtb)
    mk = [
        "# Generated by rom-stage-kernel.py",
        "TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilt/Image",
        "TARGET_FORCE_PREBUILT_KERNEL := true",
        "BOARD_PREBUILT_DTBOIMAGE := $(DEVICE_PATH)/prebuilt/dtbo.img",
        "BOARD_PREBUILT_DTBIMAGE_DIR := $(DEVICE_PATH)/prebuilt/dtb",
        f"BOARD_KERNEL_PAGESIZE := {page}",
        "BOARD_MKBOOTIMG_ARGS += "
        f"--kernel_offset {kernel:#x} --ramdisk_offset {ramdisk:#x} --tags_offset {tags:#x} --dtb_offset {dtb_addr:#x}",
    ]
    for partition, prefix, list_key in (
        ("vendor_ramdisk", "VENDOR_RAMDISK", "first_stage"),
        ("vendor_dlkm", "VENDOR", "vendor_dlkm"),
        ("system_dlkm", "SYSTEM", "system_dlkm"),
    ):
        dest = pre / partition
        dest.mkdir()
        modules = partitions[partition]
        for name, src in modules.items():
            shutil.copyfile(src, dest / name)
        paths = " ".join(f"$(DEVICE_PATH)/prebuilt/{partition}/{name}" for name in sorted(modules))
        mk.append(f"BOARD_{prefix}_KERNEL_MODULES := {paths}")
        mk.append(f"BOARD_{prefix}_KERNEL_MODULES_LOAD := {' '.join(lists[list_key]) or 'false'}")
        if partition == "vendor_ramdisk":
            mk.append("BOARD_VENDOR_RAMDISK_RECOVERY_KERNEL_MODULES_LOAD := " + " ".join(lists["recovery"]))
        if partition in pool["fs"]:
            fs = pool["fs"][partition]
            require(fs in ("ext4", "erofs"), f"unexpected stock filesystem {fs}")
            mk.append(f"{FS_MAKE[partition]} := {fs}")
        original = a.stock_pool / ("ramdisk" if partition == "vendor_ramdisk" else partition)
        for name, suffix in (("modules.blocklist", "BLOCKLIST_FILE"), ("modules.options", "OPTIONS_FILE")):
            src = original / name
            if not src.is_file() and partition == "system_dlkm" and name == "modules.blocklist":
                src = a.stock_pool / "vendor_dlkm/system_dlkm.modules.blocklist"
            if src.is_file():
                shutil.copyfile(src, dest / name)
                mk.append(f"BOARD_{prefix}_KERNEL_MODULES_{suffix} := $(DEVICE_PATH)/prebuilt/{partition}/{name}")
    report = {"package": package, "stock_payload": payload["sha256"], "lists": lists, "fs": pool["fs"],
              "dtbs_using_ramdisk_fstab": dtb_updates,
              "boot_security_patch": baseline(a.branch)["security_patch"],
              "module_abi": {part: {name: kmi.module_abi(path) for name, path in sorted(mods.items())}
                             for part, mods in partitions.items()}}
    (pre / "stage-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (pre / "kernel-modules.mk").write_text("\n".join(mk) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "device-tree", "stock-pool", "stock-images"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--payload-metadata", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        stage(args)
    except (OSError, ValueError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        print(f"FAIL: kernel stage: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
