# ROM 本地构建手册（Realme GT5 / ossi）

云端（火山引擎 16C/64G/300G）实测结论：**时间几乎全花在网络上**。A16 一棵树同步到
113 GB 仍未结束，四棵树与四次构建在 300 GB 内无法轮流完成；镜像端还会对并发克隆排队
（`Waiting in queue (Position 100+)`）。因此改为本地构建，云端那套可复用逻辑保留为脚本。

## 0. 需要的机器条件

| 项 | 最低 | 说明 |
|---|---|---|
| 磁盘 | **250 GB 起** | 单树源码 ~110 GB（A16 实测）+ `out/` 60–80 GB |
| 内存 | 32 GB | 16 GB 会在 soong/链接阶段 OOM |
| CPU | 8 核起 | 16 核一次 `mka bacon` 约 2–4 小时 |
| 系统 | Linux x86_64 | 需要 `java`（A16 用 21）、`ccache`、`repo` |

当前工作站 `/home` 余量 166 GB，**不足**以容纳一棵完整 A16 树 + 产物，构建前需清理或
把源码树放到外置盘（脚本会按 `--min-free-gb` 拒绝启动）。

## 1. 四分支与源码基线

| 分支 | 固件 OTA | ROM 基线 | `--deps-branch` | lunch |
|---|---|---|---|---|
| `5.15.180` | 16.0.3.500 | Infinity-X `16` | `lineage-23.2` | `infinity_ossi-userdebug` |
| `5.15.167` | 15.0.0.1400 | Infinity-X `15` | `lineage-22.2` | `infinity_ossi-userdebug` |
| `5.15.149` | 15.0.0.320 | Infinity-X `15` | `lineage-22.2` | `infinity_ossi-userdebug` |
| `5.15.123` | 14.0.0.1120 | **LineageOS 21** | `lineage-21` | `lineage_ossi-userdebug` |

Infinity-X 的清单只有 `15 / 15-QPRx / 16 / 16-QPRx / 17`，**没有 Android 14**；
把 A15/A16 源码配 14.0.0.1120 的 vendor blob 不是可用产品，所以 `5.15.123` 用 LineageOS 21。

## 2. 构建输入（已在本机生成）

每个分支三样，全部按该分支自己的 OTA 产出：

```
~/gt5_work/dumps/<branch>/      Blob 实体（708–813 MB，1634 个文件）
~/gt5_work/pools/<branch>/      stock-modules.load + stock-modules/（345–385 个 .ko）
~/gt5_work/pkgs/<branch>/       Image + Module.symvers + modules/（内核包）
```

重新生成的方法：

```bash
# 1. 从该分支 OTA 解出的 img 目录挑选并物化 Blob
python3 scripts/rom-select-blobs.py \
  --base-list <平台 proprietary-files.txt> \
  --images <ota-img-dir> --label <branch> \
  --out proprietary-files.txt --materialize ~/gt5_work/dumps/<branch>

# 2. 原厂一阶段清单与模块池
bash scripts/stock-module-lists.sh <ota-img-dir> ~/gt5_work/pools/<branch>

# 3. 该分支工作流产出的 kernel-package 工件（GitHub Actions 下载）
```

## 3. 同步源码

```bash
scripts/rom-sync.sh --dir ~/rom16 \
  --manifest https://github.com/ProjectInfinity-X/manifest --branch 16 \
  --jobs 16
```

`rom-sync.sh` 会：

1. `repo init --depth=1`（`REPO_URL` 用清华的 git-repo）；
2. 调 `rom-manifest-mirror.py` 把 `aosp` 与默认 `github` remote 指向清华镜像
   （AOSP → `git/AOSP/`，Lineage → `git/lineageOS/`）；
3. `repo sync --force-sync --no-clone-bundle --no-tags`。

实测速度：清华镜像 **60 MB/s**，GitHub 直连 18–25 KB/s，经本机代理的 SSH 隧道
3.4 MB/s。**不要**让 AOSP 走隧道——那是几小时的差别。

## 4. 构建

```bash
scripts/rom-build-local.sh \
  --src ~/rom16 --branch 5.15.180 \
  --blobs ~/gt5_work/dumps/5.15.180 \
  --pool  ~/gt5_work/pools/5.15.180 \
  --pkg   ~/gt5_work/pkgs/5.15.180 \
  --lunch infinity_ossi-userdebug --deps-branch lineage-23.2
```

