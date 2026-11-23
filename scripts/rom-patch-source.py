#!/usr/bin/env python3
"""Apply idempotent Infinity-X 15 compatibility patches after source/deps sync."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
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


def patch_soong_runtime_memory(src: Path) -> None:
    """Carry opt-in Go limits through Soong's clean env and honor its CPU limit."""
    changes = [
        (
            src / "build/soong/ui/build/soong.go",
            "\tinvocationEnv := make(map[string]string)\n",
            "\tinvocationEnv := make(map[string]string)\n"
            "\t// ossi: pass explicit host memory limits through the clean builder env.\n"
            '\tfor _, key := range []string{"GOGC", "GOMEMLIMIT", "GOMAXPROCS"} {\n'
            '\t\tif value, ok := pb.config.Environment().Get("SOONG_" + key); ok && value != "" {\n'
            "\t\t\tinvocationEnv[key] = value\n"
            "\t\t}\n"
            "\t}\n",
        ),
        (
            src / "build/blueprint/bootstrap/command.go",
            "\truntime.GOMAXPROCS(runtime.NumCPU())\n",
            "\t// ossi: retain an explicit runtime CPU limit on memory-constrained hosts.\n"
            '\tif os.Getenv("GOMAXPROCS") == "" {\n'
            "\t\truntime.GOMAXPROCS(runtime.NumCPU())\n"
            "\t}\n",
        ),
    ]
    # Validate every anchor first, so source changes cannot leave a partial patch.
    pending = []
    for path, old, new in changes:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        if new in original:
            continue
        if original.count(old) != 1:
            raise RuntimeError(f"Soong memory patch needs review: {path}")
        pending.append((path, original.replace(old, new, 1)))
    for path, updated in pending:
        path.write_text(updated, encoding="utf-8")


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


def patch_oplus_richtap_libaacvibrator(src: Path) -> None:
    """Link oplus-richtap vibrator against the real prebuilt vendor/realme/ossi libaacvibrator."""
    vendor_bp = src / "vendor/realme/ossi/Android.bp"
    oplus_ns = src / "hardware/oplus/Android.bp"
    richtap_bp = src / "hardware/oplus/aidl/vibrator/richtap/Android.bp"
    if not (vendor_bp.is_file() and oplus_ns.is_file() and richtap_bp.is_file()):
        return
    if 'name: "libaacvibrator"' not in vendor_bp.read_text(encoding="utf-8"):
        return

    def add_vendor_import(text: str) -> str:
        if '"vendor/realme/ossi"' in text:
            return text
        anchor = '        "hardware/google/pixel",\n'
        if anchor in text:
            return text.replace(anchor, anchor + '        "vendor/realme/ossi",\n', 1)
        return re.sub(
            r'(soong_namespace\s*\{\s*imports:\s*\[)',
            r'\1\n        "vendor/realme/ossi",',
            text,
            count=1,
        )

    def drop_dummy_stub(text: str) -> str:
        return re.sub(
            r'\n*cc_library_shared\s*\{\s*name:\s*"libaacvibrator",\s*soc_specific:\s*true,\s*\}\s*\n?',
            "\n",
            text,
            count=1,
        )

    _patch_text(oplus_ns, add_vendor_import)
    _patch_text(richtap_bp, drop_dummy_stub)


def patch_releasetools_mkbootimg_arg_order(src: Path) -> None:
    """Keep board mkbootimg_args overrides after mkbootimg_version_args, matching core/Makefile."""
    common_py = src / "build/make/tools/releasetools/common.py"
    old_boot = (
        '  if partition_name == "recovery":\n'
        '    args = info_dict.get("recovery_mkbootimg_args")\n'
        '    if not args:\n'
        '      # Fall back to "mkbootimg_args" for recovery image\n'
        '      # in case "recovery_mkbootimg_args" is not set.\n'
        '      args = info_dict.get("mkbootimg_args")\n'
        '  elif partition_name == "init_boot":\n'
        '    args = info_dict.get("mkbootimg_init_args")\n'
        '  else:\n'
        '    args = info_dict.get("mkbootimg_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
        '\n'
        '  args = info_dict.get("mkbootimg_version_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
    )
    new_boot = (
        '  args = info_dict.get("mkbootimg_version_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
        '\n'
        '  if partition_name == "recovery":\n'
        '    args = info_dict.get("recovery_mkbootimg_args")\n'
        '    if not args:\n'
        '      # Fall back to "mkbootimg_args" for recovery image\n'
        '      # in case "recovery_mkbootimg_args" is not set.\n'
        '      args = info_dict.get("mkbootimg_args")\n'
        '  elif partition_name == "init_boot":\n'
        '    args = info_dict.get("mkbootimg_init_args")\n'
        '  else:\n'
        '    args = info_dict.get("mkbootimg_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
    )
    old_vendor = (
        '  args = info_dict.get("mkbootimg_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
        '\n'
        '  args = info_dict.get("mkbootimg_version_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
    )
    new_vendor = (
        '  args = info_dict.get("mkbootimg_version_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
        '\n'
        '  args = info_dict.get("mkbootimg_args")\n'
        '  if args and args.strip():\n'
        '    cmd.extend(shlex.split(args))\n'
    )

    def reorder(text: str) -> str:
        if old_boot in text:
            text = text.replace(old_boot, new_boot, 1)
        if old_vendor in text:
            text = text.replace(old_vendor, new_vendor, 1)
        return text

    _patch_text(common_py, reorder)


