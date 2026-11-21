#!/usr/bin/env python3
"""Apply idempotent Infinity-X 15 compatibility patches after source/deps sync."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _patch_text(path: Path, transform) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def patch_simple_settings_config(src: Path) -> None:
    """Keep SimpleSettingsConfig compatible when org.lineageos.platform.internal is absent."""
    if (src / "vendor/lineage").is_dir():
        return
    pkg_dir = src / "packages/apps/SimpleSettingsConfig"
    bp = pkg_dir / "Android.bp"
    if not bp.is_file() or '"org.lineageos.platform.internal"' not in bp.read_text(encoding="utf-8"):
        return

    def clean_bp(text: str) -> str:
        text = re.sub(
            r'\n\s*static_libs:\s*\[\s*"org\.lineageos\.platform\.internal",?\s*\],\s*\n',
            "\n",
            text,
        )
        text = re.sub(r'\n\s*platform_apis:\s*true,?', '\n    sdk_version: "current",', text)
        return text

    def clean_manifest(text: str) -> str:
        return "\n".join(
            line for line in text.splitlines()
            if "lineageos.permission.WRITE_" not in line
        ) + ("\n" if text.endswith("\n") else "")

    def clean_boot_receiver(text: str) -> str:
        text = text.replace("import lineageos.providers.LineageSettings;\n", "")
        text = re.sub(
            r'^[ \t]*case "lineage_(?:global|secure|system)":\n[ \t]*LineageSettings\.[^\n]+\n[ \t]*break;\n\n?',
            "",
            text,
            flags=re.MULTILINE,
        )
        return text

    _patch_text(bp, clean_bp)
    _patch_text(pkg_dir / "AndroidManifest.xml", clean_manifest)
    _patch_text(pkg_dir / "src/org/lineageos/settingsconfig/BootReceiver.java", clean_boot_receiver)


def patch_infinity_livedisplay_and_matrix(src: Path) -> None:
    """Map Lineage common matrix to Infinity-X and drop AIDL LiveDisplay when absent."""
    infinity_matrix = src / "vendor/infinity/config/device_framework_matrix.xml"
    common_mk = src / "device/oneplus/sm8550-common/common.mk"
    if not infinity_matrix.is_file() or not common_mk.is_file():
        return

    has_aidl_livedisplay = any(
        (src / p).is_dir()
        for p in ("hardware/lineage/livedisplay", "hardware/lineage/interfaces/livedisplay/aidl")
    )

    def update_common_mk(text: str) -> str:
        text = text.replace(
            "vendor/lineage/config/device_framework_matrix.xml",
            "vendor/infinity/config/device_framework_matrix.xml",
        )
        if not has_aidl_livedisplay:
            text = re.sub(
                r"# LiveDisplay\nPRODUCT_PACKAGES \+= \\\n\s*vendor\.lineage\.livedisplay-service\.oplus\n",
                "# LiveDisplay (disabled for Infinity-X without AIDL livedisplay interface)\n",
                text,
            )
        return text

    _patch_text(common_mk, update_common_mk)

    if not has_aidl_livedisplay:
        livedisplay_bp = src / "hardware/oplus/aidl/livedisplay/Android.bp"
        if livedisplay_bp.is_file():
            livedisplay_bp.rename(livedisplay_bp.with_name("Android.bp.disabled"))


def patch_soong_custom_super_partitions(src: Path) -> None:
    """Skip Soong generated_super diff-test when super includes OEM custom my_* partitions."""
    super_img = src / "build/soong/fsgen/super_img.go"
    old = (
        "func buildingSuperImage(partitionVars android.PartitionVariables) bool {\n"
        "\treturn partitionVars.ProductBuildSuperPartition\n"
        "}"
    )
    new = (
        "func buildingSuperImage(partitionVars android.PartitionVariables) bool {\n"
        "\tif !partitionVars.ProductBuildSuperPartition {\n"
        "\t\treturn false\n"
        "\t}\n"
        '\tsupported := []string{"system", "system_dlkm", "system_ext", "product", '
        '"vendor", "vendor_dlkm", "odm", "odm_dlkm"}\n'
        "\tfor _, info := range partitionVars.BoardSuperPartitionGroups {\n"
        "\t\tfor _, p := range info.PartitionList {\n"
        "\t\t\tif !android.InList(p, supported) {\n"
        "\t\t\t\treturn false\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "\treturn true\n"
        "}"
    )

    def update_super_img(text: str) -> str:
        if "android.InList(p, supported)" in text or old not in text:
            return text
        return text.replace(old, new, 1)

    _patch_text(super_img, update_super_img)


def patch_dangling_kernel_include_symlinks(src: Path) -> None:
    """Remove dangling symlinks under kernel/oneplus/sm8550/include when sm8550-modules is absent."""
    inc = src / "kernel/oneplus/sm8550/include"
    if not inc.is_dir():
        return
    for entry in inc.rglob("*"):
        if entry.is_symlink() and not entry.exists():
            entry.unlink()


def patch_kernel_build_out_prefix(src: Path) -> None:
    """Ensure any relative OUT_DIR (e.g. out/ossi/5.15.149) gets BUILD_TOP/ for kernel O=."""
    old = (
        "ifeq ($(OUT_DIR_PREFIX),out)\n"
        "    KERNEL_BUILD_OUT_PREFIX := $(BUILD_TOP)/\n"
        "endif"
    )
    new = (
        "ifeq ($(filter /%,$(OUT_DIR_PREFIX)),)\n"
        "    KERNEL_BUILD_OUT_PREFIX := $(BUILD_TOP)/\n"
        "endif"
    )
    for rel in (
        "vendor/infinity/config/BoardConfigKernel.mk",
        "vendor/lineage/config/BoardConfigKernel.mk",
    ):
        _patch_text(src / rel, lambda text: text.replace(old, new, 1) if old in text else text)


def patch_telephony_framework_compat(src: Path) -> None:
    """Bridge newer Lineage Telephony security checks onto Infinity-X frameworks/base."""
    tp_java = src / "frameworks/base/telephony/common/com/android/internal/telephony/TelephonyPermissions.java"
    tm_java = src / "frameworks/base/telephony/java/android/telephony/TelephonyManager.java"
    pim_java = src / "packages/services/Telephony/src/com/android/phone/PhoneInterfaceManager.java"
    ccl_java = src / "packages/services/Telephony/src/com/android/phone/CarrierConfigLoader.java"

    if tp_java.is_file() and "boolean isShell(" not in tp_java.read_text(encoding="utf-8"):
        _patch_text(
            pim_java,
            lambda text: text.replace(
                "TelephonyPermissions.isShell(Binder.getCallingUid())",
                "UserHandle.isSameApp(Binder.getCallingUid(), Process.SHELL_UID)",
            ),
        )
        _patch_text(
            ccl_java,
            lambda text: text.replace(
                "TelephonyPermissions.isShell(getBinderCallingUid())",
                "UserHandle.isSameApp(getBinderCallingUid(), Process.SHELL_UID)",
            ),
        )

    if tm_java.is_file() and "String getModemService(" not in tm_java.read_text(encoding="utf-8"):
        old_modem = (
            "            TelephonyManager tm = mContext.getSystemService(TelephonyManager.class);\n"
            "            String modemService = tm.getModemService();"
        )
        new_modem = (
            "            PhoneConfigurationManager pcm = PhoneConfigurationManager.getInstance();\n"
            "            String modemService = pcm != null ? pcm.getModemService() : null;"
        )
        _patch_text(
            ccl_java,
            lambda text: text.replace(old_modem, new_modem, 1) if old_modem in text else text,
        )


def patch_oplus_vendor_init_hook(src: Path) -> None:
    """Bridge Lineage 22.2 vendor_process_bootenv() to Infinity-X vendor_load_properties()."""
    vendor_init_h = src / "system/core/init/vendor_init.h"
    init_oplus = src / "device/oneplus/sm8550-common/init/init_oplus.cpp"
    if not vendor_init_h.is_file() or not init_oplus.is_file():
        return
    if "vendor_load_properties" not in vendor_init_h.read_text(encoding="utf-8"):
        return

    def add_bridge(text: str) -> str:
        if "void vendor_load_properties(" in text or "void vendor_process_bootenv(" not in text:
            return text
        suffix = "\n" if text.endswith("\n") else "\n\n"
        return (
            text
            + suffix
            + "void vendor_load_properties() {\n"
            + "    vendor_process_bootenv();\n"
            + "}\n"
        )

    _patch_text(init_oplus, add_bridge)


def apply_all(src: Path) -> None:
    patch_simple_settings_config(src)
    patch_infinity_livedisplay_and_matrix(src)
    patch_soong_custom_super_partitions(src)
    patch_dangling_kernel_include_symlinks(src)
    patch_kernel_build_out_prefix(src)
    patch_telephony_framework_compat(src)
    patch_oplus_vendor_init_hook(src)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: rom-patch-source.py <source-tree>", file=sys.stderr)
        return 2
    apply_all(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
