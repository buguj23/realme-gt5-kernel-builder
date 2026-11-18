# ROM 本地构建手册（Realme GT5 / ossi）

首次同步及构建可按 250 GB 预留空间。构建脚本默认为已有源码树预留 120 GiB 工作空间。运行器需安装 `repo`、`git`、`rsync`、`python3`、`openssl`、`avbtool`、`lz4`、`simg2img`、`debugfs`、`fsck.erofs`、Device Tree Compiler 的 `fdtget` 和 `fdtput`、构建工具及所选 Android 版本要求的 JDK。自动选择 Blob 时需要可用的只读 loop mount。

## 源码基线

| 内核分支 | 原厂 ColorOS | Android 源码 | 设备依赖 | lunch |
|---|---|---|---|---|
| `5.15.123` | 14.0.0.1120 | LineageOS `lineage-21.0` | `lineage-21` | `lineage_ossi-trunk_staging-userdebug` |
| `5.15.149` | 15.0.0.320 | Infinity-X `15` | `lineage-22.2` | `infinity_ossi-userdebug` |
| `5.15.167` | 15.0.0.1400 | Infinity-X `15` | `lineage-22.2` | `infinity_ossi-userdebug` |
| `5.15.180` | 16.0.3.500 | Infinity-X `16` | `lineage-23.2` | `infinity_ossi-userdebug` |

`official/kernels.json` 记录分支参数和 OTA 元数据 SHA-256。设备首发 API 为 33。ROM 平台 SDK 和原厂 boot/vendor SPL 根据选定的分支配置。

## 原厂输入

- `--stock-images` 指向匹配原厂版本的镜像目录，其中放置 `payload_metadata.bin` 和 `super-layout.json`。这两个文件也可由 `--payload-metadata` 与 `--stock-layout` 显式指定。前者接受 `payload.bin` 或其中的元数据前缀。后者使用同版本、同 SKU 活动槽 LP 镜像的 `lpdump -j` 输出。暂存器按 OTA 的分区名和尺寸识别 LP 组。两槽都匹配时，通过 `--stock-slot a|b` 或 CI 的 `stock_slot` 指定原厂活动槽。
- 备齐原厂 `boot`、`init_boot`、`vendor_boot`、`dtbo`、两个 DLKM 镜像和供 Blob 选择的分区镜像。只读 loop mount 使用 raw 镜像。OEM 暂存和 DLKM 提取也接受 Android sparse 镜像。
- A14/A15 的原厂部分 OTA 清单列出八个 OEM 逻辑分区。若同版本 LP 布局中还有 `my_company` 或 `my_preload`，需要提供从相同原厂布局提取的对应完整镜像。脚本会核对镜像尺寸和 OEM 签名。经布局确认缺席的分区，其挂载项也从生成的 fstab 移除。
- OEM 公钥取自通过原厂 OTA 哈希校验的分区，随 vendor ramdisk 交付。`--oem-key` 可额外指定可信的 OEM 公钥 PEM。

## 内核包与构建

GitHub Actions 工件 `kernel-package_<变体>_<分支>` 需要 schema 2。解包后将目录作为 `--pkg`。本地也可由单个 Kbuild 输出组包。

```bash
scripts/kernel-package.sh /path/to/kernel/common/out ~/gt5_work/kernel-package \
  --branch 5.15.180 --variant local --commit "$(git rev-parse HEAD)"
mkdir -p ~/gt5_work/pkgs/5.15.180
tar --zstd -xf ~/gt5_work/kernel-package/kernel-package.tar.zst -C ~/gt5_work/pkgs/5.15.180

scripts/rom-build-local.sh --sync --src ~/gt5-rom/5.15.180 --branch 5.15.180 \
  --pkg ~/gt5_work/pkgs/5.15.180 --stock-images ~/gt5-stock/5.15.180
```

`--check-only` 离线验证原厂身份、OEM 布局和签名、DTB/DTBO、内核包及两个启动阶段的模块。模块池可通过 `scripts/stock-module-lists.sh STOCK_DIR OUTPUT --branch 5.15.180` 提前提取，再用 `--pool` 复用。构建可复用通过以下命令生成的 schema 3 Blob dump 及对应清单。

暂存器在原厂 DTB 中识别仅包含旧式非逻辑 `/vendor` 条目的 fstab 节点，并禁用该节点。首阶段 init 据此读取 vendor ramdisk 中包含完整逻辑分区和 AVB 配置的 `fstab.qcom`。DTBO 采用同一 OTA 的原厂数据。

```bash
python3 scripts/rom-select-blobs.py --base-list /path/to/platform/proprietary-files.txt \
  --images ~/gt5-stock/5.15.180 --label 5.15.180 \
  --out ~/gt5_work/ossi-blobs.txt --materialize ~/gt5_work/ossi-raw
# 给构建命令附加 --blobs ~/gt5_work/ossi-raw --blob-list ~/gt5_work/ossi-blobs.txt
```

构建按平台 SDK 执行 extract-utils fixup，从已校验的 GT5 文件生成 Blob 哈希，检查生成的 vendor 源文件，再运行 Android 编译。两个 ROM 产品均使用 `ossi` 作为 OTA 设备名。自托管 CI 使用同一入口，默认在 `~/gt5-stock/<branch>` 读取原厂目录。已有源码树须匹配表中的 manifest。

## 工件验收

通过验收后，输出目录含 target-files、OTA ZIP、记录 Android 源码提交的 manifest 和 `rom-delivery.json`。验收检查实际 A/B 分区及容量、OTA ZIP 整包签名和 payload 签名、DTB/DTBO、两套模块加载顺序、DLKM 镜像和 AVB 信任链。引导镜像及 `vbmeta_vendor` 使用原厂 boot/vendor SPL 的 UTC 时间戳，`vbmeta_system` 使用 ROM 平台 SPL，签入的回滚索引写入验收记录。当前构建产物为 userdebug，默认使用 Android 调试签名。正式发布需要独立签名配置及设备验收。

16.0.3.500 尚待从完整 OTA 重采的四项整镜像哈希标记为 `null`。构建使用锁定 OTA 元数据中的分区哈希校验输入。

当前工作区已复核三份 A14/A15 原厂 OTA 元数据和各六个引导及 AVB 镜像。四个基线的 DTB 均已离线复核。原厂 LP 布局、DLKM 与新内核包到齐后，才能确认实际分区集合和逐阶段 KMI。完整 Android 构建及启动、Recovery 和 A/B 更新仍待实包验收。

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
- 四棵树和四次构建超过 300 GB。远端按对应源码基线和原厂输入分别准备。
