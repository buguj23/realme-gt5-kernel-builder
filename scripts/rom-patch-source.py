#!/usr/bin/env python3
"""Apply idempotent Project Infinity-X 3.12 (Android 16 / bp4a) Treble GSI patches.

Includes:
  1. Soong/Blueprint host memory limits (SOONG_GOGC / SOONG_GOMEMLIMIT / SOONG_GOMAXPROCS)
  2. Upstream Infinity-X 16 GSI product fixes (infinity_gsi_arm64.mk, gsi_system_ext.mk,
     gsi_arm64.mk, gsi_product.mk, build/make/target/product/gsi/Android.bp)
  3. Realme GT5 (RMX3820_15.0.0.320 / 5.15.149) vendor compatibility:
     - Strip vendor/odm entries from system_ext property_contexts (ColorOS TrieBuilder fix)
     - Remove permissive backuptool for strict Android 16 user builds
     - OPLUS/OPPO optical UDFPS SurfaceFlinger Z-order fix (0x41000005 / 0x41000033)
  4. Custom ROM / LineageOS anti-detection patches adapted from yokeshiq's repos for Android 16:
     - bionic/libc/bionic/custom_rom_hide.cpp (allowlist, /data/resource-cache/*lineage*,
       /etc/selinux/ blocking, dirent filtering, /etc/sysconfig/*.xml filtering, full prop hiding)
     - frameworks/base (12 Java files: ApkAssets, AssetManager, Resources, ServiceManager,
       SystemProperties, SettingsProvider, BroadcastController, ComputerEngine,
       PackageManagerService, ResolveIntentHelper, PackageInfoUtils, PermissionManagerService)
     - vendor/infinity/config/version.mk (drop ro.modversion) + Updater Constants.java migration
  5. Unified Simplified Chinese (zh-rCN) supplement localization (20 packages, ~9,000 entries)
     with default-key + upstream-dedup filtering so aapt2 never emits warnings or duplicates
  6. Mainland China captive-portal default URLs (NetworkStack values & values-mcc460)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def _patch_text(path: Path, transform) -> bool:
    if not path.is_file():
        return False
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _replace_once_or_checked(text: str, old: str, new: str, *, marker: str, label: str) -> str:
    if marker in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 anchor match, found {count}")
    return text.replace(old, new, 1)


def patch_soong_runtime_memory(src: Path) -> None:
    """Carry opt-in Go limits through Soong's clean env and honor its CPU limit."""
    changes = [
        (
            src / "build/soong/ui/build/soong.go",
            "\tinvocationEnv := make(map[string]string)\n",
            "\tinvocationEnv := make(map[string]string)\n"
            "\t// gsi-3.12: pass explicit host memory limits through the clean builder env.\n"
            '\tfor _, key := range []string{"GOGC", "GOMEMLIMIT", "GOMAXPROCS"} {\n'
            '\t\tif value, ok := pb.config.Environment().Get("SOONG_" + key); ok && value != "" {\n'
            "\t\t\tinvocationEnv[key] = value\n"
            "\t\t}\n"
            "\t}\n",
            'pb.config.Environment().Get("SOONG_" + key)',
        ),
        (
            src / "build/blueprint/bootstrap/command.go",
            "\truntime.GOMAXPROCS(runtime.NumCPU())\n",
            "\t// gsi-3.12: retain an explicit runtime CPU limit on memory-constrained hosts.\n"
            '\tif os.Getenv("GOMAXPROCS") == "" {\n'
            "\t\truntime.GOMAXPROCS(runtime.NumCPU())\n"
            "\t}\n",
            'os.Getenv("GOMAXPROCS") == ""',
        ),
    ]
    pending = []
    for path, old, new, marker in changes:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        if marker in original:
            continue
        if original.count(old) != 1:
            raise RuntimeError(f"Soong memory patch needs review: {path}")
        pending.append((path, original.replace(old, new, 1)))
    for path, updated in pending:
        path.write_text(updated, encoding="utf-8")


def patch_infinity_gsi_product(src: Path) -> None:
    """Fix upstream Infinity-X 16 GSI product definitions and user-build SELinux debug policy leak."""
    # 1. vendor/infinity/build/target/product/infinity_gsi_arm64.mk
    gsi_mk = src / "vendor/infinity/build/target/product/infinity_gsi_arm64.mk"
    def fix_infinity_gsi_mk(text: str) -> str:
        text = text.replace(
            "include vendor/infinity/build/target/product/lineage_generic_target.mk",
            "include vendor/infinity/build/target/product/infinity_generic_target.mk",
        )
        text = text.replace(
            "PRODUCT_NAME := lineage_gsi_arm64",
            "PRODUCT_NAME := infinity_gsi_arm64",
        )
        if "building_lineage_gsi" not in text:
            text = text.rstrip() + (
                "\n\n# Disable AOSP Soong-defined GSI system images in favor of Make-based Infinity-X GSI\n"
                "$(call soong_config_set_bool,gsi,building_lineage_gsi,true)\n"
                "PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := false\n"
            )
        return text
    _patch_text(gsi_mk, fix_infinity_gsi_mk)

    # 2. device/generic/common/gsi_arm64.mk
    arm64_mk = src / "device/generic/common/gsi_arm64.mk"
    _patch_text(
        arm64_mk,
        lambda t: t.replace(
            "PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := true",
            "PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := false",
        ),
    )

    # 3. device/generic/common/gsi_system_ext.mk
    # Guard compliance debug policy so user builds NEVER ship system_ext_userdebug_plat_sepolicy.cil
    # (which otherwise injects shell->su and adbd->adbroot rules into live SELinux policy!).
    sys_ext_mk = src / "device/generic/common/gsi_system_ext.mk"
    old_dbg = (
        "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := true\n"
        "PRODUCT_PACKAGES += system_ext_userdebug_plat_sepolicy.cil"
    )
    new_dbg = (
        "ifneq ($(filter userdebug eng,$(TARGET_BUILD_VARIANT)),)\n"
        "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := true\n"
        "PRODUCT_PACKAGES += system_ext_userdebug_plat_sepolicy.cil\n"
        "else\n"
        "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := false\n"
        "endif"
    )
    _patch_text(
        sys_ext_mk,
        lambda t: t if "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := false" in t else t.replace(old_dbg, new_dbg, 1),
    )

    # 4. device/generic/common/gsi_product.mk — strip duplicate AOSP apns-full-conf copy rule
    gsi_prod_mk = src / "device/generic/common/gsi_product.mk"
    def strip_dup_apns(text: str) -> str:
        return re.sub(
            r"\n?PRODUCT_COPY_FILES\s*\+=\s*\\\n\s*device/sample/etc/apns-full-conf\.xml:[^\n]+\n?",
            "\n",
            text,
        )
    _patch_text(gsi_prod_mk, strip_dup_apns)

    # 5. build/make/target/product/gsi/Android.bp — disable android_gsi when building_lineage_gsi=true
    gsi_bp = src / "build/make/target/product/gsi/Android.bp"
    old_android_gsi_enabled = (
        '    enabled: select(soong_config_variable("ANDROID", "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT"), {\n'
        '        "true": true,\n'
        '        default: false,\n'
        '    }),'
    )
    new_android_gsi_enabled = (
        '    enabled: select((soong_config_variable("ANDROID", "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT"),\n'
        '                     soong_config_variable("gsi", "building_lineage_gsi")), {\n'
        '        ("true", true): false,\n'
        '        ("true", default): true,\n'
        '        default: false,\n'
        '    }),'
    )
    _patch_text(
        gsi_bp,
        lambda t: t if '("true", true): false' in t else t.replace(old_android_gsi_enabled, new_android_gsi_enabled, 1),
    )


