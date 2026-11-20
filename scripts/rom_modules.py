"""Read the load lists and modules in vendor_boot and DLKM images."""
import argparse
import gzip
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

import kmi
from rom_inputs import extract_fs, raw_image, require, sha256, stock_payload, verify_stock

MODULE = re.compile(r"[A-Za-z0-9_.+-]+\.ko")
LIST_FILES = ("modules.load", "modules.load.recovery", "modules.dep",
              "modules.softdep", "modules.blocklist", "modules.options")
DT_FSTAB = "/firmware/android/fstab"


def module_list(path):
    names = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name = Path(line).name
            require(MODULE.fullmatch(name) and not any(c.isspace() for c in line),
                    f"{path}: invalid module name {line!r}")
            names.append(name)
    # Several stock GT5 lists repeat a module. Keep that exact sequence.
    require(names, f"{path}: empty module list")
    return names


def newc_files(data):
    """Read regular files from an Android newc archive without extracting links."""
    at = 0
    while at < len(data):
        while at < len(data) and data[at] == 0:
            at += 1
        if at == len(data):
            break
        require(at + 110 <= len(data) and data[at:at + 6] in (b"070701", b"070702"),
                "invalid vendor ramdisk cpio archive")
        fields = [int(data[i:i + 8], 16) for i in range(at + 6, at + 110, 8)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        start = at + 110
        end = start + namesize
        require(namesize > 0 and end <= len(data) and data[end - 1] == 0, "invalid cpio filename")
        name = data[start:end - 1].decode("utf-8")
        start = (end + 3) & ~3
        end = start + size
        require(end <= len(data), f"truncated cpio file {name}")
        at = (end + 3) & ~3
        if mode & 0o170000 == 0o100000:
            yield name.removeprefix("./").lstrip("/"), memoryview(data)[start:end]


def ramdisk_files(data):
    if data.startswith((b"\x02\x21\x4c\x18", b"\x04\x22\x4d\x18")):
        data = subprocess.run(["lz4", "-dc"], input=data, capture_output=True, check=True).stdout
    elif data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    require(data.startswith((b"070701", b"070702")), "unsupported ramdisk compression")
    return newc_files(data)


def vendor_boot(image, directory):
    """Extract relevant stock or built ramdisk files and the real DTB."""
    directory.mkdir(parents=True, exist_ok=True)
    with Path(image).open("rb") as stream:
        hdr = stream.read(2128)
        require(len(hdr) == 2128 and hdr[:8] == b"VNDRBOOT", f"{image}: not vendor_boot")
        version, page, kernel, ramdisk, ramdisk_size = struct.unpack_from("<5I", hdr, 8)
        tag, = struct.unpack_from("<I", hdr, 2076)
        hsize, dtb_size, dtb_addr, table_size, entries, entry_size, config_size = struct.unpack_from(
            "<IIQIIII", hdr, 2096)
        require(version == 4 and page in (2048, 4096, 8192, 16384) and hsize == len(hdr),
                f"{image}: invalid vendor_boot v4 header")
        require(dtb_size > 0 and entries and entry_size == 108 and table_size == entries * entry_size,
                f"{image}: missing DTB or invalid ramdisk table")

        def align(size):
            return (size + page - 1) // page * page

        start = align(hsize)
        dtb_off = start + align(ramdisk_size)
        table_off = dtb_off + align(dtb_size)
        config_off = table_off + align(table_size)
        require(config_off + config_size <= Path(image).stat().st_size, f"{image}: truncated vendor_boot")
        stream.seek(dtb_off)
        dtb = stream.read(dtb_size)
        require(dtb[:4] == b"\xd0\x0d\xfe\xed", f"{image}: not a flattened device tree")
        (directory / "dtb.img").write_bytes(dtb)
        stream.seek(table_off)
        table = [struct.unpack_from("<III", stream.read(entry_size)) for _ in range(entries)]
        for size, offset, role in table:
            require(size > 0 and offset + size <= ramdisk_size and role in range(4),
                    f"{image}: invalid ramdisk fragment")
            stream.seek(start + offset)
            for name, contents in ramdisk_files(stream.read(size)):
                if name in ("first_stage_ramdisk/fstab.qcom", "fstab.qcom") or re.fullmatch(
                        r"(?:first_stage_ramdisk/)?avb/ossi-oem/[0-9a-f]{64}\.avbpubkey", name):
                    dest = directory / name
                elif re.fullmatch(r"(?:first_stage_ramdisk/)?lib/modules/[^/]+", name):
                    filename = Path(name).name
                    if not (MODULE.fullmatch(filename) or filename in LIST_FILES):
                        continue
                    dest = directory / ("recovery" if role == 2 else "ramdisk") / filename
                else:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    require(dest.read_bytes() == contents, f"{image}: conflicting {name} in ramdisk fragments")
                else:
                    dest.write_bytes(contents)
    return (version, page, kernel, ramdisk, tag, dtb_addr)


def dtb_for_ramdisk_fstab(data):
    """Let AOSP read the complete ramdisk fstab on stock GT5 DTBs."""
    output = bytearray()
    offset = changed = 0
    with tempfile.TemporaryDirectory(prefix="ossi-fstab-dtb-") as tmp:
        tree = Path(tmp) / "board.dtb"
        while offset < len(data):
            require(data[offset:offset + 4] == b"\xd0\x0d\xfe\xed" and len(data) - offset >= 40,
                    "invalid concatenated vendor_boot DTB header")
            size, = struct.unpack_from(">I", data, offset + 4)
            require(40 <= size <= len(data) - offset, "invalid vendor_boot DTB size")
            current = data[offset:offset + size]
            tree.write_bytes(current)
            subprocess.run(["fdtget", "-l", tree, "/"], check=True, stdout=subprocess.DEVNULL)

            def prop(node, name):
                return subprocess.check_output(["fdtget", "-t", "s", "-d", "", tree, node, name],
                                               text=True).strip()

            if (prop("/firmware/android", "compatible") == "android,firmware"
                    and prop(DT_FSTAB, "compatible") == "android,fstab"
                    and prop(DT_FSTAB, "status") in ("", "ok", "okay")):
                nodes = subprocess.check_output(["fdtget", "-l", tree, DT_FSTAB], text=True).split()
                vendor = DT_FSTAB + "/vendor"
                flags = prop(vendor, "fsmgr_flags").split(",")
                require(nodes == ["vendor"] and set(flags) == {"wait", "slotselect", "avb"}
                        and prop(vendor, "mnt_point") in ("", "/vendor")
                        and prop(vendor, "dev").endswith("/by-name/vendor")
                        and prop(vendor, "type") == "ext4",
                        "unexpected device-tree fstab; expected the stock legacy vendor entry")
                # Upstream first-stage init selects a usable DT fstab before it
                # reads the ramdisk. The legacy entry lacks dynamic partitions.
                subprocess.run(["fdtput", "-t", "s", tree, DT_FSTAB, "status", "disabled"], check=True)
                current = tree.read_bytes()
                changed += 1
            output.extend(current)
            offset += size
    require(output, "missing vendor_boot DTB")
    return bytes(output), changed


def modules_from_fs(image, dest):
    """Extract only with read-only filesystem tools and keep each partition distinct."""
    return extract_fs(image, dest, "lib/modules")


def inventory(directory):
    files = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink() or not (MODULE.fullmatch(path.name) or path.name in LIST_FILES):
            continue
        require(path.name not in files, f"{directory}: duplicate module or list {path.name}")
        files[path.name] = path
    return files


def path_modules(directory):
    return {name: path for name, path in inventory(directory).items() if MODULE.fullmatch(name)}


def recovery_list(directory):
    recovery = directory / "recovery"
    shared = directory / "ramdisk"
    candidates = (recovery / "modules.load.recovery", shared / "modules.load.recovery",
                  recovery / "modules.load")
    for path in candidates:
        if path.is_file():
            return module_list(path)
    raise ValueError(f"{directory}: missing Recovery module list")


def check_vendor_boot(image, stock, expected=None, dtb=None, oem_key=None, fstab=None,
                      module_abi=None):
    with tempfile.TemporaryDirectory(prefix="ossi-vendor-boot-") as work:
        target = Path(work) / "target"
        original = Path(work) / "stock"
        envelope = vendor_boot(image, target)
        require(envelope == vendor_boot(stock, original), "vendor_boot header addresses differ from stock")
        expected = expected or {
            "first_stage": module_list(original / "ramdisk/modules.load"),
            "recovery": recovery_list(original),
        }
        require(module_list(target / "ramdisk/modules.load") == expected["first_stage"],
                "vendor_boot normal modules.load order differs")
        require(recovery_list(target) == expected["recovery"], "vendor_boot Recovery modules.load order differs")
        normal = path_modules(target / "ramdisk")
        recovery_only = path_modules(target / "recovery")
        recovery = normal | recovery_only
        require(set(expected["first_stage"]) <= normal.keys(), "vendor_boot normal module files missing")
        require(set(expected["recovery"]) <= recovery.keys(), "vendor_boot Recovery module files missing")
        if module_abi is not None:
            require(recovery.keys() == module_abi.keys(), "vendor_boot module inventory differs from staging")
            for modules in (normal, recovery_only):
                for name, module in modules.items():
                    require(kmi.module_abi(module) == module_abi[name],
                            f"vendor_boot {name}: ABI differs from staging")
        else:
            for modules, order in ((normal, expected["first_stage"]), (recovery, expected["recovery"])):
                for name in sorted(set(order)):
                    kmi.module_abi(modules[name])
        for source, relative in ((dtb, "dtb.img"), (fstab, "first_stage_ramdisk/fstab.qcom")):
            if source:
                output = target / relative
                require(output.is_file() and output.read_bytes() == Path(source).read_bytes(),
                        f"vendor_boot {relative} differs from staged file")
        if oem_key:
            keys = {p.name: p.read_bytes() for p in Path(oem_key).glob("*.avbpubkey")}
            for directory in ("avb/ossi-oem", "first_stage_ramdisk/avb/ossi-oem"):
                installed = {p.name: p.read_bytes() for p in (target / directory).glob("*.avbpubkey")}
                require(keys and keys == installed, f"vendor_boot {directory} keys differ from staging")


def collect_stock(images, output, branch, metadata=None):
    payload = stock_payload(images, branch, metadata)
    verify_stock(images, payload, ("vendor_boot", "vendor_dlkm", "system_dlkm"))
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.exists(), f"{output}: select a new module pool directory")
    with tempfile.TemporaryDirectory(prefix="ossi-stock-", dir=output.parent) as work:
        root = Path(work)
        stage = root / "pool"
        stage.mkdir()
        vendor_boot(images / "vendor_boot.img", stage)
        first = module_list(stage / "ramdisk/modules.load")
        recovery = recovery_list(stage)
        normal_pool = path_modules(stage / "ramdisk")
        recovery_pool = normal_pool | path_modules(stage / "recovery")
        require(set(first) <= normal_pool.keys(), "stock normal load list has missing modules")
        require(set(recovery) <= recovery_pool.keys(), "stock Recovery load list has missing modules")
        lists = {"first_stage": first, "recovery": recovery}
        fs = {}
        for partition in ("vendor_dlkm", "system_dlkm"):
            dest = stage / partition
            fs[partition] = modules_from_fs(images / f"{partition}.img", root / partition)
            contents = inventory(root / partition)
            names = {name for name in contents if MODULE.fullmatch(name)}
            require(names, f"stock {partition} has no modules")
            dest.mkdir()
            for name, source in contents.items():
                shutil.move(source, dest / name)
            order = dest / "modules.load"
            lists[partition] = module_list(order) if order.is_file() and order.read_text().strip() else []
            require(set(lists[partition]) <= names, f"stock {partition} load list has missing modules")
            require(partition != "vendor_dlkm" or lists[partition], "stock vendor_dlkm has no load order")
        files = {str(p.relative_to(stage)): sha256(p) for p in stage.rglob("*") if p.is_file()}
        (stage / "manifest.json").write_text(json.dumps({"schema": 1, "payload": payload["sha256"],
                                                        "files": files, "lists": lists, "fs": fs}, indent=2) + "\n")
        stage.rename(output)
    print(f"Stock module pool {output}: normal {len(first)}, Recovery {len(recovery)}")


