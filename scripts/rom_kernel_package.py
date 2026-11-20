"""Assemble and verify a ROM kernel package from one Kbuild output directory."""
import argparse
import json
import mmap
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import kmi
from rom_inputs import baseline, require, sha256

RELEASE = rb"Linux version ([0-9]+\.[0-9]+\.[0-9]+[^\x00\s]*)"
VARIANTS = ("Pure-OGKI", "YukiSU-LKM", "local")


def kernel_release(path):
    with path.open("rb") as stream:
        require(stream.read(64)[56:60] == b"ARM\x64", f"{path}: not a raw ARM64 Image")
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            releases = {match[1].decode("ascii") for match in re.finditer(RELEASE, data)}
    require(len(releases) == 1, f"{path}: missing or ambiguous Linux release")
    return releases.pop()


def package_files(path):
    modules = path / "modules"
    require(modules.is_dir() and not modules.is_symlink(), f"{path}: missing real modules directory")
    files = {"Image": path / "Image", "Module.symvers": path / "Module.symvers"}
    for module in sorted(modules.iterdir()):
        require(module.suffix == ".ko" and re.fullmatch(r"[A-Za-z0-9_.+-]+\.ko", module.name), f"{module}: invalid module file")
        files[f"modules/{module.name}"] = module
    require(len(files) > 2, f"{path}: kernel package contains no modules")
    for file in files.values():
        require(file.is_file() and not file.is_symlink() and file.stat().st_size > 0, f"{file}: incomplete package file")
    return files


def validate_content(path, branch, files):
    release = kernel_release(path / "Image")
    require(release == branch or release.startswith(branch + "-"), f"Image release {release} does not match {branch}")
    for name, image in files.items():
        if name.startswith("modules/"):
            require(kmi.arm64_module(image) and kmi.vermagic(image).split()[0] == release,
                    f"{name}: architecture or vermagic release differs from Image")
    return release


def verify_package(path, branch, variant=None, commit=None):
    branch = baseline(branch)["branch"]
    info = json.loads((path / "manifest.json").read_text())
    require(info["schema"] == 2 and info["branch"] == branch and info["variant"] in VARIANTS,
            "kernel package manifest does not match the selected branch")
    require(variant is None or info["variant"] == variant, "kernel package variant differs from requested variant")
    require(re.fullmatch(r"[0-9a-f]{40}", info["source_commit"]), "missing kernel package source commit")
    require(commit is None or info["source_commit"] == commit, "kernel package source commit differs from kernel run")
    files = package_files(path)
    require(files.keys() == info["files"].keys(), "kernel package file inventory differs")
    for name, file in files.items():
        require(sha256(file) == info["files"][name], f"{name}: kernel package SHA-256 differs")
    require(validate_content(path, branch, files) == info["kernel_release"], "kernel package release differs from manifest")
    subprocess.run([sys.executable, str(Path(kmi.__file__)), "verify", "--symvers", path / "Module.symvers",
                    "--modules", path / "modules", "--image", path / "Image"], check=True)
    return info


def assemble(build, output, branch, variant, commit):
    branch = baseline(branch)["branch"]
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "provide the source checkout commit as --commit")
    build = build.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ossi-kernel-package-", dir=output) as temp:
        root = Path(temp)
        stage = root / "package"
        (stage / "modules").mkdir(parents=True)
        shutil.copyfile(build / "arch/arm64/boot/Image", stage / "Image")
        shutil.copyfile(build / "Module.symvers", stage / "Module.symvers")
        for line in (build / "modules.order").read_text().splitlines():
            relative = Path(line.strip())
            require(relative.suffix == ".ko" and not relative.is_absolute() and ".." not in relative.parts,
                    f"{build}: invalid module in modules.order: {line!r}")
            source = build / relative
            if not source.is_file() and relative.parts[0] == "kernel":
                source = build.joinpath(*relative.parts[1:])
            require(source.is_file() and source.resolve().is_relative_to(build), f"{source}: module missing from build")
            dest = stage / "modules" / relative.name
            require(not dest.exists(), f"{build}: duplicate output module {relative.name}")
            shutil.copyfile(source, dest)
        files = package_files(stage)
        manifest = {"schema": 2, "source_commit": commit, "branch": branch, "variant": variant,
                    "kernel_release": validate_content(stage, branch, files),
                    "files": {name: sha256(file) for name, file in files.items()}}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify_package(stage, branch, variant, commit)
        archive = root / "kernel-package.tar.zst"
        subprocess.run(["tar", "--zstd", "-cf", archive, "-C", stage, "."], check=True)
        archive.replace(output / archive.name)
        (stage / "manifest.json").replace(output / "manifest.json")
    print(f"Kernel package: {output / archive.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    pack = sub.add_parser("assemble")
    pack.add_argument("build", type=Path)
    pack.add_argument("output", type=Path)
    pack.add_argument("--variant", choices=VARIANTS, required=True)
    pack.add_argument("--commit", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("package", type=Path)
    verify.add_argument("--variant", choices=VARIANTS)
    verify.add_argument("--commit")
    for command in (pack, verify):
        command.add_argument("--branch", required=True)
    args = parser.parse_args()
    if args.operation == "assemble":
        assemble(args.build, args.output, args.branch, args.variant, args.commit)
    else:
        verify_package(args.package, args.branch, args.variant, args.commit)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        print(f"FAIL: kernel package: {error}", file=sys.stderr)
        raise SystemExit(1)