def patch_lineage_vendor_property_contexts(src: Path) -> None:
    """Strip vendor/odm property_contexts entries from system_ext to prevent ColorOS TrieBuilder collisions."""
    pc = src / "device/lineage/sepolicy/common/private/property_contexts"
    if not pc.is_file():
        return

    vendor_re = re.compile(r"^(?:ro\.vendor\.|vendor\.|persist\.vendor\.|ro\.odm\.)")

    def strip_vendor_entries(text: str) -> str:
        lines = [
            line for line in text.splitlines(keepends=True)
            if not vendor_re.match(line.lstrip())
        ]
        return "".join(lines)

    _patch_text(pc, strip_vendor_entries)


def patch_sepolicy_user_build_compat(src: Path) -> None:
    """Remove permissive backuptool domain so Android 16 user builds pass strict SELinux checks."""
    bt = src / "device/lineage/sepolicy/common/private/backuptool.te"
    _patch_text(
        bt,
        lambda t: re.sub(
            r"(?m)^permissive backuptool;\s*$",
            "# permissive backuptool; # disabled for Android 16 user build SELinux compliance",
            t,
        ),
    )


def patch_oplus_udfps_extension(src: Path) -> None:
    """Apply OPLUS/OPPO/Realme optical UDFPS Z-order fix in SurfaceFlinger UdfpsExtension.cpp."""
    ext = src / "frameworks/native/services/surfaceflinger/CompositionEngine/src/UdfpsExtension.cpp"
    if not ext.is_file():
        return

    def update_udfps(text: str) -> str:
        if "0x41000033" in text:
            return text
        text = text.replace(
            "uint32_t getUdfpsDimZOrder(uint32_t z) {\n    return z;\n}",
            "uint32_t getUdfpsDimZOrder(uint32_t z) {\n"
            "    (void)z;\n"
            "    return 0x41000005u;\n"
            "}",
            1,
        )
        text = text.replace(
            "uint32_t getUdfpsZOrder(uint32_t z, __unused bool touched) {\n    return z;\n}",
            "uint32_t getUdfpsZOrder(uint32_t z, bool touched) {\n"
            "    if (touched) {\n"
            "        z = 0x41000033u;\n"
            "    }\n"
            "    return z;\n"
            "}",
            1,
        )
        return text

    _patch_text(ext, update_udfps)


def patch_yokeshiq_drop_ro_modversion(src: Path) -> None:
    """Drop ro.modversion from vendor/infinity/config/version.mk and migrate Updater to ro.infinity.build.version."""
    version_mk = src / "vendor/infinity/config/version.mk"
    def clean_version_mk(text: str) -> str:
        out = []
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith("ro.modversion="):
                continue
            if stripped.startswith("ro.infinity.device=$(INFINITY_BUILD)"):
                continue
            out.append(line)
        return "".join(out)
    _patch_text(version_mk, clean_version_mk)

    updater_const = src / "packages/apps/Updater/app/src/main/java/com/infinity/updater/misc/Constants.java"
    _patch_text(
        updater_const,
        lambda t: t.replace(
            'public static final String PROP_BUILD_VERSION = "ro.modversion";',
            'public static final String PROP_BUILD_VERSION = "ro.infinity.build.version";',
        ),
    )


