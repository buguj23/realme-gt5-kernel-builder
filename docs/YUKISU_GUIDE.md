# YukiSU (`CONFIG_KSU=m`) Integration Guide for GT5 (`5.15.149`)

`Rouyashiki/YukiSU` supports **LKM mode (`CONFIG_KSU=m`) only** on ARM64 GKI 2.0 (`android13-5.15`). It must never be compiled built-in (`CONFIG_KSU=y`), and must never be combined with `SUSFS`, `KPM`, or `FakeConfig`.

## Two Supported Deployment Paths

### Option 1: Pure-OGKI + Official Prebuilt YukiSU LKM (Fastest)
1. Build with `KSU_MODE=Pure-OGKI` (zero KMI struct edits, `3260/3260` stock CRC parity).
2. Flash `Image` (Boot / AnyKernel3).
3. Use YukiSU Manager (ImgPatch / `ksud`) to patch stock/ROM `init_boot.img` with official `android13-5.15` `kernelsu.ko` (`ksuinit` resolves non-exported symbols dynamically via `/proc/kallsyms` and loads `kernelsu.ko` into kernel before `init`).
4. Use YukiSU **UTS View** for runtime `uname` spoofing instead of mutating kernel `LOCALVERSION`.

### Option 2: Same-Tree `Module.symvers` Out-of-Tree LKM (`YukiSU-LKM`)
Required whenever custom Kconfig fragments or patches (e.g. `ZRAM_LZ4KD`) alter kernel CRCs:
1. Build the OGKI kernel (`make O=out gki_defconfig ...` + `headers_install`) producing:
   - `Image`
   - `Module.symvers`
   - `.config`
   - `vmlinux`
2. Run `scripts/integrate-yukisu.sh --kp-dir <kp_dir> --kdir <out>`:
   - Clones `Rouyashiki/YukiSU`
   - Compiles out-of-tree (`M=YukiSU/kernel CONFIG_KSU=m CONFIG_KSU_SUPERKEY=y CONFIG_KSU_YUKIZYGISK=y KBUILD_MODPOST_WARN=1`) against `<out>`
   - Runs YukiSU's `tools/check_symbol kernelsu.ko <out>/vmlinux` to verify every undefined symbol exists in `vmlinux`'s symbol table
   - Strips debug info (`llvm-strip -d`) and checks `vermagic` against `Image`.
3. Deliver `kernelsu.ko` into `init_boot.img` (via YukiSU Manager Custom LKM / `ksud` / DirectLKM) or stage `/data/adb/ksu/kernelsu.ko` via AnyKernel3.

## Mutual Exclusion Checklist
- Do not enable standalone Zygisk Next / ReZygisk simultaneously if `ENABLE_YUKIZYGISK=1` is compiled into `kernelsu.ko`.
- Keep `CONFIG_KPROBES=y`, `CONFIG_KRETPROBES=y`, `CONFIG_HAVE_SYSCALL_TRACEPOINTS=y`, `CONFIG_KALLSYMS=y`, `CONFIG_KALLSYMS_ALL=y`, `CONFIG_OVERLAY_FS=y`, `CONFIG_CGROUP_BPF=y`, and `CONFIG_COMPAT=y` visible (no FakeConfig hiding).
