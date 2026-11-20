#!/usr/bin/env python3
"""Consumer-visible module ABI and boot-phase dependency regressions."""
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kmi
from rom_inputs import baseline
from rom_kernel_package import VARIANTS, assemble, kernel_release, verify_package

STAGER = runpy.run_path(str(SCRIPTS / "rom-stage-kernel.py"))
RELEASE_TEXT = "5.15.149-fixture"


class ModuleDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mods = self.root / "modules"
        self.mods.mkdir()
        self.symvers = self.root / "Module.symvers"
        self.symvers.write_text("0x12345678\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n"
                                "0x11223344\tservice\tdrivers/provider\tEXPORT_SYMBOL\n")
        (self.root / "Image").write_bytes(
            b"\0" * 56 + b"ARM\x64" + b"\0" * 4
            + b"Linux version %s (%s)\0Linux version " + RELEASE_TEXT.encode()
            + b" (builder@host)\0" + bytes.fromhex("78563412"))

    def module(self, name, imports=None, exports=None, directory=None):
        # Real ELF objects: exercise section/symbol decoding, not mocked readers.
        asm = ['.section .modinfo,"a"', f'.asciz "vermagic={RELEASE_TEXT} SMP modversions aarch64"',
               '.section __versions,"a"']
        for symbol, crc in (imports or {}).items():
            asm += [f".quad {crc}", f'.asciz "{symbol}"', f".zero {55 - len(symbol)}"]
        for symbol, crc in (exports or {}).items():
            asm += ['.section __ksymtab,"a"', f"__ksymtab_{symbol}: .long 0",
                    f".globl __crc_{symbol}", f".set __crc_{symbol}, {crc}"]
        source = self.root / f"{name}.S"
        source.write_text("\n".join(asm) + "\n")
        output = (directory or self.mods) / f"{name}.ko"
        subprocess.run(["clang", "--target=aarch64-linux-gnu", "-c", str(source), "-o", str(output)], check=True,
                       capture_output=True)
        return output

    def verify(self):
        return subprocess.run([sys.executable, str(SCRIPTS / "kmi.py"), "verify",
                               "--symvers", str(self.symvers), "--modules", str(self.mods)],
                              capture_output=True, text=True)

    def test_versions_and_layout_are_mandatory(self):
        self.module("consumer")
        self.assertNotEqual(self.verify().returncode, 0)
        self.module("consumer", {"service": 0x11223344})
        self.assertNotEqual(self.verify().returncode, 0)

    def test_symvers_module_row_does_not_replace_delivered_provider(self):
        self.module("consumer", {"module_layout": 0x12345678, "service": 0x11223344})
        self.assertNotEqual(self.verify().returncode, 0)
        self.module("provider", {"module_layout": 0x12345678}, {"service": 0x11223344})
        self.assertEqual(self.verify().returncode, 0)

    def test_actual_export_crc_and_provider_dependency_are_checked(self):
        self.module("consumer", {"module_layout": 0x12345678, "service": 0x11223344})
        self.module("provider", {"module_layout": 0x12345678}, {"service": 0x55667788})
        self.assertNotEqual(self.verify().returncode, 0)
        self.module("provider", {"module_layout": 0x12345678, "unavailable": 1},
                    {"service": 0x11223344})
        self.assertNotEqual(self.verify().returncode, 0)

    def test_first_stage_cannot_depend_on_later_partition(self):
        pool = self.root / "stock"
        ramdisk, vendor = pool / "ramdisk", pool / "vendor_dlkm"
        for p in (ramdisk, vendor):
            p.mkdir(parents=True)
        self.module("consumer", {"module_layout": 0x12345678, "service": 0x11223344}, directory=ramdisk)
        provider = self.module("provider", {"module_layout": 0x12345678}, {"service": 0x11223344}, directory=vendor)
        lists = {"first_stage": ["consumer.ko"], "recovery": ["consumer.ko"]}
        with self.assertRaisesRegex(ValueError, "normal first stage.*no delivered provider"):
            STAGER["select_modules"](self.root, pool, lists)
        shutil.copyfile(provider, ramdisk / provider.name)
        (ramdisk / "modules.dep").write_text("consumer.ko: provider.ko\nprovider.ko:\n")
        result = STAGER["select_modules"](self.root, pool, lists)
        self.assertIn("provider.ko", result["vendor_ramdisk"])

    def test_recovery_only_export_is_kept_out_of_normal_dlkm(self):
        pool = self.root / "stock"
        ramdisk, system = pool / "ramdisk", pool / "system_dlkm"
        for p in (ramdisk, system):
            p.mkdir(parents=True)
        self.module("anchor", {"module_layout": 0x12345678}, directory=ramdisk)
        self.module("oplus_bsp_zsmalloc", {"module_layout": 0x12345678},
                    {"zs_pool_stats": 1}, directory=ramdisk)
        normal = self.module("zsmalloc", {"module_layout": 0x12345678},
                             {"zs_pool_stats": 2}, directory=system)
        result = STAGER["select_modules"](self.root, pool, {
            "first_stage": ["anchor.ko"], "recovery": ["anchor.ko", "oplus_bsp_zsmalloc.ko"]})
        self.assertIn("oplus_bsp_zsmalloc.ko", result["vendor_ramdisk"])
        self.assertNotIn("oplus_bsp_zsmalloc.ko", result["vendor_dlkm"])
        shutil.copyfile(normal, ramdisk / normal.name)
        with self.assertRaisesRegex(ValueError, "Recovery.*duplicate export"):
            STAGER["select_modules"](self.root, pool, {
                "first_stage": ["anchor.ko"], "recovery": ["oplus_bsp_zsmalloc.ko", "zsmalloc.ko"]})

    def test_system_dlkm_blocklist_prevents_vendor_dlkm_duplicate_export(self):
        pool = self.root / "stock"
        ramdisk, recovery, vendor, system = (
            pool / "ramdisk", pool / "recovery", pool / "vendor_dlkm", pool / "system_dlkm"
        )
        for p in (ramdisk, recovery, vendor, system):
            p.mkdir(parents=True)
        self.module("anchor", {"module_layout": 0x12345678}, directory=ramdisk)
        self.module("zsmalloc", {"module_layout": 0x12345678}, {"zs_map_object": 1}, directory=system)
        self.module("zram", {"module_layout": 0x12345678, "zs_map_object": 1}, directory=system)
        self.module("oplus_bsp_zsmalloc", {"module_layout": 0x12345678},
                    {"zs_map_object": 1}, directory=vendor)
        shutil.copyfile(vendor / "oplus_bsp_zsmalloc.ko", recovery / "oplus_bsp_zsmalloc.ko")
        (vendor / "system_dlkm.modules.blocklist").write_text("blocklist zram\nblocklist zsmalloc\n")
        result = STAGER["select_modules"](self.root, pool, {
            "first_stage": ["anchor.ko"], "recovery": ["anchor.ko", "oplus_bsp_zsmalloc.ko"]})
        self.assertIn("oplus_bsp_zsmalloc.ko", result["vendor_dlkm"])
        self.assertIn("zsmalloc.ko", result["system_dlkm"])

    def test_stock_soft_dependencies_are_included_without_changing_load_order(self):
        names = ["consumer.ko", "recovery-only.ko", "optional-service.ko"]
        paths = {name: self.mods / name for name in names}
        dependency_list = self.mods / "modules.dep"
        (self.mods / "modules.softdep").write_text("softdep consumer pre:optional_service post: absent\n")
        order = ["consumer.ko"]
        selected = STAGER["dependency_closure"](order, paths, dependency_list)
        self.assertEqual(set(selected), {"consumer.ko", "optional-service.ko"})
        self.assertEqual(order, ["consumer.ko"])

    def test_module_abi_detects_change_beyond_layout_crc(self):
        module = self.module("consumer", {"module_layout": 0x12345678, "service": 1})
        original = kmi.module_abi(module)
        if shutil.which("llvm-strip"):
            subprocess.run(["llvm-strip", "--strip-debug", module], check=True, capture_output=True)
            self.assertEqual(kmi.module_abi(module), original)
        self.module("consumer", {"module_layout": 0x12345678, "service": 2})
        self.assertNotEqual(kmi.module_abi(module), original)

    def test_kernel_banner_format_string_is_not_a_release(self):
        self.assertEqual(kernel_release(self.root / "Image"), RELEASE_TEXT)

    @unittest.skipUnless(shutil.which("zstd"), "requires the kernel packager's zstd")
    def test_manifest_uses_one_build_and_detects_changed_module(self):
        source = self.root / "build"
        (source / "arch/arm64/boot").mkdir(parents=True)
        shutil.copyfile(self.root / "Image", source / "arch/arm64/boot/Image")
        shutil.copyfile(self.symvers, source / "Module.symvers")
        self.module("one", {"module_layout": 0x12345678}, directory=source)
        self.module("stale", {"module_layout": 0x12345678}, directory=source)
        (source / "modules.order").write_text("one.ko\n")
        for variant in VARIANTS:
            archive = self.root / f"archive-{variant}"
            assemble(source, archive, "5.15.149", variant, "a" * 40)
            package = self.root / f"pkg-{variant}"
            package.mkdir()
            subprocess.run(["tar", "--zstd", "-xf", archive / "kernel-package.tar.zst", "-C", package], check=True)
            info = verify_package(package, "5.15.149", variant=variant)
            self.assertEqual(set(info["files"]), {"Image", "Module.symvers", "modules/one.ko"})
            with (package / "modules/one.ko").open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_package(package, "5.15.149")

    def test_single_5_15_149_baseline_and_yukisu_lkm_contracts(self):
        kernels = json.loads((ROOT / "official/kernels.json").read_text())
        self.assertEqual(list(kernels.keys()), ["149"])
        spec = baseline("5.15.149")
        self.assertEqual(spec["file"], "realme_gt5_v")
        self.assertEqual(spec["module_layout"], "0x0222dd63")
        self.assertEqual(spec["security_patch"], "2024-11-05")
        self.assertEqual(spec["metadata_fs"], "f2fs")
        self.assertEqual(spec["api"], 35)
        kmeta = json.loads((ROOT / "kernel.json").read_text())
        self.assertEqual(kmeta["branch"], "5.15.149")
        self.assertEqual(kmeta["file"], "realme_gt5_v")
        self.assertFalse(kmeta["susfs"])
        self.assertFalse(kmeta["kpm"])
        self.assertFalse(kmeta["fake_config"])
        xml = ROOT / "manifests/realme-sm8550/realme_gt5_v.xml"
        self.assertTrue(xml.is_file())
        self.assertIn("realme_GT5-AndroidV-common-source", xml.read_text())
        features = (ROOT / "configs/features.config").read_text()
        for required in ("CONFIG_MODULES=y", "CONFIG_MODVERSIONS=y", "CONFIG_KPROBES=y",
                         "CONFIG_KRETPROBES=y", "CONFIG_KALLSYMS_ALL=y", "CONFIG_OVERLAY_FS=y",
                         "CONFIG_CGROUP_BPF=y", "CONFIG_COMPAT=y"):
            self.assertIn(required, features)
        self.assertFalse(re.search(r"^CONFIG_KSU=y|^CONFIG_KPM=y|^CONFIG_KSU_SUSFS=y", features, re.M))
        board_ogki = (ROOT / "rom/device/realme/sm8550-ogki/BoardConfigOgki.mk").read_text()
        self.assertNotIn("CONFIG_KSU=", board_ogki)
        self.assertNotIn("BakaSU", "".join(VARIANTS))
        self.assertIn("Pure-OGKI", VARIANTS)
        self.assertIn("YukiSU-LKM", VARIANTS)


if __name__ == "__main__":
    unittest.main()