脚本顺序：预检（工具/输入/**剩余空间**）→ 铺设备树 → 拷 Blob → 补齐
`sm8550-common`/`hardware/oplus`/`pixelworks` → 内核包逐符号暂存 → `lunch` → `mka bacon`。
任一步失败即停，日志同时写 `$SRC/build.log`。

`--check-only` 只做输入校验，不开始编译。

## 5. 构建后校验

```bash
# 1. vendor_boot 的 ABL 信封与一阶段清单必须与该分支原厂一致
scripts/rom-vendor-boot-fix.sh ~/rom16/out/target/product/ossi/vendor_boot.img \
  --stock <该分支 stock vendor_boot.img> --check-only

# 2. 整包 vs 该分支 OTA 事实
python3 scripts/branch-facts.py --stock <ota-img-dir> --label <branch> --json facts.json
python3 scripts/branch-compare.py --facts facts.json \
  --deliver ~/rom16/out/target/product/ossi
```

`branch-compare.py` 会核对：内核 release、boot 头版本、一阶段条数、`/metadata` 文件系统、
`vendor_dlkm`/`system_dlkm` 的 CRC 分布与文件系统类型。

## 6. 多分支的磁盘编排

四棵树放不下，按「一个 Android 版本一棵树」的顺序：

1. `rom16` → 构建 `5.15.180`；
2. 删除 `rom16/out`（保留 zip）→ 建 `rom15` → 构建 `5.15.167`；
3. **同一棵 `rom15`** 换 Blob 与内核包 → 构建 `5.15.149`
   （更换 vendor blob 后建议 `rm -rf out/target/product/ossi/{vendor,vendor_dlkm,system_dlkm}.img` 再增量构建）；
4. 删 `rom15` → 建 `rom21`（`--manifest ... --branch` 用 LineageOS 清单）→ 构建 `5.15.123`。

## 7. 尚未闭合的两件事

1. `BOARD_SUPER_PARTITION_GROUPS` 仍为 `oplus_dynamic_partitions`，需设备侧
   `adb shell lpdump | grep group_name` 确认——这是唯一可能造成不可逆后果的项。
2. 机型专有 sepolicy 需要实机 denial 日志才能补；当前已含
   `device/qcom/sepolicy_vndr` 与 `hardware/oplus/sepolicy/qti`。

## 附录：云端尝试的记录（不含任何凭据）

一次性云主机（16 vCPU / 60 GB / 300 GB 数据盘，Ubuntu 26.04）上实际做过的事，
供将来需要远端构建时复用：

```bash
# 依赖（Ubuntu 26.04：libxml2 / liblz4-tool 已改名，直接用下列集合）
apt-get install -y git git-lfs python3 curl rsync ccache bison flex build-essential \
  zip unzip bc gperf imagemagick libssl-dev libxml2-utils xsltproc zlib1g-dev \
  libelf-dev lz4 zstd pngcrush openjdk-21-jdk gcc-multilib g++-multilib lib32z1-dev

# repo 走清华
curl -fsSL https://mirrors.tuna.tsinghua.edu.cn/git/git-repo -o /usr/local/bin/repo
chmod +x /usr/local/bin/repo
export REPO_URL=https://mirrors.tuna.tsinghua.edu.cn/git/git-repo
```

结论（2026-11-17 实测）：

| 路径 | 速率 |
|---|---|
| 清华 AOSP / Lineage 镜像 | 60 MB/s（单流大文件） |
| GitHub 直连（云主机） | 18–25 KB/s |
| 经本机代理的 SSH 反向隧道 | 3.4 MB/s |

- A16 树同步到 **113 GB** 仍未结束，随后放弃；
- 镜像对并发克隆排队（`Waiting in queue (Position 100+)`），`-j16` 并不能线性提速；
- 反向隧道的数据对云主机是**入方向**（多数云厂商不计费），出方向才计费；
- 四棵树 + 四次构建在 300 GB 内无法轮流完成，必须按第 6 节顺序清理。

因此本地构建是默认路径；若再次使用远端，只需把第 3、4 节的脚本原样搬过去。
