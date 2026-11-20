#!/usr/bin/env python3
"""Unit tests for domestic China mirror adaptation, multi-threaded downloads, and runner safety."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mirror_helper  # noqa: E402
import rom_inputs  # noqa: E402


class _MockMirrorHandler(BaseHTTPRequestHandler):
    GOOD_PAYLOAD = b"REALME_GT5_VERIFIED_STOCK_PAYLOAD_5_15_149" * 64

    def do_GET(self):
        if self.path == "/fail":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"upstream error")
            return
        if self.path == "/html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>proxy error banner</body></html>")
            return
        if self.path == "/good":
            body = self.GOOD_PAYLOAD
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


class ChinaMirrorTests(unittest.TestCase):
    def test_detect_mirror_mode(self):
        old_env = os.environ.copy()
        try:
            for key in ("MIRROR_MODE", "GITHUB_ACTIONS", "RUNNER_ENVIRONMENT"):
                os.environ.pop(key, None)
            self.assertEqual(mirror_helper.detect_mirror_mode("auto"), "cn")

            os.environ["GITHUB_ACTIONS"] = "true"
            os.environ["RUNNER_ENVIRONMENT"] = "github-hosted"
            self.assertEqual(mirror_helper.detect_mirror_mode("auto"), "direct")
            self.assertEqual(mirror_helper.detect_mirror_mode("cn"), "cn")

            os.environ["RUNNER_ENVIRONMENT"] = "self-hosted"
            self.assertEqual(mirror_helper.detect_mirror_mode("auto"), "cn")
            self.assertEqual(mirror_helper.detect_mirror_mode("direct"), "direct")
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_github_proxy_idempotent_and_raw_cdn(self):
        raw_repo = "https://github.com/DestoryG/kernel_manifest.git"
        wrapped = mirror_helper.apply_github_proxy(raw_repo, "https://ghfast.top")
        self.assertEqual(wrapped, "https://ghfast.top/https://github.com/DestoryG/kernel_manifest.git")
        re_wrapped = mirror_helper.apply_github_proxy(wrapped, "https://v6.gh-proxy.org/")
        self.assertEqual(re_wrapped, "https://v6.gh-proxy.org/https://github.com/DestoryG/kernel_manifest.git")
        direct = mirror_helper.apply_github_proxy(re_wrapped, "")
        self.assertEqual(direct, raw_repo)

        raw_file = "https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo"
        expanded = mirror_helper.expand_github_url(raw_file, mode="cn")
        self.assertIn("https://cdn.jsdelivr.net/gh/GerritCodeReview/git-repo@main/repo", expanded)
        self.assertIn("https://fastly.jsdelivr.net/gh/GerritCodeReview/git-repo@main/repo", expanded)

    def test_manifest_rewrite_rotation_and_clo_preservation(self):
        sample = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<manifest>\n'
            '  <remote fetch="https://git.codelinaro.org/clo/la" name="clo-la"/>\n'
            '  <remote fetch="https://github.com/realme-kernel-opensource" name="origin"/>\n'
            '  <remote fetch="https://android.googlesource.com" name="aosp"/>\n'
            '  <remote fetch="https://github.com/LineageOS" name="lineage"/>\n'
            '</manifest>\n'
        )
        pass1 = mirror_helper.rewrite_manifest_text(
            sample,
            aosp_mirror="https://mirrors.tuna.tsinghua.edu.cn/git/AOSP/",
            lineage_mirror="https://mirrors.bfsu.edu.cn/git/lineageOS/",
            github_prefix="https://ghfast.top/",
        )
        self.assertIn('fetch="https://git.codelinaro.org/clo/la"', pass1)
        self.assertIn('fetch="https://mirrors.tuna.tsinghua.edu.cn/git/AOSP/"', pass1)
        self.assertIn('fetch="https://mirrors.bfsu.edu.cn/git/lineageOS/LineageOS"', pass1)
        self.assertIn('fetch="https://ghfast.top/https://github.com/realme-kernel-opensource"', pass1)

        # Rotate GitHub proxy without double wrapping.
        pass2 = mirror_helper.rewrite_manifest_text(pass1, github_prefix="https://v6.gh-proxy.org/")
        self.assertIn('fetch="https://v6.gh-proxy.org/https://github.com/realme-kernel-opensource"', pass2)
        self.assertNotIn("ghfast.top", pass2)

        # Rotate back to direct GitHub.
        pass3 = mirror_helper.rewrite_manifest_text(pass2, github_prefix="")
        self.assertIn('fetch="https://github.com/realme-kernel-opensource"', pass3)

    def test_ubuntu_apt_deb822_and_legacy_rewrite(self):
        deb822 = (
            "Types: deb\n"
            "URIs: http://archive.ubuntu.com/ubuntu/\n"
            "Suites: noble noble-updates\n\n"
            "Types: deb\n"
            "URIs: http://security.ubuntu.com/ubuntu/\n"
            "Suites: noble-security\n"
        )
        rewritten, count = mirror_helper.transform_ubuntu_sources(
            deb822, "https://mirrors.cloud.tencent.com/ubuntu"
        )
        self.assertEqual(count, 2)
        self.assertEqual(rewritten.count("https://mirrors.cloud.tencent.com/ubuntu"), 2)

        intranet = "URIs: http://mirrors.cloud.aliyuncs.com/ubuntu/\n"
        unchanged, count_intranet = mirror_helper.transform_ubuntu_sources(
            intranet, "https://mirrors.tuna.tsinghua.edu.cn/ubuntu"
        )
        self.assertEqual(count_intranet, 0)
        self.assertEqual(unchanged, intranet)

    def test_multi_mirror_download_fallback_and_sha256(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMirrorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            urls = [
                f"http://127.0.0.1:{port}/fail",
                f"http://127.0.0.1:{port}/html",
                f"http://127.0.0.1:{port}/good",
            ]
            import hashlib
            expected_sha = hashlib.sha256(_MockMirrorHandler.GOOD_PAYLOAD).hexdigest()
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "asset.bin"
                mirror_helper.download_multi_mirror(
                    urls, dest, jobs=4, expected_sha256=expected_sha, expand_github=False
                )
                self.assertEqual(dest.read_bytes(), _MockMirrorHandler.GOOD_PAYLOAD)

                bad_dest = Path(tmp) / "bad.bin"
                with self.assertRaises(RuntimeError):
                    mirror_helper.download_multi_mirror(
                        [f"http://127.0.0.1:{port}/good"],
                        bad_dest,
                        jobs=2,
                        expected_sha256="0" * 64,
                        expand_github=False,
                    )
        finally:
            server.shutdown()
            server.server_close()

    def test_maximize_build_space_skips_self_hosted(self):
        env = os.environ.copy()
        env["RUNNER_ENVIRONMENT"] = "self-hosted"
        env.pop("FORCE_MAXIMIZE_BUILD_SPACE", None)
        res = subprocess.run(
            ["bash", str(SCRIPTS / "maximize-build-space.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("Skipping maximize-build-space.sh", res.stdout)

    def test_legacy_bloat_removed_and_stock_metadata_present(self):
        for obsolete in (
            ROOT / "ZRAM.zip",
            ROOT / "lib" / "ccache",
            SCRIPTS / "cache_apt_pkgs.sh",
            SCRIPTS / "check_unicode_format.py",
        ):
            self.assertFalse(obsolete.exists(), f"obsolete file should be removed: {obsolete}")

        meta = ROOT / "official" / "stock" / "15.0.0.320" / "payload_metadata.bin"
        self.assertTrue(meta.is_file(), "verified payload_metadata.bin must be present")
        parsed = rom_inputs.stock_payload(meta.parent, "5.15.149", meta)
        self.assertIn("boot", parsed["partitions"])
        self.assertIn("vendor_dlkm", parsed["partitions"])

    def test_workflows_support_self_hosted_and_cn_mirrors(self):
        import yaml
        for wf_name in ("build-kernel-gt5.yml", "build-infinity-rom.yml", "cleanup.yml"):
            wf_path = ROOT / ".github" / "workflows" / wf_name
            data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
            self.assertIn("jobs", data)
            text = wf_path.read_text(encoding="utf-8")
            self.assertNotIn("storage.googleapis.com/git-repo-downloads/repo", text)
        kernel_wf = (ROOT / ".github" / "workflows" / "build-kernel-gt5.yml").read_text(encoding="utf-8")
        self.assertIn("runner.environment == 'github-hosted'", kernel_wf)
        self.assertIn("mirror_helper.py ensure-repo", kernel_wf)
        self.assertIn("gt5_kernel_5_15_149", kernel_wf)

        gitignore_res = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore", "official/stock/15.0.0.320/payload_metadata.bin"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(gitignore_res.returncode, 0, "payload_metadata.bin must not be gitignored")

        help_res = subprocess.run(
            [sys.executable, str(SCRIPTS / "40-verify-crc.py"), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("--recursive", help_res.stdout)
        self.assertIn("--allow-ko-providers", help_res.stdout)


if __name__ == "__main__":
    unittest.main()
