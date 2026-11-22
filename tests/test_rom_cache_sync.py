"""Unit tests for streaming chunked ROM cache upload and restore."""
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
MOD = runpy.run_path(str(SCRIPTS / "rom-cache-sync.py"))


@unittest.skipUnless(shutil.which("zstd") and shutil.which("tar"), "requires tar and zstd")
class RomCacheSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out/ossi/5.15.149"
        # Populate representative cache files and excluded bloat/logs
        for rel, content in [
            ("host/linux-x86/bin/avbtool", b"avbtool-bin" * 200),
            ("soong/build.infinity_ossi.ninja", b"rule r1\n" * 400),
            ("soong/.intermediates/frameworks/base/framework.jar", b"dexdata" * 500),
            ("soong/.temp/scratch.bin", b"temp-excluded"),
            ("target/product/ossi/obj/SHARED_LIBRARIES/libfoo.so", b"elfdata" * 300),
            ("target/product/ossi/obj/PACKAGING/target_files_intermediates/big.img", b"repack-excluded" * 500),
            ("target/product/ossi/infinity_ossi-ota.zip", b"ota-excluded" * 500),
            ("target/product/ossi/my_stock.img", b"oem-excluded" * 500),
            ("target/product/ossi/symbols/libfoo.so", b"sym-excluded" * 500),
            (".ninja_log", b"# ninja log v5\n"),
            ("env-infinity_ossi.sh", b"export SECRET=never-upload\n"),
            ("dist/infinity_ossi-target_files.zip", b"dist-excluded" * 500),
        ]:
            p = self.out / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)

    def test_pruned_tiers_roundtrip_and_exclusions(self):
        work = self.root / "work"
        work.mkdir()
        saved_chunks: dict[str, bytes] = {}
        tier_records = []

        for tier in MOD["TIERS"]:
            def capture(part_path: Path, size: int, digest: str):
                self.assertEqual(part_path.stat().st_size, size)
                self.assertEqual(MOD["sha256_file"](part_path), digest)
                saved_chunks[part_path.name] = part_path.read_bytes()

            rec = MOD["stream_tier_chunks"](
                out_dir=self.out,
                tier=tier,
                prefix="ossi-5.15.149-cache",
                work_dir=work,
                chunk_bytes=256,  # force multi-part splitting
                zstd_level=3,
                zstd_threads=1,
                on_chunk=capture,
            )
            tier_records.append(rec)
            # Chunk temp files must be cleaned up immediately after on_chunk
            self.assertEqual(list(work.iterdir()), [])

        self.assertGreaterEqual(len(saved_chunks), 3)

        # Verify tier1 alone does NOT duplicate soong/.intermediates (kept exclusively in tier3)
        tier1_only = self.root / "tier1_only"
        tier1_only.mkdir()
        import subprocess
        z1 = subprocess.Popen(["zstd", "-d", "-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        t1 = subprocess.Popen(["tar", "--numeric-owner", "-C", str(tier1_only), "-xf", "-"], stdin=z1.stdout)
        z1.stdout.close()
        for part in tier_records[0]["parts"]:
            z1.stdin.write(saved_chunks[part["name"]])
        z1.stdin.close()
        self.assertEqual(z1.wait(), 0)
        self.assertEqual(t1.wait(), 0)
        self.assertFalse((tier1_only / "soong/.intermediates").exists())

        # Restore all tiers into a brand new source tree and verify exact included vs excluded files
        restored_out = self.root / "restored/out/ossi/5.15.149"
        restored_out.mkdir(parents=True)
        for rec in tier_records:
            zstd_p = subprocess.Popen(["zstd", "-d", "-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            tar_p = subprocess.Popen(["tar", "--numeric-owner", "-C", str(restored_out), "-xf", "-"], stdin=zstd_p.stdout)
            zstd_p.stdout.close()
            for part in rec["parts"]:
                zstd_p.stdin.write(saved_chunks[part["name"]])
            zstd_p.stdin.close()
            self.assertEqual(zstd_p.wait(), 0)
            self.assertEqual(tar_p.wait(), 0)

        # Included incremental cache files must exist and match byte-for-byte
        for rel in (
            "host/linux-x86/bin/avbtool",
            "soong/build.infinity_ossi.ninja",
            "soong/.intermediates/frameworks/base/framework.jar",
            "target/product/ossi/obj/SHARED_LIBRARIES/libfoo.so",
            ".ninja_log",
        ):
            self.assertEqual((restored_out / rel).read_bytes(), (self.out / rel).read_bytes())

        # Excluded bloat/logs/env must NOT be present
        for rel in (
            "soong/.temp/scratch.bin",
            "target/product/ossi/obj/PACKAGING/target_files_intermediates/big.img",
            "target/product/ossi/infinity_ossi-ota.zip",
            "target/product/ossi/my_stock.img",
            "target/product/ossi/symbols/libfoo.so",
            "env-infinity_ossi.sh",
            "dist/infinity_ossi-target_files.zip",
        ):
            self.assertFalse((restored_out / rel).exists(), f"{rel} should have been excluded")


if __name__ == "__main__":
    unittest.main()
