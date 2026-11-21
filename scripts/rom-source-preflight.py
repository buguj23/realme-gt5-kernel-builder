#!/usr/bin/env python3
"""Check prerequisites behind the previous ossi Actions build failures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def validate(*, src: Path, work: Path, avb_key: str, kernel_source: str,
             prebuilt_kernel: str, force_prebuilt: str) -> dict:
    src = src.resolve()
    errors: list[str] = []
    checks: dict[str, str] = {}

    def source_path(value: str, label: str) -> Path | None:
        path = Path(value)
        if not value or path.is_absolute():
            errors.append(f"{label} must be a nonempty source-relative path: {value!r}")
            return None
        resolved = (src / path).resolve()
        if not resolved.is_relative_to(src):
            errors.append(f"{label} resolves outside source tree: {value!r}")
            return None
        return resolved

    if work.resolve().is_relative_to(src):
        errors.append("Build work/vendor backup directory is inside the Soong source tree")
    else:
        checks["work_outside_source"] = str(work.resolve())

    # Previous runs created Android.bp files under this in-tree backup location.
    for pattern in (".ossi-build.*", ".ossi-work.*"):
        for directory in src.glob(pattern):
            if directory.is_dir() and next(directory.rglob("Android.bp"), None) is not None:
                errors.append(f"Soong-visible stale vendor/build backup: {directory.name}")

    for platform in ("sm7250", "sm8150"):
        for name in ("Android.bp", "Android.mk"):
            path = src / "hardware/qcom" / platform / name
            if path.is_symlink() and not path.exists():
                errors.append(f"Dangling QCOM build file: {path.relative_to(src)}")

    key = source_path(avb_key, "OSSI_AVB_KEY")
    if key is not None:
        if not key.is_file() or key.stat().st_size == 0:
            errors.append(f"AVB key missing or empty: {avb_key}")
        else:
            checks["avb_key"] = avb_key

    kernel = source_path(kernel_source, "TARGET_KERNEL_SOURCE")
    if kernel is not None:
        for name in ("Makefile", "include/uapi/linux/types.h", "arch/arm64/include/uapi/asm/unistd.h"):
            if not (kernel / name).is_file():
                errors.append(f"Kernel UAPI source missing: {kernel_source}/{name}")
        include = kernel / "include"
        if include.is_dir():
            dangling = [str(p.relative_to(src)) for p in include.rglob("*")
                        if p.is_symlink() and not p.exists()]
            if dangling:
                errors.append("Dangling kernel include links: " + ", ".join(dangling[:10]))
        checks["kernel_uapi_source"] = kernel_source

    image = source_path(prebuilt_kernel, "TARGET_PREBUILT_KERNEL")
    if image is not None:
        if not image.is_file() or image.stat().st_size == 0:
            errors.append(f"Prebuilt kernel Image missing or empty: {prebuilt_kernel}")
        else:
            checks["prebuilt_kernel"] = prebuilt_kernel
    if force_prebuilt != "true":
        errors.append("TARGET_FORCE_PREBUILT_KERNEL must remain true for the delivered OGKI Image")
    else:
        checks["force_prebuilt"] = force_prebuilt

    if errors:
        raise ValueError("\n".join(errors))
    return {"status": "passed", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("src", "work", "avb-key", "kernel-source", "prebuilt-kernel", "force-prebuilt"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = validate(src=Path(args.src), work=Path(args.work), avb_key=args.avb_key,
                          kernel_source=args.kernel_source, prebuilt_kernel=args.prebuilt_kernel,
                          force_prebuilt=args.force_prebuilt)
    except (ValueError, OSError, RuntimeError) as exc:
        report = {"status": "failed", "error": str(exc)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
