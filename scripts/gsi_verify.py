#!/usr/bin/env python3
"""Verify Project Infinity-X 3.12 (Android 16) Treble GSI images and property_contexts."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

VENDOR_ODM_PREFIX_RE = re.compile(r"^(?:ro\.vendor\.|vendor\.|persist\.vendor\.|ro\.odm\.)", re.MULTILINE)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_property_contexts(contexts_by_file: list[tuple[str, str]]) -> None:
    """Simulate AOSP TrieBuilder::AddToTrie to reject duplicate property_contexts keys."""
    root = {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
    for label, text in contexts_by_file:
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            require(len(parts) >= 2, f"{label}:{lineno}: malformed property_contexts entry")
            name, ctx = parts[0], parts[1]
            if name == "*":
                continue
            exact = len(parts) >= 3 and parts[2] == "exact"
            pieces = name.split(".")
            ends_dot = False
            if pieces[-1] == "":
                ends_dot = True
                pieces.pop()
            node = root
            for piece in pieces[:-1]:
                node = node["children"].setdefault(
                    piece, {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
                )
            last = pieces[-1]
            src = f"{label}:{lineno} ({ctx})"
            if exact:
                require(
                    last not in node["exacts"],
                    f"duplicate exact property_contexts key '{name}': {node['exacts'].get(last)} vs {src}",
                )
                node["exacts"][last] = src
            elif not ends_dot:
                require(
                    last not in node["prefixes"],
                    f"duplicate prefix property_contexts key '{name}': {node['prefixes'].get(last)} vs {src}",
                )
                node["prefixes"][last] = src
            else:
                child = node["children"].setdefault(
                    last, {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
                )
                require(
                    child["context"] is None,
                    f"duplicate prefix property_contexts key '{name}': {child['context']} vs {src}",
                )
                child["context"] = src


def check_system_ext_property_contexts_clean(text: str) -> None:
    """Ensure system_ext_property_contexts contains zero vendor/odm entries that collide with ColorOS."""
    bad = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and VENDOR_ODM_PREFIX_RE.match(line.lstrip())
    ]
    require(not bad, f"vendor/odm entries still present in system_ext_property_contexts: {bad[:5]}")


def _debugfs_cat(image: Path, relpath: str) -> str:
    res = subprocess.run(
        ["debugfs", "-R", f"cat {relpath}", str(image)],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.stdout if res.returncode == 0 else ""


def _debugfs_stat_exists(image: Path, relpath: str) -> bool:
    res = subprocess.run(
        ["debugfs", "-R", f"stat {relpath}", str(image)],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0 and "Inode:" in res.stdout


def verify_raw_gsi_image(
    image: Path,
    *,
    variant: str = "user",
    lineage_hide: bool = True,
    report_path: Path | None = None,
) -> str:
    """Inspect a built raw ext4 GSI system.img for required Realme GT5 & stealth invariants."""
    require(image.is_file() and image.stat().st_size > 0, f"missing GSI image: {image}")

    build_prop = _debugfs_cat(image, "system/build.prop")
    product_prop = _debugfs_cat(image, "system/product/etc/build.prop")
    skip_mount = _debugfs_cat(image, "system/system_ext/etc/init/config/skip_mount.cfg")
    init_gsi_rc = _debugfs_cat(image, "system/system_ext/etc/init/init.gsi.rc")
    sepolicy_cil = _debugfs_cat(image, "system/system_ext/etc/selinux/system_ext_sepolicy.cil")
    sys_ext_pc = _debugfs_cat(image, "system/system_ext/etc/selinux/system_ext_property_contexts")
    fp_perm_exists = _debugfs_stat_exists(image, "system/system_ext/etc/permissions/android.hardware.fingerprint.xml")
    userdebug_cil_exists = _debugfs_stat_exists(
        image, "system/system_ext/etc/selinux/system_ext_userdebug_plat_sepolicy.cil"
    )

    require("SET_BOOTSTAGE@ANDROID_BOOT_COMPLETED" in init_gsi_rc, "init.gsi.rc missing OPLUS Phoenix disarm")
    require("proc_phoenix" in sepolicy_cil, "system_ext_sepolicy.cil missing proc_phoenix SELinux rule")
    check_system_ext_property_contexts_clean(sys_ext_pc)
    require(fp_perm_exists, "missing system_ext/etc/permissions/android.hardware.fingerprint.xml")
    if variant == "user":
        require(
            not userdebug_cil_exists,
            "user build must not ship system_ext_userdebug_plat_sepolicy.cil (leaks su/adbroot policy)",
        )
    if lineage_hide:
        combined_props = build_prop + "\n" + product_prop
        require("ro.modversion=" not in combined_props, "ro.modversion must be stripped when lineage_hide is enabled")

    prop_lines = [
        line
        for line in (build_prop + "\n" + product_prop).splitlines()
        if re.match(
            r"^ro\.(build\.display\.id|build\.fingerprint|build\.type|build\.tags|"
            r"build\.version\.release|build\.version\.sdk|build\.version\.security_patch|"
            r"infinity\.|system\.build\.)",
            line,
        )
    ]
    phoenix_lines = [line for line in sepolicy_cil.splitlines() if "proc_phoenix" in line]

    report = "\n".join([
        "=== GSI build.prop & product/etc/build.prop ===",
        "\n".join(prop_lines) or "(none)",
        "=== GSI skip_mount.cfg ===",
        skip_mount.strip() or "(none)",
        "=== GSI init.gsi.rc (with OPLUS Phoenix disarm) ===",
        init_gsi_rc.strip() or "(none)",
        "=== GSI proc_phoenix SELinux rules ===",
        "\n".join(phoenix_lines) or "(none)",
        "=== GSI system_ext_property_contexts vendor/odm check ===",
        "(0 vendor/odm entries — clean!)",
        "=== GSI fingerprint permission & userdebug SELinux check ===",
        f"android.hardware.fingerprint.xml: present={fp_perm_exists}",
        f"system_ext_userdebug_plat_sepolicy.cil: present={userdebug_cil_exists} (variant={variant})",
        f"ro.modversion stripped: {lineage_hide}",
    ]) + "\n"

    if report_path is not None:
        report_path.write_text(report, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("property-contexts", help="Check property_contexts files for TrieBuilder duplicates")
    pc.add_argument("files", nargs="+", type=Path)

    img = sub.add_parser("image", help="Verify raw ext4 GSI image invariants")
    img.add_argument("--img", required=True, type=Path)
    img.add_argument("--variant", default="user", choices=("user", "userdebug"))
    img.add_argument("--no-lineage-hide", action="store_true")
    img.add_argument("--report", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "property-contexts":
            ctxs = [(p.name, p.read_text(encoding="utf-8")) for p in args.files]
            check_property_contexts(ctxs)
            for name, text in ctxs:
                if "system_ext" in name:
                    check_system_ext_property_contexts_clean(text)
            print(f"TrieBuilder property_contexts check passed ({len(ctxs)} files, 0 duplicates)")
            return 0
        report = verify_raw_gsi_image(
            args.img,
            variant=args.variant,
            lineage_hide=not args.no_lineage_hide,
            report_path=args.report,
        )
        print(report, end="")
        return 0
    except (OSError, ValueError) as exc:
        print(f"FAIL: gsi_verify: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
