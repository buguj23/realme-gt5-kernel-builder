"""Reproduce the source/layout failures seen in the ossi Actions runs."""
from pathlib import Path
import runpy
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
validate = runpy.run_path(str(SCRIPTS / "rom-source-preflight.py"))["validate"]
patch_kernel = runpy.run_path(str(SCRIPTS / "rom-patch-source.py"))["patch_dangling_kernel_include_symlinks"]


class SourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "source"
        self.args = dict(src=self.src, work=self.root / "work", avb_key="keys/avb.pem",
                         kernel_source="kernel/oneplus/sm8550",
                         prebuilt_kernel="device/realme/ossi/prebuilt/Image", force_prebuilt="true")
        for name in (self.args["avb_key"], self.args["prebuilt_kernel"],
                     "kernel/oneplus/sm8550/Makefile", "kernel/oneplus/sm8550/include/uapi/linux/types.h",
                     "kernel/oneplus/sm8550/arch/arm64/include/uapi/asm/unistd.h"):
            path = self.src / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")

    def test_valid_prebuilt_with_separate_uapi_source(self):
        self.assertEqual(validate(**self.args)["status"], "passed")

    def test_avb_absolute_and_escaping_paths_are_rejected(self):
        for path in (str(self.src / "keys/avb.pem"), "../elsewhere/avb.pem"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "OSSI_AVB_KEY"):
                validate(**{**self.args, "avb_key": path})
        (self.src / "keys/link.pem").symlink_to(self.root / "outside.pem")
        with self.assertRaisesRegex(ValueError, "outside source tree"):
            validate(**{**self.args, "avb_key": "keys/link.pem"})

    def test_soong_visible_backups_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "backup directory"):
            validate(**{**self.args, "work": self.src / ".ossi-build.old"})
        path = self.src / ".ossi-build.old/vendor-previous/Android.bp"
        path.parent.mkdir(parents=True); path.write_text("cc_prebuilt_library_shared {}\n")
        with self.assertRaisesRegex(ValueError, "stale vendor/build backup"):
            validate(**self.args)

    def test_missing_headers_and_disabled_prebuilt_mode_are_rejected(self):
        (self.src / "kernel/oneplus/sm8550/include/uapi/linux/types.h").unlink()
        with self.assertRaisesRegex(ValueError, "Kernel UAPI source missing"):
            validate(**self.args)
        with self.assertRaisesRegex(ValueError, "TARGET_FORCE_PREBUILT_KERNEL"):
            validate(**{**self.args, "force_prebuilt": "false"})

    def test_qcom_dangling_build_link_is_rejected(self):
        path = self.src / "hardware/qcom/sm7250/Android.bp"
        path.parent.mkdir(parents=True); path.symlink_to("gps/os_pickup.bp")
        with self.assertRaisesRegex(ValueError, "Dangling QCOM build file"):
            validate(**self.args)

    def test_kernel_link_fix_preserves_valid_headers_and_is_idempotent(self):
        include = self.src / "kernel/oneplus/sm8550/include"
        broken = include / "oplus-missing"
        broken.symlink_to("../../sm8550-modules/absent")
        valid = include / "types-alias.h"
        valid.symlink_to("uapi/linux/types.h")
        with self.assertRaisesRegex(ValueError, "Dangling kernel include"):
            validate(**self.args)
        patch_kernel(self.src)
        patch_kernel(self.src)
        self.assertFalse(broken.is_symlink())
        self.assertTrue(valid.is_symlink())
        self.assertEqual(valid.read_text(), "fixture\n")
        self.assertEqual(validate(**self.args)["status"], "passed")

    def test_rom_build_local_keeps_out_and_dist_relative_to_src(self):
        script = (SCRIPTS / "rom-build-local.sh").read_text(encoding="utf-8")
        self.assertIn('export OUT_DIR="out/ossi/$BR"', script)
        self.assertIn('export DIST_DIR="$OUT_DIR/dist"', script)
        self.assertNotIn('export OUT_DIR="$SRC/out/ossi/$BR"', script)


if __name__ == "__main__":
    unittest.main()
