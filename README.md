# Realme GT5 (`5.15.149`) — OEM OGKI Kernel & `ossi` ROM Builder

Single-branch repository targeting **Realme GT5 150W (`RMX3820` / `RE5C33` / `ossi`)** on stock firmware **`RMX3820_15.0.0.320(CN01)`** (`RMX3820_11.F.06_2060_202411241938`, Android 15 / API 35, SPL `2024-11-05`).

## Verified Baseline (`5.15.149`)

| Item | Value |
|---|---|
| Upstream Kernel Manifest | [`DestoryG/kernel_manifest`](https://github.com/DestoryG/kernel_manifest) (`realme/sm8550` / [`realme_gt5_v.xml`](manifests/realme-sm8550/realme_gt5_v.xml)) |
| Kernel Source | [`realme-kernel-opensource/realme_GT5-AndroidV-*`](https://github.com/realme-kernel-opensource/realme_GT5-AndroidV-common-source) (`5.15.149`) |
| Stock Kernel Release | `5.15.149-android13-8-o-01120-g3337bebe8205` |
| KMI / Generation / CRC | `android13-5.15` (gen `8`), `module_layout = 0x0222dd63` (**3260 / 3260** stock module imports matched) |
| Compiler Toolchain | Hermetic Clang `r450784e` (`14.0.7`) |
| Root Architecture | `Pure-OGKI` (zero built-in root) or `YukiSU-LKM` (`Rouyashiki/YukiSU`, out-of-tree `CONFIG_KSU=m`) |
| Banned Options | `CONFIG_KSU=y`, `SUSFS`, `KPM`, `FakeConfig`, OnePlus analogue manifests (`0xbb266e1e`) |
| Dynamic Partitions | `qti_dynamic_partitions` (`14491320320` B), `/metadata` = **`f2fs`**, DLKMs = `ext4`, vendor/odm/my_* = `erofs` |

## Kernel Build (Local & CI)

```bash
# 1. Fetch realme_gt5_v OEM OGKI sources via DestoryG/kernel_manifest
scripts/00-fetch.sh

# 2. Optional KMI-safe patches (SUSFS/KPM/FakeConfig explicitly disallowed)
scripts/10-patch.sh

# 3a. Pure-OGKI (zero root; export Image + Module.symvers + .config + vmlinux)
KSU_MODE=Pure-OGKI scripts/20-build.sh
scripts/30-package.sh

# 3b. Or YukiSU-LKM (same-tree out-of-tree CONFIG_KSU=m kernelsu.ko verified by check_symbol)
KSU_MODE=YukiSU-LKM scripts/20-build.sh
scripts/30-package.sh

# Optional: verify stock module CRCs
python3 scripts/40-verify-crc.py "$HOME/gt5_kernel_5_15_149/kernel_platform/common/out/Module.symvers" /path/to/stock_modules
```

One-step local wrapper:
```bash
kernel/build-kernel-local.sh --fetch --patch --mode YukiSU-LKM
```

## Domestic Cloud / Preemptible Runner Setup (`抢占实例`)

All network-facing scripts (`00-fetch.sh`, `10-patch.sh`, `integrate-yukisu.sh`, `rom-sync.sh`, `rom-provision-deps.sh`, `rom-build-local.sh`, `fetch-stock.sh`) use [`scripts/mirror_helper.py`](scripts/mirror_helper.py) and [`scripts/lib-mirror.sh`](scripts/lib-mirror.sh) to probe live China mirrors (TUNA / BFSU / USTC / NJU / Aliyun / Tencent / Huawei / GitHub acceleration proxies), download multi-threaded with `aria2c`, and cleanly resume after preemptions or intermittent WAN drops.

```bash
# 1. Bootstrap Ubuntu packages (auto-switches APT to fastest live CN mirror), aria2, repo, ccache
sudo bash scripts/setup-cn-runner.sh            # Kernel runner
sudo bash scripts/setup-cn-runner.sh --with-rom-deps  # Kernel + Infinity-X ROM runner

# 2. Fetch verified RMX3820_15.0.0.320 stock baseline from release `rmx3820-15.0.0.320-stock`
scripts/fetch-stock.sh --mode kernel   # ~97 MiB: boot/init_boot/vendor_boot/dtbo/DLKMs/payload_metadata
scripts/fetch-stock.sh --mode full     # Full partition set for ROM staging & extract-files
```

GitHub Actions workflows default to `self-hosted` (`MIRROR_MODE=cn`) with `ubuntu-latest` selectable as an input:
- [`.github/workflows/build-kernel-gt5.yml`](.github/workflows/build-kernel-gt5.yml) (`Build Realme GT5 OGKI (5.15.149)`)
- [`.github/workflows/build-infinity-rom.yml`](.github/workflows/build-infinity-rom.yml) (`Build Project Infinity-X (ossi)`)
- [`.github/workflows/cleanup.yml`](.github/workflows/cleanup.yml) (`Workflow and Cache Cleanup`)

## Documentation

- [ROM Build & Staging Guide](docs/ROM_BUILD.md)
- [KMI & Partition Verification](docs/ROM_KMI.md)
- [YukiSU `CONFIG_KSU=m` Adaptation Guide](docs/YUKISU_GUIDE.md)
- [Upstream Lineage & Design Contracts](docs/UPSTREAM.md)
