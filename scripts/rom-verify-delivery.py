#!/usr/bin/env python3
"""Verify the actual ROM target-files and OTA before collecting artifacts."""
import argparse
import base64
from contextlib import nullcontext
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import BadZipFile, ZipFile

import kmi
from rom_inputs import BASE_PARTITIONS, avb_info, baseline, payload_metadata, raw_image, require, sha256
from rom_modules import check_vendor_boot, inventory, module_list, modules_from_fs, ramdisk_files

BOOT_PARTS = set("boot dtbo init_boot recovery vbmeta vbmeta_system vbmeta_vendor vendor_boot".split())
METADATA = "META-INF/com/android/metadata"
CHAINS = {"boot": 4, "dtbo": 3, "recovery": 1, "vendor_boot": 6, "vbmeta_system": 2, "vbmeta_vendor": 5}
CHUNK_SIZE = 4 * 1024 * 1024


def key_values(text):
    result = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            require(key not in result or result[key] == value, f"conflicting metadata values for {key}")
            result[key] = value
    return result


def check_partition_lists(dynamic, ab_partitions, oem):
    group = oem["group"]
    expected = BASE_PARTITIONS | oem["images"].keys()
    require(set(ab_partitions.split()) == expected | BOOT_PARTS, "target-files OTA partition list differs from staging")
    require(dynamic["super_partition_groups"].split() == [group] and
            int(dynamic[f"super_{group}_group_size"]) == oem["max_size"] and
            int(dynamic["super_partition_size"]) == oem["super_size"] and
            set(dynamic[f"super_{group}_partition_list"].split()) == expected,
            "target-files dynamic group differs from the verified stock layout")
    return expected


def check_ota_signature(ota, certificate, work):
    """Check the whole-file SignApk signature used by Android Recovery."""
    total_size = ota.stat().st_size
    require(total_size >= 28, "OTA ZIP is too short for a whole-file signature")
    with ota.open("rb") as stream:
        stream.seek(-6, 2)
        signature_start, marker, comment_size = struct.unpack("<H2sH", stream.read(6))
        require(marker == b"\xff\xff" and 6 < signature_start <= comment_size <= total_size - 22,
                "OTA ZIP is missing a valid whole-file signature footer")
        stream.seek(-comment_size - 22, 2)
        end_record = stream.read()
        magic = b"PK\x05\x06"
        require(end_record.startswith(magic) and magic not in end_record[4:]
                and struct.unpack_from("<H", end_record, 20)[0] == comment_size,
                "invalid end of central directory for signed OTA ZIP")
        signature = work / "ota-signature.der"
        signature.write_bytes(end_record[-signature_start:-6])
        stream.seek(0)
        remaining = total_size - comment_size - 2
        cmd = ["openssl", "cms", "-verify", "-binary", "-inform", "DER",
               "-nointern", "-certfile", certificate, "-noverify",
               "-in", signature, "-content", "/dev/stdin", "-out", "/dev/null"]
        # Recovery trusts supplied public keys. Use only the expected build
        # certificate and stream the signed bytes, excluding the ZIP comment.
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as verify:
            try:
                with verify.stdin:
                    while remaining:
                        chunk = stream.read(min(remaining, CHUNK_SIZE))
                        require(chunk, "truncated signed OTA ZIP")
                        verify.stdin.write(chunk)
                        remaining -= len(chunk)
            except BrokenPipeError:
                pass
            require(verify.wait() == 0 and remaining == 0, "OTA ZIP signature differs from the build certificate")


