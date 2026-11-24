#!/usr/bin/env python3
"""Consumer-visible kernel module ABI, packaging, and 5.15.149 OGKI/GSI baseline contracts."""
import json
from pathlib import Path
import re
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

    def test_single_5_15_149_baseline_and_infinity_3_12_gsi_contracts(self):
        kernels = json.loads((ROOT / "official/kernels.json").read_text())
        self.assertEqual(list(kernels.keys()), ["149"])
        spec = baseline("5.15.149")
        self.assertEqual(spec["file"], "realme_gt5_v")
        self.assertEqual(spec["module_layout"], "0x0222dd63")
        self.assertEqual(spec["security_patch"], "2024-11-05")
        self.assertEqual(spec["metadata_fs"], "f2fs")
        self.assertEqual(spec["api"], 35)
        # Dedicated Infinity-X 3.12 (Android 16 / bp4a) GSI target
        self.assertEqual(spec["source_branch"], "16")
        self.assertEqual(spec["rom_version"], "3.12")
        self.assertEqual(spec["rom_android"], "16")
        self.assertEqual(spec["target_release"], "bp4a")
        self.assertEqual(spec["product"], "infinity_gsi_arm64")

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
        self.assertNotIn("BakaSU", "".join(VARIANTS))
        self.assertIn("Pure-OGKI", VARIANTS)
        self.assertIn("YukiSU-LKM", VARIANTS)
        # Strict GSI-only branch contract: ossi full ROM tree must not exist
        self.assertFalse((ROOT / "rom").exists())
        self.assertFalse((ROOT / ".github/workflows/build-infinity-rom.yml").exists())
        self.assertFalse((SCRIPTS / "rom-build-local.sh").exists())


if __name__ == "__main__":
    unittest.main()
