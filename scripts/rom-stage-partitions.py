#!/usr/bin/env python3
"""Stage OEM images and the first-stage fstab for a verified GT5 stock layout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

from rom_inputs import (BASE_PARTITIONS, NAME, avb_footer_key, avb_info, raw_image, require, sha256,
                        stock_payload, verify_image)

SPARSE_MAGIC = 0xED26FF3A


def required_filesystems(fstab):
    partitions = {}
    for number, line in enumerate(fstab.read_text().splitlines(), 1):
        fields = line.split("#", 1)[0].split()
        if not fields or not fields[0].startswith("my_"):
            continue
        if len(fields) != 5:
            raise ValueError(f"{fstab}:{number}: malformed OEM mount")
        name, _, fs_type, _, flags = fields
        if not {"logical", "first_stage_mount", "slotselect"} <= set(flags.split(",")):
            raise ValueError(f"{fstab}:{number}: OEM mount lacks first-stage logical A/B flags")
        if fs_type not in {"ext4", "erofs"}:
            raise ValueError(f"{fstab}:{number}: unsupported filesystem {fs_type}")
        partitions.setdefault(name, set()).add(fs_type)
    require(partitions, f"{fstab}: no OEM logical mounts")
    return partitions


def image_header(path):
    """Validate sparse framing and return the first 4096 expanded bytes + size."""
    size = path.stat().st_size
    with path.open("rb") as image:
        header = image.read(28)
        if len(header) < 28:
            raise ValueError(f"{path}: truncated image")
        if struct.unpack_from("<I", header)[0] != SPARSE_MAGIC:
            image.seek(0)
            return image.read(4096), size, "raw"
        _, major, minor, file_hdr, chunk_hdr, block, blocks, chunks, _ = struct.unpack(
            "<I4H4I", header)
        if major != 1 or minor != 0 or file_hdr < 28 or chunk_hdr < 12 or block == 0 or block % 4:
            raise ValueError(f"{path}: invalid sparse header")
        image.seek(file_hdr)
        prefix = bytearray()
        expanded = 0
        for _ in range(chunks):
            chunk = image.read(chunk_hdr)
            if len(chunk) != chunk_hdr:
                raise ValueError(f"{path}: truncated sparse chunk header")
            kind, _, count, total = struct.unpack_from("<2H2I", chunk)
            length = count * block
            payload = total - chunk_hdr
            want = min(length, 4096 - len(prefix))
            if kind == 0xCAC1 and payload == length:  # RAW
                prefix.extend(image.read(want))
                image.seek(length - want, os.SEEK_CUR)
            elif kind == 0xCAC2 and payload == 4:  # FILL
                fill = image.read(4)
                if len(fill) != 4:
                    raise ValueError(f"{path}: truncated sparse fill")
                prefix.extend((fill * ((want + 3) // 4))[:want])
            elif kind == 0xCAC3 and payload == 0:  # DONT_CARE
                prefix.extend(bytes(want))
            elif kind == 0xCAC4 and payload == 4 and count == 0:  # CRC32
                image.seek(4, os.SEEK_CUR)
            else:
                raise ValueError(f"{path}: invalid sparse chunk 0x{kind:x}")
            expanded += length
            if expanded > blocks * block or image.tell() > size:
                raise ValueError(f"{path}: truncated or oversized sparse chunk")
        if expanded != blocks * block or image.tell() != size:
            raise ValueError(f"{path}: sparse size/chunk count mismatch")
        return bytes(prefix), expanded, "sparse"


def inspect_image(path, allowed):
    header, expanded, encoding = image_header(path)
    if len(header) < 4096:
        raise ValueError(f"{path}: filesystem superblock is truncated")
    sb = header[1024:]
    if struct.unpack_from("<H", sb, 56)[0] == 0xEF53:
        fs_type = "ext4"
        log_block = struct.unpack_from("<I", sb, 24)[0]
        if log_block > 6:
            raise ValueError(f"{path}: invalid ext4 block size")
        block = 1024 << log_block
        blocks = struct.unpack_from("<I", sb, 4)[0]
        incompat = struct.unpack_from("<I", sb, 96)[0]
        if incompat & 0x80:  # EXT4_FEATURE_INCOMPAT_64BIT
            blocks |= struct.unpack_from("<I", sb, 336)[0] << 32
        filesystem_size = blocks * block
    elif struct.unpack_from("<I", sb)[0] == 0xE0F5E1E2:
        fs_type = "erofs"
        log_block = sb[12]
        if not 9 <= log_block <= 16:
            raise ValueError(f"{path}: invalid erofs block size")
        filesystem_size = struct.unpack_from("<I", sb, 36)[0] << log_block
    else:
        raise ValueError(f"{path}: not an ext4 or erofs filesystem")
    if fs_type not in allowed:
        raise ValueError(f"{path}: {fs_type} not permitted by fstab ({sorted(allowed)})")
    if not 4096 <= filesystem_size <= expanded or expanded % 4096:
        raise ValueError(f"{path}: invalid filesystem/image size {filesystem_size}/{expanded}")
    return fs_type, encoding, expanded


def stock_layout(path, payload, mounts, slot=None):
    """Match the OTA dynamic group to an actual lpdump -j capture."""
    require(payload["virtual_ab"] and len(payload["groups"]) == 1,
            "expected one stock Virtual A/B dynamic group")
    group_name, group = next(iter(payload["groups"].items()))
    layout = json.loads(path.read_text())
    blocks = layout.get("blockDevices", layout.get("block_devices", []))
    require(len(blocks) == 1 and blocks[0]["name"] == "super", f"{path}: expected one super device")
    group_size = group["size"]
    super_size = int(blocks[0]["size"])
    require(group_size > 0 and super_size >= group_size + 4 * 1024 * 1024
            and super_size % 4096 == 0, f"{path}: invalid super/group size")
    updated = set(group["partitions"])
    require(BASE_PARTITIONS <= updated, f"{path}: OTA is missing required logical partitions")

    def check_group(candidate, suffix):
        physical_group = group_name + suffix
        maximum = int(candidate.get("maximumSize", candidate.get("maximum_size", 0)))
        require(maximum == group_size, "dynamic group capacity differs from the OTA")
        other_slot = {"_a": "_b", "_b": "_a"}.get(suffix)
        partitions = {}
        seen = set()
        for part in layout["partitions"]:
            raw_name = part["name"]
            name = raw_name.removesuffix(suffix) if suffix else raw_name
            if part.get("groupName", part.get("group_name")) != physical_group:
                if other_slot and raw_name.endswith(other_slot):
                    continue
                require(not name.startswith("my_") and name not in BASE_PARTITIONS,
                        f"{raw_name} is outside {physical_group}")
                continue
            require(raw_name.endswith(suffix) and NAME.fullmatch(name) and name not in seen,
                    f"invalid logical partition {raw_name} in {physical_group}")
            seen.add(name)
            size = int(part.get("size", 0))
            require(size >= 0, f"negative size for {raw_name}")
            if size:
                partitions[name] = size
        require(updated <= partitions.keys(), "logical partitions differ from the OTA")
        require(partitions.keys() <= BASE_PARTITIONS | mounts.keys(),
                f"unsupported stock partitions {sorted(partitions.keys() - BASE_PARTITIONS - mounts.keys())}")
        require(payload["partial"] or updated == partitions.keys(), "extra partitions in full OTA layout")
        for name in sorted(updated & payload["partitions"].keys()):
            require(partitions[name] == payload["partitions"][name]["size"],
                    f"{name} size differs from the OTA")
        require(sum(partitions.values()) <= group_size, f"logical partitions exceed {physical_group} capacity")
        return partitions

    # On-device LP metadata lists both slots, even with lpdump --slot.
    # The updated group must match both names and sizes from the pinned OTA.
    suffixes = (f"_{slot}",) if slot else ("", "_a", "_b")
    groups = {entry["name"]: entry for entry in layout["groups"]}
    require(len(groups) == len(layout["groups"]), f"{path}: duplicate LP group")
    matches, errors = [], []
    for suffix in suffixes:
        name = group_name + suffix
        if name in groups:
            try:
                matches.append(check_group(groups[name], suffix))
            except ValueError as error:
                errors.append(f"{name}: {error}")
    require(matches, f"{path}: no LP group matches the OTA ({'; '.join(errors) or 'group absent'})")
    require(len(matches) == 1, f"{path}: both LP slots match the OTA, set --stock-slot to the active slot")
    return group_name, group_size, super_size, matches[0]


def render_fstab(text, oem_names):
    lines = []
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if fields:
            name = fields[0].removeprefix("/mnt/vendor/")
            if name.startswith("my_") and name not in oem_names:
                continue
            if name == "odm":
                line = line.replace("avb_keys=/vendor/etc/oplus_avb.pubkey", "avb=vbmeta_vendor")
            elif fields[0] in oem_names:
                require("avb_keys=/vendor/etc/oplus_avb.pubkey" in line, f"missing OEM AVB key reference for {name}")
                line = line.replace("avb_keys=/vendor/etc/oplus_avb.pubkey", "avb_keys=/avb/ossi-oem")
        lines.append(line)
    return "\n".join(lines) + "\n"


def make_fragment(group, capacity, super_size, partitions):
    names = " ".join(sorted(partitions))
    prefix = "BOARD_" + group.upper()
    system = " ".join(sorted(BASE_PARTITIONS))
    lines = [
        "# Generated by scripts/rom-stage-partitions.py from one OTA; do not edit.",
        f"OGKI_STAGED_OEM_PARTITIONS := {names}",
        f"BOARD_SUPER_PARTITION_SIZE := {super_size}",
        f"BOARD_SUPER_PARTITION_GROUPS := {group}",
        f"{prefix}_SIZE := {capacity}",
        f"{prefix}_PARTITION_LIST := {system} $(OGKI_STAGED_OEM_PARTITIONS)",
        "AB_OTA_PARTITIONS += $(OGKI_STAGED_OEM_PARTITIONS)",
        "BOARD_CUSTOMIMAGES_PARTITION_LIST += $(OGKI_STAGED_OEM_PARTITIONS)",
    ]
    for name in sorted(partitions):
        upper = name.upper()
        lines.extend([
            f"BOARD_{upper}_IMAGE_LIST := $(DEVICE_PATH)/prebuilt/oem_partitions/{name}.img",
            f"INSTALLED_{upper}IMAGE_TARGET = $(PRODUCT_OUT)/{name}.img",
            f"BOARD_{upper}_IMAGE_NO_FLASHALL := true",
        ])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--device-tree", required=True, type=Path)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--payload-metadata", type=Path)
    parser.add_argument("--stock-layout", type=Path, help="lpdump -j JSON from the exact stock build")
    parser.add_argument("--stock-slot", choices=("a", "b"), help="active stock slot if both LP groups match")
    parser.add_argument("--oem-key", type=Path, help="optional additional pin for the OEM AVB public PEM")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        images = args.images.resolve(strict=True)
        device = args.device_tree.resolve(strict=True)
        fstab = device / "fstab.default"
        mounts = required_filesystems(fstab)
        payload = stock_payload(images, args.branch, args.payload_metadata)
        layout = args.stock_layout or images / "super-layout.json"
        group, capacity, super_size, layout_parts = stock_layout(layout, payload, mounts, args.stock_slot)
        required = sorted(layout_parts.keys() & mounts.keys())
        require(required, "verified super layout contains no OEM images")
        inspected = {}
        keys = set()
        carried_forward = {}
        for name in required:
            source = images / f"{name}.img"
            fs_type, encoding, expanded = inspect_image(source, mounts[name])
            with raw_image(source) as raw:
                if name in payload["partitions"]:
                    verify_image(raw, payload["partitions"][name])
                else:
                    require(payload["partial"] and expanded == layout_parts[name],
                            f"{source}: carried-forward image size differs from the stock layout")
                avb_info(raw, name, footer=True)
                avb = ["avbtool", "verify_image", "--image", raw]
                if args.oem_key:
                    avb.extend(("--key", args.oem_key))
                subprocess.run(avb,
                               check=True, stdout=subprocess.DEVNULL)
                public_key = avb_footer_key(raw)
                if name in payload["partitions"]:
                    keys.add(public_key)
                else:
                    carried_forward[name] = public_key
                inspected[name] = {"fs": fs_type, "size": expanded, "sha256": sha256(raw)}
            require(expanded <= layout_parts[name], f"{source}: does not fit stock logical partition")
            print(f"{name}: {fs_type}, {encoding}, {expanded} expanded bytes")
        require(keys and all(key in keys for key in carried_forward.values()),
                f"the OEM key of carried-forward partitions {sorted(carried_forward)} must be pinned by stock OTA images")
        rendered_fstab = render_fstab(fstab.read_text(), inspected)
        fragment = make_fragment(group, capacity, super_size, inspected)
        report = {"group": group, "max_size": capacity, "super_size": super_size,
                  "stock_payload": payload["sha256"], "partitions": sorted(layout_parts),
                  "stock_layout_sha256": sha256(layout),
                  "omitted_mounts": sorted(mounts.keys() - inspected.keys()), "images": inspected}
        if args.dry_run:
            print(fragment, end="")
            return 0
        prebuilt = device / "prebuilt"
        prebuilt.mkdir(exist_ok=True)
        require(not any((prebuilt / path).exists() for path in ("oem-partitions.mk", "oem-avb-keys", "oem_partitions")),
                "OEM staging already exists in this device tree")
        # Complete validation and copying before replacing any installed image.
        # Publish the makefile last, so an initial failed stage cannot enable a
        # board configuration with an incomplete collection of OEM images.
        with tempfile.TemporaryDirectory(prefix=".oem-stage-", dir=prebuilt) as temp:
            stage = Path(temp)
            for name in inspected:
                shutil.copyfile(images / f"{name}.img", stage / f"{name}.img")
            (stage / "oem-partitions.mk").write_text(fragment)
            (stage / "oem-partitions.json").write_text(json.dumps(report, indent=2) + "\n")
            (stage / "fstab.ossi").write_text(rendered_fstab)
            key_dir = stage / "oem-avb-keys"
            key_dir.mkdir()
            for key in keys:
                (key_dir / (hashlib.sha256(key).hexdigest() + ".avbpubkey")).write_bytes(key)
            destination = prebuilt / "oem_partitions"
            destination.mkdir(exist_ok=True)
            for name in inspected:
                os.replace(stage / f"{name}.img", destination / f"{name}.img")
            key_dir.rename(prebuilt / key_dir.name)
            for name in ("fstab.ossi", "oem-partitions.json"):
                os.replace(stage / name, prebuilt / name)
            os.replace(stage / "oem-partitions.mk", prebuilt / "oem-partitions.mk")
        print(f"Staged {len(inspected)} OEM partitions into {prebuilt}")
        return 0
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
