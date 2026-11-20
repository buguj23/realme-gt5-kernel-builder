#!/usr/bin/env python3
"""Retrieve a verified package from the GT5 kernel workflow."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode
import urllib.error
import urllib.request
import zipfile

from rom_inputs import baseline, require
from rom_kernel_package import VARIANTS, verify_package

WORKFLOW = "build-kernel-gt5.yml"


def _run_retry(cmd, retries=3, **kwargs):
    for attempt in range(1, retries + 1):
        try:
            return subprocess.run(cmd, check=True, **kwargs)
        except subprocess.CalledProcessError:
            if attempt >= retries:
                raise
            time.sleep(attempt * 2)


def api(path):
    return json.loads(_run_retry(["gh", "api", path], capture_output=True, text=True).stdout)


def valid_run(run, repo, branch):
    return (run["path"].split("@", 1)[0] == ".github/workflows/" + WORKFLOW
            and run["conclusion"] == "success"
            and run["head_repository"]["full_name"].lower() == repo.lower()
            and run["head_branch"] == branch)


def _gh_token():
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return subprocess.check_output(["gh", "auth", "token"], text=True).strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _artifact_redirect_url(repo, artifact_id):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
        headers={
            "Authorization": f"Bearer {_gh_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "realme-gt5-builder/1.0",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=20) as resp:
            return resp.headers.get("Location") or resp.geturl()
    except urllib.error.HTTPError as err:
        if err.code in (301, 302, 303, 307, 308):
            location = err.headers.get("Location")
            if location:
                return location
        raise


def _download_artifact(repo, run_id, artifact, artifact_id, dest_dir):
    if artifact_id and shutil.which("aria2c"):
        try:
            url = None
            for attempt in range(1, 4):
                try:
                    url = _artifact_redirect_url(repo, artifact_id)
                    if url:
                        break
                except (OSError, urllib.error.URLError, subprocess.CalledProcessError):
                    if attempt >= 3:
                        raise
                    time.sleep(attempt * 2)
            zip_path = dest_dir / "artifact.zip"
            _run_retry([
                "aria2c", "-x", "16", "-s", "16", "-k", "1M",
                "--connect-timeout=15", "--timeout=45", "--max-tries=3",
                "--allow-overwrite=true", "-d", str(dest_dir), "-o", zip_path.name, url,
            ], retries=2)
            with zipfile.ZipFile(zip_path) as archive:
                info = archive.getinfo("kernel-package.tar.zst")
                with archive.open(info) as src, (dest_dir / "kernel-package.tar.zst").open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            zip_path.unlink(missing_ok=True)
            return
        except (OSError, urllib.error.URLError, zipfile.BadZipFile, KeyError, subprocess.CalledProcessError) as error:
            print(f"aria2c artifact download fallback for run {run_id}: {error}", file=sys.stderr)
    _run_retry(["gh", "run", "download", str(run_id), "-R", repo, "-n", artifact, "-D", str(dest_dir)])


def artifact_runs(repo, branch, artifact, run_id):
    base = f"repos/{repo}/actions"
    if run_id:
        require(re.fullmatch(r"[0-9]+", run_id), "kernel run ID must be numeric")
        runs = [api(f"{base}/runs/{run_id}")]
    else:
        query = urlencode({"branch": branch, "status": "success", "per_page": 30})
        runs = api(f"{base}/workflows/{WORKFLOW}/runs?{query}")["workflow_runs"]
        runs.sort(key=lambda run: run["created_at"], reverse=True)
    for run in runs:
        if not valid_run(run, repo, branch):
            continue
        matches = [a for a in api(f"{base}/runs/{run['id']}/artifacts?per_page=100")["artifacts"]
                   if a["name"] == artifact and not a["expired"]]
        require(len(matches) <= 1, f"run {run['id']} has duplicate {artifact} artifacts")
        if matches:
            run["_artifact_id"] = matches[0]["id"]
            yield run


def extract_package(archive, path):
    """Accept only the files produced by kernel-package.sh."""
    with subprocess.Popen(["zstd", "-dc", archive], stdout=subprocess.PIPE) as decompressor:
        with tarfile.open(fileobj=decompressor.stdout, mode="r|") as incoming:
            for member in incoming:
                name = PurePosixPath(member.name)
                if member.isdir() and str(name) in (".", "modules"):
                    continue
                valid = str(name) in ("Image", "Module.symvers", "manifest.json") or (
                    len(name.parts) == 2 and name.parts[0] == "modules"
                    and re.fullmatch(r"[A-Za-z0-9_.+-]+\.ko", name.name))
                require(valid and member.isfile(), f"unexpected kernel artifact member {member.name!r}")
                dest = path / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with incoming.extractfile(member) as source, dest.open("xb") as output:
                    shutil.copyfileobj(source, output)
        require(decompressor.wait() == 0, "failed to decompress the kernel artifact")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--variant", required=True, choices=VARIANTS[:-1])
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    branch = baseline(args.branch)["branch"]
    artifact = f"kernel-package_{args.variant}_{branch}"
    dest = args.output.resolve()
    require(not dest.exists(), f"kernel package already exists at {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache_root = Path(os.environ.get("GT5_KERNEL_CACHE_DIR") or (Path.home() / ".cache" / "gt5-kernel-packages"))
    for run in artifact_runs(args.repo, branch, artifact, args.run_id):
        try:
            cache_file = cache_root / str(run["id"]) / args.variant / "kernel-package.tar.zst"
            with tempfile.TemporaryDirectory(prefix="ossi-kernel-download-", dir=dest.parent) as tmp:
                temp = Path(tmp)
                stage = temp / "package"
                used_cache = False
                if cache_file.is_file():
                    try:
                        stage.mkdir()
                        extract_package(cache_file, stage)
                        verify_package(stage, branch, args.variant, run["head_sha"])
                        used_cache = True
                        print(f"Using verified local kernel package cache: {cache_file}")
                    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError):
                        cache_file.unlink(missing_ok=True)
                        shutil.rmtree(stage, ignore_errors=True)
                if not used_cache:
                    _download_artifact(args.repo, run["id"], artifact, run.get("_artifact_id"), temp)
                    stage.mkdir()
                    archive = temp / "kernel-package.tar.zst"
                    extract_package(archive, stage)
                    verify_package(stage, branch, args.variant, run["head_sha"])
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    tmp_cache = cache_file.with_name(f".tmp-{os.getpid()}-kernel-package.tar.zst")
                    shutil.copyfile(archive, tmp_cache)
                    tmp_cache.replace(cache_file)
                stage.rename(dest)
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError, tarfile.TarError) as error:
            print(f"Skipping invalid kernel artifact in run {run['id']}: {error}", file=sys.stderr)
            continue
        if args.github_output:
            with args.github_output.open("a") as output:
                print(f"run-id={run['id']}", file=output)
        print(f"Verified kernel run {run['id']} for {branch} / {args.variant}")
        return
    raise ValueError(f"no successful run with a compatible {artifact}; rebuild the kernel package if all artifacts predate schema 2")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