def patch_yokeshiq_bionic_lineage_hide(src: Path) -> None:
    """Enhance Infinity-X 16 bionic custom_rom_hide.cpp with yokeshiq's anti-detection rules.

    Covers:
      - SystemUI / Settings / Launcher / Shell / org.lineageos.* allowlist
      - Blocking /data/resource-cache/*lineage* idmap caches
      - Blocking /etc/selinux/ probes (ROM detected (a)) consistently across stat/lstat/faccessat/open
      - Blocking & dirent-filtering lineage / addon.d / hwservice_contexts / platform-infinity
      - Filtering */etc/sysconfig/*.xml (preinstalled-packages-platform-list-product.xml -> LineageOS (17))
      - Hiding all lineage / ro.modversion / ro.cm.* / ro.infinity.* properties via bionic prop APIs
    """
    hide_cpp = src / "bionic/libc/bionic/custom_rom_hide.cpp"
    if not hide_cpp.is_file():
        return

    def transform(text: str) -> str:
        # 1. Add system UI/settings/launcher/lineageos allowlist to compute_allowlisted()
        text = _replace_once_or_checked(
            text,
            '    for (const char* const* p = kAllowlistedPackages; *p; ++p) {\n'
            '        if (strcmp(cmdline, *p) == 0) return true;\n'
            '    }\n'
            '    return false;\n'
            '}',
            '    if (strcmp(cmdline, "com.android.systemui") == 0 ||\n'
            '        strcmp(cmdline, "com.android.settings") == 0 ||\n'
            '        strcmp(cmdline, "com.android.launcher3") == 0 ||\n'
            '        strcmp(cmdline, "com.android.shell") == 0 ||\n'
            '        strncmp(cmdline, "com.android.launcher", 20) == 0 ||\n'
            '        strncmp(cmdline, "org.lineageos.", 14) == 0) {\n'
            '        return true;\n'
            '    }\n'
            '    for (const char* const* p = kAllowlistedPackages; *p; ++p) {\n'
            '        if (strcmp(cmdline, *p) == 0) return true;\n'
            '    }\n'
            '    return false;\n'
            '}',
            marker='strncmp(cmdline, "org.lineageos.", 14) == 0',
            label="bionic/custom_rom_hide.cpp:compute_allowlisted",
        )

        # 2. Expand is_rom_path() with yokeshiq's static node / selinux / idmap rules
        text = _replace_once_or_checked(
            text,
            '    if (is_blocked_dir(clean)) return true;\n'
            '    return false;\n'
            '}',
            '    if (is_blocked_dir(clean)) return true;\n'
            '\n'
            '    // yokeshiq lineage_hide: allow app /data/* except Lineage idmap caches\n'
            '    if (strncmp(clean, "/data/", 6) == 0) {\n'
            '        return (strstr(clean, "resource-cache") != nullptr &&\n'
            '                strcasestr(clean, "lineage") != nullptr);\n'
            '    }\n'
            '    // Block SELinux policy directory probes (ROM detected (a))\n'
            '    if (strstr(clean, "/etc/selinux/") != nullptr) return true;\n'
            '    // Block Lineage / Infinity static artifacts and sysconfig files\n'
            '    if (strcasestr(clean, "lineage") != nullptr ||\n'
            '        strstr(clean, "addon.d") != nullptr ||\n'
            '        strstr(clean, "hwservice_contexts") != nullptr ||\n'
            '        strstr(clean, "platform-infinity") != nullptr) {\n'
            '        return true;\n'
            '    }\n'
            '    return false;\n'
            '}',
            marker='// yokeshiq lineage_hide: allow app /data/*',
            label="bionic/custom_rom_hide.cpp:is_rom_path",
        )

        # 3. Expand custom_rom_hide_should_filter_dirent() to filter Lineage/addon.d/hwservice_contexts/platform-infinity entries
        text = _replace_once_or_checked(
            text,
            '    char dir_path[256];\n'
            '    if (resolve_fd_path(dirfd, dir_path, sizeof(dir_path))) {\n'
            '        for (const char* const* pp = kDirParents; *pp; ++pp) {\n'
            '            if (strcmp(dir_path, *pp) == 0) {\n'
            '                for (const char* const* dn = kBlockedDirnames; *dn; ++dn) {\n'
            '                    if (strcmp(name, *dn) == 0) {\n'
            '                        result = true;\n'
            '                        break;\n'
            '                    }\n'
            '                }\n'
            '                break;\n'
            '            }\n'
            '        }\n'
            '    }',
            '    char dir_path[256];\n'
            '    bool has_dir = resolve_fd_path(dirfd, dir_path, sizeof(dir_path));\n'
            '    if (has_dir) {\n'
            '        for (const char* const* pp = kDirParents; *pp; ++pp) {\n'
            '            if (strcmp(dir_path, *pp) == 0) {\n'
            '                for (const char* const* dn = kBlockedDirnames; *dn; ++dn) {\n'
            '                    if (strcmp(name, *dn) == 0) {\n'
            '                        result = true;\n'
            '                        break;\n'
            '                    }\n'
            '                }\n'
            '                break;\n'
            '            }\n'
            '        }\n'
            '    }\n'
            '    if (!result) {\n'
            '        bool in_app_data = has_dir && strncmp(dir_path, "/data/", 6) == 0 &&\n'
            '                           strstr(dir_path, "resource-cache") == nullptr;\n'
            '        if (!in_app_data && (\n'
            '                strcasestr(name, "lineage") != nullptr ||\n'
            '                strstr(name, "addon.d") != nullptr ||\n'
            '                strstr(name, "hwservice_contexts") != nullptr ||\n'
            '                strstr(name, "platform-infinity") != nullptr)) {\n'
            '            result = true;\n'
            '        }\n'
            '    }',
            marker='bool in_app_data = has_dir && strncmp(dir_path, "/data/", 6) == 0',
            label="bionic/custom_rom_hide.cpp:should_filter_dirent",
        )

        # 4. Keep open("/etc/selinux/...") consistent with stat/faccessat (fall through to ENOENT)
        text = _replace_once_or_checked(
            text,
            'int custom_rom_hide_filter_sepolicy(const char* path) {\n'
            '    if (!is_app_process()) return -1;\n'
            '    if (!path || reinterpret_cast<uintptr_t>(path) < 0x1000000) return -1;',
            'int custom_rom_hide_filter_sepolicy(const char* path) {\n'
            '    if (!is_app_process()) return -1;\n'
            '    if (!path || reinterpret_cast<uintptr_t>(path) < 0x1000000) return -1;\n'
            '    // Defer /etc/selinux/ to custom_rom_hide_should_block() -> ENOENT (matches stat/faccessat)\n'
            '    if (strstr(path, "/etc/selinux/") != nullptr) return -1;',
            marker='// Defer /etc/selinux/ to custom_rom_hide_should_block()',
            label="bionic/custom_rom_hide.cpp:filter_sepolicy",
        )

        # 5. Also filter */etc/sysconfig/*.xml inside custom_rom_hide_filter_vintf()
        #    (strips org.lineageos.* <install-in-user-type> blocks -> defeats LineageOS detected (17))
        text = _replace_once_or_checked(
            text,
            '    for (const char* const* p = kVintfFilterPaths; *p; ++p) {\n'
            '        if (strcmp(path, *p) == 0) { match = true; break; }\n'
            '    }\n'
            '    if (!match) { errno = saved_errno; return -1; }',
            '    for (const char* const* p = kVintfFilterPaths; *p; ++p) {\n'
            '        if (strcmp(path, *p) == 0) { match = true; break; }\n'
            '    }\n'
            '    if (!match && strstr(path, "/etc/sysconfig/") != nullptr &&\n'
            '        strstr(path, ".xml") != nullptr && strcasestr(path, "lineage") == nullptr) {\n'
            '        match = true;\n'
            '    }\n'
            '    if (!match) { errno = saved_errno; return -1; }',
            marker='strstr(path, "/etc/sysconfig/") != nullptr',
            label="bionic/custom_rom_hide.cpp:filter_vintf_match",
        )
        text = _replace_once_or_checked(
            text,
            '        bool opens_block  = strstr(pos, "<hal") != nullptr || strstr(pos, "<interface") != nullptr;\n'
            '        bool closes_block = strstr(pos, "</hal>") != nullptr || strstr(pos, "</interface>") != nullptr;',
            '        bool opens_block  = strstr(pos, "<hal") != nullptr || strstr(pos, "<interface") != nullptr ||\n'
            '                            strstr(pos, "<install-in-user-type") != nullptr;\n'
            '        bool closes_block = strstr(pos, "</hal>") != nullptr || strstr(pos, "</interface>") != nullptr ||\n'
            '                            strstr(pos, "</install-in-user-type>") != nullptr;',
            marker='strstr(pos, "<install-in-user-type") != nullptr',
            label="bionic/custom_rom_hide.cpp:filter_vintf_sysconfig_blocks",
        )

        # 6. Broaden property hiding to all lineage / ro.modversion / ro.cm.* / ro.infinity.* keys
        text = _replace_once_or_checked(
            text,
            'bool custom_rom_hide_should_spoof_prop(const char* name, char* value) {\n'
            '    if (!name || !value) return false;\n'
            '    if (reinterpret_cast<uintptr_t>(name) < 0x1000000) return false;\n'
            '    if (reinterpret_cast<uintptr_t>(value) < 0x1000000) return false;\n'
            '    if (!is_app_process()) return false;\n'
            '    for (const char* const* p = kSpoofedEmptyProps; *p; ++p) {\n'
            '        if (strcmp(name, *p) == 0) { value[0] = \'\\0\'; return true; }\n'
            '    }\n'
            '    for (const PropOverride* o = kSpoofedValueProps; o->name; ++o) {\n'
            '        if (strcmp(name, o->name) == 0) { strcpy(value, o->value); return true; }\n'
            '    }\n'
            '    return false;\n'
            '}\n'
            '\n'
            'bool custom_rom_hide_should_hide_prop(const char* name) {\n'
            '    if (!name || reinterpret_cast<uintptr_t>(name) < 0x1000000) return false;\n'
            '    if (!is_app_process()) return false;\n'
            '    for (const char* const* p = kSpoofedEmptyProps; *p; ++p) {\n'
            '        if (strcmp(name, *p) == 0) return true;\n'
            '    }\n'
            '    return false;\n'
            '}',
            'static bool is_hidden_rom_prop(const char* name) {\n'
            '    for (const char* const* p = kSpoofedEmptyProps; *p; ++p) {\n'
            '        if (strcmp(name, *p) == 0) return true;\n'
            '    }\n'
            '    if (strcasestr(name, "lineage") != nullptr ||\n'
            '        strstr(name, "ro.modversion") != nullptr ||\n'
            '        strncasecmp(name, "ro.cm.", 6) == 0 ||\n'
            '        strncasecmp(name, "ro.infinity.", 12) == 0) {\n'
            '        return true;\n'
            '    }\n'
            '    return false;\n'
            '}\n'
            '\n'
            'bool custom_rom_hide_should_spoof_prop(const char* name, char* value) {\n'
            '    if (!name || !value) return false;\n'
            '    if (reinterpret_cast<uintptr_t>(name) < 0x1000000) return false;\n'
            '    if (reinterpret_cast<uintptr_t>(value) < 0x1000000) return false;\n'
            '    if (!is_app_process()) return false;\n'
            '    if (is_hidden_rom_prop(name)) { value[0] = \'\\0\'; return true; }\n'
            '    for (const PropOverride* o = kSpoofedValueProps; o->name; ++o) {\n'
            '        if (strcmp(name, o->name) == 0) { strcpy(value, o->value); return true; }\n'
            '    }\n'
            '    return false;\n'
            '}\n'
            '\n'
            'bool custom_rom_hide_should_hide_prop(const char* name) {\n'
            '    if (!name || reinterpret_cast<uintptr_t>(name) < 0x1000000) return false;\n'
            '    if (!is_app_process()) return false;\n'
            '    return is_hidden_rom_prop(name);\n'
            '}',
            marker='static bool is_hidden_rom_prop(const char* name)',
            label="bionic/custom_rom_hide.cpp:is_hidden_rom_prop",
        )

        return text

    _patch_text(hide_cpp, transform)


