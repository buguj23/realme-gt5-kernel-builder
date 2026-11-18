#!/usr/bin/env python3
"""Pin this checkout to one Action-Build SM8550 5.15 analogue + matching ROM."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from rom_inputs import baseline

ROOT = Path(__file__).resolve().parents[1]


def sub_file(path: Path, mapping: dict[str, str]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    orig = text
    for a, b in mapping.items():
        text = text.replace(a, b)
    if text != orig:
        path.write_text(text)


def lock_workflow(release: str) -> None:
    p = ROOT / ".github/workflows/build-kernel-gt5.yml"
    text = p.read_text(encoding="utf-8")
    text, count = re.subn(
        r"(^      FILE:\n(?:        [^\n]+\n)*?        default: )[^\n]+"
        r"(\n        options:\n)(?:          - [^\n]+\n)+",
        lambda match: match[1] + release + match[2] + f"          - {release}\n",
        text, count=1, flags=re.M)
    if count != 1:
        raise ValueError("kernel workflow FILE input not found")
    p.write_text(text)


def lock_fetch(file: str) -> None:
    p = ROOT / "scripts/00-fetch.sh"
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"FILE=\$\{FILE:-[^}]+\}", f"FILE=${{FILE:-{file}}}", text, count=1)
    p.write_text(text)


def write_readme(file: str, android: str, api: int, kmi: str, note: str) -> None:
    (ROOT / "README.md").write_text(
        f"""# Realme GT5 — kernel `{file}` + ROM ossi

Branch for **one** Action-Build SM8550 5.15 OGKI analogue.

| | |
|---|---|
| Analogue | `{file}` ({note}) |
| Android | {android} (API {api}) |
| KMI | `{kmi}` |
| SoC | SM8550 kalama |
| Device | ossi / RMX3820 / RE5C33 |
| Root | YukiSU LKM `CONFIG_KSU=m` |
| Kernel | OEM OGKI `oplus_build_kernel.sh kalama gki` — **not** Google GKI |
| ROM | [Build instructions](docs/ROM_BUILD.md) |
| metadata | **f2fs** (stock) |

```bash
export FILE={file}
scripts/00-fetch.sh
scripts/10-patch.sh
scripts/20-build.sh
```

CI: **Build Realme GT5 OGKI (KSU)** uses the matching stock baseline.
""",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) not in (2, 6):
        print("usage: specialize-branch.py RELEASE | FILE ANDROID API KMI NOTE", file=sys.stderr)
        return 2
    if len(sys.argv) == 2:
        spec = baseline(sys.argv[1])
        note = f"Stock baseline {spec['coloros']}"
    else:
        file, android, api_s, kmi, note = sys.argv[1:]
        entries = json.loads((ROOT / "official/kernels.json").read_text()).values()
        candidates = [entry for entry in entries if
                      (entry["file"], entry["android"], entry["api"], entry["kmi"]) == (file, android, int(api_s), kmi)]
        specific = [entry for entry in candidates if entry["branch"] in note or entry["coloros"] in note]
        candidates = specific or candidates
        if len(candidates) != 1:
            print("Specify the Linux release to select one stock baseline", file=sys.stderr)
            return 2
        spec = candidates[0]
    file, android, api, kmi = (spec[key] for key in ("file", "android", "api", "kmi"))
    release = spec["branch"]

    kernel = {
        "codename": "ossi",
        "model": "RMX3820",
        "board": "RE5C33",
        "soc": "sm8550",
        "cpud": "kalama",
        "file": file,
        "android": android,
        "api": api,
        "kmi": kmi,
        "build_method": "gki",
        "build_method_meaning": "OEM OGKI flavor of oplus_build_kernel.sh, NOT Google generic GKI",
        "root": "YukiSU LKM CONFIG_KSU=m + Kasumi + YukiZygisk",
        "metadata_fs": spec["metadata_fs"],
        "linux_release": release,
        "coloros": spec["coloros"],
        "linux": spec["linux"],
        "security_patch": spec["security_patch"],
        "os_patch_level": spec["os_patch_level"],
        "note": note,
    }
    (ROOT / "kernel.json").write_text(json.dumps(kernel, indent=2) + "\n")

    (ROOT / "rom/device/realme/ossi/branch.mk").write_text(
        f"# Default for {release}. The builder can stage any stock baseline.\n"
        f"BOARD_KERNEL_ANALOGUE := {file}\n"
        f"BOOT_SECURITY_PATCH := {spec['security_patch']}\n"
        f"VENDOR_SECURITY_PATCH := $(BOOT_SECURITY_PATCH)\n"
    )

    vend = ROOT / "rom/vendor/realme/ossi/ossi-vendor.mk"
    vt = vend.read_text()
    vt = re.sub(r"Android \d+", f"Android {android}", vt)
    vend.write_text(vt)

    lock_workflow(release)
    lock_fetch(file)
    write_readme(file, android, api, kmi, note)
    print(f"specialized {file} android={android} api={api}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