def ota_header(ota, dest, payload_file=None):
    with ZipFile(ota) as archive:
        require({"payload.bin", "payload_properties.txt", METADATA} <= set(archive.namelist()),
                "incomplete A/B OTA ZIP")
        info = key_values(archive.read(METADATA).decode("utf-8"))
        devices = {d.strip() for d in re.split(r"[|,]", info.get("pre-device", "")) if d.strip()}
        require(info.get("ota-type") == "AB" and "ossi" in devices,
                "OTA ZIP is not an ossi A/B update")
        properties = key_values(archive.read("payload_properties.txt").decode("utf-8"))
        payload_output = payload_file.open("wb") if payload_file else nullcontext()
        with archive.open("payload.bin") as stream, payload_output as payload:
            header = stream.read(24)
            require(len(header) == 24, "truncated OTA payload")
            _, length, _ = struct.unpack_from(">QQI", header, 4)
            require(0 < length <= 64 * 1024 * 1024, "invalid OTA payload metadata length")
            prefix = header + stream.read(length)
            require(int(properties["METADATA_SIZE"]) == len(prefix) == length + 24,
                    "OTA payload metadata size differs from the ZIP properties")
            dest.write_bytes(prefix)
            if payload:
                payload.write(prefix)
            h = hashlib.sha256(prefix)
            size = len(prefix)
            for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                size += len(chunk)
                h.update(chunk)
                if payload:
                    payload.write(chunk)
            require(size == int(properties["FILE_SIZE"]) and
                    base64.b64encode(h.digest()).decode("ascii") == properties["FILE_HASH"],
                    "OTA payload size or SHA-256 differs from the ZIP properties")
    return payload_metadata(dest, properties["METADATA_HASH"])


def check_recovery(ramdisk, fstab):
    expected_paths = {"system/bin/recovery", "system/etc/recovery.fstab", "etc/recovery.fstab"}
    recovery = {name: data for name, data in ramdisk_files(ramdisk) if name in expected_paths}
    executable = recovery.get("system/bin/recovery", b"")
    require(len(executable) >= 64 and executable[:6] == b"\x7fELF\x02\x01",
            "recovery: missing AArch64 recovery program")
    kind, machine = struct.unpack_from("<HH", executable, 16)
    require(kind in (2, 3) and machine == 183, "recovery: invalid recovery executable")
    require(recovery.get("system/etc/recovery.fstab") == fstab and
            recovery.get("etc/recovery.fstab", fstab) == fstab,
            "recovery: installed recovery.fstab differs from staging")