def patch_yokeshiq_frameworks_base_lineage_hide(src: Path) -> int:
    """Apply all 12 yokeshiq frameworks/base anti-detection hooks rebased for Infinity-X 16 (3.12).

    Returns the number of Java files modified.
    """
    fwb = src / "frameworks/base"
    if not fwb.is_dir():
        return 0

    changed = 0

    # 1. ApkAssets.java
    def _apk_assets(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "    @UnsupportedAppUsage\n"
            "    public @NonNull String getAssetPath() {\n"
            "        synchronized (this) {\n"
            "            return TextUtils.emptyIfNull(nativeGetAssetPath(mNativePtr));\n"
            "        }\n"
            "    }",
            "    @UnsupportedAppUsage\n"
            "    public @NonNull String getAssetPath() {\n"
            "        synchronized (this) {\n"
            "            final String path = TextUtils.emptyIfNull(nativeGetAssetPath(mNativePtr));\n"
            "            if (android.os.Process.myUid() >= android.os.Process.FIRST_APPLICATION_UID) {\n"
            '                if (path.toLowerCase().contains("lineage")) {\n'
            "                    final String currentPkg = android.app.ActivityThread.currentPackageName();\n"
            '                    if (currentPkg == null || (!currentPkg.startsWith("org.lineageos.")\n'
            '                            && !currentPkg.startsWith("com.android.launcher")\n'
            '                            && !"com.android.systemui".equals(currentPkg)\n'
            '                            && !"com.android.settings".equals(currentPkg))) {\n'
            '                        return ""; // gsi-3.12 lineage_hide\n'
            "                    }\n"
            "                }\n"
            "            }\n"
            "            return path;\n"
            "        }\n"
            "    }",
            marker="gsi-3.12 lineage_hide",
            label="ApkAssets.java:getAssetPath",
        )
        t = _replace_once_or_checked(
            t,
            "    public @NonNull String getDebugName() {\n"
            "        synchronized (this) {\n"
            '            return mNativePtr == 0 ? "<destroyed>" : nativeGetDebugName(mNativePtr);\n'
            "        }\n"
            "    }",
            "    public @NonNull String getDebugName() {\n"
            "        synchronized (this) {\n"
            "            if (mNativePtr == 0) {\n"
            '                return "<destroyed>";\n'
            "            }\n"
            "            final String name = nativeGetDebugName(mNativePtr);\n"
            "            if (android.os.Process.myUid() >= android.os.Process.FIRST_APPLICATION_UID\n"
            '                    && name != null && name.toLowerCase().contains("lineage")) {\n'
            "                final String currentPkg = android.app.ActivityThread.currentPackageName();\n"
            '                if (currentPkg == null || (!currentPkg.startsWith("org.lineageos.")\n'
            '                        && !currentPkg.startsWith("com.android.launcher")\n'
            '                        && !"com.android.systemui".equals(currentPkg)\n'
            '                        && !"com.android.settings".equals(currentPkg))) {\n'
            '                    return ""; // gsi-3.12 lineage_hide debugName\n'
            "                }\n"
            "            }\n"
            "            return name;\n"
            "        }\n"
            "    }",
            marker="gsi-3.12 lineage_hide debugName",
            label="ApkAssets.java:getDebugName",
        )
        return t

    # 2. AssetManager.java
    def _asset_manager(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "    public @NonNull String[] getApkPaths() {\n"
            "        synchronized (this) {\n"
            "            if (mOpen) {\n"
            "                String[] paths = new String[mApkAssets.length];",
            "    public @NonNull String[] getApkPaths() {\n"
            "        synchronized (this) {\n"
            "            if (mOpen) {\n"
            "                // gsi-3.12 lineage_hide\n"
            "                if (android.os.Process.myUid() >= android.os.Process.FIRST_APPLICATION_UID) {\n"
            "                    final String currentPkg = android.app.ActivityThread.currentPackageName();\n"
            '                    if (currentPkg == null || (!currentPkg.startsWith("org.lineageos.")\n'
            '                            && !currentPkg.startsWith("com.android.launcher")\n'
            '                            && !"com.android.systemui".equals(currentPkg)\n'
            '                            && !"com.android.settings".equals(currentPkg))) {\n'
            "                        java.util.ArrayList<String> list = new java.util.ArrayList<>();\n"
            "                        for (int i = 0; i < mApkAssets.length; i++) {\n"
            "                            String p = mApkAssets[i].getAssetPath();\n"
            '                            if (p != null && !p.isEmpty() && !p.toLowerCase().contains("lineage")) {\n'
            "                                list.add(p);\n"
            "                            }\n"
            "                        }\n"
            "                        return list.toArray(new String[0]);\n"
            "                    }\n"
            "                }\n"
            "                String[] paths = new String[mApkAssets.length];",
            marker="gsi-3.12 lineage_hide",
            label="AssetManager.java:getApkPaths",
        )

    # 3. Resources.java
    def _resources(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "    public int getIdentifier(String name, String defType, String defPackage) {\n"
            "        return mResourcesImpl.getIdentifier(name, defType, defPackage);\n"
            "    }",
            "    public int getIdentifier(String name, String defType, String defPackage) {\n"
            "        // gsi-3.12 lineage_hide\n"
            "        if (android.os.Process.myUid() >= android.os.Process.FIRST_APPLICATION_UID) {\n"
            '            final String pkg = (defPackage != null) ? defPackage.toLowerCase() : "";\n'
            '            final String resName = (name != null) ? name.toLowerCase() : "";\n'
            '            if (pkg.contains("lineage") || resName.contains("lineage")) {\n'
            "                final String currentPkg = android.app.ActivityThread.currentPackageName();\n"
            '                if (currentPkg == null || (!currentPkg.startsWith("org.lineageos.")\n'
            '                        && !currentPkg.startsWith("com.android.launcher")\n'
            '                        && !"com.android.systemui".equals(currentPkg)\n'
            '                        && !"com.android.settings".equals(currentPkg))) {\n'
            "                    return 0;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        return mResourcesImpl.getIdentifier(name, defType, defPackage);\n"
            "    }",
            marker="gsi-3.12 lineage_hide",
            label="Resources.java:getIdentifier",
        )

    # 4. ServiceManager.java (A16 uses @android.ravenwood.annotation.RavenwoodReplace)
    def _service_manager(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "    public static IBinder getService(String name) {\n"
            "        try {",
            "    // gsi-3.12 lineage_hide\n"
            "    private static boolean isBlockedService(String name) {\n"
            "        if (name == null || android.os.Process.myUid() < android.os.Process.FIRST_APPLICATION_UID) {\n"
            "            return false;\n"
            "        }\n"
            "        final String lower = name.toLowerCase();\n"
            '        if (lower.contains("lineage") || lower.startsWith("cm_")) {\n'
            "            final String pkg = android.app.ActivityThread.currentPackageName();\n"
            '            if (pkg != null && (pkg.startsWith("org.lineageos.")\n'
            '                    || pkg.startsWith("com.android.launcher")\n'
            '                    || "com.android.systemui".equals(pkg)\n'
            '                    || "com.android.settings".equals(pkg)\n'
            '                    || "com.android.shell".equals(pkg))) {\n'
            "                return false;\n"
            "            }\n"
            "            return true;\n"
            "        }\n"
            "        return false;\n"
            "    }\n"
            "\n"
            "    public static IBinder getService(String name) {\n"
            "        if (isBlockedService(name)) {\n"
            "            return null;\n"
            "        }\n"
            "        try {",
            marker="private static boolean isBlockedService(String name)",
            label="ServiceManager.java:getService",
        )
        t = _replace_once_or_checked(
            t,
            "    public static IBinder checkService(String name) {\n"
            "        try {",
            "    public static IBinder checkService(String name) {\n"
            "        if (isBlockedService(name)) {\n"
            "            return null;\n"
            "        }\n"
            "        try {",
            marker="public static IBinder checkService(String name) {\n        if (isBlockedService(name))",
            label="ServiceManager.java:checkService",
        )
        t = _replace_once_or_checked(
            t,
            "    public static String[] listServices() {\n"
            "        try {\n"
            "            return getIServiceManager().listServices(IServiceManager.DUMP_FLAG_PRIORITY_ALL);",
            "    public static String[] listServices() {\n"
            "        try {\n"
            "            String[] services = getIServiceManager().listServices(IServiceManager.DUMP_FLAG_PRIORITY_ALL);\n"
            "            if (services != null && android.os.Process.myUid() >= android.os.Process.FIRST_APPLICATION_UID) {\n"
            "                java.util.ArrayList<String> list = new java.util.ArrayList<>();\n"
            "                for (String s : services) {\n"
            "                    if (!isBlockedService(s)) {\n"
            "                        list.add(s);\n"
            "                    }\n"
            "                }\n"
            "                return list.toArray(new String[0]);\n"
            "            }\n"
            "            return services;",
            marker="if (!isBlockedService(s))",
            label="ServiceManager.java:listServices",
        )
        return t

    # 5. SystemProperties.java
    def _system_properties(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "    public static String get(@NonNull String key) {\n"
            "        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
            "        return native_get(key);\n"
            "    }",
            "    // gsi-3.12 lineage_hide\n"
            "    private static boolean isBlockedPropKey(String key) {\n"
            "        if (key == null || android.os.Process.myUid() < android.os.Process.FIRST_APPLICATION_UID) {\n"
            "            return false;\n"
            "        }\n"
            "        final String lower = key.toLowerCase();\n"
            '        if (lower.contains("lineage") || lower.startsWith("ro.lineage.")\n'
            '                || "ro.modversion".equals(lower) || lower.startsWith("ro.cm.")\n'
            '                || lower.startsWith("ro.infinity.")) {\n'
            "            final String pkg = android.app.ActivityThread.currentPackageName();\n"
            '            if (pkg != null && (pkg.startsWith("org.lineageos.")\n'
            '                    || pkg.startsWith("com.android.launcher")\n'
            '                    || "com.android.systemui".equals(pkg)\n'
            '                    || "com.android.settings".equals(pkg)\n'
            '                    || "com.infinity.updater".equals(pkg)\n'
            '                    || "com.android.shell".equals(pkg))) {\n'
            "                return false;\n"
            "            }\n"
            "            return true;\n"
            "        }\n"
            "        return false;\n"
            "    }\n"
            "\n"
            "    public static String get(@NonNull String key) {\n"
            "        if (isBlockedPropKey(key)) {\n"
            '            return "";\n'
            "        }\n"
            "        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
            "        return native_get(key);\n"
            "    }",
            marker="private static boolean isBlockedPropKey(String key)",
            label="SystemProperties.java:get",
        )
        t = _replace_once_or_checked(
            t,
            "    public static String get(@NonNull String key, @Nullable String def) {\n"
            "        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
            "        return native_get(key, def);\n"
            "    }",
            "    public static String get(@NonNull String key, @Nullable String def) {\n"
            "        if (isBlockedPropKey(key)) {\n"
            '            return def != null ? def : "";\n'
            "        }\n"
            "        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
            "        return native_get(key, def);\n"
            "    }",
            marker="public static String get(@NonNull String key, @Nullable String def) {\n        if (isBlockedPropKey(key))",
            label="SystemProperties.java:get_def",
        )
        for sig, call in (
            ("public static int getInt(@NonNull String key, int def)", "native_get_int(key, def)"),
            ("public static long getLong(@NonNull String key, long def)", "native_get_long(key, def)"),
            ("public static boolean getBoolean(@NonNull String key, boolean def)", "native_get_boolean(key, def)"),
        ):
            t = _replace_once_or_checked(
                t,
                f"    {sig} {{\n"
                f"        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
                f"        return {call};\n"
                f"    }}",
                f"    {sig} {{\n"
                f"        if (isBlockedPropKey(key)) {{\n"
                f"            return def;\n"
                f"        }}\n"
                f"        if (TRACK_KEY_ACCESS) onKeyAccess(key);\n"
                f"        return {call};\n"
                f"    }}",
                marker=f"{sig} {{\n        if (isBlockedPropKey(key))",
                label=f"SystemProperties.java:{sig}",
            )
        return t

    # 6. SettingsProvider.java
    def _settings_provider(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "        switch (method) {\n"
            "            case Settings.CALL_METHOD_GET_CONFIG -> {",
            "        // gsi-3.12 lineage_hide\n"
            "        final int callingUid = android.os.Binder.getCallingUid();\n"
            "        if (callingUid >= android.os.Process.FIRST_APPLICATION_UID && name != null) {\n"
            '            if (name.startsWith("lineage_") || name.startsWith("trust_") || name.startsWith("cm_")\n'
            '                    || name.startsWith("lineageos.") || name.startsWith("org.lineageos.")) {\n'
            "                String callingPkg = getCallingPackage();\n"
            '                boolean isWhitelisted = "com.android.systemui".equals(callingPkg)\n'
            '                        || "com.android.launcher3".equals(callingPkg)\n'
            '                        || "com.android.settings".equals(callingPkg)\n'
            '                        || "com.android.shell".equals(callingPkg)\n'
            '                        || (callingPkg != null && (callingPkg.startsWith("org.lineageos.")\n'
            '                                || callingPkg.startsWith("com.android.launcher")));\n'
            '                if (!isWhitelisted && method != null && method.startsWith("GET_")) {\n'
            "                    return android.os.Bundle.EMPTY;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "\n"
            "        switch (method) {\n"
            "            case Settings.CALL_METHOD_GET_CONFIG -> {",
            marker="gsi-3.12 lineage_hide",
            label="SettingsProvider.java:call",
        )

    # 7. BroadcastController.java (A16 anchor: if (!isCallerSystem) {\n            if (isProtectedBroadcast) {)
    def _broadcast_controller(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "        if (!isCallerSystem) {\n"
            "            if (isProtectedBroadcast",
            "        if (!isCallerSystem) {\n"
            "            // gsi-3.12 lineage_hide\n"
            '            if (action != null && action.toLowerCase().contains("lineage")) {\n'
            "                scheduleCanceledResultTo(resultToApp, resultTo, intent,\n"
            "                        userId, brOptions, callingUid, callerPackage);\n"
            "                return ActivityManager.BROADCAST_SUCCESS;\n"
            "            }\n"
            "            if (isProtectedBroadcast",
            marker="gsi-3.12 lineage_hide",
            label="BroadcastController.java:broadcastIntentLocked",
        )

    # 8. ComputerEngine.java (A16 exact anchors — no duplicate updateFlagsForPackage)
    def _computer_engine(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "    protected ApplicationInfo androidApplication() {\n"
            "        return mLocalAndroidApplication;\n"
            "    }",
            "    // gsi-3.12 lineage_hide\n"
            "    private static String[] filterLineageStringArray(String[] paths) {\n"
            "        if (paths == null || paths.length == 0) {\n"
            "            return paths;\n"
            "        }\n"
            "        ArrayList<String> filtered = new ArrayList<>(paths.length);\n"
            "        for (String path : paths) {\n"
            '            if (path != null && !path.toLowerCase().contains("lineage")) {\n'
            "                filtered.add(path);\n"
            "            }\n"
            "        }\n"
            "        return filtered.toArray(new String[0]);\n"
            "    }\n"
            "\n"
            "    private boolean isSystemWhitelistedUid(int uid) {\n"
            "        if (uid < Process.FIRST_APPLICATION_UID) {\n"
            "            return true;\n"
            "        }\n"
            "        final String[] callingPackages = getPackagesForUid(uid);\n"
            "        if (callingPackages != null) {\n"
            "            for (String pkg : callingPackages) {\n"
            '                if ("com.android.systemui".equals(pkg)\n'
            '                        || "com.android.launcher3".equals(pkg)\n'
            '                        || "com.android.settings".equals(pkg)\n'
            '                        || "com.android.shell".equals(pkg)\n'
            '                        || pkg.startsWith("org.lineageos.")\n'
            '                        || pkg.startsWith("com.android.launcher")) {\n'
            "                    return true;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        return false;\n"
            "    }\n"
            "\n"
            "    protected ApplicationInfo androidApplication() {\n"
            "        final int callingUid = Binder.getCallingUid();\n"
            "        if (callingUid >= Process.FIRST_APPLICATION_UID && !isSystemWhitelistedUid(callingUid)\n"
            "                && mLocalAndroidApplication != null) {\n"
            "            ApplicationInfo copy = new ApplicationInfo(mLocalAndroidApplication);\n"
            "            copy.resourceDirs = filterLineageStringArray(copy.resourceDirs);\n"
            "            copy.overlayPaths = filterLineageStringArray(copy.overlayPaths);\n"
            "            copy.sharedLibraryFiles = filterLineageStringArray(copy.sharedLibraryFiles);\n"
            "            return copy;\n"
            "        }\n"
            "        return mLocalAndroidApplication;\n"
            "    }",
            marker="private static String[] filterLineageStringArray",
            label="ComputerEngine.java:androidApplication",
        )
        t = _replace_once_or_checked(
            t,
            "    public final PackageInfo getPackageInfoInternal(String packageName, long versionCode,\n"
            "            long flags, int filterCallingUid, int userId) {\n"
            "        if (!mUserManager.exists(userId)) return null;\n"
            "        if (shouldHideFromCaller(filterCallingUid, packageName)) return null;\n"
            "        flags = updateFlagsForPackage(flags, userId);",
            "    public final PackageInfo getPackageInfoInternal(String packageName, long versionCode,\n"
            "            long flags, int filterCallingUid, int userId) {\n"
            "        if (!mUserManager.exists(userId)) return null;\n"
            "        if (shouldHideFromCaller(filterCallingUid, packageName)) return null;\n"
            "        // gsi-3.12 lineage_hide getPackageInfoInternal\n"
            "        if (filterCallingUid >= Process.FIRST_APPLICATION_UID && packageName != null) {\n"
            '            if (packageName.startsWith("org.lineageos.") || packageName.equals("lineageos.platform")) {\n'
            "                if (!isSystemWhitelistedUid(filterCallingUid)) {\n"
            "                    return null;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        flags = updateFlagsForPackage(flags, userId);",
            marker="gsi-3.12 lineage_hide getPackageInfoInternal",
            label="ComputerEngine.java:getPackageInfoInternal",
        )
        t = _replace_once_or_checked(
            t,
            "        // if we're in an isolated process, get the real calling UID\n"
            "        if (Process.isIsolated(callingUid)) {\n"
            "            callingUid = getIsolatedOwner(callingUid);\n"
            "        }\n"
            "        final String instantAppPkgName = getInstantAppPackageName(callingUid);",
            "        // if we're in an isolated process, get the real calling UID\n"
            "        if (Process.isIsolated(callingUid)) {\n"
            "            callingUid = getIsolatedOwner(callingUid);\n"
            "        }\n"
            "        // gsi-3.12 lineage_hide shouldFilterApplication\n"
            "        if (callingUid >= Process.FIRST_APPLICATION_UID && ps != null && ps.getPackageName() != null) {\n"
            "            if (UserHandle.getAppId(callingUid) != ps.getAppId()) {\n"
            "                final String pkgName = ps.getPackageName().toLowerCase();\n"
            "                final String pkgPath = ps.getPathString();\n"
            '                if (pkgName.contains("lineage")\n'
            '                        || (pkgPath != null && pkgPath.toLowerCase().contains("lineage"))) {\n'
            "                    if (!isSystemWhitelistedUid(callingUid)) {\n"
            "                        return true;\n"
            "                    }\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        final String instantAppPkgName = getInstantAppPackageName(callingUid);",
            marker="gsi-3.12 lineage_hide shouldFilterApplication",
            label="ComputerEngine.java:shouldFilterApplication",
        )
        t = _replace_once_or_checked(
            t,
            "    public ProviderInfo resolveContentProvider(@NonNull String name,\n"
            "            @PackageManager.ResolveInfoFlagsBits long flags, @UserIdInt int userId,\n"
            "            int callingUid) {\n"
            "        // Callers of this API may not always separate the userID and authority. Let's parse it",
            "    public ProviderInfo resolveContentProvider(@NonNull String name,\n"
            "            @PackageManager.ResolveInfoFlagsBits long flags, @UserIdInt int userId,\n"
            "            int callingUid) {\n"
            "        // gsi-3.12 lineage_hide resolveContentProvider\n"
            "        if (callingUid >= Process.FIRST_APPLICATION_UID && name != null) {\n"
            '            if (name.toLowerCase().contains("lineage")) {\n'
            "                if (!isSystemWhitelistedUid(callingUid)) {\n"
            "                    return null;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        // Callers of this API may not always separate the userID and authority. Let's parse it",
            marker="gsi-3.12 lineage_hide resolveContentProvider",
            label="ComputerEngine.java:resolveContentProvider",
        )
        return t

    # 9. PackageManagerService.java
    def _pms(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "    public boolean hasSystemFeature(String name, int version) {\n"
            "        // allow instant applications",
            "    public boolean hasSystemFeature(String name, int version) {\n"
            "        // gsi-3.12 lineage_hide hasSystemFeature\n"
            "        if (Binder.getCallingUid() >= Process.FIRST_APPLICATION_UID && name != null) {\n"
            '            if (name.startsWith("org.lineageos.") || name.startsWith("lineageos.")) {\n'
            "                return false;\n"
            "            }\n"
            "        }\n"
            "        // allow instant applications",
            marker="gsi-3.12 lineage_hide hasSystemFeature",
            label="PackageManagerService.java:hasSystemFeature",
        )
        t = _replace_once_or_checked(
            t,
            '            fi.reqGlEsVersion = SystemProperties.getInt("ro.opengles.version",\n'
            "                    FeatureInfo.GL_ES_VERSION_UNDEFINED);\n"
            "            res.add(fi);\n"
            "\n"
            "            return new ParceledListSlice<>(res);",
            '            fi.reqGlEsVersion = SystemProperties.getInt("ro.opengles.version",\n'
            "                    FeatureInfo.GL_ES_VERSION_UNDEFINED);\n"
            "            res.add(fi);\n"
            "\n"
            "            // gsi-3.12 lineage_hide getSystemAvailableFeatures\n"
            "            if (Binder.getCallingUid() >= Process.FIRST_APPLICATION_UID) {\n"
            "                res.removeIf(feat -> feat.name != null &&\n"
            '                        (feat.name.startsWith("org.lineageos.") || feat.name.startsWith("lineageos.")));\n'
            "            }\n"
            "\n"
            "            return new ParceledListSlice<>(res);",
            marker="gsi-3.12 lineage_hide getSystemAvailableFeatures",
            label="PackageManagerService.java:getSystemAvailableFeatures",
        )
        t = _replace_once_or_checked(
            t,
            "        @Override\n"
            "        public @NonNull List<String> getInitialNonStoppedSystemPackages() {\n"
            "            return mInitialNonStoppedSystemPackages != null\n"
            "                    ? new ArrayList<>(mInitialNonStoppedSystemPackages) : new ArrayList<>();\n"
            "        }",
            "        @Override\n"
            "        public @NonNull List<String> getInitialNonStoppedSystemPackages() {\n"
            "            ArrayList<String> list = mInitialNonStoppedSystemPackages != null\n"
            "                    ? new ArrayList<>(mInitialNonStoppedSystemPackages) : new ArrayList<>();\n"
            "            // gsi-3.12 lineage_hide getInitialNonStoppedSystemPackages\n"
            "            if (Binder.getCallingUid() >= Process.FIRST_APPLICATION_UID) {\n"
            '                list.removeIf(pkg -> pkg != null && pkg.toLowerCase().contains("lineage"));\n'
            "            }\n"
            "            return list;\n"
            "        }",
            marker="gsi-3.12 lineage_hide getInitialNonStoppedSystemPackages",
            label="PackageManagerService.java:getInitialNonStoppedSystemPackages",
        )
        t = _replace_once_or_checked(
            t,
            "        @Override\n"
            "        public boolean isProtectedBroadcast(String actionName) {\n"
            "            if (actionName != null) {\n"
            "                // TODO: remove these terrible hacks",
            "        @Override\n"
            "        public boolean isProtectedBroadcast(String actionName) {\n"
            "            if (actionName != null) {\n"
            "                // gsi-3.12 lineage_hide isProtectedBroadcast\n"
            "                final int callingUid = Binder.getCallingUid();\n"
            "                if (callingUid >= Process.FIRST_APPLICATION_UID\n"
            '                        && actionName.toLowerCase().contains("lineage")) {\n'
            "                    final String[] callingPackages = snapshotComputer().getPackagesForUid(callingUid);\n"
            "                    boolean isWhitelisted = false;\n"
            "                    if (callingPackages != null) {\n"
            "                        for (String pkg : callingPackages) {\n"
            '                            if ("com.android.systemui".equals(pkg)\n'
            '                                    || "com.android.launcher3".equals(pkg)\n'
            '                                    || "com.android.settings".equals(pkg)\n'
            '                                    || "com.android.shell".equals(pkg)\n'
            '                                    || pkg.startsWith("org.lineageos.")) {\n'
            "                                isWhitelisted = true;\n"
            "                                break;\n"
            "                            }\n"
            "                        }\n"
            "                    }\n"
            "                    if (!isWhitelisted) {\n"
            "                        return false;\n"
            "                    }\n"
            "                }\n"
            "                // TODO: remove these terrible hacks",
            marker="gsi-3.12 lineage_hide isProtectedBroadcast",
            label="PackageManagerService.java:isProtectedBroadcast",
        )
        return t

    # 10. ResolveIntentHelper.java
    def _resolve_intent(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "            @PackageManager.ResolveInfoFlagsBits long flags, int userId,\n"
            "            int filterCallingUid, int callingPid, boolean forSend) {\n"
            "        if (!mUserManager.exists(userId)) return Collections.emptyList();\n"
            "        // The identity used to filter the receiver components",
            "            @PackageManager.ResolveInfoFlagsBits long flags, int userId,\n"
            "            int filterCallingUid, int callingPid, boolean forSend) {\n"
            "        if (!mUserManager.exists(userId)) return Collections.emptyList();\n"
            "        // gsi-3.12 lineage_hide\n"
            "        if (filterCallingUid >= Process.FIRST_APPLICATION_UID && intent != null && intent.getAction() != null) {\n"
            "            final String action = intent.getAction().toLowerCase();\n"
            '            if (action.contains("lineage")) {\n'
            "                final String[] callingPackages = computer.getPackagesForUid(filterCallingUid);\n"
            "                boolean isWhitelisted = false;\n"
            "                if (callingPackages != null) {\n"
            "                    for (String pkg : callingPackages) {\n"
            '                        if ("com.android.systemui".equals(pkg)\n'
            '                                || "com.android.launcher3".equals(pkg)\n'
            '                                || "com.android.settings".equals(pkg)\n'
            '                                || "com.android.shell".equals(pkg)\n'
            '                                || pkg.startsWith("org.lineageos.")) {\n'
            "                            isWhitelisted = true;\n"
            "                            break;\n"
            "                        }\n"
            "                    }\n"
            "                }\n"
            "                if (!isWhitelisted) {\n"
            "                    return Collections.emptyList();\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        // The identity used to filter the receiver components",
            marker="gsi-3.12 lineage_hide",
            label="ResolveIntentHelper.java:queryIntentReceiversInternal",
        )

    # 11. PackageInfoUtils.java
    def _package_info_utils(t: str) -> str:
        t = _replace_once_or_checked(
            t,
            "            ai.resourceDirs = overlayPaths.getResourceDirs().toArray(new String[0]);\n"
            "            ai.overlayPaths = overlayPaths.getOverlayPaths().toArray(new String[0]);\n"
            "        }\n"
            "        ai.isArchived = PackageArchiver.isArchived(state);",
            "            ai.resourceDirs = overlayPaths.getResourceDirs().toArray(new String[0]);\n"
            "            ai.overlayPaths = overlayPaths.getOverlayPaths().toArray(new String[0]);\n"
            "        }\n"
            "        // gsi-3.12 lineage_hide\n"
            "        if ((ai.flags & ApplicationInfo.FLAG_SYSTEM) == 0 && android.os.Binder.getCallingUid() >= android.os.Process.FIRST_APPLICATION_UID) {\n"
            "            ai.resourceDirs = filterLineagePaths(ai.resourceDirs);\n"
            "            ai.overlayPaths = filterLineagePaths(ai.overlayPaths);\n"
            "            ai.sharedLibraryFiles = filterLineagePaths(ai.sharedLibraryFiles);\n"
            "        }\n"
            "        ai.isArchived = PackageArchiver.isArchived(state);",
            marker="filterLineagePaths(ai.resourceDirs)",
            label="PackageInfoUtils.java:updateApplicationInfo",
        )
        t = _replace_once_or_checked(
            t,
            "        updateApplicationInfo(ai, flags, state);\n"
            "        return ai;\n"
            "    }",
            "        updateApplicationInfo(ai, flags, state);\n"
            "        return ai;\n"
            "    }\n"
            "\n"
            "    private static String[] filterLineagePaths(String[] paths) {\n"
            "        if (paths == null || paths.length == 0) {\n"
            "            return paths;\n"
            "        }\n"
            "        java.util.ArrayList<String> filtered = new java.util.ArrayList<>(paths.length);\n"
            "        for (String path : paths) {\n"
            '            if (path != null && !path.toLowerCase().contains("lineage")) {\n'
            "                filtered.add(path);\n"
            "            }\n"
            "        }\n"
            "        return filtered.toArray(new String[0]);\n"
            "    }",
            marker="private static String[] filterLineagePaths",
            label="PackageInfoUtils.java:filterLineagePaths",
        )
        return t

    # 12. PermissionManagerService.java
    def _perm_mgr(t: str) -> str:
        return _replace_once_or_checked(
            t,
            "    @Override\n"
            "    public PermissionInfo getPermissionInfo(String permissionName, String packageName, int flags) {\n"
            "        return mPermissionManagerServiceImpl.getPermissionInfo(permissionName, flags, packageName);\n"
            "    }",
            "    // gsi-3.12 lineage_hide\n"
            "    private boolean isSystemWhitelistedUid(int uid) {\n"
            "        if (uid < Process.FIRST_APPLICATION_UID) {\n"
            "            return true;\n"
            "        }\n"
            "        final String[] callingPackages = mContext.getPackageManager().getPackagesForUid(uid);\n"
            "        if (callingPackages != null) {\n"
            "            for (String pkg : callingPackages) {\n"
            '                if ("com.android.systemui".equals(pkg)\n'
            '                        || "com.android.launcher3".equals(pkg)\n'
            '                        || "com.android.settings".equals(pkg)\n'
            '                        || "com.android.shell".equals(pkg)\n'
            '                        || pkg.startsWith("org.lineageos.")\n'
            '                        || pkg.startsWith("com.android.launcher")) {\n'
            "                    return true;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        return false;\n"
            "    }\n"
            "\n"
            "    @Override\n"
            "    public PermissionInfo getPermissionInfo(String permissionName, String packageName, int flags) {\n"
            "        final int callingUid = Binder.getCallingUid();\n"
            "        if (callingUid >= Process.FIRST_APPLICATION_UID && permissionName != null) {\n"
            '            if (permissionName.toLowerCase().contains("lineage")) {\n'
            "                if (!isSystemWhitelistedUid(callingUid)) {\n"
            "                    return null;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "        return mPermissionManagerServiceImpl.getPermissionInfo(permissionName, flags, packageName);\n"
            "    }",
            marker="gsi-3.12 lineage_hide",
            label="PermissionManagerService.java:getPermissionInfo",
        )

    targets = [
        ("core/java/android/content/res/ApkAssets.java", _apk_assets),
        ("core/java/android/content/res/AssetManager.java", _asset_manager),
        ("core/java/android/content/res/Resources.java", _resources),
        ("core/java/android/os/ServiceManager.java", _service_manager),
        ("core/java/android/os/SystemProperties.java", _system_properties),
        ("packages/SettingsProvider/src/com/android/providers/settings/SettingsProvider.java", _settings_provider),
        ("services/core/java/com/android/server/am/BroadcastController.java", _broadcast_controller),
        ("services/core/java/com/android/server/pm/ComputerEngine.java", _computer_engine),
        ("services/core/java/com/android/server/pm/PackageManagerService.java", _pms),
        ("services/core/java/com/android/server/pm/ResolveIntentHelper.java", _resolve_intent),
        ("services/core/java/com/android/server/pm/parsing/PackageInfoUtils.java", _package_info_utils),
        ("services/core/java/com/android/server/pm/permission/PermissionManagerService.java", _perm_mgr),
    ]
    for rel, fn in targets:
        if _patch_text(fwb / rel, fn):
            changed += 1
    return changed


