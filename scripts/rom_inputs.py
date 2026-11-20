"""Stock OTA identities shared by the ROM build tools."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[a-z][a-z0-9_]*")
BASE_PARTITIONS = set("odm product system system_dlkm system_ext vendor vendor_dlkm".split())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def baseline(branch):
    entries = json.loads((ROOT / "official/kernels.json").read_text())
    for entry in entries.values():
        if branch in (entry["branch"], entry["coloros"]):
            return entry
    raise ValueError(f"unknown stock baseline: {branch}")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def protobuf(data):
    """Read the protobuf wire types used in the OTA metadata."""
    at = 0

    def varint():
        nonlocal at
        value = 0
        for bit in range(0, 70, 7):
            require(at < len(data), "truncated protobuf varint")
            byte = data[at]
            at += 1
            value |= (byte & 127) << bit
            if byte < 128:
                require(value < 1 << 64, "oversized protobuf varint")
                return value
        raise ValueError("oversized protobuf varint")

    fields = {}
    while at < len(data):
        tag = varint()
        index, wire = tag >> 3, tag & 7
        require(index != 0, "invalid protobuf field number")
        if wire == 0:
            value = varint()
        else:
            require(wire in (1, 2, 5), "unsupported protobuf wire type")
            length = varint() if wire == 2 else {1: 8, 5: 4}[wire]
            require(length <= len(data) - at, "truncated protobuf field")
            value = data[at:at + length]
            at += length
        fields.setdefault(index, []).append(value)
    return fields


def one(fields, number, kind, default=None):
    values = fields.get(number, [])
    if not values and default is not None:
        return default
    require(len(values) == 1 and isinstance(values[0], kind),
            f"invalid protobuf field {number}")
    return values[0]


def partition_name(value):
    require(isinstance(value, bytes), "invalid partition name")
    name = value.decode("ascii")
    require(NAME.fullmatch(name), f"invalid partition name: {name}")
    return name


def payload_metadata(path, expected=None):
    # AOSP system/update_engine/update_metadata.proto, version 2 payload header.
    with Path(path).open("rb") as stream:
        header = stream.read(24)
        require(len(header) == 24 and header[:4] == b"CrAU", f"{path}: invalid payload header")
        version, size, _ = struct.unpack_from(">QQI", header, 4)
        require(version == 2 and 0 < size <= 64 * 1024 * 1024, f"{path}: invalid manifest size/version")
        manifest = stream.read(size)
    require(len(manifest) == size, f"{path}: truncated manifest")
    digest = base64.b64encode(hashlib.sha256(header + manifest).digest()).decode("ascii")
    require(expected is None or expected == digest, f"{path}: payload metadata SHA-256 differs from stock")
    fields = protobuf(manifest)
    parts = {}
    for entry in fields.get(13, []):
        part = protobuf(entry)
        name = partition_name(one(part, 1, bytes))
        info = protobuf(one(part, 7, bytes))
        size, sha = one(info, 1, int), one(info, 2, bytes)
        require(name not in parts and len(sha) == 32, f"{path}: invalid new_partition_info for {name}")
        parts[name] = {"size": size, "sha256": sha.hex()}
    dynamic = protobuf(one(fields, 15, bytes))
    groups = {}
    for entry in dynamic.get(1, []):
        group = protobuf(entry)
        name = partition_name(one(group, 1, bytes))
        names = [partition_name(part) for part in group.get(3, [])]
        size = one(group, 2, int, 0)
        require(name not in groups and len(names) == len(set(names)), f"{path}: duplicate dynamic partition/group")
        groups[name] = {"size": size, "partitions": names}
    return {"sha256": digest, "partitions": parts, "groups": groups,
            "partial": bool(one(fields, 16, int, 0)), "virtual_ab": bool(one(dynamic, 2, int, 0))}


def stock_payload(images, branch, path=None):
    entry = baseline(branch)
    return payload_metadata(path or Path(images) / "payload_metadata.bin", entry["payload_metadata_sha256"])


def verify_image(path, expected):
    require(Path(path).is_file() and Path(path).stat().st_size == expected["size"],
            f"{path}: missing image or size differs from the payload")
    require(sha256(path) == expected["sha256"], f"{path}: SHA-256 differs from the payload")


def verify_stock(images, payload, names):
    for name in names:
        require(name in payload["partitions"], f"stock payload lacks {name}")
        with raw_image(Path(images) / f"{name}.img") as raw:
            verify_image(raw, payload["partitions"][name])


@contextmanager
def raw_image(path):
    path = Path(path)
    with path.open("rb") as stream:
        sparse = stream.read(4) == b"\x3a\xff\x26\xed"
    if not sparse:
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="ossi-unsparse-") as tmp:
        raw = Path(tmp) / path.name
        subprocess.run(["simg2img", path, raw], check=True)
        yield raw


def avb_info(path, partition=None, footer=False):
    info = subprocess.check_output(["avbtool", "info_image", "--image", path], text=True)
    flags = re.search(r"^Flags:\s*(\d+)\s*$", info, re.M)
    algorithm = re.search(r"^Algorithm:\s*(\S+)", info, re.M)
    require(flags and algorithm and flags[1] == "0" and algorithm[1] != "NONE",
            f"{path}: AVB must be signed with flags 0")
    if footer:
        require(re.search(r"^Footer version:", info, re.M | re.I), f"{path}: missing AVB footer")
    if partition:
        require(re.search(r"^\s+Partition Name:\s*" + re.escape(partition) + r"\s*$", info, re.M),
                f"{path}: AVB partition name differs from {partition}")
    return info


def avb_footer_key(path):
    """Read the encoded AVB public key from a verified raw image footer."""
    size = Path(path).stat().st_size
    with Path(path).open("rb") as stream:
        require(size >= 64, f"{path}: missing AVB footer")
        stream.seek(-64, 2)
        footer = stream.read(64)
        require(footer[:4] == b"AVBf", f"{path}: invalid AVB footer magic")
        offset, meta_size = struct.unpack_from(">QQ", footer, 20)
        require(meta_size >= 256 and offset + meta_size <= size - 64, f"{path}: invalid vbmeta location")
        stream.seek(offset)
        header = stream.read(256)
        require(header[:4] == b"AVB0", f"{path}: invalid vbmeta header")
        auth, auxiliary = struct.unpack_from(">QQ", header, 12)
        key_offset, key_size = struct.unpack_from(">QQ", header, 64)
        require(auth + auxiliary <= meta_size - 256 and 0 < key_size <= auxiliary - key_offset,
                f"{path}: invalid vbmeta public key")
        stream.seek(offset + 256 + auth + key_offset)
        return stream.read(key_size)


def extract_fs(image, dest, subpath=None):
    """Extract an EROFS or ext4 partition (or subpath) using rootless host tools."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with raw_image(image) as raw:
        with Path(raw).open("rb") as stream:
            stream.seek(1024)
            sb = stream.read(1024)
        require(len(sb) == 1024, f"{image}: truncated filesystem superblock")
        target = "/" + subpath.strip("/") if subpath else None
        if sb[:4] == b"\xe2\xe1\xf5\xe0":
            cmd = ["fsck.erofs", f"--extract={dest}"]
            if target:
                cmd.append(f"--path={target}")
            cmd.append(str(raw))
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            return "erofs"
        if sb[56:58] == b"\x53\xef":
            # debugfs' rdump may return zero on errors; inspect stderr after extracting.
            result = subprocess.run(["debugfs", "-R", f'rdump {target or "/"} "{dest}"', str(raw)],
                                    check=True, capture_output=True, text=True)
            errors = [
                line for line in result.stderr.splitlines()
                if not line.startswith("debugfs ")
                and not (os.geteuid() != 0 and "Operation not permitted while changing ownership of" in line)
            ]
            require(not errors, f"{image}: extraction error: {' '.join(errors[:2])}")
            return "ext4"
        raise ValueError(f"{image}: expected ext4 or EROFS")
