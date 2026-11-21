#!/usr/bin/env python3
"""rom-select-blobs.py — turn a platform blob list into one branch's real list.

A blob list is only usable if every path exists in *that* branch's OTA. This
mounts each partition image read-only (loop, erofs or ext4) and keeps the entries
that are actually present, preserving extract-utils annotations (`;SYMLINK=`,
`;MODULE_SUFFIX=`, `;REQUIRED=`) verbatim.

Files that the platform list does not mention but that this device ships — the
Oplus HAL services and their libraries — are appended in a clearly marked section
only when they match a fixed pattern and exist. Nothing is invented: every emitted
line was stat()ed inside the mounted image.

usage:
  rom-select-blobs.py --base-list upstream.txt --images DIR --out proprietary-files.txt
                      [--report JSON] [--no-extras] [--mount /tmp/mnt]

DIR must contain <partition>.img for the partitions the list references.
Requires passwordless sudo for `mount -o loop,ro`.
Missing images, mount failures, and failed materialization are fatal; only missing
individual blobs are filtered from the list.
Materialization requires --label (kernel release or ColorOS version) and writes
.rom-blob-identity.json only after every selected file has been copied.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from rom_inputs import BASE_PARTITIONS, NAME, extract_fs, stock_payload, require, sha256, verify_stock

# Oplus-specific payload the platform list has no reason to carry.
# Avoid sweeping generic vendor/etc/vintf/manifest/*.xml or HALs built from source by hardware/oplus
# (performance / osense.client / commondcs), which would collide with common.mk in VINTF/Ninja.
EXTRA_PATTERNS = [
    (re.compile(r'^(odm|vendor)/bin/hw/.*oplus'), 'service'),
    (re.compile(r'^(odm|vendor)/lib(64)?/hw/.*oplus'), 'hal library'),
    (re.compile(r'^(odm|vendor)/lib(64)?/.*oplus[^/]*\.so$'), 'library'),
    (re.compile(r'^(odm|vendor)/etc/vintf/manifest/.*oplus.*\.xml$'), 'vintf manifest'),
    (re.compile(r'^(odm|vendor)/etc/init/.*oplus.*\.rc$'), 'init script'),
    (re.compile(r'^(odm|vendor)/etc/permissions/.*oplus.*\.xml$'), 'permission xml'),
]

EXCLUDE_EXTRA_PATTERNS = (
    re.compile(r'^(odm|vendor)/lib(64)?/vendor\.oplus\.hardware\.(osense\.client|performance|commondcs|urcc|biometrics\.fingerprintpay|esim|charger|touch|radio)-V\d+-ndk\.so$'),
    re.compile(r'^odm/bin/hw/vendor-oplus-hardware-(performance|commondcs|osense\.client)-'),
    re.compile(r'^odm/etc/init/vendor-oplus-hardware-(performance|commondcs|osense\.client)-'),
    re.compile(r'^odm/etc/vintf/manifest/manifest_(performance|commondcs|osense).*\.xml$'),
    re.compile(r'^odm/etc/vintf/manifest/manifest_oplus_ifaa\.xml$'),
    re.compile(r'^odm/etc/vintf/manifest/manifest_oplus_virtualdevice_camera\.xml$'),
    re.compile(r'^odm/lib(64)?/vendor\.oplus\.hardware\.virtual_device\.camera\.'),
    re.compile(r'^odm/lib(64)?/vendor\.oplus\.hardware\.biometrics\.fingerprint@2\.1\.so$'),
    re.compile(r'^vendor/etc/vintf/manifest/vendor\.qti\.hardware\.display\.composer-service\.xml$'),
)

AOSP_OR_CAF_LIB_PREFIXES = (
    "android.hardware.",
    "android.frameworks.",
    "android.hidl.",
    "android.system.",
    "camera.device@",
    "libprotobuf-cpp-",
    "libcodec2",
    "libgralloc",
    "libqti_vndfwk",
    "vendor.qti.",
    "vendor.display.",
)

AOSP_OR_CAF_EXACT_LIBS = frozenset({
    "libc.so", "libm.so", "libdl.so", "liblog.so", "libcutils.so", "libutils.so",
    "libbase.so", "libc++.so", "libstdc++.so", "libstdc++_vendor.so", "libz.so",
    "libbinder.so", "libbinder_ndk.so", "libhidlbase.so", "libhidltransport.so",
    "libhwbinder.so", "libhidlmemory.so", "libfmq.so", "libhardware.so",
    "libui.so", "libgui.so", "libnativewindow.so", "libneuralnetworks.so",
    "libsqlite.so", "libexpat.so", "libxml2.so", "libpng.so", "libjpeg.so",
    "libvulkan.so", "libEGL.so", "libGLESv2.so", "libGLESv3.so", "libsync.so",
    "libion.so", "libdmabufheap.so", "libprocessgroup.so", "libvndksupport.so",
    "libcamera_metadata.so", "libcamera2ndk_vendor.so", "libdumpstateutil.so",
    "libsysutils.so", "libyuv.so", "libstagefright_bufferpool@2.0.1.so",
    "libtinyxml2.so", "libjsoncpp.so", "libjson.so", "liblz4.so", "libzstd.so",
    "libcrypto.so", "libssl.so", "liblzma.so", "libbacktrace.so", "libunwindstack.so",
    "libar-acdb.so", "libar-gsl.so", "liblx-osal.so", "libats.so",
    "libagmclient.so", "libpalclient.so", "libqservice.so",
    "libdisplaydebug.so", "libdrmutils.so", "libgpu_tonemapper.so",
    "libqdMetaData.so", "libdisplayconfig.system.qti.so", "libwfdaac_vendor.so",
    "libwpa_client.so", "libcld80211.so", "librmnetctl.so", "libsensorndkbridge.so",
    "libtinycompress.so", "libtinyalsa.so", "libaudioroute.so",
    "vendor.oplus.hardware.osense.client-V1-ndk.so",
    "vendor.oplus.hardware.performance-V1-ndk.so",
    "vendor.oplus.hardware.commondcs-V1-ndk.so",
})


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def parse_entry(line):
    """-> (path, original_line) with the annotation preserved on the line."""
    raw = line.rstrip("\n")
    if not raw.strip() or raw.lstrip().startswith("#"):
        return None
    body = raw.lstrip('-+ ')
    # extract-utils syntax: "<src>[:<dst>][;ANNOTATION=...]" — the source is
    # what must exist in the dump.
    path = re.split(r"[;:|]", body, maxsplit=1)[0].strip()
    if not path or "/" not in path:
        return None
    partition = path.split("/", 1)[0]
    require(NAME.fullmatch(partition) and (partition in BASE_PARTITIONS or partition.startswith("my_"))
            and ".." not in Path(path).parts, f"unsupported blob path {path!r}")
    return path, raw


def split_entry(raw):
    """Split `<spec>[|hash1|hash2]` into (prefix_without_hashes, hash_suffix)."""
    if "|" in raw:
        head, tail = raw.split("|", 1)
        return head, "|" + tail
    return raw, ""


def entry_target(raw):
    """Return effective destination path (`dst` in `src:dst;...`) without prefix or args."""
    head, _ = split_entry(raw)
    body = head.lstrip("-+ ")
    spec = body.split(";", 1)[0].strip()
    return spec.split(":", 1)[-1].strip()


def soong_module_identity(raw):
    """Return (merge_group, base_name, current_suffix, partition, rel_dir, ext) for Soong naming."""
    dst = entry_target(raw)
    parts = PurePosixPath(dst).parts
    part = parts[0]
    head, _ = split_entry(raw)
    args = head.split(";")[1:]
    suffix = ""
    explicit_mod = None
    for arg in args:
        if arg.startswith("MODULE_SUFFIX="):
            suffix = arg.split("=", 1)[1]
        elif arg.startswith("MODULE="):
            explicit_mod = arg.split("=", 1)[1]

    basename = parts[-1]
    root, ext = os.path.splitext(basename)
    # Match extract_utils/makefiles.py write_product_packages dispatch
    if len(parts) >= 4 and parts[1] == "lib" and parts[2] == "rfsa":
        sub = "/".join(parts[3:-1])
        group = ("rfsa", part, sub, basename)
        base_name = explicit_mod or root
        return group, base_name, suffix, part, sub, ext
    if len(parts) >= 3 and parts[1] in ("lib", "lib64"):
        sub = "/".join(parts[2:-1])
        group = ("lib", part, sub, root)
        base_name = explicit_mod or root
        return group, base_name, suffix, part, sub, ext
    if len(parts) >= 3 and parts[1] in ("bin", "etc"):
        kind = parts[1]
        sub = "/".join(parts[2:-1])
        group = (kind, part, sub, basename)
        base_name = explicit_mod or basename
        return group, base_name, suffix, part, sub, ext
    sub = "/".join(parts[1:-1])
    group = ("other", part, sub, basename)
    base_name = explicit_mod or root
    return group, base_name, suffix, part, sub, ext


def append_module_suffix(raw, suffix):
    head, hashes = split_entry(raw)
    return f"{head};MODULE_SUFFIX={suffix}{hashes}"


def dedup_soong_entries(lines):
    """Assign deterministic `;MODULE_SUFFIX=` so zero Soong module names collide."""
    parsed = [soong_module_identity(line) for line in lines]
    # Group lines by Soong merge_group (e.g. lib/ + lib64/ of same partition+subdir merge)
    group_names = {}
    for line, (group, base, suffix, part, sub, ext) in zip(lines, parsed):
        mod_name = base + suffix
        group_names.setdefault(group, []).append((mod_name, suffix, part, sub, ext))

    # Count how many distinct Soong merge_groups claim each module name
    name_to_groups = {}
    for group, items in group_names.items():
        # Prefer explicit suffix if any bitness variant already carried one
        chosen_suffix = next((s for _, s, *_ in items if s), "")
        base = group[3] if group[0] in ("lib", "rfsa") else items[0][0]
        # Recompute base without suffix cleanly from first item
        for i_line, info in zip(lines, parsed):
            if info[0] == group:
                base = info[1]
                break
        effective = base + chosen_suffix
        name_to_groups.setdefault(effective, []).append(group)

    # Compute required suffix overrides for colliding groups
    group_override = {}
    used_names = {name for name, groups in name_to_groups.items() if len(groups) == 1}
    for name, groups in name_to_groups.items():
        if len(groups) <= 1:
            continue
        # Keep the first primary group (prefer odm / system_ext / lib64 over vendor / rfsa) unsuffixed
        def priority(g):
            kind, part, sub, _ = g
            return (1 if kind == "rfsa" else 0, 0 if part == "odm" else 1 if part == "system_ext" else 2, 0 if not sub else 1, part, sub)

        ordered = sorted(groups, key=priority)
        keep_first = ordered[0]
        used_names.add(name)
        for group in ordered[1:]:
            kind, part, sub, _ = group
            # Grab metadata from matching line
            ext = next(info[5] for info in parsed if info[0] == group)
            base = next(info[1] for info in parsed if info[0] == group)
            cands = []
            if kind == "rfsa":
                if ext and ext != ".so":
                    cands.append(ext)
                if sub and sub != "adsp":
                    cands.append("." + sub.replace("adsp/", "").replace("/", "_"))
                if part != "odm":
                    cands.append(f"_{part}")
                cands.append(".rfsa")
            else:
                if sub:
                    cands.append("." + sub.replace("/", "_"))
                cands.append(f"_{part}")
                if sub:
                    cands.append(f"_{part}_{sub.replace('/', '_')}")
            chosen = next((c for c in cands if (base + c) not in used_names), None)
            if chosen is None:
                idx = 2
                while f"{base}_{part}_{idx}" in used_names:
                    idx += 1
                chosen = f"_{part}_{idx}"
            used_names.add(base + chosen)
            group_override[group] = chosen

    result = []
    for line, (group, base, suffix, _part, _sub, _ext) in zip(lines, parsed):
        override = group_override.get(group)
        if override and not suffix:
            result.append(append_module_suffix(line, override))
        else:
            # Propagate suffix across 32/64 pair if one variant already carried it
            if not suffix:
                existing = next((info[2] for info in parsed if info[0] == group and info[2]), "")
                if existing:
                    line = append_module_suffix(line, existing)
            result.append(line)
    return result


def elf_needed(path):
    """Read DT_NEEDED library names directly from an ELF32/ELF64 binary without subprocesses."""
    try:
        with open(path, "rb") as stream:
            data = stream.read()
    except OSError:
        return []
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[5] != 1:
        return []
    ei_class = data[4]
    if ei_class == 2:
        e_shoff, = struct.unpack_from("<Q", data, 40)
        e_shentsize, e_shnum = struct.unpack_from("<HH", data, 58)
        sh_off_pos, sh_size_pos, sh_link_pos, sh_fmt = 24, 32, 40, "<QQ"
        dyn_fmt, dyn_step = "<qQ", 16
    elif ei_class == 1:
        e_shoff, = struct.unpack_from("<I", data, 32)
        e_shentsize, e_shnum = struct.unpack_from("<HH", data, 46)
        sh_off_pos, sh_size_pos, sh_link_pos, sh_fmt = 16, 20, 24, "<II"
        dyn_fmt, dyn_step = "<iI", 8
    else:
        return []
    if not e_shoff or e_shoff + e_shentsize * e_shnum > len(data):
        return []
    dyn_off = dyn_size = link_idx = 0
    for i in range(e_shnum):
        o = e_shoff + i * e_shentsize
        if struct.unpack_from("<I", data, o + 4)[0] == 6:  # SHT_DYNAMIC
            dyn_off, dyn_size = struct.unpack_from(sh_fmt, data, o + sh_off_pos)
            link_idx, = struct.unpack_from("<I", data, o + sh_link_pos)
            break
    if not dyn_off or link_idx >= e_shnum or dyn_off + dyn_size > len(data):
        return []
    lo = e_shoff + link_idx * e_shentsize
    str_off, str_size = struct.unpack_from(sh_fmt, data, lo + sh_off_pos)
    if str_off + str_size > len(data):
        return []
    strtab = data[str_off:str_off + str_size]
    out = []
    for off in range(dyn_off, dyn_off + dyn_size, dyn_step):
        tag, val = struct.unpack_from(dyn_fmt, data, off)
        if tag == 0:
            break
        if tag == 1 and val < len(strtab):  # DT_NEEDED
            end = strtab.find(b"\0", val)
            out.append(strtab[val:None if end == -1 else end].decode("utf-8", "replace"))
    return out


def is_excluded_extra(path):
    return any(pat.match(path) for pat in EXCLUDE_EXTRA_PATTERNS)


class Mounts:
    def __init__(self, image_dir, mnt, sudo=True):
        self.image_dir = image_dir
        self.mnt = mnt
        self.sudo = ["sudo", "-n"] if sudo else []
        self.mounted = None
        self.mounted_via_kernel = False
        self.extracted = {}
        self.erofs_images = {}

    def _mount(self, image):
        cmd = [*self.sudo, "mount", "-o", "loop,ro", image, self.mnt]
        res = run(cmd)
        if res.returncode != 0:
            res = run([*self.sudo, "mount", "-o", "loop,ro", "-t", "ext4", image, self.mnt])
        if res.returncode == 0:
            self.mounted_via_kernel = True
            return
        # Fallback to rootless EROFS/ext4 extraction when loop mount is unavailable.
        self.mounted_via_kernel = False

    def _umount(self):
        if self.mounted_via_kernel:
            run([*self.sudo, "umount", self.mnt], check=True)
            self.mounted_via_kernel = False
        self.mounted = None

    def _root(self, partition=None):
        part = partition or self.mounted
        return self.extracted.get(part, self.mnt)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        if self.mounted:
            self._umount()
        for path in self.extracted.values():
            for root_dir, dirs, _ in os.walk(path):
                try:
                    os.chmod(root_dir, 0o700)
                except OSError:
                    pass
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root_dir, d), 0o700)
                    except OSError:
                        pass
            shutil.rmtree(path, ignore_errors=True)

    def open(self, partition):
        if self.mounted == partition:
            return
        if self.mounted:
            self._umount()
        if partition in self.extracted:
            self.mounted = partition
            return
        image = os.path.join(self.image_dir, f"{partition}.img")
        if not os.path.isfile(image):
            raise FileNotFoundError(f"partition image not found: {image}")
        self._mount(image)
        if not self.mounted_via_kernel:
            dest = os.path.join(self.mnt, f".extracted_{partition}")
            try:
                extract_fs(image, dest)
            except subprocess.CalledProcessError:
                # Some Oplus OEM EROFS images (e.g. my_product) contain vendor-custom
                # compressed APKs that fail bulk fsck.erofs extraction; fall back
                # to verified per-path EROFS inspection + extraction.
                if not shutil.which("dump.erofs") or run(["dump.erofs", "-s", image]).returncode != 0:
                    raise
                shutil.rmtree(dest, ignore_errors=True)
                os.makedirs(dest, exist_ok=True)
                self.erofs_images[partition] = image
            self.extracted[partition] = dest
        self.mounted = partition

    def _resolve(self, partition, rel):
        self.open(partition)
        root = Path(self._root(partition))
        if partition == "system" and (root / "system").is_dir():
            sar = root / "system" / rel
            if sar.is_file() or sar.is_symlink():
                return sar
        return root / rel

    def exists(self, partition, rel):
        self.open(partition)
        if partition in self.erofs_images:
            res = run(["dump.erofs", f"--path=/{rel}", self.erofs_images[partition]])
            return res.returncode == 0 and "regular file" in res.stdout
        return self._resolve(partition, rel).is_file()

    def path_for(self, partition, rel):
        self.open(partition)
        if partition in self.erofs_images:
            root = Path(self._root(partition)).resolve()
            dest = (root / rel).resolve()
            require(dest.is_relative_to(root), f"{partition}/{rel}: invalid path")
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["fsck.erofs", f"--path=/{rel}", f"--extract={dest}", self.erofs_images[partition]],
                    check=True, capture_output=True, text=True,
                )
            return dest
        cand = self._resolve(partition, rel)
        root = Path(self._root(partition)).resolve()
        source = cand.resolve(strict=True)
        require(source.is_relative_to(root), f"{partition}/{rel}: blob symlink leaves the stock filesystem")
        return source

    def walk(self, partition):
        self.open(partition)
        root = self._root(partition)
        out = []
        for dirpath, _dirs, files in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    # runtime-generated entries (e.g. odm vintf manifests pointing
                    # at /proc/oplusManifest) are not files we can ship
                    continue
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                out.append(rel)
        return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-list", required=True)
    ap.add_argument("--extra-list", action="append", default=[],
                    help="additional blob list(s) to merge after --base-list")
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    ap.add_argument("--mount", default=None)
    ap.add_argument("--no-extras", action="store_true")
    ap.add_argument("--materialize", help="copy the selected files into this dump dir")
    ap.add_argument("--label", default="")
    ap.add_argument("--payload-metadata", type=Path)
    a = ap.parse_args(argv)
    with ExitStack() as cleanup:
        return select(a, cleanup)


def select(a, cleanup):
    list_paths = [a.base_list, *(getattr(a, "extra_list", None) or [])]
    sources = []
    seen_sources = set()
    for list_path in list_paths:
        for line in Path(list_path).read_text().splitlines():
            parsed = parse_entry(line)
            if parsed and parsed[0] not in seen_sources and not is_excluded_extra(parsed[0]):
                seen_sources.add(parsed[0])
                sources.append(parsed)
    dump = None
    if a.materialize:
        if not a.label:
            raise ValueError("--materialize requires --label (kernel release or ColorOS version)")
        payload = stock_payload(a.images, a.label, a.payload_metadata)
        image_parts = {path.split("/", 1)[0] for path, _ in sources}
        if not a.no_extras:
            image_parts.update(("odm", "vendor"))
        verify_stock(a.images, payload, sorted(image_parts))
        output = Path(a.materialize)
        require(not output.exists() and not output.is_symlink(), f"{output}: select a new blob dump directory")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix=".ossi-blobs-", dir=output.parent)))
        dump = temp / "blobs"
        dump.mkdir()

    mnt = a.mount or cleanup.enter_context(tempfile.TemporaryDirectory(prefix="blobmnt-"))
    os.makedirs(mnt, exist_ok=True)
    sudo = bool(os.environ.get("SUDO_MOUNT", "1") == "1")

    kept, dropped, seen = [], [], set()
    per_part = {}
    with Mounts(a.images, mnt, sudo=sudo) as mounts:
        for path, original in sources:
            part = path.split("/", 1)[0]
            rel = path.split("/", 1)[1]
            per_part.setdefault(part, [0, 0])
            per_part[part][1] += 1
            if mounts.exists(part, rel):
                kept.append(original)
                seen.add(path)
                per_part[part][0] += 1
            else:
                require(";REQUIRED" not in original, f"required stock blob is missing: {path}")
                dropped.append(path)

        extras = []
        if not a.no_extras:
            stock_lib_index = {}
            for part in ("odm", "vendor"):
                for rel in mounts.walk(part):
                    path = f"{part}/{rel}"
                    if re.match(rf"^{part}/lib(64)?/[^/]+\.so$", path):
                        stock_lib_index.setdefault(os.path.basename(path), []).append(path)
                    if path in seen or is_excluded_extra(path):
                        continue
                    for pattern, why in EXTRA_PATTERNS:
                        if pattern.match(path):
                            extras.append((path, why))
                            seen.add(path)
                            break

            # Resolve non-AOSP DT_NEEDED helper libraries inside odm/vendor for extra Oplus ELFs.
            system_libs = set(AOSP_OR_CAF_EXACT_LIBS)
            if os.path.isfile(os.path.join(mounts.image_dir, "system.img")):
                for rel in mounts.walk("system"):
                    if rel.endswith(".so") and ("/lib/" in f"/{rel}" or "/lib64/" in f"/{rel}"):
                        system_libs.add(os.path.basename(rel))
            known_basenames = {PurePosixPath(entry_target(line)).name for line in kept}
            known_basenames.update(PurePosixPath(p).name for p, _ in extras)
            extra_seeds = [
                p for line in kept
                if (p := parse_entry(line)[0]).startswith(("odm/", "vendor/"))
                and re.search(r'(oplus|arcsoft|OPAlgo)', p)
            ]
            queue = [p for p, _ in extras] + extra_seeds
            while queue:
                cur = queue.pop(0)
                if not (cur.endswith(".so") or "/bin/" in cur):
                    continue
                cur_part, cur_rel = cur.split("/", 1)
                try:
                    real_path = mounts.path_for(cur_part, cur_rel)
                except (FileNotFoundError, ValueError):
                    continue
                for lib in elf_needed(real_path):
                    if (lib in system_libs or lib.startswith(AOSP_OR_CAF_LIB_PREFIXES)
                            or lib in known_basenames):
                        continue
                    cands = stock_lib_index.get(lib, [])
                    same_part = [c for c in cands if c.startswith(f"{cur_part}/")]
                    chosen = same_part or [c for c in cands if c.startswith("odm/")] or cands
                    for c in chosen:
                        if c not in seen and not is_excluded_extra(c):
                            seen.add(c)
                            extras.append((c, "oplus dependency"))
                            queue.append(c)
                    if chosen:
                        known_basenames.add(lib)

            extras.sort()

        if dump:
            targets = [parse_entry(line)[0] for line in kept]
            targets += [p for p, _ in extras]
            paths = {}
            for src in sorted(set(targets)):
                part, rel = src.split("/", 1)
                source = mounts.path_for(part, rel)
                dest = dump / src
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                paths[src] = sha256(dest)
            require(paths, "stock blob selection is empty")

    deduped = dedup_soong_entries(kept + [p for p, _ in extras])
    kept = deduped[:len(kept)]
    extra_lines = deduped[len(kept):]

    header = [
        "## Generated by scripts/rom-select-blobs.py — every line below was stat()ed",
        "## inside this branch's own OTA images; nothing is hand-invented.",
    ]
    if a.label:
        header.append(f"## branch: {a.label}")
    header.append("## Platform base: LineageOS device/oneplus/sm8550-common proprietary-files.txt")
    header.append("")

    with open(a.out, "w") as f:
        f.write("\n".join(header) + "\n")
        f.write("\n".join(kept) + "\n")
        if extra_lines:
            f.write("\n# ---- Oplus HAL payload present on this device (auto-included) ----\n")
            f.write("\n".join(extra_lines) + "\n")

    report = {
        "label": a.label,
        "kept": len(kept),
        "dropped": len(dropped),
        "extras": len(extras),
        "per_partition": {k: {"present": v[0], "listed": v[1]} for k, v in sorted(per_part.items())},
        "dropped_samples": dropped[:20],
        "extras_samples": [p for p, _ in extras[:20]],
    }
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1)
    if dump:
        identity = {"schema": 3, "label": a.label, "stock_payload": payload["sha256"],
                    "files": paths, "list_sha256": sha256(a.out)}
        (dump / ".rom-blob-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
        dump.rename(output)
        print(f"materialized {len(paths)} files into {output}")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as error:
        print(f"FAIL: stock blobs: {error}", file=sys.stderr)
        raise SystemExit(1)
