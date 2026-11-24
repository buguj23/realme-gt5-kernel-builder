#!/usr/bin/env python3
"""Upload and restore pruned Android ROM incremental build caches via GitHub Releases.

Streams tar -> zstd directly into <=1900 MiB chunks so local disk overhead stays
under ~2 GiB and the local out/ tree is never modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

DEFAULT_REPO = "buguj23/realme-gt5-kernel-builder"
DEFAULT_BRANCH = "infinity-x-3.12"
DEFAULT_TAG = "gsi-cache-3.12-infinity"
DEFAULT_CHUNK_BYTES = 1900 * 1024 * 1024  # 1900 MiB (< GitHub Release 2 GiB cap)
READ_BLOCK = 4 * 1024 * 1024

# Logical incremental cache tiers relative to OUT_DIR (out/gsi).
# Excludes redundant final outputs (dist/, ota.zip, my_*.img), repackaging copies
# (obj/PACKAGING/), debug symbols (symbols/), and host logs/env scripts.
TIERS: list[dict] = [
    {
        "name": "tier1-host-meta",
        "description": "Host build tools, Ninja/Kati state, and Soong build graphs",
        "include_globs": [
            "host",
            "soong",
            ".ninja_log",
            ".ninja_deps",
            ".kati_stamp-*",
            "build-*.ninja",
            "combined-*.ninja",
            "soong_ui",
            "microfactory_Linux",
            "mk2rbc",
            "rbcrun",
            "release-config",
            ".module_paths",
            ".out-dir",
            ".top",
            ".*_intermediates",
            ".*_hash",
            ".*_version",
            "file_name_tag.txt",
            "last_kati_suffix",
            "release-config.out",
            "build_date.txt",
        ],
        "excludes": [
            "soong/.intermediates",
            "soong/.temp",
            "soong/*.log*",
            "soong/*.pb",
            "*.log",
            "*.log.*",
            "*.trace",
            "*.trace.*",
            "*.lock*",
        ],
    },
    {
        "name": "tier2-target",
        "description": "Compiled target intermediates and partition staging (excluding PACKAGING/OTA/OEM copies/symbols)",
        "include_globs": [
            "target",
        ],
        "excludes": [
            "target/product/*/obj/PACKAGING",
            "target/product/*/*-ota.zip",
            "target/product/*/my_*.img",
            "target/product/*/symbols",
            "target/product/*/installed-files*.txt",
        ],
    },
    {
        "name": "tier3-soong-intermediates",
        "description": "Soong .intermediates compiled object/jar/dex/apex cache",
        "include_globs": [
            "soong/.intermediates",
        ],
        "excludes": [
            "*.tmp",
        ],
    },
]


def clean_gh_env() -> dict[str, str]:
    """Use gh's authenticated keyring credentials without stale PAT env vars."""
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    return env


