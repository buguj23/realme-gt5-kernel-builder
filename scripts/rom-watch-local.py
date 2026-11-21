#!/usr/bin/env python3
"""Stream an existing systemd ROM build into an Actions job without controlling it."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

UNIT = "bianyi-build.service"
PROPERTIES = ("ActiveState", "SubState", "Result", "ExecMainStatus", "MainPID", "InvocationID",
              "MemoryCurrent", "MemorySwapCurrent", "MemoryHigh", "MemoryMax", "ControlGroup")


def sanitize(text: str, root: Path) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = text.replace(str(root), "$BIANYI").replace(str(Path.home()), "$HOME")
    text = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]+|\bgithub_pat_[A-Za-z0-9_]+", "[REDACTED]", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:access_token|token|password|secret|sig|signature)=)[^\s&]+", r"\1[REDACTED]", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def service_state() -> dict[str, str]:
    args = ["systemctl", "--user", "show", UNIT]
    for prop in PROPERTIES:
        args += ["-p", prop]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if proc.returncode:
        raise RuntimeError("systemctl show failed: " + proc.stderr.strip())
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def gib(value: str) -> str:
    try:
        number = int(value)
        return "n/a" if number >= 2**63 else f"{number / 2**30:.2f} GiB"
    except (ValueError, TypeError):
        return "n/a"


def outcome(service: dict, state: dict, expected: str, observed: bool) -> str:
    actual = service.get("InvocationID", "")
    if actual and actual != expected:
        return "replaced"
    if service.get("ActiveState") in {"active", "activating", "deactivating"}:
        return "running" if actual == expected else "missing"
    if not observed and actual != expected:
        return "missing"
    if (state.get("state") == "completed" and state.get("phase") == "delivery_verified"
            and service.get("Result", "success") == "success"
            and service.get("ExecMainStatus", "0") == "0"):
        return "success"
    return "failure"


def metrics(service: dict, root: Path) -> dict:
    data = {"ram": gib(service.get("MemoryCurrent")), "swap": gib(service.get("MemorySwapCurrent")),
            "ram_high": gib(service.get("MemoryHigh")), "ram_max": gib(service.get("MemoryMax"))}
    meminfo = dict((line.split()[0].rstrip(":"), int(line.split()[1]) * 1024)
                   for line in Path("/proc/meminfo").read_text().splitlines() if len(line.split()) >= 2)
    data["host_available"] = gib(meminfo.get("MemAvailable"))
    stat = os.statvfs(root)
    data["disk_free"] = gib(stat.f_bavail * stat.f_frsize)
    data["load"] = " / ".join(f"{n:.2f}" for n in os.getloadavg())
    cg = Path("/sys/fs/cgroup") / service.get("ControlGroup", "").lstrip("/")
    for resource in ("memory", "io"):
        try:
            full = next(line for line in (cg / f"{resource}.pressure").read_text().splitlines() if line.startswith("full "))
            data[f"{resource}_stall"] = full.split()[1].split("=", 1)[1] + "%"
        except (OSError, StopIteration):
            data[f"{resource}_stall"] = "n/a"
    return data


def infer_phase(lines: list[str], fallback: str) -> str:
    phase = fallback
    for line in lines:
        if "[preflight " in line:
            phase = line[line.index("[preflight "):][:220]
        elif "Writing ninja" in line or "analyzing Android.bp" in line:
            phase = "Soong dependency analysis"
        elif "[rom-build] full ROM" in line:
            phase = "Full ROM / OTA / VINTF build"
    return phase


def summary(path: str, service: dict, state: dict, stats: dict, phase: str,
            status: str, recent: list[str]) -> None:
    if not path:
        return
    lines = ["### Local Infinity-X build", "", "Realme GT5 / ossi · Android 15 · Pure-OGKI 5.15.149", "",
             f"Updated: {datetime.now().astimezone().isoformat(timespec='seconds')}", "",
             "Live updates appear in **Stream local build (15s)**. This summary is a snapshot.", "",
             "| Item | Value |", "| --- | --- |"]
    for key, value in {"Result": status, "Phase": phase, "Service": service.get("ActiveState", "unknown"),
                       "Build state": state.get("state", "unknown"), **stats}.items():
        lines.append(f"| {html.escape(key)} | {html.escape(str(value)).replace('|', '&#124;')} |")
    lines += ["", "<details><summary>Recent build output</summary>", "", "<pre>",
              html.escape("\n".join(recent[-45:])), "</pre>", "</details>", ""]
    Path(path).write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--invocation", required=True)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.invocation):
        parser.error("invocation must be the 32-character systemd invocation ID")
    if not 5 <= args.interval <= 300:
        parser.error("interval must be between 5 and 300 seconds")
    root = args.root.resolve(strict=True)
    if args.summary_only:
        record = read_json(args.report)
        if record.get("invocation") != args.invocation:
            print("No matching monitoring snapshot is available.", flush=True)
            return 0
        summary(os.environ.get("GITHUB_STEP_SUMMARY", ""), record["service"], record["build"],
                record["stats"], record["phase"], record["status"], record["recent"])
        print(f"Last observed result: {record['status']}; observation time: {record['updated_at']}", flush=True)
        return 0
    log = root / "logs/build.log"
    offset = max(0, log.stat().st_size - 24000) if log.exists() else 0
    recent: deque[str] = deque(maxlen=60)
    observed = False
    phase = "unknown"
    failures = 0
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    print("Watching the existing local build; stopping this monitor leaves the build running.", flush=True)
    while True:
        try:
            service = service_state()
            failures = 0
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            failures += 1
            print(f"[monitor] {exc}", flush=True)
            if failures >= 4:
                return 2
            time.sleep(args.interval)
            continue
        state = read_json(root / "state/build-status.json")
        status = outcome(service, state, args.invocation, observed)
        observed = observed or service.get("InvocationID") == args.invocation
        lines = []
        if log.exists():
            size = log.stat().st_size
            if size < offset:
                offset = 0
            if size - offset > 128 * 1024:
                print(f"[monitor] {size - offset - 128 * 1024} earlier log bytes omitted; full log remains local.", flush=True)
                offset = size - 128 * 1024
            with log.open("rb") as stream:
                stream.seek(offset)
                raw = stream.read()
                # Keep a partial line for the next read, including split secrets/UTF-8.
                end = max(raw.rfind(b"\n"), raw.rfind(b"\r")) + 1
                if status != "running":
                    end = len(raw)
                if end:
                    lines = sanitize(raw[:end].decode(errors="replace"), root).splitlines()
                    offset += end
        phase = infer_phase(lines, phase if phase != "unknown" else state.get("phase", "unknown"))
        recent.extend(line for line in lines if line.strip())
        if len(lines) > 60:
            print(f"[monitor] {len(lines)-60} intermediate progress lines condensed.", flush=True)
        for line in lines[-60:]:
            # Prefix every line: untrusted build output must not become Actions commands.
            print("[local] " + line[:1800], flush=True)
        stats = metrics(service, root)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{stamp}] {status} | {phase} | RAM {stats['ram']} | swap {stats['swap']} | "
              f"host available {stats['host_available']} | disk free {stats['disk_free']} | "
              f"memory stall {stats['memory_stall']} | IO stall {stats['io_stall']} | load {stats['load']}", flush=True)
        record = {"invocation": args.invocation, "updated_at": stamp, "service": service, "build": state,
                  "stats": stats, "phase": phase, "status": status, "recent": list(recent)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.report)
        summary(summary_path, service, state, stats, phase, status, list(recent))
        if args.once:
            return 0 if status in {"running", "success"} else 1
        if status != "running":
            print(f"[monitor] Final result: {status}; build exit code={service.get('ExecMainStatus', 'unknown')}", flush=True)
            return 0 if status == "success" else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    # Actions recognizes :: commands even after a line prefix; disable interpretation.
    guard = "local_build_" + uuid.uuid4().hex
    print(f"::stop-commands::{guard}", flush=True)
    try:
        raise SystemExit(main())
    finally:
        print(f"::{guard}::", flush=True)
