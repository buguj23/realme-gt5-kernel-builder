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
    REPO_PAYLOAD = (b"#!/usr/bin/env python3\n" + b"# copyright\n" * 350 + b"REPO_URL = 'https://example.invalid/git-repo'\n")

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
        if self.path == "/repo":
            body = self.REPO_PAYLOAD
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
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

        # Rewrite Gitea LFS remote to local file seed cleanly and idempotently.
        lfs_xml = '<manifest>\n  <remote name="lfs" fetch="https://gitea.com/projectInfinity-x" revision="15" />\n</manifest>\n'
        seeded = mirror_helper.rewrite_manifest_text(lfs_xml, lfs_mirror="file:///data/builder/.cache/gt5-rom-seed/15")
        self.assertIn('fetch="file:///data/builder/.cache/gt5-rom-seed/15"', seeded)

    def test_rom_check_inputs_accepts_proxied_official_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifests = Path(tmp) / ".repo" / "manifests"
            manifests.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(manifests)], check=True)
            subprocess.run(
                ["git", "-C", str(manifests), "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-q", "-m", "init"],
                check=True,
            )
            subprocess.run(["git", "-C", str(manifests), "branch", "-M", "default"], check=True)
            subprocess.run(["git", "-C", str(manifests), "config", "--local", "remote.origin.url",
                            "https://cdn.gh-proxy.org/https://github.com/ProjectInfinity-X/manifest.git"], check=True)
            subprocess.run(["git", "-C", str(manifests), "config", "--local", "branch.default.merge", "refs/heads/15"], check=True)
            res = subprocess.run(
                [sys.executable, str(SCRIPTS / "rom-check-inputs.py"), "source", "--src", tmp, "--branch", "5.15.149"],
                capture_output=True, text=True,
            )
            self.assertEqual(res.returncode, 0, res.stderr)

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

                repo_dest = Path(tmp) / "repo"
                mirror_helper.download_multi_mirror(
                    [f"http://127.0.0.1:{port}/html", f"http://127.0.0.1:{port}/repo"],
                    repo_dest,
                    jobs=2,
                    expand_github=False,
                    expect_token=b"REPO_URL",
                )
                self.assertEqual(repo_dest.read_bytes(), _MockMirrorHandler.REPO_PAYLOAD)
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
            for job_name, job_cfg in data["jobs"].items():
                job_env = job_cfg.get("env") or {}
                for k, v in job_env.items():
                    text_val = str(v)
                    self.assertNotIn("runner.", text_val, f"{wf_name}:{job_name}.env.{k} must not use runner context")
                    self.assertNotIn("env.", text_val, f"{wf_name}:{job_name}.env.{k} must not use env context")
            text = wf_path.read_text(encoding="utf-8")
            self.assertNotIn("storage.googleapis.com/git-repo-downloads/repo", text)
            if wf_name == "build-infinity-rom.yml":
                for step in data["jobs"]["build"]["steps"]:
                    self.assertNotIn("uses", step, "build-infinity-rom build job must not stall Set up job on codeload.github.com")
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

    def test_prune_incomplete_repo_projects_preserves_valid_and_cleans_unfetched(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            repo_dir = work / ".repo"

            # 1. Incomplete shallow project: projects/prebuilts/rust.git symlinked to project-objects, no refs + stale tmp_pack
            rust_proj = repo_dir / "projects" / "prebuilts" / "rust.git"
            rust_obj = repo_dir / "project-objects" / "platform" / "prebuilts" / "rust.git"
            subprocess.run(["git", "init", "--bare", str(rust_obj)], check=True, capture_output=True)
            stale_pack = rust_obj / "objects" / "pack" / "tmp_pack_stale"
            stale_pack.write_bytes(b"stale")
            rust_proj.mkdir(parents=True)
            for d in ("objects", "hooks", "rr-cache"):
                (rust_proj / d).symlink_to(rust_obj / d)
            subprocess.run(["git", "init", "--bare", str(rust_proj)], check=True, capture_output=True)
            (work / "prebuilts" / "rust").mkdir(parents=True)
            (work / "prebuilts" / "rust" / ".git").write_text("gitdir: ../../.repo/projects/prebuilts/rust.git\n")

            # 2. Healthy fetched project: shared project-objects with a valid ref + shallow file
            good_proj = repo_dir / "projects" / "build" / "make.git"
            good_obj = repo_dir / "project-objects" / "platform" / "build" / "make.git"
            subprocess.run(["git", "init", "--bare", str(good_obj)], check=True, capture_output=True)
            good_proj.mkdir(parents=True)
            (good_proj / "objects").symlink_to(good_obj / "objects")
            subprocess.run(["git", "init", "--bare", str(good_proj)], check=True, capture_output=True)
            blob = subprocess.check_output(
                ["git", f"--git-dir={good_proj}", "hash-object", "-w", "--stdin"],
                input=b"hello\n",
            ).decode().strip()
            tree = subprocess.check_output(
                ["git", f"--git-dir={good_proj}", "mktree"],
                input=f"100644 blob {blob}\tREADME\n".encode(),
            ).decode().strip()
            commit = subprocess.check_output(
                [
                    "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    f"--git-dir={good_proj}", "commit-tree", tree, "-m", "init",
                ]
            ).decode().strip()
            subprocess.run(
                ["git", f"--git-dir={good_proj}", "update-ref", "refs/remotes/m/15", commit],
                check=True,
            )
            (good_proj / "shallow").write_text(commit + "\n")

            cmd = f'source "{SCRIPTS / "lib-mirror.sh"}" && _prune_incomplete_repo_projects "{work}"'
            res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=True)
            self.assertIn("pruned 1 incomplete/unfetched project", res.stderr)
            self.assertFalse(rust_proj.exists())
            self.assertFalse(rust_obj.exists())
            self.assertFalse((work / "prebuilts" / "rust" / ".git").exists())
            self.assertTrue(good_proj.exists())
            self.assertTrue(good_obj.exists())
            self.assertTrue((good_proj / "shallow").exists())


if __name__ == "__main__":
    unittest.main()
