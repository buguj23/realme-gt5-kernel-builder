#!/usr/bin/env python3
"""Multi-mirror probing, manifest rewriting, APT setup, and multi-threaded downloads for CN/global runners."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT_GIT = "git/2.43.0"
USER_AGENT_HTTP = "Mozilla/5.0 (X11; Linux x86_64) realme-gt5-builder/1.0"

DEFAULT_GITHUB_PROXIES = (
    "https://cdn.gh-proxy.org/",
    "https://edgeone.gh-proxy.org/",
    "https://gh-proxy.org/",
    "https://v6.gh-proxy.org/",
)

# Known proxy prefixes stripped before applying a different mirror so rewrites stay idempotent.
KNOWN_GITHUB_PROXY_PREFIXES = (
    "https://cdn.gh-proxy.org/",
    "https://edgeone.gh-proxy.org/",
    "https://gh-proxy.org/",
    "https://gh-proxy.com/",
    "https://v6.gh-proxy.org/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
    "https://mirror.ghproxy.com/",
    "https://hk.gh-proxy.org/",
    "https://ghproxy.cc/",
    "https://gh.llkk.cc/",
    "https://gh.ddlc.top/",
)

DEFAULT_AOSP_MIRRORS = (
    "https://mirrors.bfsu.edu.cn/git/AOSP/",
    "https://mirrors.tuna.tsinghua.edu.cn/git/AOSP/",
    "https://mirrors.ustc.edu.cn/aosp/",
    "https://android.googlesource.com/",
)

DEFAULT_LINEAGE_MIRRORS = (
    "https://mirrors.bfsu.edu.cn/git/lineageOS/",
    "https://mirrors.tuna.tsinghua.edu.cn/git/lineageOS/",
)

DEFAULT_REPO_GIT_MIRRORS = (
    "https://mirrors.bfsu.edu.cn/git/git-repo",
    "https://mirror.nju.edu.cn/git/git-repo",
    "https://mirrors.tuna.tsinghua.edu.cn/git/git-repo",
    "https://gerrit.googlesource.com/git-repo",
)

DEFAULT_REPO_BIN_URLS = (
    "https://cdn.gh-proxy.org/https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo",
    "https://edgeone.gh-proxy.org/https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo",
    "https://gh-proxy.org/https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo",
    "https://cdn.jsdelivr.net/gh/GerritCodeReview/git-repo@main/repo",
    "https://fastly.jsdelivr.net/gh/GerritCodeReview/git-repo@main/repo",
    "https://v6.gh-proxy.org/https://raw.githubusercontent.com/GerritCodeReview/git-repo/main/repo",
    "https://storage.googleapis.com/git-repo-downloads/repo",
)

DEFAULT_APT_MIRRORS = (
    "https://mirrors.cloud.tencent.com/ubuntu",
    "https://mirrors.aliyun.com/ubuntu",
    "https://mirrors.huaweicloud.com/ubuntu",
    "https://mirrors.tuna.tsinghua.edu.cn/ubuntu",
    "https://mirrors.bfsu.edu.cn/ubuntu",
    "https://mirrors.ustc.edu.cn/ubuntu",
    "https://mirror.nju.edu.cn/ubuntu",
)

DEFAULT_CLO_MIRRORS = (
    "https://git.codelinaro.org/clo/la",
)

DOMESTIC_DIRECT_HOSTS = (
    "ivolces.com",
    "tsinghua.edu.cn",
    "bfsu.edu.cn",
    "ustc.edu.cn",
    "nju.edu.cn",
    "aliyun.com",
    "aliyuncs.com",
    "huaweicloud.com",
    "cloud.tencent.com",
    "tencentyun.com",
    "iscas.ac.cn",
    "ghfast.top",
    "gh-proxy.org",
    "ghproxy.net",
    "gh-proxy.com",
    "jsdelivr.net",
)

ARCHIVE_APT_HOSTS = (
    "archive.ubuntu.com",
    "cn.archive.ubuntu.com",
    "azure.archive.ubuntu.com",
    "security.ubuntu.com",
    "ports.ubuntu.com",
)


def _split_csv_env(name: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    items = []
    for part in raw.split(","):
        p = part.strip()
        if p in ("direct", "DIRECT", "-"):
            items.append("")
        elif p:
            items.append(p)
    return tuple(items) if items else fallback


def normalize_proxy_prefix(prefix: str) -> str:
    """Ensure proxy prefix ends with '/' unless empty (meaning direct upstream)."""
    p = (prefix or "").strip()
    if not p or p.lower() in ("direct", "none", "off", "-"):
        return ""
    if not p.endswith("/"):
        p += "/"
    return p


def is_domestic_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if host in ("localhost", "::1") or host.startswith("127."):
        return True
    return any(host == d or host.endswith("." + d) for d in DOMESTIC_DIRECT_HOSTS)


def detect_mirror_mode(explicit: str | None = None) -> str:
    """Return 'cn' or 'direct' depending on CLI override, env, and runner environment."""
    val = (explicit or os.environ.get("MIRROR_MODE") or "auto").strip().lower()
    if val in ("cn", "china", "mirror", "on", "1", "true"):
        return "cn"
    if val in ("direct", "global", "off", "0", "false"):
        return "direct"
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        if os.environ.get("RUNNER_ENVIRONMENT", "").lower() == "github-hosted":
            return "direct"
    return "cn"


def strip_github_proxy(url: str) -> str:
    """Strip known GitHub mirror prefixes so wrapping stays idempotent."""
    candidates = list(KNOWN_GITHUB_PROXY_PREFIXES)
    for item in _split_csv_env("GITHUB_MIRRORS", DEFAULT_GITHUB_PROXIES):
        norm = normalize_proxy_prefix(item)
        if norm and norm not in candidates:
            candidates.append(norm)
    explicit_single = normalize_proxy_prefix(os.environ.get("GITHUB_PROXY", ""))
    if explicit_single and explicit_single not in candidates:
        candidates.append(explicit_single)

    cleaned = url
    changed = True
    while changed:
        changed = False
        for prefix in candidates:
            if prefix and cleaned.startswith(prefix + "https://"):
                cleaned = cleaned[len(prefix):]
                changed = True
                break
            if prefix and cleaned.startswith(prefix.rstrip("/") + "/https://"):
                cleaned = cleaned[len(prefix.rstrip("/")) + 1:]
                changed = True
                break
    return cleaned


def apply_github_proxy(url: str, prefix: str) -> str:
    base = strip_github_proxy(url)
    norm = normalize_proxy_prefix(prefix)
    if not norm:
        return base
    return norm + base


def github_proxy_list(mode: str | None = None) -> list[str]:
    """Return ordered list of proxy prefixes ('' denotes direct upstream)."""
    resolved_mode = detect_mirror_mode(mode)
    explicit = os.environ.get("GITHUB_PROXY", "").strip()
    configured = [normalize_proxy_prefix(p) for p in _split_csv_env("GITHUB_MIRRORS", DEFAULT_GITHUB_PROXIES)]
    order: list[str] = []
    if explicit:
        order.append(normalize_proxy_prefix(explicit))
    if resolved_mode == "direct":
        order.append("")
        order.extend(configured)
    else:
        order.extend(configured)
        order.append("")
    dedup: list[str] = []
    for p in order:
        if p not in dedup:
            dedup.append(p)
    return dedup


def expand_github_url(url: str, mode: str | None = None) -> list[str]:
    """Expand a github.com or raw.githubusercontent.com URL across proxies and CDNs."""
    base = strip_github_proxy(url)
    parsed = urllib.parse.urlsplit(base)
    host = (parsed.hostname or "").lower()
    urls: list[str] = []
    prefixes = github_proxy_list(mode)
    if host == "github.com":
        for p in prefixes:
            urls.append(apply_github_proxy(base, p))
    elif host == "raw.githubusercontent.com":
        for p in prefixes:
            urls.append(apply_github_proxy(base, p))
        parts = [x for x in parsed.path.split("/") if x]
        if len(parts) >= 4:
            owner, repo, ref = parts[0], parts[1], parts[2]
            rel = "/".join(parts[3:])
            for cdn in ("https://cdn.jsdelivr.net/gh", "https://fastly.jsdelivr.net/gh"):
                urls.append(f"{cdn}/{owner}/{repo}@{ref}/{rel}")
    else:
        urls.append(url)
    dedup: list[str] = []
    for u in urls:
        if u not in dedup:
            dedup.append(u)
    return dedup


def _tunnel_proxy_url() -> str:
    port = int(os.environ.get("MIRROR_LOCAL_PROXY_PORT", "7890"))
    return f"http://127.0.0.1:{port}"


def _build_opener(respect_proxy: bool, use_tunnel: bool = False) -> urllib.request.OpenerDirector:
    if use_tunnel:
        proxy = _tunnel_proxy_url()
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if respect_proxy:
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe_http(
    url: str,
    timeout: float = 6.0,
    is_git: bool = False,
    reject_html: bool = True,
    expect_token: bytes | None = None,
) -> tuple[bool, int, str]:
    """Return (ok, latency_ms, reason) for one candidate URL."""
    domestic = is_domestic_url(url)
    use_tunnel = False
    respect_proxy = os.environ.get("MIRROR_RESPECT_PROXY", "0") == "1"
    if domestic and os.environ.get("MIRROR_FORCE_PROXY", "0") != "1":
        respect_proxy = False
    elif not domestic and local_tunnel_up() and not os.environ.get("GITHUB_PROXY", "").strip():
        use_tunnel = True
    opener = _build_opener(respect_proxy, use_tunnel=use_tunnel)
    target = url
    if is_git:
        clean = url.rstrip("/")
        if not clean.endswith("/info/refs?service=git-upload-pack"):
            if not clean.endswith(".git") and "/git/git-repo" not in clean:
                pass
            target = clean + "/info/refs?service=git-upload-pack"
    headers = {"User-Agent": USER_AGENT_GIT if is_git else USER_AGENT_HTTP}
    if not is_git and not expect_token:
        headers["Range"] = "bytes=0-511"
    req = urllib.request.Request(target, headers=headers, method="GET")
    t0 = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            sample = resp.read(8192 if expect_token else 512)
            ms = int((time.monotonic() - t0) * 1000)
            if status not in (200, 206):
                return False, ms, f"http {status}"
            if reject_html and "text/html" in ctype and not url.endswith(".html"):
                return False, ms, "unexpected text/html body"
            if is_git and b"service=git-upload-pack" not in sample and b"0000" not in sample:
                return False, ms, "not a git-upload-pack endpoint"
            if expect_token and expect_token not in sample:
                return False, ms, "missing expected signature"
            return True, ms, "ok"
    except urllib.error.HTTPError as exc:
        ms = int((time.monotonic() - t0) * 1000)
        reason = f"http {exc.code}"
        exc.close()
        return False, ms, reason
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return False, ms, str(exc)[:100]


def rank_urls(
    urls: list[str],
    timeout: float = 6.0,
    is_git: bool = False,
    reject_html: bool = True,
    expect_token: bytes | None = None,
) -> list[tuple[str, int]]:
    """Probe candidates in parallel and return working ones sorted by lowest latency."""
    if not urls:
        return []
    results: list[tuple[str, int]] = []
    workers = min(len(urls), 12)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(_probe_http, u, timeout, is_git, reject_html, expect_token): u
            for u in urls
        }
        for fut in concurrent.futures.as_completed(future_map):
            url = future_map[fut]
            try:
                ok, ms, _ = fut.result()
            except Exception:
                continue
            if ok:
                results.append((url, ms))
    results.sort(key=lambda item: item[1])
    return results


def local_tunnel_up(host: str = "127.0.0.1", port: int | None = None) -> bool:
    """Return True when a local outbound proxy or SSH -R reverse tunnel is listening."""
    if os.environ.get("MIRROR_IGNORE_TUNNEL", "0") == "1":
        return False
    import socket
    check_port = port or int(os.environ.get("MIRROR_LOCAL_PROXY_PORT", "7890"))
    try:
        with socket.create_connection((host, check_port), timeout=0.25):
            return True
    except OSError:
        return False


def rank_github_urls(url: str, mode: str | None = None, timeout: float = 6.0, is_git: bool = True) -> list[str]:
    resolved_mode = detect_mirror_mode(mode)
    candidates = expand_github_url(url, mode=resolved_mode)
    base = strip_github_proxy(url)
    # Only force the 127.0.0.1 tunnel ahead of CN CDN mirrors when explicitly requested (e.g. private repos or zero-proxy mode).
    if os.environ.get("MIRROR_PREFER_TUNNEL", "0") == "1" and local_tunnel_up() and not os.environ.get("GITHUB_PROXY", "").strip():
        return [base] + [u for u in candidates if u != base]
    if resolved_mode == "cn" and os.environ.get("MIRROR_RACE_DIRECT", "0") != "1":
        domestic = [u for u in candidates if u != base]
        ranked_dom = [u for u, _ in rank_urls(domestic, timeout=timeout, is_git=is_git, reject_html=True)]
        if is_git:
            # v6.gh-proxy.org can win 1KB info/refs probes yet throttle large pack transfers; keep it behind IPv4/CDN proxies.
            ranked_dom = [u for u in ranked_dom if "v6.gh-proxy.org" not in u] + [
                u for u in ranked_dom if "v6.gh-proxy.org" in u
            ]
        if ranked_dom:
            # Prefer domestic proxies for sustained pack/release throughput in CN; keep direct as last fallback.
            if base in candidates and base not in ranked_dom:
                ranked_dom.append(base)
            return ranked_dom
    ranked = rank_urls(candidates, timeout=timeout, is_git=is_git, reject_html=True)
    if ranked:
        return [u for u, _ in ranked]
    return candidates


def rewrite_manifest_text(
    text: str,
    *,
    aosp_mirror: str | None = None,
    lineage_mirror: str | None = None,
    github_prefix: str | None = None,
    clo_mirror: str | None = None,
    lfs_mirror: str | None = None,
) -> str:
    """Rewrite <remote fetch=...> attributes idempotently across AOSP, LineageOS, GitHub, CLO, and Gitea LFS."""
    if aosp_mirror:
        aosp = aosp_mirror.rstrip("/") + "/"
        text = re.sub(
            r'fetch="https://android\.googlesource\.com/?"',
            lambda _: f'fetch="{aosp}"',
            text,
        )
        # Support repeated re-writes when a mirror rotated previously.
        for candidate in DEFAULT_AOSP_MIRRORS:
            cand = candidate.rstrip("/") + "/"
            if cand != aosp:
                text = text.replace(f'fetch="{cand}"', f'fetch="{aosp}"')
                text = text.replace(f'fetch="{cand.rstrip("/")}"', f'fetch="{aosp.rstrip("/")}"')

    if lineage_mirror:
        lin_base = lineage_mirror.rstrip("/")
        lin_org = lin_base + "/LineageOS"
        text = re.sub(
            r'fetch="https://github\.com/LineageOS/?"',
            lambda _: f'fetch="{lin_org}"',
            text,
        )
        for candidate in DEFAULT_LINEAGE_MIRRORS:
            cand_org = candidate.rstrip("/") + "/LineageOS"
            if cand_org != lin_org:
                text = text.replace(f'fetch="{cand_org}"', f'fetch="{lin_org}"')
                text = text.replace(f'fetch="{cand_org}/"', f'fetch="{lin_org}"')

    if github_prefix is not None:
        norm = normalize_proxy_prefix(github_prefix)

        def _replace_gh(match: re.Match[str]) -> str:
            raw_url = match.group(1)
            return f'fetch="{apply_github_proxy(raw_url, norm)}"'

        text = re.sub(
            r'fetch="(https://[^"]*github\.com[^"]*)"',
            _replace_gh,
            text,
        )

    if clo_mirror:
        clo = clo_mirror.rstrip("/")
        text = re.sub(
            r'(<remote[^>]*name="clo-la"[^>]*fetch=")([^"]+)(")',
            lambda m: f"{m.group(1)}{clo}{m.group(3)}",
            text,
        )
        for candidate in DEFAULT_CLO_MIRRORS:
            text = text.replace(f'fetch="{candidate}"', f'fetch="{clo}"')
            text = text.replace(f'fetch="{candidate}/"', f'fetch="{clo}"')

    if lfs_mirror:
        lfs = lfs_mirror.rstrip("/")
        text = re.sub(
            r'(<remote[^>]*name="lfs"[^>]*fetch=")([^"]+)(")',
            lambda m: f"{m.group(1)}{lfs}{m.group(3)}",
            text,
        )
        text = re.sub(
            r'fetch="https://gitea\.com/projectInfinity-x/?"',
            lambda _: f'fetch="{lfs}"',
            text,
        )

    return text


def detect_ubuntu_codename() -> str:
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        for line in os_release.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VERSION_CODENAME="):
                return line.split("=", 1)[1].strip().strip('"').lower()
    return "noble"


def transform_ubuntu_sources(text: str, mirror_url: str, force: bool = False) -> tuple[str, int]:
    """Rewrite standard Ubuntu archive URIs to a domestic mirror in DEB822 or one-line apt files."""
    target = mirror_url.rstrip("/")
    count = 0
    lines_out: list[str] = []
    hosts = list(ARCHIVE_APT_HOSTS)
    if force:
        for cand in DEFAULT_APT_MIRRORS:
            host = urllib.parse.urlsplit(cand).hostname
            if host and host not in hosts:
                hosts.append(host)
    pattern = re.compile(
        r"https?://(?:" + "|".join(re.escape(h) for h in hosts) + r")/ubuntu\b"
    )
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("#"):
            lines_out.append(line)
            continue
        new_line, n = pattern.subn(target, line)
        count += n
        lines_out.append(new_line)
    return "".join(lines_out), count


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_multi_mirror(
    urls: list[str],
    output: Path,
    *,
    jobs: int = 16,
    expected_sha256: str | None = None,
    timeout: float = 8.0,
    expand_github: bool = True,
    mode: str | None = None,
    expect_token: bytes | None = None,
) -> Path:
    """Download one file using fastest live mirrors with aria2c multi-thread + curl fallback."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if expected_sha256 and output.is_file():
        if sha256_file(output).lower() == expected_sha256.lower():
            return output

    expanded: list[str] = []
    for u in urls:
        for item in (expand_github_url(u, mode=mode) if expand_github else [u]):
            if item not in expanded:
                expanded.append(item)

    ranked = rank_urls(
        expanded,
        timeout=timeout,
        is_git=False,
        reject_html=not str(output).endswith(".html"),
        expect_token=expect_token,
    )
    active_urls = [u for u, _ in ranked] if ranked else expanded

    # 1. Primary: aria2c multi-server + multi-connection resumable transfer.
    aria2 = shutil.which("aria2c")
    tunnel_on = local_tunnel_up() and os.environ.get("MIRROR_FORCE_PROXY", "0") != "1"
    if aria2:
        env = os.environ.copy()
        aria2_proxy_args: list[str] = []
        if all(is_domestic_url(u) for u in active_urls) and env.get("MIRROR_FORCE_PROXY", "0") != "1":
            for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
                env.pop(k, None)
            aria2_proxy_args = ["--all-proxy="]
        elif tunnel_on and all(not is_domestic_url(u) for u in active_urls):
            aria2_proxy_args = [f"--all-proxy={_tunnel_proxy_url()}"]
        cmd = [
            aria2,
            "-c",
            "-x", str(max(1, min(16, jobs))),
            "-s", str(max(1, min(16, jobs))),
            "-k", "1M",
            "--file-allocation=none",
            "--max-tries=4",
            "--retry-wait=2",
            "--connect-timeout=15",
            "--timeout=45",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--summary-interval=0",
            "--console-log-level=warn",
            *aria2_proxy_args,
            "-d", str(output.parent),
            "-o", output.name,
            *active_urls,
        ]
        res = subprocess.run(cmd, env=env)
        if res.returncode == 0 and output.is_file():
            if not expected_sha256 or sha256_file(output).lower() == expected_sha256.lower():
                if not expect_token or expect_token in output.read_bytes()[:8192]:
                    return output
            output.unlink(missing_ok=True)

    # 2. Fallback: curl / Python per-URL sequential retry.
    curl = shutil.which("curl")
    last_err = "no candidate succeeded"
    for candidate in active_urls:
        env = os.environ.copy()
        use_tunnel = not is_domestic_url(candidate) and local_tunnel_up()
        if is_domestic_url(candidate) and env.get("MIRROR_FORCE_PROXY", "0") != "1":
            for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
                env.pop(k, None)
        tmp = output.with_name(output.name + ".part")
        ok = False
        if curl:
            curl_args = [curl, "-fsSL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "15", "-C", "-"]
            if is_domestic_url(candidate) and env.get("MIRROR_FORCE_PROXY", "0") != "1":
                curl_args += ["--noproxy", "*"]
            elif use_tunnel:
                curl_args += ["-x", _tunnel_proxy_url()]
            res = subprocess.run([*curl_args, candidate, "-o", str(tmp)], env=env)
            ok = res.returncode == 0 and tmp.is_file()
        else:
            opener = _build_opener(not is_domestic_url(candidate), use_tunnel=use_tunnel)
            try:
                with opener.open(urllib.request.Request(candidate, headers={"User-Agent": USER_AGENT_HTTP}), timeout=30) as resp:
                    with tmp.open("wb") as fh:
                        shutil.copyfileobj(resp, fh)
                ok = True
            except Exception as exc:
                last_err = str(exc)
                ok = False
        if not ok:
            tmp.unlink(missing_ok=True)
            continue
        if expect_token and expect_token not in tmp.read_bytes()[:8192]:
            tmp.unlink(missing_ok=True)
            last_err = f"{candidate}: missing expected header"
            continue
        if expected_sha256 and sha256_file(tmp).lower() != expected_sha256.lower():
            tmp.unlink(missing_ok=True)
            last_err = f"{candidate}: SHA-256 mismatch"
            continue
        tmp.replace(output)
        return output

    raise RuntimeError(f"failed to download {output.name}: {last_err}")


def cmd_mode(args: argparse.Namespace) -> int:
    print(detect_mirror_mode(args.mode))
    return 0


def cmd_probe_github(args: argparse.Namespace) -> int:
    for url in rank_github_urls(args.url, mode=args.mode, timeout=args.timeout, is_git=not args.http_only):
        print(url)
    return 0


def cmd_probe_apt(args: argparse.Namespace) -> int:
    codename = args.codename or detect_ubuntu_codename()
    base_list = list(_split_csv_env("APT_MIRRORS", DEFAULT_APT_MIRRORS))
    probes = [f"{m.rstrip('/')}/dists/{codename}/Release" for m in base_list]
    ranked = rank_urls(probes, timeout=args.timeout, is_git=False, reject_html=True)
    if ranked:
        fastest = ranked[0][0].rsplit(f"/dists/{codename}/Release", 1)[0]
        print(fastest)
        return 0
    print(base_list[0])
    return 0


def cmd_probe_git_base(urls: tuple[str, ...], timeout: float) -> int:
    if not urls:
        return 1
    return 0


def _pick_first_live(urls: list[str], *, timeout: float = 6.0, is_git: bool = True, reject_html: bool = True) -> str | None:
    """Return highest-priority candidate URL that responds cleanly (avoids /info/refs ping races vs queued mirrors)."""
    if not urls:
        return None
    live = {u for u, _ in rank_urls(urls, timeout=timeout, is_git=is_git, reject_html=reject_html)}
    for u in urls:
        if u in live:
            return u
    return None


def cmd_probe_aosp(args: argparse.Namespace) -> int:
    mode = detect_mirror_mode(getattr(args, "mode", "auto"))
    base_list = list(_split_csv_env("AOSP_MIRRORS", DEFAULT_AOSP_MIRRORS))
    if mode == "direct":
        print("https://android.googlesource.com/")
        return 0
    domestic = [m for m in base_list if is_domestic_url(m)]
    probe_list = domestic or base_list
    probes = [m.rstrip("/") + "/platform/manifest.git" for m in probe_list]
    picked = _pick_first_live(probes, timeout=args.timeout, is_git=True, reject_html=True)
    if picked:
        print(picked.removesuffix("platform/manifest.git"))
        return 0
    fallback_probes = [m.rstrip("/") + "/platform/manifest.git" for m in base_list if m not in probe_list]
    picked_fb = _pick_first_live(fallback_probes, timeout=args.timeout, is_git=True, reject_html=True)
    if picked_fb:
        print(picked_fb.removesuffix("platform/manifest.git"))
        return 0
    print(base_list[0])
    return 0


def cmd_probe_lineage(args: argparse.Namespace) -> int:
    base_list = list(_split_csv_env("LINEAGE_MIRRORS", DEFAULT_LINEAGE_MIRRORS))
    probes = [m.rstrip("/") + "/LineageOS/android.git" for m in base_list]
    picked = _pick_first_live(probes, timeout=args.timeout, is_git=True, reject_html=True)
    if picked:
        print(picked.removesuffix("LineageOS/android.git"))
    else:
        print(base_list[0])
    return 0


def cmd_probe_repo_url(args: argparse.Namespace) -> int:
    mode = detect_mirror_mode(args.mode)
    base_list = list(_split_csv_env("REPO_URL_MIRRORS", DEFAULT_REPO_GIT_MIRRORS))
    if mode == "direct":
        print("https://gerrit.googlesource.com/git-repo")
        return 0
    domestic = [m for m in base_list if is_domestic_url(m)]
    probe_list = domestic or base_list
    picked = _pick_first_live(probe_list, timeout=args.timeout, is_git=True, reject_html=True)
    if picked:
        print(picked)
        return 0
    fallback = [m for m in base_list if m not in probe_list]
    picked_fb = _pick_first_live(fallback, timeout=args.timeout, is_git=True, reject_html=True)
    print(picked_fb if picked_fb else base_list[0])
    return 0


def cmd_rewrite_manifest(args: argparse.Namespace) -> int:
    src = Path(args.input)
    text = src.read_text(encoding="utf-8")
    out = rewrite_manifest_text(
        text,
        aosp_mirror=args.aosp_mirror,
        lineage_mirror=args.lineage_mirror,
        github_prefix=args.github_prefix,
        clo_mirror=args.clo_mirror,
        lfs_mirror=args.lfs_mirror,
    )
    dst = Path(args.output) if args.output else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out, encoding="utf-8")
    return 0