def patch_lineage_vendor_property_contexts(src: Path) -> None:
    """Drop ro.vendor.dolby.dax.version from system_ext property_contexts to prevent ColorOS vendor TrieBuilder collisions."""
    pc = src / "device/lineage/sepolicy/common/private/property_contexts"
    if not pc.is_file():
        return

    def drop_dolby_collision(text: str) -> str:
        lines = [line for line in text.splitlines(keepends=True) if not line.lstrip().startswith("ro.vendor.dolby.dax.version")]
        return "".join(lines)

    _patch_text(pc, drop_dolby_collision)


def patch_infinity_zh_cn_translations(src: Path, translations_root: Path | None = None) -> int:
    """Install Simplified Chinese (zh-rCN) supplement XMLs while filtering any keys already defined upstream."""
    if translations_root is None:
        translations_root = Path(__file__).resolve().parent.parent / "rom/translations/zh-rCN"
    if not translations_root.is_dir():
        return 0

    ET.register_namespace("xliff", "urn:oasis:names:tc:xliff:document:1.2")
    installed = 0
    for extra_xml in sorted(translations_root.rglob("infinity_zh_cn_extra.xml")):
        rel = extra_xml.relative_to(translations_root)
        target_xml = src / rel
        res_dir = target_xml.parent.parent  # .../res
        if not res_dir.is_dir():
            continue

        # Collect existing zh-rCN keys from other XML files so upstream additions never trigger aapt2 duplicates.
        existing_keys: set[tuple[str, str]] = set()
        zh_dir = target_xml.parent
        if zh_dir.is_dir():
            for peer in sorted(zh_dir.glob("*.xml")):
                if peer.name == target_xml.name:
                    continue
                try:
                    peer_root = ET.parse(peer).getroot()
                except ET.ParseError:
                    continue
                for el in peer_root:
                    name = el.attrib.get("name")
                    if name:
                        existing_keys.add((el.tag, name))

        src_root = ET.parse(extra_xml).getroot()
        kept_elements = [
            el for el in src_root
            if (el.tag, el.attrib.get("name", "")) not in existing_keys
        ]
        if not kept_elements:
            if target_xml.is_file():
                target_xml.unlink()
            continue

        zh_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<!-- Auto-merged Simplified Chinese (zh-rCN) supplement for Project Infinity-X 2.9 -->',
            '<resources xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2">',
        ]
        for el in kept_elements:
            frag = ET.tostring(el, encoding="unicode").strip()
            frag = frag.replace(' xmlns:xliff="urn:oasis:names:tc:xliff:document:1.2"', "")
            for line in frag.splitlines():
                lines.append("    " + line)
        lines.append("</resources>")
        target_xml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        installed += len(kept_elements)
    return installed


def patch_cn_captive_portal(src: Path) -> None:
    """Use Mainland China reachable captive-portal validation URLs by default (even without SIM inserted)."""
    ns_res = src / "packages/modules/NetworkStack/res"
    val_cfg = ns_res / "values/config.xml"
    mcc_cfg = ns_res / "values-mcc460/config.xml"

    def update_values(text: str) -> str:
        text = text.replace(
            '<string name="default_captive_portal_http_url" translatable="false">http://connectivitycheck.gstatic.com/generate_204</string>',
            '<string name="default_captive_portal_http_url" translatable="false">http://connect.rom.miui.com/generate_204</string>',
        )
        text = text.replace(
            '<string name="default_captive_portal_https_url" translatable="false">https://www.google.com/generate_204</string>',
            '<string name="default_captive_portal_https_url" translatable="false">https://connect.rom.miui.com/generate_204</string>',
        )
        text = text.replace(
            "        <item>http://www.google.com/gen_204</item>\n"
            "        <item>http://play.googleapis.com/generate_204</item>",
            "        <item>http://connectivitycheck.qualcomm.cn/generate_204</item>\n"
            "        <item>http://connectivitycheck.gstatic.cn/generate_204</item>",
        )
        text = text.replace(
            '<bool name="config_no_sim_card_uses_neighbor_mcc">false</bool>',
            '<bool name="config_no_sim_card_uses_neighbor_mcc">true</bool>',
        )
        return text

    def update_mcc460(text: str) -> str:
        text = text.replace(
            '<string name="default_captive_portal_http_url" translatable="false">http://connectivitycheck.gstatic.cn/generate_204</string>',
            '<string name="default_captive_portal_http_url" translatable="false">http://connect.rom.miui.com/generate_204</string>',
        )
        text = text.replace(
            '<string name="default_captive_portal_https_url" translatable="false">https://connectivitycheck.gstatic.cn/generate_204</string>',
            '<string name="default_captive_portal_https_url" translatable="false">https://connect.rom.miui.com/generate_204</string>',
        )
        text = text.replace(
            "        <item>http://www.googleapis.cn/generate_204</item>",
            "        <item>http://connectivitycheck.qualcomm.cn/generate_204</item>\n"
            "        <item>http://connectivitycheck.gstatic.cn/generate_204</item>",
        )
        return text

    _patch_text(val_cfg, update_values)
    _patch_text(mcc_cfg, update_mcc460)


def apply_all(src: Path) -> None:
    patch_soong_runtime_memory(src)
    patch_simple_settings_config(src)
    patch_infinity_livedisplay_and_matrix(src)
    patch_soong_custom_super_partitions(src)
    patch_dangling_kernel_include_symlinks(src)
    patch_kernel_build_out_prefix(src)
    patch_telephony_framework_compat(src)
    patch_oplus_vendor_init_hook(src)
    patch_oplus_richtap_libaacvibrator(src)
    patch_releasetools_mkbootimg_arg_order(src)
    patch_lineage_vendor_property_contexts(src)
    patch_infinity_zh_cn_translations(src)
    patch_cn_captive_portal(src)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: rom-patch-source.py <source-tree>", file=sys.stderr)
        return 2
    apply_all(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