def resolve_tier_paths(out_dir: Path, include_globs: list[str]) -> list[str]:
    """Resolve existing top-level relative paths inside out_dir matching globs."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in include_globs:
        if "/" in pattern and not any(ch in pattern for ch in "*?["):
            candidate = out_dir / pattern
            if candidate.exists() or candidate.is_symlink():
                rel = pattern
                if rel not in seen:
                    seen.add(rel)
                    found.append(rel)
            continue
        for match in sorted(out_dir.glob(pattern)):
            rel = str(match.relative_to(out_dir))
            if rel not in seen:
                seen.add(rel)
                found.append(rel)
    return found


def build_tar_cmd(out_dir: Path, paths: list[str], excludes: list[str]) -> list[str]:
    cmd = ["tar", "--numeric-owner", "--warning=no-file-changed", "-C", str(out_dir)]
    for ex in excludes:
        cmd.append(f"--exclude={ex}")
    cmd.extend(["-cf", "-", *paths])
    return cmd


def run_with_retry(cmd: list[str], *, env: dict[str, str], retries: int = 5, label: str = "") -> str:
    last_err = ""
    for attempt in range(1, retries + 1):
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout
        last_err = (res.stderr or res.stdout or f"exit {res.returncode}").strip()
        if attempt < retries:
            wait = min(30, 3 * attempt)
            print(f"[retry {attempt}/{retries}] {label or cmd[0]} failed: {last_err}; retrying in {wait}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
    raise RuntimeError(f"{label or cmd[0]} failed after {retries} attempts: {last_err}")


def ensure_release(repo: str, tag: str, title: str, notes: str, env: dict[str, str]) -> dict[str, int]:
    """Ensure the prerelease exists and return existing {asset_name: size}."""
    view = subprocess.run(
        ["gh", "release", "view", tag, "-R", repo, "--json", "assets"],
        env=env,
        capture_output=True,
        text=True,
    )
    if view.returncode != 0:
        run_with_retry(
            [
                "gh", "release", "create", tag,
                "-R", repo,
                "--prerelease",
                "--title", title,
                "--notes", notes,
            ],
            env=env,
            label=f"create release {tag}",
        )
        return {}
    data = json.loads(view.stdout)
    return {a["name"]: int(a["size"]) for a in data.get("assets", [])}


def upload_asset(repo: str, tag: str, path: Path, env: dict[str, str]) -> None:
    size_mib = path.stat().st_size / (1024 * 1024)
    t0 = time.monotonic()
    run_with_retry(
        ["gh", "release", "upload", tag, str(path), "-R", repo, "--clobber"],
        env=env,
        retries=6,
        label=f"upload {path.name}",
    )
    dt = max(0.01, time.monotonic() - t0)
    print(f"[uploaded] {path.name} ({size_mib:.1f} MiB in {dt:.1f}s, {size_mib / dt:.2f} MiB/s)", flush=True)


def stream_tier_chunks(
    *,
    out_dir: Path,
    tier: dict,
    prefix: str,
    work_dir: Path,
    chunk_bytes: int,
    zstd_level: int,
    zstd_threads: int,
    on_chunk,
) -> dict:
    """Stream tar | zstd into <=chunk_bytes parts, invoking on_chunk(path, size, sha256) per part."""
    paths = resolve_tier_paths(out_dir, tier["include_globs"])
    if not paths:
        raise RuntimeError(f"Tier {tier['name']} matched no files under {out_dir}")

    tar_cmd = build_tar_cmd(out_dir, paths, tier["excludes"])
    zstd_cmd = ["zstd", f"-T{zstd_threads}", f"-{zstd_level}", "-c", "-q"]

    tar_proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert tar_proc.stdout is not None
    zstd_proc = subprocess.Popen(zstd_cmd, stdin=tar_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tar_proc.stdout.close()
    assert zstd_proc.stdout is not None

    parts: list[dict] = []
    total_compressed = 0
    part_idx = 0

    try:
        while True:
            part_name = f"{prefix}-{tier['name']}.tar.zst.part-{part_idx:02d}"
            part_path = work_dir / part_name
            hasher = hashlib.sha256()
            written = 0
            with part_path.open("wb") as fh:
                while written < chunk_bytes:
                    to_read = min(READ_BLOCK, chunk_bytes - written)
                    buf = zstd_proc.stdout.read(to_read)
                    if not buf:
                        break
                    fh.write(buf)
                    hasher.update(buf)
                    written += len(buf)
            if written == 0:
                part_path.unlink(missing_ok=True)
                break
            digest = hasher.hexdigest()
            total_compressed += written
            on_chunk(part_path, written, digest)
            parts.append({"name": part_name, "size": written, "sha256": digest})
            part_path.unlink(missing_ok=True)
            part_idx += 1
            if written < chunk_bytes:
                break

        zstd_stderr = zstd_proc.stderr.read().decode("utf-8", "replace") if zstd_proc.stderr else ""
        tar_stderr = tar_proc.stderr.read().decode("utf-8", "replace") if tar_proc.stderr else ""
        zstd_rc = zstd_proc.wait()
        tar_rc = tar_proc.wait()
        if tar_rc not in (0, 1):
            raise RuntimeError(f"tar failed for {tier['name']} (rc={tar_rc}): {tar_stderr.strip()}")
        if zstd_rc != 0:
            raise RuntimeError(f"zstd failed for {tier['name']} (rc={zstd_rc}): {zstd_stderr.strip()}")
    finally:
        for proc in (zstd_proc, tar_proc):
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    if not parts:
        raise RuntimeError(f"Tier {tier['name']} produced empty compressed stream")
    return {
        "name": tier["name"],
        "description": tier["description"],
        "included": paths,
        "excludes": tier["excludes"],
        "compressed_bytes": total_compressed,
        "parts": parts,
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(READ_BLOCK), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_upload(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    if not out_dir.is_dir():
        raise RuntimeError(f"OUT_DIR not found: {out_dir}")
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    env = clean_gh_env()

    selected = [t for t in TIERS if not args.tiers or t["name"] in args.tiers]
    if not selected:
        raise RuntimeError("No matching tiers selected")

    prefix = f"gsi-{args.branch}-cache"
    manifest_path = work_dir / "rom-cache-manifest.json"
    sums_path = work_dir / "SHA256SUMS.txt"

    notes = (
        f"Pruned incremental GSI build cache for Realme GT5 (`5.15.149` OGKI / `{args.branch}` / Project Infinity-X 3.12 Android 16).\n\n"
        f"- Build namespace root: `{args.build_root}`\n"
        f"- Relative `OUT_DIR`: `{args.out_relpath}`\n"
        f"- Compression: `zstd -{args.zstd_level}` split into `<= {args.chunk_mib} MiB` chunks\n"
        f"- Restore: `python3 scripts/rom-cache-sync.py restore --repo {args.repo} --tag {args.tag} --src <rom-src>`\n"
    )
    existing_assets: dict[str, int] = {}
    if not args.dry_run:
        existing_assets = ensure_release(
            args.repo,
            args.tag,
            f"GT5 {args.branch} Infinity-X 3.12 GSI Incremental Build Cache",
            notes,
            env,
        )
        print(f"[release] {args.repo}@{args.tag} ready ({len(existing_assets)} existing assets)", flush=True)

    # Load previous partial manifest if resuming same upload session.
    previous_parts: dict[str, dict] = {}
    if args.resume_state and Path(args.resume_state).is_file():
        prev = json.loads(Path(args.resume_state).read_text(encoding="utf-8"))
        for t in prev.get("tiers", []):
            for p in t.get("parts", []):
                previous_parts[p["name"]] = p

    tier_results: list[dict] = []
    extra_assets: list[dict] = []

    for extra_arg, dest_name in (
        (args.source_manifest, "source-manifest.xml"),
        (args.delivery_json, "rom-delivery.json"),
    ):
        if extra_arg:
            src_file = Path(extra_arg).resolve()
            if not src_file.is_file():
                raise RuntimeError(f"Missing metadata file: {src_file}")
            tmp_copy = work_dir / dest_name
            shutil.copyfile(src_file, tmp_copy)
            digest = sha256_file(tmp_copy)
            size = tmp_copy.stat().st_size
            if not args.dry_run:
                upload_asset(args.repo, args.tag, tmp_copy, env)
            extra_assets.append({"name": dest_name, "size": size, "sha256": digest})
            tmp_copy.unlink(missing_ok=True)

    for tier in selected:
        print(f"[tier] packing {tier['name']}: {tier['description']}", flush=True)
        t0 = time.monotonic()

        def handle_chunk(part_path: Path, size: int, digest: str) -> None:
            if args.dry_run:
                print(f"[dry-run] {part_path.name} ({size / (1024*1024):.1f} MiB, sha256={digest[:12]}...)", flush=True)
                return
            prev = previous_parts.get(part_path.name)
            if prev and prev.get("sha256") == digest and existing_assets.get(part_path.name) == size:
                print(f"[skip] {part_path.name} already uploaded with matching size & sha256", flush=True)
                return
            upload_asset(args.repo, args.tag, part_path, env)

        result = stream_tier_chunks(
            out_dir=out_dir,
            tier=tier,
            prefix=prefix,
            work_dir=work_dir,
            chunk_bytes=args.chunk_mib * 1024 * 1024,
            zstd_level=args.zstd_level,
            zstd_threads=args.zstd_threads,
            on_chunk=handle_chunk,
        )
        dt = time.monotonic() - t0
        print(f"[tier done] {tier['name']}: {len(result['parts'])} parts, "
              f"{result['compressed_bytes'] / (1024**3):.2f} GiB in {dt:.1f}s", flush=True)
        tier_results.append(result)

        if args.resume_state:
            state_path = Path(args.resume_state)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"tiers": tier_results}, indent=2) + "\n", encoding="utf-8")

    # Delete obsolete stale part files from older runs if part counts shrank.
    expected_part_names = {p["name"] for t in tier_results for p in t["parts"]}
    if not args.dry_run and existing_assets:
        for old_name in sorted(existing_assets):
            if old_name.startswith(f"{prefix}-") and old_name not in expected_part_names:
                print(f"[prune] deleting stale asset {old_name}", flush=True)
                subprocess.run(
                    ["gh", "release", "delete-asset", args.tag, old_name, "-R", args.repo, "--yes"],
                    env=env,
                    check=False,
                )

    total_bytes = sum(t["compressed_bytes"] for t in tier_results)
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": args.repo,
        "tag": args.tag,
        "branch": args.branch,
        "builder_commit": args.builder_commit or "",
        "build_root_path": args.build_root,
        "out_relpath": args.out_relpath,
        "compression": f"zstd-{args.zstd_level}",
        "chunk_bytes": args.chunk_mib * 1024 * 1024,
        "total_compressed_bytes": total_bytes,
        "metadata_assets": extra_assets,
        "tiers": tier_results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    sum_lines = []
    for item in extra_assets:
        sum_lines.append(f"{item['sha256']}  {item['name']}")
    for t in tier_results:
        for p in t["parts"]:
            sum_lines.append(f"{p['sha256']}  {p['name']}")
    sum_lines.append(f"{sha256_file(manifest_path)}  {manifest_path.name}")
    sums_path.write_text("\n".join(sum_lines) + "\n", encoding="utf-8")

    if not args.dry_run:
        upload_asset(args.repo, args.tag, manifest_path, env)
        upload_asset(args.repo, args.tag, sums_path, env)
        if args.save_manifest:
            Path(args.save_manifest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest_path, args.save_manifest)
        manifest_path.unlink(missing_ok=True)
        sums_path.unlink(missing_ok=True)

    print(f"[complete] uploaded {sum(len(t['parts']) for t in tier_results)} cache parts "
          f"({total_bytes / (1024**3):.2f} GiB compressed) to {args.repo}@{args.tag}", flush=True)
    return 0


def download_asset(repo: str, tag: str, name: str, dest: Path, *, use_gh: bool, env: dict[str, str]) -> None:
    if use_gh:
        run_with_retry(
            ["gh", "release", "download", tag, "-R", repo, "-p", name, "-O", str(dest), "--clobber"],
            env=env,
            retries=5,
            label=f"download {name}",
        )
        return
    url = f"https://github.com/{repo}/releases/download/{tag}/{name}"
    urls = [url]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import mirror_helper  # type: ignore
        urls = mirror_helper.expand_github_url(url)
    except Exception:
        pass
    last_err = ""
    for candidate in urls:
        try:
            with urllib.request.urlopen(candidate, timeout=60) as resp, dest.open("wb") as out:
                shutil.copyfileobj(resp, out, length=READ_BLOCK)
            return
        except Exception as exc:
            last_err = f"{candidate}: {exc}"
    raise RuntimeError(f"Failed to download {name}: {last_err}")


def cmd_restore(args: argparse.Namespace) -> int:
    src_dir = Path(args.src).resolve()
    env = clean_gh_env()
    use_gh = bool(shutil.which("gh")) and not args.no_gh

    with tempfile.TemporaryDirectory(prefix=".ossi-cache-restore-", dir=args.work_dir or None) as td:
        work = Path(td)
        manifest_file = work / "rom-cache-manifest.json"
        download_asset(args.repo, args.tag, "rom-cache-manifest.json", manifest_file, use_gh=use_gh, env=env)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        out_dir = src_dir / manifest["out_relpath"]
        out_dir.mkdir(parents=True, exist_ok=True)

        selected = [t for t in manifest["tiers"] if not args.tiers or t["name"] in args.tiers]
        if not selected:
            raise RuntimeError("No matching tiers in remote manifest")

        for tier in selected:
            print(f"[restore] {tier['name']} ({len(tier['parts'])} parts)", flush=True)
            part_files: list[Path] = []
            for p in tier["parts"]:
                dest = work / p["name"]
                download_asset(args.repo, args.tag, p["name"], dest, use_gh=use_gh, env=env)
                actual = sha256_file(dest)
                if actual != p["sha256"] or dest.stat().st_size != p["size"]:
                    raise RuntimeError(f"Checksum/size mismatch for {p['name']}: got {actual}, expected {p['sha256']}")
                part_files.append(dest)

            zstd_proc = subprocess.Popen(["zstd", "-d", "-T0", "-c"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            assert zstd_proc.stdin is not None and zstd_proc.stdout is not None
            tar_proc = subprocess.Popen(["tar", "--numeric-owner", "-C", str(out_dir), "-xf", "-"], stdin=zstd_proc.stdout)
            zstd_proc.stdout.close()
            try:
                for pf in part_files:
                    with pf.open("rb") as fh:
                        for chunk in iter(lambda: fh.read(READ_BLOCK), b""):
                            zstd_proc.stdin.write(chunk)
                    pf.unlink(missing_ok=True)
                zstd_proc.stdin.close()
            finally:
                zrc = zstd_proc.wait()
                trc = tar_proc.wait()
            if zrc != 0 or trc != 0:
                raise RuntimeError(f"Extraction failed for {tier['name']} (zstd={zrc}, tar={trc})")

        stamp = out_dir / ".ossi-cache-restored.json"
        stamp.write_text(json.dumps({
            "restored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "repo": args.repo,
            "tag": args.tag,
            "cache_created_at": manifest.get("created_at"),
            "builder_commit": manifest.get("builder_commit"),
            "original_build_root_path": manifest.get("build_root_path"),
        }, indent=2) + "\n", encoding="utf-8")
        print(f"[restored] cache extracted into {out_dir}", flush=True)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Stream pruned out/ cache chunks to a GitHub Release")
    up.add_argument("--out-dir", required=True, help="Path to out/gsi")
    up.add_argument("--work-dir", required=True, help="Temp directory holding at most 1 chunk (~1.9 GiB)")
    up.add_argument("--repo", default=DEFAULT_REPO)
    up.add_argument("--tag", default=DEFAULT_TAG)
    up.add_argument("--branch", default=DEFAULT_BRANCH)
    up.add_argument("--out-relpath", default="out/gsi")
    up.add_argument("--build-root", default="/mnt/rom-src")
    up.add_argument("--builder-commit", default="")
    up.add_argument("--source-manifest", default="")
    up.add_argument("--delivery-json", default="")
    up.add_argument("--resume-state", default="")
    up.add_argument("--save-manifest", default="")
    up.add_argument("--chunk-mib", type=int, default=1900)
    up.add_argument("--zstd-level", type=int, default=9)
    up.add_argument("--zstd-threads", type=int, default=0)
    up.add_argument("--tiers", nargs="*", default=[])
    up.add_argument("--dry-run", action="store_true")

    rs = sub.add_parser("restore", help="Download, verify, and extract cache chunks into <src>/<out_relpath>")
    rs.add_argument("--src", required=True, help="ROM source root directory")
    rs.add_argument("--repo", default=DEFAULT_REPO)
    rs.add_argument("--tag", default=DEFAULT_TAG)
    rs.add_argument("--work-dir", default="")
    rs.add_argument("--tiers", nargs="*", default=[])
    rs.add_argument("--no-gh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "upload":
        return cmd_upload(args)
    if args.command == "restore":
        return cmd_restore(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