def _collect_xml_keys(directory: Path, *, exclude_name: str = "") -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not directory.is_dir():
        return keys
    for xml_file in sorted(directory.glob("*.xml")):
        if exclude_name and xml_file.name == exclude_name:
            continue
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        for el in root:
            name = el.attrib.get("name")
            if name:
                keys.add((el.tag, name))
    return keys


def patch_infinity_zh_cn_translations(src: Path, translations_root: Path | None = None) -> int:
    """Install Simplified Chinese (zh-rCN) supplement XMLs safely for Android 16 (Infinity-X 3.12).

    Safety rules:
      1. Skip any (tag, name) already defined in upstream values-zh-rCN/*.xml (zero aapt2 duplicates).
      2. When default English values/*.xml exist in <res_dir>/values/, only emit keys that exist in
         default values/ (zero aapt2 missing-default-value errors across A15/A16/A17 drift).
    """
    if translations_root is None:
        translations_root = Path(__file__).resolve().parent.parent / "gsi/translations/zh-rCN"
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

        zh_dir = target_xml.parent
        existing_keys = _collect_xml_keys(zh_dir, exclude_name=target_xml.name)
        default_keys = _collect_xml_keys(res_dir / "values")

        src_root = ET.parse(extra_xml).getroot()
        kept_elements = []
        for el in src_root:
            key = (el.tag, el.attrib.get("name", ""))
            if not key[1] or key in existing_keys:
                continue
            if default_keys and key not in default_keys:
                continue
            kept_elements.append(el)

        if not kept_elements:
            if target_xml.is_file():
                target_xml.unlink()
            continue

        zh_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<!-- Auto-merged Simplified Chinese (zh-rCN) supplement for Project Infinity-X 3.12 (Android 16) GSI -->',
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
        for old_http in (
            "http://connectivitycheck.gstatic.com/generate_204",
            "http://connectivitycheck.gstatic.cn/generate_204",
        ):
            text = text.replace(
                f'<string name="default_captive_portal_http_url" translatable="false">{old_http}</string>',
                '<string name="default_captive_portal_http_url" translatable="false">http://connect.rom.miui.com/generate_204</string>',
            )
        for old_https in (
            "https://www.google.com/generate_204",
            "https://connectivitycheck.gstatic.cn/generate_204",
        ):
            text = text.replace(
                f'<string name="default_captive_portal_https_url" translatable="false">{old_https}</string>',
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
        for old_http in (
            "http://connectivitycheck.gstatic.cn/generate_204",
            "http://connectivitycheck.gstatic.com/generate_204",
        ):
            text = text.replace(
                f'<string name="default_captive_portal_http_url" translatable="false">{old_http}</string>',
                '<string name="default_captive_portal_http_url" translatable="false">http://connect.rom.miui.com/generate_204</string>',
            )
        for old_https in (
            "https://connectivitycheck.gstatic.cn/generate_204",
            "https://www.google.com/generate_204",
        ):
            text = text.replace(
                f'<string name="default_captive_portal_https_url" translatable="false">{old_https}</string>',
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


def apply_all(
    src: Path,
    *,
    lineage_hide: bool = True,
    translations: bool = True,
) -> dict[str, int]:
    patch_soong_runtime_memory(src)
    patch_infinity_gsi_product(src)
    patch_lineage_vendor_property_contexts(src)
    patch_sepolicy_user_build_compat(src)
    patch_oplus_udfps_extension(src)
    patch_cn_captive_portal(src)

    fwb_patched = 0
    if lineage_hide:
        patch_yokeshiq_drop_ro_modversion(src)
        patch_yokeshiq_bionic_lineage_hide(src)
        fwb_patched = patch_yokeshiq_frameworks_base_lineage_hide(src)

    zh_count = patch_infinity_zh_cn_translations(src) if translations else 0
    return {"fwb_lineage_hide_files": fwb_patched, "zh_cn_entries": zh_count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path, help="Path to Project Infinity-X 16 (3.12) source root")
    parser.add_argument("--no-lineage-hide", action="store_true", help="Skip yokeshiq anti-detection patches")
    parser.add_argument("--skip-translations", action="store_true", help="Skip zh-rCN supplement localization")
    args = parser.parse_args(argv)
    stats = apply_all(
        args.src,
        lineage_hide=not args.no_lineage_hide,
        translations=not args.skip_translations,
    )
    print(
        f"Applied Infinity-X 3.12 GSI patches: "
        f"{stats['fwb_lineage_hide_files']} frameworks/base files, "
        f"{stats['zh_cn_entries']} zh-rCN entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