def load_pool(path, payload_digest):
    manifest = json.loads((path / "manifest.json").read_text())
    require(manifest["schema"] == 1 and manifest["payload"] == payload_digest, "stock module pool OTA identity differs")
    files = {str(p.relative_to(path)): p for p in path.rglob("*") if p.is_file() and p != path / "manifest.json"}
    require(files.keys() == manifest["files"].keys(), "stock module pool files differ from inventory")
    for name, source in files.items():
        require(not source.is_symlink() and sha256(source) == manifest["files"][name], f"stock module pool changed: {name}")
    actual = {"first_stage": module_list(path / "ramdisk/modules.load"), "recovery": recovery_list(path)}
    for part in ("vendor_dlkm", "system_dlkm"):
        order = path / part / "modules.load"
        actual[part] = module_list(order) if order.is_file() and order.read_text().strip() else []
    require(actual == manifest["lists"], "stock module pool load lists differ from inventory")
    require(actual["vendor_dlkm"] and all(path_modules(path / part) for part in ("vendor_dlkm", "system_dlkm")),
            "stock module pool is missing either DLKM group")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    stock = sub.add_parser("stock")
    stock.add_argument("images", type=Path)
    stock.add_argument("output", type=Path)
    stock.add_argument("--branch", required=True)
    stock.add_argument("--payload-metadata", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("image", type=Path)
    compare.add_argument("--stock", required=True, type=Path)
    compare.add_argument("--check-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.operation == "stock":
        collect_stock(args.images.resolve(), args.output.resolve(), args.branch, args.payload_metadata)
    else:
        check_vendor_boot(args.image, args.stock)
        print("vendor_boot header and ordered normal/Recovery lists match")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
