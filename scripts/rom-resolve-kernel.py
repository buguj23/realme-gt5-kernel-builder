#!/usr/bin/env python3
"""Retrieve a verified package from the GT5 kernel workflow."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlencode

from rom_inputs import baseline, require
from rom_kernel_package import VARIANTS, verify_package

WORKFLOW = "build-kernel-gt5.yml"


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def valid_run(run, repo, branch):
    return (run["path"].split("@", 1)[0] == ".github/workflows/" + WORKFLOW
            and run["conclusion"] == "success"
            and run["head_repository"]["full_name"].lower() == repo.lower()
            and run["head_branch"] == branch)


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
    for run in artifact_runs(args.repo, branch, artifact, args.run_id):
        try:
            with tempfile.TemporaryDirectory(prefix="ossi-kernel-download-", dir=dest.parent) as tmp:
                temp = Path(tmp)
                subprocess.run(["gh", "run", "download", str(run["id"]), "-R", args.repo,
                                "-n", artifact, "-D", temp], check=True)
                stage = temp / "package"
                stage.mkdir()
                extract_package(temp / "kernel-package.tar.zst", stage)
                verify_package(stage, branch, args.variant, run["head_sha"])
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