def check_boot(images, pre, work, security_patch):
    year, month = map(int, security_patch.split("-")[:2])
    patch = ((year - 2000) << 4) | month
    for name in ("boot", "init_boot", "recovery"):
        path = images / f"{name}.img"
        with path.open("rb") as stream:
            hdr = stream.read(44)
            require(len(hdr) == 44 and hdr[:8] == b"ANDROID!", f"{name}: invalid boot image header")
            kernel_size, ramdisk_size, os_version, size = struct.unpack_from("<4I", hdr, 8)
            version, = struct.unpack_from("<I", hdr, 40)
            require(version == 4 and size == 1584, f"{name}: expected boot header v4")
            require((os_version >> 11) == (13 << 14) and (os_version & 0x7ff) == patch,
                    f"{name}: boot header OS version or security patch month differs from stock")
            kernel_padded = ((kernel_size + 4095) // 4096) * 4096
            require(4096 + kernel_padded + ramdisk_size <= path.stat().st_size,
                    f"{name}: truncated boot image")
            if name == "boot":
                require(kernel_size > 0 and ramdisk_size == 0, "boot: expected only a kernel")
                stream.seek(4096)
                dumped = work / "Image"
                dumped.write_bytes(stream.read(kernel_size))
                require(sha256(dumped) == sha256(pre / "Image"), "ROM boot kernel differs from staged Image")
            else:
                require(kernel_size == 0 and ramdisk_size > 0, f"{name}: expected only a ramdisk")
                if name == "recovery":
                    stream.seek(4096)
                    check_recovery(stream.read(ramdisk_size), (pre / "fstab.ossi").read_bytes())


def dtbo_payload(path):
    with path.open("rb") as stream:
        header = stream.read(8)
        require(len(header) == 8 and header[:4] == b"\xd7\xb7\xab\x1e", f"{path}: invalid DTBO magic")
        length, = struct.unpack_from(">I", header, 4)
        require(32 <= length <= path.stat().st_size, f"{path}: invalid DTBO size")
        return header + stream.read(length - len(header))


def check_dlkm(images, staged, work):
    for part in ("vendor_dlkm", "system_dlkm"):
        dest = work / part
        fs = modules_from_fs(images / f"{part}.img", dest)
        require(fs == staged["fs"][part], f"{part}: filesystem differs from verified stock format")
        files = inventory(dest)
        names = {name for name in files if name.endswith(".ko")}
        expected_abi = staged["module_abi"][part]
        require(names == expected_abi.keys(), f"{part}: shipped module inventory differs")
        load = files.get("modules.load")
        order = module_list(load) if load and load.read_text().strip() else []
        require(order == staged["lists"][part], f"{part}: load order differs")
        for name in names:
            require(kmi.module_abi(files[name]) == expected_abi[name],
                    f"{part}: {name} ABI differs from staging")


def rollback_index(security_patch):
    patch = date.fromisoformat(security_patch)
    return int(datetime.combine(patch, time.min, tzinfo=timezone.utc).timestamp())


def check_avb(images, avb_key, work, boot_patch, platform_patch):
    chain_key = work / "rom.avbpubkey"
    subprocess.run(["avbtool", "extract_public_key", "--key", avb_key, "--output", chain_key], check=True)
    top = images / "vbmeta.img"
    info = avb_info(top)
    chains = re.findall(r"^\s*Chain Partition descriptor:\s*\n\s*Partition Name:\s*(\w+)"
                        r"\s*\n\s*Rollback Index Location:\s*(\d+)", info, re.M)
    require(len(chains) == len(CHAINS) and {name: int(slot) for name, slot in chains} == CHAINS,
            "vbmeta has an unexpected chain or rollback slot layout")
    indices = {"vbmeta": 0}
    for name, patch in (("boot", boot_patch), ("dtbo", boot_patch), ("recovery", boot_patch),
                        ("vendor_boot", boot_patch), ("vbmeta_vendor", boot_patch),
                        ("vbmeta_system", platform_patch)):
        indices[name] = rollback_index(patch)
    for name, index in indices.items():
        header = info if name == "vbmeta" else avb_info(images / f"{name}.img")
        match = re.search(r"^Rollback Index:[ \t]*(\d+)[ \t]*$", header, re.M)
        require(match and int(match[1]) == index, f"{name}: AVB rollback index differs from the build policy")
    args = ["avbtool", "verify_image", "--image", top, "--key", avb_key, "--follow_chain_partitions"]
    for name, slot in CHAINS.items():
        args.extend(("--expected_chain_partition", f"{name}:{slot}:{chain_key}"))
    subprocess.run(args, check=True)
    digests = json.loads(subprocess.check_output(
        ["avbtool", "print_partition_digests", "--image", top, "--json"], text=True))
    expected = BASE_PARTITIONS | {"boot", "dtbo", "init_boot", "recovery", "vendor_boot"}
    require(expected <= {entry["name"] for entry in digests["partitions"]},
            "required partitions are missing from the ROM AVB chain")
    return {"public_key_sha256": sha256(chain_key), "rollback_indices": indices}


def check_property_contexts(contexts_by_file):
    """Simulate AOSP TrieBuilder::AddToTrie to reject duplicate property_contexts keys."""
    root = {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
    for label, text in contexts_by_file:
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            require(len(parts) >= 2, f"{label}:{lineno}: malformed property_contexts entry")
            name, ctx = parts[0], parts[1]
            if name == "*":
                continue
            exact = len(parts) >= 3 and parts[2] == "exact"
            pieces = name.split(".")
            ends_dot = False
            if pieces[-1] == "":
                ends_dot = True
                pieces.pop()
            node = root
            for piece in pieces[:-1]:
                node = node["children"].setdefault(
                    piece, {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
                )
            last = pieces[-1]
            src = f"{label}:{lineno} ({ctx})"
            if exact:
                require(last not in node["exacts"],
                        f"duplicate exact property_contexts key '{name}': {node['exacts'].get(last)} vs {src}")
                node["exacts"][last] = src
            elif not ends_dot:
                require(last not in node["prefixes"],
                        f"duplicate prefix property_contexts key '{name}': {node['prefixes'].get(last)} vs {src}")
                node["prefixes"][last] = src
            else:
                child = node["children"].setdefault(
                    last, {"context": None, "children": {}, "prefixes": {}, "exacts": {}}
                )
                require(child["context"] is None,
                        f"duplicate prefix property_contexts key '{name}': {child['context']} vs {src}")
                child["context"] = src


def check_target_files_runtime_guards(archive):
    """Verify target-files will not hit PropertyInit TrieBuilder or OPLUS Phoenix watchdog failures."""
    names = set(archive.namelist())
    pc_paths = (
        "SYSTEM/etc/selinux/plat_property_contexts",
        "SYSTEM_EXT/etc/selinux/system_ext_property_contexts",
        "PRODUCT/etc/selinux/product_property_contexts",
        "VENDOR/etc/selinux/vendor_property_contexts",
        "ODM/etc/selinux/odm_property_contexts",
    )
    contexts = [(p, archive.read(p).decode("utf-8", errors="replace")) for p in pc_paths if p in names]
    if contexts:
        check_property_contexts(contexts)

    modules_load = "VENDOR_BOOT/RAMDISK/lib/modules/modules.load"
    if modules_load in names and "oplus_phoenix.ko" in archive.read(modules_load).decode("utf-8", errors="replace").split():
        rc_texts = "\n".join(
            archive.read(n).decode("utf-8", errors="replace")
            for n in sorted(names)
            if n.endswith(".rc") and (n.startswith("SYSTEM/") or n.startswith("SYSTEM_EXT/") or n.startswith("VENDOR/") or n.startswith("ODM/"))
        )
        require(
            'write /proc/phoenix "SET_BOOTSTAGE@ANDROID_BOOT_COMPLETED"' in rc_texts,
            "oplus_phoenix.ko is loaded in vendor_boot without /proc/phoenix ANDROID_BOOT_COMPLETED disarm",
        )
        cil_texts = "\n".join(
            archive.read(n).decode("utf-8", errors="replace")
            for n in sorted(names)
            if n.endswith(".cil") and n.startswith(("SYSTEM/etc/selinux/", "SYSTEM_EXT/etc/selinux/", "VENDOR/etc/selinux/", "ODM/etc/selinux/"))
        )
        genfs = re.search(r'\(genfscon\s+proc\s+"/phoenix"\s+\(u\s+object_r\s+(\S+)\s+', cil_texts)
        require(genfs is not None, "oplus_phoenix.ko is loaded without genfscon proc /phoenix SELinux label")
        label = genfs.group(1)
        require(
            re.search(rf'\(allow\s+(?:init(?:_[0-9_]+)?|vendor_init(?:_[0-9_]+)?)\s+{re.escape(label)}\s+\(file\s+\([^)]*\bwrite\b', cil_texts)
            is not None,
            f"SELinux policy labels /proc/phoenix as {label} without granting init write access",
        )


def verify(target, ota, pre, stock, key, dest, source_manifest, ota_cert, delta_generator, platform_patch):
    staged = json.loads((pre / "stage-report.json").read_text())
    oem = json.loads((pre / "oem-partitions.json").read_text())
    require(staged["stock_payload"] == oem["stock_payload"], "staging used different stock OTAs")
    spec = baseline(staged["package"]["branch"])
    require(staged["stock_payload"] == spec["payload_metadata_sha256"], "staged OTA differs from the branch profile")
    with tempfile.TemporaryDirectory(prefix=".ossi-delivery-", dir=target.resolve().parent) as directory:
        work = Path(directory)
        images = work / "images"
        images.mkdir()
        with ZipFile(target) as archive:
            check_target_files_runtime_guards(archive)
            dynamic = key_values(archive.read("META/dynamic_partitions_info.txt").decode("utf-8"))
            parts = check_partition_lists(dynamic, archive.read("META/ab_partitions.txt").decode("utf-8"), oem)
            expected = parts | BOOT_PARTS
            require({"IMAGES/" + n + ".img" for n in expected} <= set(archive.namelist()),
                    "target-files archive is missing required images")
            for name in sorted(expected):
                filename = name + ".img"
                with archive.open(f"IMAGES/{filename}") as source, (images / filename).open("wb") as output:
                    shutil.copyfileobj(source, output)

        payload_file = work / "payload.bin"
        check_ota_signature(ota, ota_cert, work)
        payload = ota_header(ota, work / "payload_metadata.bin", payload_file)
        public_key = work / "ota-public.pem"
        subprocess.run(["openssl", "x509", "-in", ota_cert, "-pubkey", "-noout", "-out", public_key], check=True)
        subprocess.run([delta_generator, "--in_file", payload_file, "--public_key", public_key], check=True)
        payload_file.unlink()
        group = payload["groups"].get(oem["group"])
        require(payload["virtual_ab"] and not payload["partial"] and len(payload["groups"]) == 1 and
                group and group["size"] == oem["max_size"] and set(group["partitions"]) == parts,
                "built OTA payload has a different dynamic group/layout")
        require(set(payload["partitions"]) == expected, "built OTA payload has missing or unexpected partitions")
        require(sum(payload["partitions"][p]["size"] for p in parts) <= oem["max_size"],
                "built dynamic partitions exceed the group budget")
        hashes = {}
        for name in sorted(expected):
            with raw_image(images / f"{name}.img") as raw:
                digest = sha256(raw)
                entry = payload["partitions"][name]
                require(raw.stat().st_size == entry["size"] and digest == entry["sha256"],
                        f"OTA {name} digest or size differs from target-files")
                if name in oem["images"]:
                    require(digest == oem["images"][name]["sha256"], f"OEM {name} differs from verified input")
                    avb_info(raw, name, footer=True)
                hashes[name] = digest
        check_boot(images, pre, work, staged["boot_security_patch"])
        require(dtbo_payload(images / "dtbo.img") == dtbo_payload(pre / "dtbo.img"),
                "ROM DTBO contents differ from staged stock DTBO")
        check_vendor_boot(images / "vendor_boot.img", stock / "vendor_boot.img", staged["lists"],
                          pre / "dtb/ossi.dtb", pre / "oem-avb-keys", pre / "fstab.ossi",
                          staged["module_abi"]["vendor_ramdisk"])
        check_dlkm(images, staged, work)
        avb = check_avb(images, key, work, staged["boot_security_patch"], platform_patch)

    require(len({ota.name, target.name, source_manifest.name, "rom-delivery.json"}) == 4,
            "duplicate delivery filename")
    dest.parent.mkdir(parents=True, exist_ok=True)
    require(not dest.exists() and not dest.is_symlink(), f"{dest}: delivery output already exists")
    with tempfile.TemporaryDirectory(prefix=".ossi-publish-", dir=dest.parent) as temp:
        staged_output = Path(temp) / "delivery"
        staged_output.mkdir()
        for source in (ota, target, source_manifest):
            shutil.copyfile(source, staged_output / source.name)
        result = {"baseline": {name: spec[name] for name in ("branch", "coloros", "source_manifest",
                                                            "source_branch", "product", "api")},
                  "stock_payload": oem["stock_payload"], "stock_layout_sha256": oem["stock_layout_sha256"],
                  "kernel": staged["package"], "avb": avb,
                  "boot_security_patch": staged["boot_security_patch"], "platform_security_patch": platform_patch,
                  "partitions": hashes, "artifacts": {p.name: sha256(p) for p in sorted(staged_output.iterdir())}}
        (staged_output / "rom-delivery.json").write_text(json.dumps(result, indent=2) + "\n")
        staged_output.rename(dest)
    print(f"Verified ROM artifacts: {dest}")


def locate_dist(dist, ota=None):
    target, ota_packages = [], []
    for path in sorted(dist.glob("*.zip")):
        with ZipFile(path) as archive:
            if "META/ab_partitions.txt" in archive.namelist():
                target.append(path)
            if ota is None and "payload.bin" in archive.namelist():
                ota_packages.append(path)
    require(len(target) == 1, f"build dist must contain one target-files ZIP (found {len(target)})")
    if ota is not None:
        require(ota.is_file(), f"missing AOSP OTA ZIP: {ota}")
        return target[0], ota
    require(len(ota_packages) == 1, f"build dist must contain one A/B OTA ZIP (found {len(ota_packages)})")
    return target[0], ota_packages[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prebuilt", "stock", "avb-key", "ota-cert", "delta-generator", "output", "source-manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--platform-security-patch", required=True, help="platform SPL from the Android build")
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--target-files", type=Path)
    parser.add_argument("--ota", type=Path)
    a = parser.parse_args()
    try:
        require(a.dist or (a.target_files and a.ota), "provide --dist or --target-files with --ota")
        target, ota = locate_dist(a.dist, a.ota) if a.dist else (a.target_files, a.ota)
        verify(target, ota, a.prebuilt, a.stock, a.avb_key, a.output, a.source_manifest,
               a.ota_cert, a.delta_generator, a.platform_security_patch)
    except (OSError, ValueError, KeyError, TypeError, struct.error, BadZipFile, subprocess.CalledProcessError) as error:
        print(f"FAIL: ROM delivery: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
