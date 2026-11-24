#!/usr/bin/env python3
"""Unit tests for Project Infinity-X 3.12 (Android 16) GSI patches and gsi_verify.py."""
from __future__ import annotations

from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
PATCH = runpy.run_path(str(SCRIPTS / "rom-patch-source.py"))
sys.path.insert(0, str(SCRIPTS))
import gsi_verify  # noqa: E402


class Infinity312GsiPatchTests(unittest.TestCase):
    def test_gsi_product_and_user_sepolicy_and_udfps_patches(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            # 1. Upstream broken infinity_gsi_arm64.mk + AndroidProducts.mk
            gsi_mk = src / "vendor/infinity/build/target/product/infinity_gsi_arm64.mk"
            gsi_mk.parent.mkdir(parents=True)
            gsi_mk.write_text(
                "$(call inherit-product, device/generic/common/gsi_arm64.mk)\n"
                "include vendor/infinity/build/target/product/lineage_generic_target.mk\n"
                "PRODUCT_NAME := lineage_gsi_arm64\n",
                encoding="utf-8",
            )
            products_mk = src / "vendor/infinity/build/target/product/AndroidProducts.mk"
            products_mk.write_text(
                "COMMON_LUNCH_CHOICES := \\\n"
                "    infinity_gsi_arm64-userdebug \\\n"
                "    infinity_gsi_x86_64-userdebug\n",
                encoding="utf-8",
            )
            # 1b. gsi_release.mk & BoardConfigGsiCommon.mk
            gsi_rel = src / "build/make/target/product/gsi_release.mk"
            gsi_rel.parent.mkdir(parents=True)
            gsi_rel.write_text(
                "BUILDING_GSI := true\n"
                "ifneq ($(filter lineage_gsi_%,$(TARGET_PRODUCT)),)\n"
                "BUILDING_LINEAGE_GSI := true\n"
                "endif\n",
                encoding="utf-8",
            )
            board_gsi = src / "build/make/target/board/BoardConfigGsiCommon.mk"
            board_gsi.parent.mkdir(parents=True)
            board_gsi.write_text(
                "BOARD_SUPER_PARTITION_SIZE := 3229614080\n"
                "BOARD_GSI_DYNAMIC_PARTITIONS_SIZE := 3221225472\n",
                encoding="utf-8",
            )
            # 2. gsi_system_ext.mk with unconditional debug policy
            sys_ext = src / "device/generic/common/gsi_system_ext.mk"
            sys_ext.parent.mkdir(parents=True)
            sys_ext.write_text(
                "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := true\n"
                "PRODUCT_PACKAGES += system_ext_userdebug_plat_sepolicy.cil\n",
                encoding="utf-8",
            )
            # 3. gsi_arm64.mk & gsi_product.mk
            (src / "device/generic/common/gsi_arm64.mk").write_text(
                "PRODUCT_ENFORCE_ARTIFACT_PATH_REQUIREMENTS := true\n",
                encoding="utf-8",
            )
            (src / "device/generic/common/gsi_product.mk").write_text(
                "PRODUCT_COPY_FILES += \\\n"
                "    device/sample/etc/apns-full-conf.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/apns-conf.xml\n",
                encoding="utf-8",
            )
            # 4. build/make/target/product/gsi/Android.bp
            gsi_bp = src / "build/make/target/product/gsi/Android.bp"
            gsi_bp.parent.mkdir(parents=True)
            gsi_bp.write_text(
                'android_system_image {\n'
                '    name: "android_gsi",\n'
                '    enabled: select(soong_config_variable("ANDROID", "PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT"), {\n'
                '        "true": true,\n'
                '        default: false,\n'
                '    }),\n'
                '}\n',
                encoding="utf-8",
            )
            # 5. backuptool.te, adbd.te & property_contexts
            sep = src / "device/lineage/sepolicy/common/private"
            sep.mkdir(parents=True)
            (sep / "backuptool.te").write_text("type backuptool, domain, coredomain;\n\npermissive backuptool;\n", encoding="utf-8")
            (sep / "adbd.te").write_text(
                "allow adbd adbroot:binder call;\n"
                "allow adbd adbroot_service:service_manager find;\n",
                encoding="utf-8",
            )
            (sep / "property_contexts").write_text(
                "persist.sys.lineage.foo u:object_r:system_prop:s0\n"
                "ro.vendor.dolby.dax.version u:object_r:vendor_default_prop:s0\n"
                "vendor.oplus.foo u:object_r:vendor_default_prop:s0\n"
                "ro.odm.bar u:object_r:vendor_default_prop:s0\n",
                encoding="utf-8",
            )
            # 6. UdfpsExtension.cpp
            udfps = src / "frameworks/native/services/surfaceflinger/CompositionEngine/src/UdfpsExtension.cpp"
            udfps.parent.mkdir(parents=True)
            udfps.write_text(
                "uint32_t getUdfpsDimZOrder(uint32_t z) {\n    return z;\n}\n\n"
                "uint32_t getUdfpsZOrder(uint32_t z, __unused bool touched) {\n    return z;\n}\n",
                encoding="utf-8",
            )
            # 7. version.mk + Updater Constants.java
            ver = src / "vendor/infinity/config/version.mk"
            ver.parent.mkdir(parents=True)
            ver.write_text(
                "PRODUCT_PRODUCT_PROPERTIES += \\\n"
                "  ro.infinity.build.version=$(INFINITY_VERSION) \\\n"
                "  ro.modversion=$(INFINITY_VERSION) \\\n"
                "  ro.infinity.device=$(INFINITY_BUILD) \\\n"
                "  ro.infinity.version=$(INFINITYVERSION)\n",
                encoding="utf-8",
            )
            const = src / "packages/apps/Updater/app/src/main/java/com/infinity/updater/misc/Constants.java"
            const.parent.mkdir(parents=True)
            const.write_text(
                'public final class Constants {\n'
                '    public static final String PROP_BUILD_VERSION = "ro.modversion";\n'
                '}\n',
                encoding="utf-8",
            )
            # 8. NetworkStack values & values-mcc460
            for rel, body in (
                (
                    "packages/modules/NetworkStack/res/values/config.xml",
                    '<resources>\n'
                    '    <string name="default_captive_portal_http_url" translatable="false">http://connectivitycheck.gstatic.com/generate_204</string>\n'
                    '    <string name="default_captive_portal_https_url" translatable="false">https://www.google.com/generate_204</string>\n'
                    '    <string-array name="default_captive_portal_fallback_urls" translatable="false">\n'
                    '        <item>http://www.google.com/gen_204</item>\n'
                    '        <item>http://play.googleapis.com/generate_204</item>\n'
                    '    </string-array>\n'
                    '    <bool name="config_no_sim_card_uses_neighbor_mcc">false</bool>\n'
                    '</resources>\n',
                ),
                (
                    "packages/modules/NetworkStack/res/values-mcc460/config.xml",
                    '<resources>\n'
                    '    <string name="default_captive_portal_http_url" translatable="false">http://connectivitycheck.gstatic.cn/generate_204</string>\n'
                    '    <string name="default_captive_portal_https_url" translatable="false">https://connectivitycheck.gstatic.cn/generate_204</string>\n'
                    '    <string-array name="default_captive_portal_fallback_urls" translatable="false">\n'
                    '        <item>http://www.googleapis.cn/generate_204</item>\n'
                    '    </string-array>\n'
                    '</resources>\n',
                ),
            ):
                p = src / rel
                p.parent.mkdir(parents=True)
                p.write_text(body, encoding="utf-8")

            PATCH["apply_all"](src, with_gapps="false", lineage_hide=True, translations=False)
            # Run a second time to verify idempotency
            PATCH["apply_all"](src, with_gapps="false", lineage_hide=True, translations=False)

            gsi_mk_text = gsi_mk.read_text()
            self.assertIn("WITH_GAPPS := false\ninclude vendor/infinity/build/target/product/infinity_generic_target.mk", gsi_mk_text)
            self.assertEqual(gsi_mk_text.count("WITH_GAPPS :="), 1)
            self.assertIn("PRODUCT_NAME := infinity_gsi_arm64", gsi_mk_text)
            self.assertIn("INFINITY_BUILD := gsi_arm64", gsi_mk_text)
            self.assertIn("BUILDING_LINEAGE_GSI := true", gsi_mk_text)
            self.assertIn("building_lineage_gsi,true", gsi_mk_text)
            self.assertEqual(products_mk.read_text().count("infinity_gsi_arm64-user \\"), 1)
            self.assertIn("lineage_gsi_% infinity_gsi_%", gsi_rel.read_text())
            self.assertIn("BOARD_GSI_DYNAMIC_PARTITIONS_SIZE := 9663676416", board_gsi.read_text())

            # Switching to with_gapps="true" replaces cleanly without duplicate lines
            PATCH["patch_infinity_gsi_product"](src, with_gapps="true")
            gsi_mk_gapps = gsi_mk.read_text()
            self.assertIn("WITH_GAPPS := true\ninclude vendor/infinity/build/target/product/infinity_generic_target.mk", gsi_mk_gapps)
            self.assertEqual(gsi_mk_gapps.count("WITH_GAPPS :="), 1)

            self.assertIn("PRODUCT_INSTALL_DEBUG_POLICY_TO_SYSTEM_EXT := false", sys_ext.read_text())
            self.assertIn('("true", true): false', gsi_bp.read_text())
            self.assertNotIn("apns-full-conf.xml", (src / "device/generic/common/gsi_product.mk").read_text())
            self.assertNotRegex((sep / "backuptool.te").read_text(), r"(?m)^permissive backuptool;")
            self.assertIn("userdebug_or_eng(`\nallow adbd adbroot:binder call;", (sep / "adbd.te").read_text())
            gsi_verify.check_system_ext_property_contexts_clean((sep / "property_contexts").read_text())
            self.assertIn("0x41000005u", udfps.read_text())
            self.assertIn("0x41000033u", udfps.read_text())
            self.assertNotIn("ro.modversion=", ver.read_text())
            self.assertNotIn("ro.infinity.device=$(INFINITY_BUILD)", ver.read_text())
            self.assertIn('"ro.infinity.build.version"', const.read_text())
            for rel in (
                "packages/modules/NetworkStack/res/values/config.xml",
                "packages/modules/NetworkStack/res/values-mcc460/config.xml",
            ):
                txt = (src / rel).read_text()
                self.assertIn("http://connect.rom.miui.com/generate_204", txt)
                self.assertIn("https://connect.rom.miui.com/generate_204", txt)
                self.assertIn("http://connectivitycheck.qualcomm.cn/generate_204", txt)

    def test_yokeshiq_bionic_patch_idempotent_zygote_safe_and_openat_filtered(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            bionic_dir = src / "bionic/libc/bionic"
            bionic_dir.mkdir(parents=True)
            hide_h = bionic_dir / "custom_rom_hide.h"
            hide_cpp = bionic_dir / "custom_rom_hide.cpp"
            open_cpp = bionic_dir / "open.cpp"

            hide_h.write_text(
                "int custom_rom_hide_filter_proc(const char* path);\n"
                "int custom_rom_hide_filter_sepolicy(const char* path);\n",
                encoding="utf-8",
            )
            open_cpp.write_text(
                'int openat(int fd, const char *pathname, int flags, ...) {\n'
                '  if (fd == AT_FDCWD && pathname && pathname[0] == \'/\') {\n'
                '    int filtered_fd = custom_rom_hide_filter_proc(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '    filtered_fd = custom_rom_hide_filter_vintf(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '    filtered_fd = custom_rom_hide_filter_sepolicy(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '  }\n'
                '  return 0;\n'
                '}\n'
                'int __openat_2(int fd, const char* pathname, int flags) {\n'
                '  if (fd == AT_FDCWD && pathname && pathname[0] == \'/\') {\n'
                '    int filtered_fd = custom_rom_hide_filter_proc(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '    filtered_fd = custom_rom_hide_filter_vintf(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '    filtered_fd = custom_rom_hide_filter_sepolicy(pathname);\n'
                '    if (filtered_fd >= 0) return FDTRACK_CREATE_NAME("openat", filtered_fd);\n'
                '  }\n'
                '  return 0;\n'
                '}\n',
                encoding="utf-8",
            )
            hide_cpp.write_text(
                'static bool compute_allowlisted() {\n'
                '    int fd = raw_openat("/proc/self/cmdline", O_RDONLY);\n'
                '    if (fd < 0) return false;\n'
                '\n'
                '    char cmdline[256];\n'
                '    ssize_t n = raw_read(fd, cmdline, sizeof(cmdline) - 1);\n'
                '    raw_close(fd);\n'
                '    if (n <= 0) return false;\n'
                '    cmdline[n] = \'\\0\';\n'
                '\n'
                '    char* colon = strchr(cmdline, \':\');\n'
                '    if (colon) *colon = \'\\0\';\n'
                '\n'
                '    for (const char* const* p = kAllowlistedPackages; *p; ++p) {\n'
                '        if (strcmp(cmdline, *p) == 0) return true;\n'
                '    }\n'
                '    return false;\n'
                '}\n'
                '\n'
                'static bool is_allowlisted_process() {\n'
                '    static pid_t cached_pid = -1;\n'
                '    static bool cached_value = false;\n'
                '    pid_t cur = getpid();\n'
                '    if (cur == cached_pid) return cached_value;\n'
                '    bool result = compute_allowlisted();\n'
                '    cached_value = result;\n'
                '    cached_pid = cur;\n'
                '    return result;\n'
                '}\n'
                'static bool is_rom_path(const char* path) {\n'
                '    if (is_blocked_dir(clean)) return true;\n'
                '    return false;\n'
                '}\n'
                'bool custom_rom_hide_should_block_at(int dirfd, const char* path) {\n'
                '    if (path[0] == \'/\') {\n'
                '        result = custom_rom_hide_should_block(path);\n'
                '    } else if (dirfd != AT_FDCWD) {\n'
                '        char dir_path[256];\n'
                '        if (resolve_fd_path(dirfd, dir_path, sizeof(dir_path))) {\n'
                '            char full_path[512];\n'
                '            snprintf(full_path, sizeof(full_path), "%s/%s", dir_path, path);\n'
                '            result = custom_rom_hide_should_block(full_path);\n'
                '        }\n'
                '    }\n'
                '    return result;\n'
                '}\n'
                'bool custom_rom_hide_should_filter_dirent(int dirfd, const char* name) {\n'
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
                '    }\n'
                '    return result;\n'
                '}\n'
                'int custom_rom_hide_filter_sepolicy(const char* path) {\n'
                '    if (!is_app_process()) return -1;\n'
                '    if (!path || reinterpret_cast<uintptr_t>(path) < 0x1000000) return -1;\n'
                '    return -1;\n'
                '}\n'
                'int custom_rom_hide_filter_vintf(const char* path) {\n'
                '    for (const char* const* p = kVintfFilterPaths; *p; ++p) {\n'
                '        if (strcmp(path, *p) == 0) { match = true; break; }\n'
                '    }\n'
                '    if (!match) { errno = saved_errno; return -1; }\n'
                '        bool opens_block  = strstr(pos, "<hal") != nullptr || strstr(pos, "<interface") != nullptr;\n'
                '        bool closes_block = strstr(pos, "</hal>") != nullptr || strstr(pos, "</interface>") != nullptr;\n'
                '    free(content);\n'
                '    raw_lseek(mem_fd, 0, SEEK_SET);\n'
                '    errno = saved_errno;\n'
                '    return mem_fd;\n'
                '}\n'
                '\n'
                'static const char* const kSpoofedEmptyProps[] = {\n'
                '    nullptr\n'
                '};\n'
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
                '}\n',
                encoding="utf-8",
            )
            PATCH["patch_yokeshiq_bionic_lineage_hide"](src)
            first_cpp = hide_cpp.read_text(encoding="utf-8")
            first_h = hide_h.read_text(encoding="utf-8")
            first_open = open_cpp.read_text(encoding="utf-8")
            for needle in (
                '__atomic_load_n(&cached_pid, __ATOMIC_ACQUIRE)',
                'strcmp(cmdline, "<pre-initialized>") == 0',
                'strncmp(cmdline, "zygote", 6) == 0',
                'strncmp(cmdline, "org.lineageos.", 14) == 0',
                'strstr(clean, "/etc/selinux/") != nullptr',
                'strstr(path, "/etc/sysconfig/") != nullptr',
                'strstr(pos, "<install-in-user-type") != nullptr',
                'bool self_closes  = opens_block && strstr(pos, "/>") != nullptr;',
                'int custom_rom_hide_filter_at(int dirfd, const char* path)',
                'static bool is_hidden_rom_prop(const char* name)',
                'strncasecmp(name, "ro.infinity.", 12) == 0',
            ):
                self.assertIn(needle, first_cpp)
            self.assertIn("int custom_rom_hide_filter_at(int dirfd, const char* path);", first_h)
            self.assertEqual(first_open.count("custom_rom_hide_filter_at(fd, pathname)"), 2)

            # Second pass must be 100% idempotent across all 3 bionic files
            PATCH["patch_yokeshiq_bionic_lineage_hide"](src)
            self.assertEqual(hide_cpp.read_text(encoding="utf-8"), first_cpp)
            self.assertEqual(hide_h.read_text(encoding="utf-8"), first_h)
            self.assertEqual(open_cpp.read_text(encoding="utf-8"), first_open)

    @unittest.skipUnless(shutil.which("clang++"), "requires clang++")
    def test_udfps_extension_compiles_cleanly_under_werror(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td)
            ext = src / "frameworks/native/services/surfaceflinger/CompositionEngine/src/UdfpsExtension.cpp"
            ext.parent.mkdir(parents=True)
            ext.write_text(
                "#ifndef TARGET_PROVIDES_UDFPS_LIB\n"
                "#include <compositionengine/UdfpsExtension.h>\n\n"
                "uint32_t getUdfpsDimZOrder(uint32_t z) {\n    return z;\n}\n\n"
                "uint32_t getUdfpsZOrder(uint32_t z, __unused bool touched) {\n    return z;\n}\n\n"
                "uint64_t getUdfpsUsageBits(uint64_t usageBits, __unused bool touched) {\n    return usageBits;\n}\n"
                "#endif\n",
                encoding="utf-8",
            )
            inc = src / "inc/compositionengine"
            inc.mkdir(parents=True)
            (inc / "UdfpsExtension.h").write_text(
                "#include <cstdint>\n#define __unused __attribute__((__unused__))\n"
                "uint32_t getUdfpsDimZOrder(uint32_t z);\n"
                "uint32_t getUdfpsZOrder(uint32_t z, bool touched);\n"
                "uint64_t getUdfpsUsageBits(uint64_t usageBits, bool touched);\n",
                encoding="utf-8",
            )
            PATCH["patch_oplus_udfps_extension"](src)
            res = subprocess.run(
                ["clang++", "-std=c++20", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-I", str(src / "inc"), str(ext)],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_gsi_verify_property_contexts_triebuilder(self):
        gsi_verify.check_property_contexts([
            ("plat_property_contexts", "ro.build. u:object_r:build_prop:s0\n"),
            ("vendor_property_contexts", "ro.vendor.dolby.dax.version u:object_r:vendor_default_prop:s0\n"),
        ])
        with self.assertRaisesRegex(ValueError, "duplicate prefix"):
            gsi_verify.check_property_contexts([
                ("system_ext_property_contexts", "ro.vendor.dolby.dax.version u:object_r:system_prop:s0\n"),
                ("vendor_property_contexts", "ro.vendor.dolby.dax.version u:object_r:vendor_default_prop:s0\n"),
            ])
        with self.assertRaisesRegex(ValueError, "vendor/odm entries"):
            gsi_verify.check_system_ext_property_contexts_clean(
                "ro.vendor.dolby.dax.version u:object_r:vendor_default_prop:s0\n"
            )

    def test_rom_build_gsi_handles_missing_init_te_and_lunch_syntax(self):
        script = (SCRIPTS / "rom-build-gsi.sh").read_text(encoding="utf-8")
        self.assertIn("INIT_TE_CREATED=1", script)
        self.assertIn('--gapps "$WITH_GAPPS"', script)
        self.assertIn('LUNCH_TARGET="infinity_gsi_arm64-${VARIANT}"', script)
        for backed_up in (
            "device/lineage/sepolicy/common/private/adbd.te",
            "build/make/target/product/gsi_release.mk",
            "build/make/target/board/BoardConfigGsiCommon.mk",
            "vendor/infinity/build/target/product/AndroidProducts.mk",
            "bionic/libc/bionic/custom_rom_hide.h",
            "bionic/libc/bionic/open.cpp",
        ):
            self.assertIn(backed_up, script)
        req_block = script.split("for required in", 1)[1].split("done", 1)[0]
        self.assertNotIn("init.te", req_block)


if __name__ == "__main__":
    unittest.main()