def cmd_configure_apt(args: argparse.Namespace) -> int:
    codename = args.codename or detect_ubuntu_codename()
    mirror = args.mirror
    if not mirror:
        probes = [f"{m.rstrip('/')}/dists/{codename}/Release" for m in _split_csv_env("APT_MIRRORS", DEFAULT_APT_MIRRORS)]
        ranked = rank_urls(probes, timeout=args.timeout, is_git=False, reject_html=True)
        mirror = ranked[0][0].rsplit(f"/dists/{codename}/Release", 1)[0] if ranked else DEFAULT_APT_MIRRORS[0]

    candidates = [Path("/etc/apt/sources.list.d/ubuntu.sources"), Path("/etc/apt/sources.list")]
    changed_files = 0
    for path in candidates:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated, replacements = transform_ubuntu_sources(original, mirror, force=args.force)
        if replacements == 0:
            continue
        changed_files += 1
        print(f"APT {path}: {replacements} URI(s) -> {mirror}")
        if not args.dry_run:
            backup = Path(str(path) + ".bak.pre-cn-mirror")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
            path.write_text(updated, encoding="utf-8")
    if changed_files == 0:
        print(f"APT sources already using local/custom mirror (selected candidate: {mirror})")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    token = args.expect_token.encode("utf-8") if args.expect_token else None
    download_multi_mirror(
        args.urls,
        Path(args.output),
        jobs=args.jobs,
        expected_sha256=args.sha256 or None,
        timeout=args.timeout,
        expand_github=not args.no_expand_github,
        mode=args.mode,
        expect_token=token,
    )
    return 0


