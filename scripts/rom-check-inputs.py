#!/usr/bin/env python3
"""Check or render the stock baseline used by the local and CI ROM builders."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from mirror_helper import strip_github_proxy
from rom_inputs import baseline, require, stock_payload, verify_stock


def manifest_source(source, manifest, branch):
    manifests = source / ".repo/manifests"

    def config(key):
        return subprocess.check_output(
            ["git", "-C", manifests, "config", "--local", "--get", key],
            text=True, stderr=subprocess.DEVNULL).strip()

    got, expected = map(urlsplit, (strip_github_proxy(config("remote.origin.url")), manifest))
    matching_origin = (got.hostname == expected.hostname and
                       got.path.rstrip("/").removesuffix(".git").lower() ==
                       expected.path.rstrip("/").removesuffix(".git").lower())
    require(matching_origin, "repo manifest origin does not match the selected stock baseline")
    require(config("branch.default.merge") == f"refs/heads/{branch}",
            f"repo source tree must track {branch}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    profile = commands.add_parser("profile")
    profile.add_argument("--branch", required=True)
    profile.add_argument("--field")
    source = commands.add_parser("source")
    source.add_argument("--src", type=Path, required=True)
    selection = source.add_mutually_exclusive_group(required=True)
    selection.add_argument("--branch")
    selection.add_argument("--manifest")
    source.add_argument("--source-branch")
    stock = commands.add_parser("stock")
    stock.add_argument("--branch", required=True)
    stock.add_argument("--stock-images", type=Path, required=True)
    stock.add_argument("--payload-metadata", type=Path)
    args = parser.parse_args()
    if args.operation == "profile":
        spec = baseline(args.branch)
        if args.field:
            print(spec[args.field])
        else:
            print(json.dumps(spec))
    elif args.operation == "source":
        if args.branch:
            spec = baseline(args.branch)
            manifest_source(args.src, spec["source_manifest"], spec["source_branch"])
        else:
            require(args.source_branch, "--source-branch is required with --manifest")
            manifest_source(args.src, args.manifest, args.source_branch)
    else:
        payload = stock_payload(args.stock_images, args.branch, args.payload_metadata)
        verify_stock(args.stock_images, payload, ("boot", "init_boot", "vendor_boot", "dtbo"))
        print(f"Stock OTA identity verified for {args.branch}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: ROM inputs: {error}", file=sys.stderr)
        raise SystemExit(1)
