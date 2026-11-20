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


def apply_all(src: Path) -> None:
    patch_simple_settings_config(src)
    patch_infinity_livedisplay_and_matrix(src)
    patch_soong_custom_super_partitions(src)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: rom-patch-source.py <source-tree>", file=sys.stderr)
        return 2
    apply_all(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