def _is_valid_repo_launcher(path: Path) -> bool:
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    head = path.read_bytes()[:8192]
    return (b"#!/usr/bin/env python" in head or head.startswith(b"#!")) and b"REPO_URL" in head


def cmd_ensure_repo(args: argparse.Namespace) -> int:
    dest = Path(args.output)
    if _is_valid_repo_launcher(dest):
        print(dest)
        return 0
    existing = shutil.which("repo")
    if existing:
        existing_path = Path(existing)
        if _is_valid_repo_launcher(existing_path):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(existing_path, dest)
            dest.chmod(0o755)
            print(dest)
            return 0
    mode = detect_mirror_mode(args.mode)
    urls = list(DEFAULT_REPO_BIN_URLS)
    if mode == "direct":
        urls = ["https://storage.googleapis.com/git-repo-downloads/repo", *urls]
    download_multi_mirror(
        urls,
        dest,
        jobs=args.jobs,
        timeout=args.timeout,
        expand_github=False,
        mode=mode,
        expect_token=b"REPO_URL",
    )
    dest.chmod(0o755)
    print(dest)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mode = sub.add_parser("mode", help="Resolve active mirror mode (cn or direct)")
    p_mode.add_argument("--mode", default="auto")
    p_mode.set_defaults(func=cmd_mode)

    p_gh = sub.add_parser("probe-github", help="Return ranked GitHub repo/URL candidates")
    p_gh.add_argument("--url", required=True)
    p_gh.add_argument("--mode", default="auto")
    p_gh.add_argument("--timeout", type=float, default=6.0)
    p_gh.add_argument("--http-only", action="store_true")
    p_gh.set_defaults(func=cmd_probe_github)

    p_apt = sub.add_parser("probe-apt", help="Return fastest Ubuntu APT domestic mirror")
    p_apt.add_argument("--codename", default="")
    p_apt.add_argument("--timeout", type=float, default=5.0)
    p_apt.set_defaults(func=cmd_probe_apt)

    p_aosp = sub.add_parser("probe-aosp", help="Return fastest AOSP git mirror")
    p_aosp.add_argument("--mode", default="auto")
    p_aosp.add_argument("--timeout", type=float, default=6.0)
    p_aosp.set_defaults(func=cmd_probe_aosp)

    p_los = sub.add_parser("probe-lineage", help="Return fastest LineageOS git mirror")
    p_los.add_argument("--timeout", type=float, default=6.0)
    p_los.set_defaults(func=cmd_probe_lineage)

    p_repo_url = sub.add_parser("probe-repo-url", help="Return fastest git-repo remote for REPO_URL")
    p_repo_url.add_argument("--mode", default="auto")
    p_repo_url.add_argument("--timeout", type=float, default=6.0)
    p_repo_url.set_defaults(func=cmd_probe_repo_url)

    p_rw = sub.add_parser("rewrite-manifest", help="Rewrite manifest <remote fetch=...> URLs")
    p_rw.add_argument("--input", required=True)
    p_rw.add_argument("--output", default="")
    p_rw.add_argument("--aosp-mirror", default=None)
    p_rw.add_argument("--lineage-mirror", default=None)
    p_rw.add_argument("--github-prefix", default=None)
    p_rw.add_argument("--clo-mirror", default=None)
    p_rw.add_argument("--lfs-mirror", default=None)
    p_rw.set_defaults(func=cmd_rewrite_manifest)

    p_capt = sub.add_parser("configure-apt", help="Switch Ubuntu APT sources to fastest live domestic mirror")
    p_capt.add_argument("--codename", default="")
    p_capt.add_argument("--mirror", default="")
    p_capt.add_argument("--timeout", type=float, default=5.0)
    p_capt.add_argument("--dry-run", action="store_true")
    p_capt.add_argument("--force", action="store_true")
    p_capt.set_defaults(func=cmd_configure_apt)

    p_dl = sub.add_parser("download", help="Download a file using multi-mirror + multi-threaded aria2c")
    p_dl.add_argument("--output", required=True)
    p_dl.add_argument("--jobs", type=int, default=16)
    p_dl.add_argument("--sha256", default="")
    p_dl.add_argument("--timeout", type=float, default=8.0)
    p_dl.add_argument("--mode", default="auto")
    p_dl.add_argument("--no-expand-github", action="store_true")
    p_dl.add_argument("--expect-token", default="")
    p_dl.add_argument("urls", nargs="+")
    p_dl.set_defaults(func=cmd_download)

    p_er = sub.add_parser("ensure-repo", help="Download/verify git-repo launcher into destination")
    p_er.add_argument("--output", default=str(Path.home() / ".local/bin/repo"))
    p_er.add_argument("--jobs", type=int, default=8)
    p_er.add_argument("--timeout", type=float, default=6.0)
    p_er.add_argument("--mode", default="auto")
    p_er.set_defaults(func=cmd_ensure_repo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
