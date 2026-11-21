"""Regression fixtures for stock layout, ordered modules, and ROM publication."""
import base64
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from rom_inputs import BASE_PARTITIONS, avb_footer_key, avb_info, payload_metadata
from rom_modules import DT_FSTAB, check_vendor_boot, dtb_for_ramdisk_fstab, inventory, modules_from_fs

PARTITIONS = runpy.run_path(str(SCRIPTS / "rom-stage-partitions.py"))
DELIVERY = runpy.run_path(str(SCRIPTS / "rom-verify-delivery.py"))
BLOBS = runpy.run_path(str(SCRIPTS / "rom-select-blobs.py"))


def varint(value):
    data = bytearray()
    while value > 127:
        data.append((value & 127) | 128)
        value >>= 7
    return bytes(data) + bytes([value])


def number(field, value):
    return varint(field << 3) + varint(value)


def blob(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


def digest(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def make_payload(names, partial=False):
    partitions = b""
    for name in sorted(names):
        contents = name.encode().ljust(4096, b"\0")
        info = number(1, len(contents)) + blob(2, hashlib.sha256(contents).digest())
        partitions += blob(13, blob(1, name.encode()) + blob(7, info))
    group = blob(1, b"qti_dynamic_partitions") + number(2, 33554432)
    group += b"".join(blob(3, name.encode()) for name in sorted(names))
    manifest = partitions + blob(15, blob(1, group) + number(2, 1)) + number(16, int(partial))
    return b"CrAU" + struct.pack(">QQI", 2, len(manifest), 0) + manifest


def newc(entries):
    archive = bytearray()
    for path, data in [*entries.items(), ("TRAILER!!!", b"")]:
        name = path.encode() + b"\0"
        fields = (0, 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0)
        archive += b"070701" + b"".join(f"{v:08x}".encode() for v in fields) + name
        archive += b"\0" * (-len(archive) % 4) + data
        archive += b"\0" * (-len(archive) % 4)
    return bytes(archive)


def sign_ota(ota, certificate, key, work):
    data = ota.read_bytes()
    assert data[-2:] == b"\0\0" and data[-22:-18] == b"PK\x05\x06"
    signed = work / "zip-body"
    signed.write_bytes(data[:-2])
    signature = subprocess.check_output(["openssl", "cms", "-sign", "-binary", "-noattr",
                                         "-signer", certificate, "-inkey", key,
                                         "-in", signed, "-outform", "DER"])
    comment_size = len(signature) + 6
    footer = struct.pack("<H2sH", comment_size, b"\xff\xff", comment_size)
    ota.write_bytes(data[:-2] + struct.pack("<H", comment_size) + signature + footer)


class RomInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_pinned_payload_rejects_other_or_truncated_manifest(self):
        path = self.root / "payload.bin"
        data = make_payload(BASE_PARTITIONS | {"my_product"})
        path.write_bytes(data)
        expected = digest(data)
        parsed = payload_metadata(path, expected)
        self.assertEqual(len(parsed["partitions"]), 8)
        self.assertEqual(parsed["groups"]["qti_dynamic_partitions"]["size"], 33554432)
        path.write_bytes(make_payload(BASE_PARTITIONS | {"my_region"}))
        with self.assertRaisesRegex(ValueError, "differs from stock"):
            payload_metadata(path, expected)
        path.write_bytes(data[:-1])
        with self.assertRaisesRegex(ValueError, "truncated manifest"):
            payload_metadata(path)

    def test_partial_payload_uses_lp_layout_for_additional_oem_partitions(self):
        names = BASE_PARTITIONS | {"my_product"}
        data = make_payload(names, partial=True)
        payload = self.root / "payload_metadata.bin"
        payload.write_bytes(data)
        parsed = payload_metadata(payload, digest(data))
        layout = self.root / "super.json"
        entry = {
            "block_devices": [{"name": "super", "size": "67108864"}],
            "groups": [{"name": "qti_dynamic_partitions", "maximum_size": "33554432"}],
            "partitions": [{"name": name, "group_name": "qti_dynamic_partitions", "size": "4096"}
                           for name in sorted(names | {"my_company"})],
        }
        layout.write_text(json.dumps(entry))
        candidates = {"my_product": {"ext4"}, "my_company": {"ext4"}, "my_preload": {"ext4"}}
        group, _, _, parts = PARTITIONS["stock_layout"](layout, parsed, candidates)
        self.assertEqual(group, "qti_dynamic_partitions")
        self.assertIn("my_company", parts)
        self.assertNotIn("my_preload", parts)
        base = (SCRIPTS.parent / "rom/device/realme/ossi/fstab.default").read_text()
        rendered = PARTITIONS["render_fstab"](base, parts.keys() & candidates.keys())
        self.assertIn("/mnt/vendor/my_company", rendered)
        self.assertNotIn("my_preload", rendered)
        self.assertIn("avb_keys=/avb/ossi-oem", rendered)
        entry["groups"][0]["maximum_size"] = "33554433"
        layout.write_text(json.dumps(entry))
        with self.assertRaisesRegex(ValueError, "capacity differs"):
            PARTITIONS["stock_layout"](layout, parsed, candidates)

    @unittest.skipUnless(all(shutil.which(t) for t in ("lpmake", "lpdump")),
                         "requires Android logical partition tools")
    def test_lpdump_selects_only_the_stock_slot_matching_the_payload(self):
        group = "qti_dynamic_partitions"
        updated = BASE_PARTITIONS | {"my_product"}
        payload_file = self.root / "payload_metadata.bin"
        payload_file.write_bytes(make_payload(updated, partial=True))
        payload = payload_metadata(payload_file)
        super_image = self.root / "super.img"
        subprocess.run([
            "lpmake", "--metadata-size", "65536", "--metadata-slots", "3", "--device-size", "67108864",
            "--virtual-ab", "--group", f"{group}_a:33554432", "--group", f"{group}_b:33554432",
            "--output", super_image,
            *[arg for name in sorted(updated | {"my_company"})
              for arg in ("--partition", f"{name}_a:readonly:4096:{group}_a")],
            "--partition", f"my_company_b:readonly:0:{group}_b",
        ], check=True, capture_output=True)
        layout = self.root / "super.json"
        layout.write_bytes(subprocess.check_output(["lpdump", "-j", "-s", "0", super_image]))
        candidates = {name: {"ext4"} for name in ("my_product", "my_company", "my_preload")}
        parts = PARTITIONS["stock_layout"](layout, payload, candidates)[3]
        self.assertEqual(parts, {name: 4096 for name in updated | {"my_company"}})
        with self.assertRaisesRegex(ValueError, "no LP group matches"):
            PARTITIONS["stock_layout"](layout, payload, candidates, "b")

        data = json.loads(layout.read_text())
        data["partitions"].extend({"name": f"{name}_b", "group_name": f"{group}_b", "size": "4096"}
                                  for name in sorted(updated | {"my_preload"}))
        layout.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "both LP slots match"):
            PARTITIONS["stock_layout"](layout, payload, candidates)
        parts = PARTITIONS["stock_layout"](layout, payload, candidates, "b")[3]
        self.assertEqual(parts.keys(), updated | {"my_preload"})

    @unittest.skipUnless(all(shutil.which(t) for t in ("dtc", "fdtget", "fdtput")),
                         "requires Device Tree Compiler tools")
    def test_only_matching_legacy_dtb_fstab_is_replaced(self):
        tree = self.root / "board.dtb"

        def compile_tree(status, flags):
            source = f"""/dts-v1/;
                / {{
                    model = "GT5 fixture";
                    firmware {{ android {{
                        compatible = "android,firmware";
                        fstab {{
                            compatible = "android,fstab";
                            status = "{status}";
                            vendor {{
                                dev = "/dev/block/platform/soc/1d84000.ufshc/by-name/vendor";
                                type = "ext4";
                                fsmgr_flags = "{flags}";
                            }};
                        }};
                    }}; }};
                }};
            """
            return subprocess.run(["dtc", "-I", "dts", "-O", "dtb"], input=source.encode(),
                                  capture_output=True, check=True).stdout

        legacy = compile_tree("ok", "wait,slotselect,avb")
        disabled = compile_tree("disabled", "wait,slotselect,avb")
        staged, changed = dtb_for_ramdisk_fstab(legacy + disabled)
        self.assertEqual(changed, 1)
        first_size, = struct.unpack_from(">I", staged, 4)
        self.assertEqual(staged[first_size:], disabled)
        tree.write_bytes(staged[:first_size])
        self.assertEqual(subprocess.check_output(["fdtget", tree, DT_FSTAB, "status"]), b"disabled\n")
        self.assertEqual(subprocess.check_output(["fdtget", tree, "/", "model"]), b"GT5 fixture\n")
        self.assertEqual(dtb_for_ramdisk_fstab(staged), (staged, 0))
        with self.assertRaisesRegex(ValueError, "unexpected device-tree fstab"):
            dtb_for_ramdisk_fstab(compile_tree("okay", "wait,slotselect,avb,logical"))
        with self.assertRaisesRegex(ValueError, "invalid vendor_boot DTB size"):
            dtb_for_ramdisk_fstab(staged[:-1])

    def test_ota_payload_checks_full_file_and_partition_lists(self):
        data = make_payload(BASE_PARTITIONS | {"my_product"})
        ota = self.root / "ota.zip"
        metadata = "ota-type=AB\npre-device=ossi\n"
        properties = (f"METADATA_HASH={digest(data)}\nMETADATA_SIZE={len(data)}\n"
                      f"FILE_HASH={digest(data)}\nFILE_SIZE={len(data)}\n")

        def write(payload):
            with ZipFile(ota, "w") as archive:
                archive.writestr("payload.bin", payload)
                archive.writestr("payload_properties.txt", properties)
                archive.writestr("META-INF/com/android/metadata", metadata)

        write(data)
        self.assertIn("my_product", DELIVERY["ota_header"](ota, self.root / "prefix")["partitions"])
        write(data + b"unexpected data")
        with self.assertRaisesRegex(ValueError, "payload size or SHA-256"):
            DELIVERY["ota_header"](ota, self.root / "prefix")
        oem = {"group": "qti_dynamic_partitions", "max_size": 33554432, "super_size": 67108864,
               "images": {"my_product": {}}}
        dynamic = {"super_partition_groups": oem["group"], "super_qti_dynamic_partitions_group_size": "33554432",
                   "super_partition_size": "67108864",
                   "super_qti_dynamic_partitions_partition_list": " ".join(BASE_PARTITIONS | {"my_product"})}
        names = BASE_PARTITIONS | {"my_product"}
        self.assertEqual(DELIVERY["check_partition_lists"](dynamic, " ".join(names | DELIVERY["BOOT_PARTS"]), oem), names)
        with self.assertRaisesRegex(ValueError, "OTA partition list"):
            DELIVERY["check_partition_lists"](dynamic, "boot", oem)

    @unittest.skipUnless(shutil.which("openssl"), "requires OpenSSL")
    def test_ota_requires_whole_file_signature_from_configured_certificate(self):
        ota = self.root / "ota.zip"
        with ZipFile(ota, "w") as archive:
            archive.writestr("payload.bin", b"payload fixture")
        check = DELIVERY["check_ota_signature"]
        cert = self.root / "ota.pem"
        key = self.root / "signing.pem"
        other_cert = self.root / "other.pem"
        for certificate, private_key in ((cert, key), (other_cert, self.root / "other-key.pem")):
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                            "-subj", "/CN=ossi test", "-keyout", private_key, "-out", certificate],
                           check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, "whole-file signature footer"):
            check(ota, cert, self.root)
        sign_ota(ota, cert, key, self.root)
        check(ota, cert, self.root)
        with self.assertRaisesRegex(ValueError, "signature differs"):
            check(ota, other_cert, self.root)
        ota.write_bytes(ota.read_bytes().replace(b"payload fixture", b"payload altered"))
        with self.assertRaisesRegex(ValueError, "signature differs"):
            check(ota, cert, self.root)

    def test_ota_from_product_out_and_target_files_from_dist(self):
        dist = self.root / "dist"
        dist.mkdir()
        target = dist / "ossi-target_files.zip"
        with ZipFile(target, "w") as archive:
            archive.writestr("META/ab_partitions.txt", "boot\n")
        ota = self.root / "ossi-ota.zip"
        with ZipFile(ota, "w") as archive:
            archive.writestr("payload.bin", b"CrAU")
        self.assertEqual(DELIVERY["locate_dist"](dist, ota), (target, ota))
        with self.assertRaisesRegex(ValueError, "missing AOSP OTA ZIP"):
            DELIVERY["locate_dist"](dist, self.root / "missing.zip")

    def test_lineage_21_oem_blob_partition_is_supported(self):
        entry = "my_bigball/etc/features.xml:vendor/etc/features.xml"
        self.assertEqual(BLOBS["parse_entry"](entry), ("my_bigball/etc/features.xml", entry))

    def test_blob_fixups_match_platform_sdk(self):
        class Fixup:
            def __init__(self):
                self.calls = []

            def __getattr__(self, method):
                def record(*args):
                    self.calls.append((method, args))
                    return self

                return record

        modules = {
            "extract_utils.fixups_blob": SimpleNamespace(blob_fixup=Fixup, blob_fixups_user_type=dict),
            "extract_utils.fixups_lib": SimpleNamespace(
                lib_fixup_remove=lambda *a, **kw: "",
                lib_fixups={},
                lib_fixups_user_type=dict,
            ),
            "extract_utils.main": SimpleNamespace(ExtractUtils=None, ExtractUtilsModule=lambda *a, **kw: kw),
        }
        script = SCRIPTS.parent / "rom/device/realme/ossi/extract-files.py"
        results = {}
        with patch.dict(sys.modules, modules):
            for sdk in (34, 35, 36):
                with patch.dict("os.environ", {"OSSI_PLATFORM_SDK": str(sdk)}):
                    results[sdk] = runpy.run_path(str(script))["blob_fixups"]
        fingerprint = "odm/bin/hw/vendor.oplus.hardware.biometrics.fingerprint@2.1-service_uff"
        shim = ("add_needed", ("libshims_aidl_fingerprint_v2.oplus.so",))
        compat = ("replace_needed", ("libtinyxml2.so", "libtinyxml2-v34.so"))
        self.assertNotIn(fingerprint, results[34])
        self.assertEqual(results[35][fingerprint].calls, [shim])
        self.assertEqual(results[36][fingerprint].calls, [compat, shim])
        self.assertEqual(
            results[35]["system_ext/bin/wfdservice64"].calls,
            [("add_needed", ("libwfdservice_shim.so",))],
        )
        self.assertEqual(
            results[35]["system_ext/lib64/libwfdservice.so"].calls,
            [("replace_needed", ("android.media.audio.common.types-V2-cpp.so", "android.media.audio.common.types-V4-cpp.so"))],
        )

    @unittest.skipUnless(all(shutil.which(t) for t in ("mkbootimg", "clang")),
                         "requires Android mkbootimg and clang")
    def test_vendor_boot_must_preserve_order_and_recovery(self):
        module = self.root / "valid.ko"
        asm = (b'.section .modinfo,"a"\n.asciz "vermagic=5.15.149-test SMP modversions aarch64"\n'
               b'.section __versions,"a"\n.quad 0x12345678\n.asciz "module_layout"\n.zero 42\n')
        subprocess.run(["clang", "--target=aarch64-linux-gnu", "-c", "-x", "assembler", "-",
                        "-o", module], input=asm, capture_output=True, check=True)

        def make(name, normal, recovery, files, corrupt=None):
            archive = self.root / f"{name}.cpio"
            paths = {f"lib/modules/{filename}": module.read_bytes() if filename != corrupt else b"invalid"
                     for filename in files}
            paths.update({"lib/modules/modules.load": normal, "lib/modules/modules.load.recovery": recovery})
            archive.write_bytes(newc(paths))
            dtb = self.root / "dtb"
            dtb.write_bytes(b"\xd0\x0d\xfe\xed" + b"\0" * 60)
            image = self.root / f"{name}.img"
            subprocess.run(["mkbootimg", "--header_version", "4", "--pagesize", "4096",
                            "--vendor_ramdisk", archive, "--dtb", dtb, "--vendor_boot", image], check=True)
            return image

        normal, recovery = b"a.ko\nb.ko\na.ko\n", b"b.ko\nc.ko\n"
        files = ("a.ko", "b.ko", "c.ko")
        stock = make("stock", normal, recovery, files)
        check_vendor_boot(stock, stock)
        reordered = make("reordered", b"b.ko\na.ko\na.ko\n", recovery, files)
        with self.assertRaisesRegex(ValueError, "normal modules.load order"):
            check_vendor_boot(reordered, stock)
        missing = make("missing", normal, recovery, files[:2])
        with self.assertRaisesRegex(ValueError, "Recovery module files missing"):
            check_vendor_boot(missing, stock)
        invalid = make("invalid", normal, recovery, files, corrupt="c.ko")
        with self.assertRaisesRegex(ValueError, "not an AArch64 kernel module"):
            check_vendor_boot(invalid, stock)

    @unittest.skipUnless(all(shutil.which(t) for t in ("clang", "ld.lld", "lz4")),
                         "requires clang, lld and lz4")
    def test_recovery_requires_a_program_and_matching_fstab(self):
        binary = self.root / "recovery"
        subprocess.run(["clang", "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib",
                        "-x", "assembler", "-", "-o", binary],
                       input=b".globl _start\n_start: ret\n", check=True, capture_output=True)
        fstab = b"vendor /vendor erofs ro wait,logical,first_stage_mount\n"

        def ramdisk(entries):
            return subprocess.check_output(["lz4", "-l", "-c"], input=newc(entries))

        entries = {"system/bin/recovery": binary.read_bytes(), "system/etc/recovery.fstab": fstab}
        check = DELIVERY["check_recovery"]
        check(ramdisk(entries), fstab)
        with self.assertRaisesRegex(ValueError, "recovery.fstab differs"):
            check(ramdisk(entries | {"etc/recovery.fstab": b"wrong table"}), fstab)
        with self.assertRaisesRegex(ValueError, "missing AArch64 recovery program"):
            check(ramdisk({"system/etc/recovery.fstab": fstab}), fstab)

    @unittest.skipUnless(all(shutil.which(t) for t in ("mkfs.ext4", "debugfs")), "requires ext4 host tools")
    def test_stock_dlkm_files_stay_in_their_partition(self):
        files = self.root / "source/lib/modules"
        files.mkdir(parents=True)
        (files / "test.ko").write_bytes(b"example")
        (files / "modules.load").write_text("test.ko\n")
        image = self.root / "vendor_dlkm.img"
        subprocess.run(["mkfs.ext4", "-q", "-F", "-d", self.root / "source", image, "2048"],
                       check=True, capture_output=True)
        dest = self.root / "modules"
        self.assertEqual(modules_from_fs(image, dest), "ext4")
        self.assertEqual(inventory(dest)["test.ko"].read_bytes(), b"example")

    @unittest.skipUnless(all(shutil.which(t) for t in ("mkfs.ext4", "avbtool", "openssl")),
                         "requires Android AVB and ext4 tools")
    def test_oem_public_key_matches_signed_partition_footer(self):
        key = self.root / "key.pem"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        image = self.root / "my_product.img"
        subprocess.run(["mkfs.ext4", "-q", "-F", image, "4096"], check=True, capture_output=True)
        subprocess.run(["avbtool", "add_hashtree_footer", "--image", image, "--partition_name", "my_product",
                        "--partition_size", str(8 * 1024 * 1024), "--algorithm", "SHA256_RSA2048",
                        "--key", key, "--do_not_generate_fec"], check=True, capture_output=True)
        avb_info(image, "my_product", footer=True)
        expected = self.root / "key.avbpubkey"
        subprocess.run(["avbtool", "extract_public_key", "--key", key, "--output", expected], check=True)
        self.assertEqual(avb_footer_key(image), expected.read_bytes())
        self.assertEqual(PARTITIONS["inspect_image"](image, {"ext4"})[:2], ("ext4", "raw"))

    @unittest.skipUnless(all(shutil.which(t) for t in ("avbtool", "openssl")), "requires Android AVB tools")
    def test_avb_chain_checks_rollback_indices_in_signed_images(self):
        boot_patch = "2026-02-01"
        platform_patch = "2026-09-05"
        indices = {"boot": 1769904000, "dtbo": 1769904000, "recovery": 1769904000,
                   "vendor_boot": 1769904000, "vbmeta_vendor": 1769904000, "vbmeta_system": 1788566400}
        key = self.root / "chain.pem"
        public_key = self.root / "chain.avbpubkey"
        subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
        subprocess.run(["avbtool", "extract_public_key", "--key", key, "--output", public_key], check=True)
        signing = ("--algorithm", "SHA256_RSA2048", "--key", key)

        def image(name):
            return self.root / f"{name}.img"

        def avb(*args):
            return subprocess.run(["avbtool", *args], capture_output=True, check=True)

        def include(parts):
            return [option for part in sorted(parts) for option in ("--include_descriptors_from_image", image(part))]

        for name in BASE_PARTITIONS | {"boot", "dtbo", "init_boot", "recovery", "vendor_boot"}:
            image(name).write_bytes(name.encode().ljust(4096, b"\0"))
            avb("add_hash_footer", "--image", image(name), "--partition_name", name, "--partition_size",
                "131072", "--rollback_index", str(indices.get(name, 0)), *signing)
        for chain, parts in (("vbmeta_system", {"system", "system_ext", "product", "system_dlkm"}),
                             ("vbmeta_vendor", {"odm", "vendor", "vendor_dlkm"})):
            avb("make_vbmeta_image", "--output", image(chain),
                "--rollback_index", str(indices[chain]), *signing, *include(parts))
        chains = [arg for name, slot in DELIVERY["CHAINS"].items()
                  for arg in ("--chain_partition", f"{name}:{slot}:{public_key}")]
        avb("make_vbmeta_image", "--output", image("vbmeta"), *signing, *include({"init_boot"}), *chains)
        report = DELIVERY["check_avb"](self.root, key, self.root, boot_patch, platform_patch)
        self.assertEqual(report["rollback_indices"], indices | {"vbmeta": 0})
        with self.assertRaisesRegex(ValueError, "vbmeta_system: AVB rollback index"):
            DELIVERY["check_avb"](self.root, key, self.root, boot_patch, "2026-10-05")

    @unittest.skipUnless(all(shutil.which(t) for t in ("mkfs.ext4", "debugfs")), "requires ext4 host tools")
    def test_rootless_blob_selection_and_zero_byte_firmware_segments(self):
        image_dir = self.root / "images"
        image_dir.mkdir()
        vendor_tree = self.root / "vendor_src"
        (vendor_tree / "firmware").mkdir(parents=True)
        (vendor_tree / "lib64").mkdir(parents=True)
        (vendor_tree / "firmware/CAMERA_ICP.b10").write_bytes(b"")
        (vendor_tree / "lib64/libtest.so").write_bytes(b"ELF")
        subprocess.run(["mkfs.ext4", "-q", "-F", "-d", vendor_tree, image_dir / "vendor.img", "2048"],
                       check=True, capture_output=True)
        odm_tree = self.root / "odm_src"
        (odm_tree / "bin/hw").mkdir(parents=True)
        (odm_tree / "bin/hw/vendor.oplus.hardware.charger-V5-service").write_bytes(b"bin")
        subprocess.run(["mkfs.ext4", "-q", "-F", "-d", odm_tree, image_dir / "odm.img", "2048"],
                       check=True, capture_output=True)
        base_list = self.root / "base.txt"
        base_list.write_text("vendor/firmware/CAMERA_ICP.b10\nvendor/lib64/libtest.so\nvendor/lib64/absent.so\n")
        selected = self.root / "proprietary-files.txt"
        with patch.dict("os.environ", {"SUDO_MOUNT": "0"}):
            with self.subTest("select_blobs"):
                from contextlib import ExitStack
                args = SimpleNamespace(
                    base_list=str(base_list), images=str(image_dir), out=str(selected),
                    report=None, mount=None, no_extras=False, materialize=None,
                    label="5.15.149", payload_metadata=None,
                )
                with ExitStack() as cleanup:
                    self.assertEqual(BLOBS["select"](args, cleanup), 0)
        text = selected.read_text()
        self.assertIn("vendor/firmware/CAMERA_ICP.b10", text)
        self.assertIn("odm/bin/hw/vendor.oplus.hardware.charger-V5-service", text)
        self.assertNotIn("vendor/lib64/absent.so", text)

        checker = runpy.run_path(str(SCRIPTS / "rom-check-inputs.py"))
        vendor_out = self.root / "vendor_out"
        prop = vendor_out / "proprietary"
        (prop / "vendor/firmware").mkdir(parents=True)
        (prop / "vendor/firmware/CAMERA_ICP.b10").write_bytes(b"")
        (prop / "vendor/lib64").mkdir(parents=True)
        (prop / "vendor/lib64/libtest.so").write_bytes(b"ELF")
        (prop / "odm/bin/hw").mkdir(parents=True)
        (prop / "odm/bin/hw/vendor.oplus.hardware.charger-V5-service").write_bytes(b"bin")
        (vendor_out / "Android.bp").write_text('"proprietary/vendor/lib64/libtest.so"\n')
        (vendor_out / "ossi-vendor.mk").write_text(
            "PRODUCT_COPY_FILES += vendor/realme/ossi/proprietary/vendor/firmware/CAMERA_ICP.b10:vendor/firmware/CAMERA_ICP.b10\n")
        checker["verify_vendor"](vendor_out, selected)

    def test_soong_dedup_and_checked_in_android_bp_unique(self):
        import re
        from collections import Counter
        entries = [
            "odm/lib/rfsa/adsp/aiboost/libQnnHtpV73Skel.so|aaa",
            "odm/lib/rfsa/adsp/libQnnHtpV73Skel.so|bbb",
            "vendor/lib/rfsa/adsp/libQnnHtpV73Skel.so|ccc",
            "odm/lib/rfsa/adsp/libQnnSaver.so|ddd",
            "odm/lib64/libQnnSaver.so|eee",
            "vendor/lib/rfsa/adsp/nearby.napp_header|fff",
            "vendor/lib/rfsa/adsp/nearby.so|111",
            "odm/lib/vendor.oplus.hardware.cwb@1.0.so|222",
            "odm/lib64/vendor.oplus.hardware.cwb@1.0.so|333",
            "vendor/lib/vendor.oplus.hardware.cwb@1.0.so|444",
            "vendor/lib64/vendor.oplus.hardware.cwb@1.0.so|555",
        ]
        deduped = BLOBS["dedup_soong_entries"](entries)
        by_group = {}
        for line in deduped:
            grp, base, suf, *_ = BLOBS["soong_module_identity"](line)
            by_group[grp] = base + suf
        self.assertEqual(len(by_group), len(set(by_group.values())))
        # Both 32-bit and 64-bit vendor variants must share one Soong suffix
        self.assertIn(";MODULE_SUFFIX=_vendor|", deduped[9])
        self.assertIn(";MODULE_SUFFIX=_vendor|", deduped[10])

        # Verify committed vendor Android.bp has zero duplicate module names
        repo = SCRIPTS.parent
        bp_text = (repo / "rom/vendor/realme/ossi/Android.bp").read_text()
        names = re.findall(r'^\s*name:\s*"([^"]+)"', bp_text, re.M)
        dups = {k: v for k, v in Counter(names).items() if v > 1}
        self.assertEqual(dups, {})

    def test_select_blobs_sar_and_excluded_extras(self):
        self.assertTrue(BLOBS["is_excluded_extra"]("vendor/lib64/vendor.oplus.hardware.performance-V1-ndk.so"))
        self.assertTrue(BLOBS["is_excluded_extra"]("odm/lib64/vendor.oplus.hardware.performance-V2-ndk.so"))
        self.assertTrue(BLOBS["is_excluded_extra"]("odm/lib/vendor.oplus.hardware.touch-V2-ndk.so"))
        self.assertTrue(BLOBS["is_excluded_extra"]("vendor/lib64/libaacvibrator.so"))
        self.assertTrue(BLOBS["is_excluded_extra"]("odm/lib64/vendor.oplus.hardware.biometrics.fingerprint@2.1.so"))
        self.assertTrue(BLOBS["is_excluded_extra"]("vendor/etc/vintf/manifest/vendor.qti.hardware.display.composer-service.xml"))
        self.assertTrue(BLOBS["is_excluded_extra"]("odm/etc/vintf/manifest/manifest_performance_aidl.xml"))
        self.assertFalse(BLOBS["is_excluded_extra"]("vendor/lib64/vendor.oplus.hardware.commondcs-V1-ndk_platform.so"))
        self.assertFalse(BLOBS["is_excluded_extra"]("odm/bin/hw/vendor.oplus.hardware.charger-V5-service"))

        # Simulate extracted System-as-Root system partition layout
        sys_root = self.root / "sys_mnt"
        (sys_root / "system/lib64").mkdir(parents=True)
        target_lib = sys_root / "system/lib64/libostatslog.so"
        target_lib.write_bytes(b"ELF")
        mounts = BLOBS["Mounts"](str(self.root), str(self.root / "mnt"), sudo=False)
        mounts.extracted["system"] = str(sys_root)
        mounts.mounted = "system"
        self.assertTrue(mounts.exists("system", "lib64/libostatslog.so"))
        self.assertEqual(mounts.path_for("system", "lib64/libostatslog.so"), target_lib.resolve())

    def test_kernel_config_fragments_syntax(self):
        import re
        repo = SCRIPTS.parent
        cfg_files = [repo / "configs/features.config", *sorted((repo / "configs/fragments").glob("*.config"))]
        self.assertGreaterEqual(len(cfg_files), 2)
        for cfg in cfg_files:
            for lineno, raw in enumerate(cfg.read_text().splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                self.assertRegex(line, r"^CONFIG_[A-Za-z0-9_]+=(y|m|n|\d+|\".*\")$", f"{cfg}:{lineno}: {line}")

    def test_infinity_compat_patches_idempotent(self):
        patcher = runpy.run_path(str(SCRIPTS / "rom-patch-source.py"))
        pkg = self.root / "packages/apps/SimpleSettingsConfig"
        (pkg / "src/org/lineageos/settingsconfig").mkdir(parents=True)
        (pkg / "Android.bp").write_text(
            'android_app {\n    name: "SimpleSettingsConfig",\n\n'
            '    static_libs: [\n        "org.lineageos.platform.internal",\n    ],\n\n'
            '    srcs: ["src/**/*.java"],\n\n    platform_apis: true,\n'
            '    certificate: "platform",\n}\n'
        )
        (pkg / "AndroidManifest.xml").write_text(
            '<manifest>\n    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />\n'
            '    <uses-permission android:name="lineageos.permission.WRITE_SECURE_SETTINGS" />\n'
            '    <uses-permission android:name="lineageos.permission.WRITE_SETTINGS" />\n</manifest>\n'
        )
        (pkg / "src/org/lineageos/settingsconfig/BootReceiver.java").write_text(
            'import android.util.Log;\nimport lineageos.providers.LineageSettings;\n'
            '                case "lineage_global":\n'
            '                    LineageSettings.Global.putString(c, k, v);\n'
            '                    break;\n\n'
            '                case "lineage_secure":\n'
            '                    LineageSettings.Secure.putString(c, k, v);\n'
            '                    break;\n'
        )
        (self.root / "vendor/infinity/config").mkdir(parents=True)
        (self.root / "vendor/infinity/config/device_framework_matrix.xml").write_text("<compatibility-matrix/>\n")
        (self.root / "device/oneplus/sm8550-common").mkdir(parents=True)
        (self.root / "device/oneplus/sm8550-common/common.mk").write_text(
            "DEVICE_FRAMEWORK_COMPATIBILITY_MATRIX_FILE := \\\n    vendor/lineage/config/device_framework_matrix.xml\n"
            "# LiveDisplay\nPRODUCT_PACKAGES += \\\n    vendor.lineage.livedisplay-service.oplus\n"
        )
        (self.root / "hardware/oplus/aidl/livedisplay").mkdir(parents=True)
        (self.root / "hardware/oplus/aidl/livedisplay/Android.bp").write_text("cc_binary {}\n")
        (self.root / "build/soong/fsgen").mkdir(parents=True)
        (self.root / "build/soong/fsgen/super_img.go").write_text(
            "func buildingSuperImage(partitionVars android.PartitionVariables) bool {\n"
            "\treturn partitionVars.ProductBuildSuperPartition\n"
            "}\n"
        )
        (self.root / "kernel/oneplus/sm8550/include/soc/oplus").mkdir(parents=True)
        dangling = self.root / "kernel/oneplus/sm8550/include/soc/oplus/boot"
        dangling.symlink_to("../../sm8550-modules/missing")

        patcher["apply_all"](self.root)
        self.assertFalse(dangling.is_symlink())
        self.assertNotIn("org.lineageos.platform.internal", (pkg / "Android.bp").read_text())
        self.assertIn('sdk_version: "current"', (pkg / "Android.bp").read_text())
        self.assertNotIn("lineageos.permission.WRITE_", (pkg / "AndroidManifest.xml").read_text())
        self.assertNotIn("LineageSettings", (pkg / "src/org/lineageos/settingsconfig/BootReceiver.java").read_text())
        common = (self.root / "device/oneplus/sm8550-common/common.mk").read_text()
        self.assertIn("vendor/infinity/config/device_framework_matrix.xml", common)
        self.assertNotIn("vendor.lineage.livedisplay-service.oplus", common)
        self.assertFalse((self.root / "hardware/oplus/aidl/livedisplay/Android.bp").exists())
        self.assertTrue((self.root / "hardware/oplus/aidl/livedisplay/Android.bp.disabled").is_file())
        super_go = (self.root / "build/soong/fsgen/super_img.go").read_text()
        self.assertIn("android.InList(p, supported)", super_go)

        # Second invocation must be an exact no-op
        before = super_go
        patcher["apply_all"](self.root)
        self.assertEqual((self.root / "build/soong/fsgen/super_img.go").read_text(), before)


if __name__ == "__main__":
    unittest.main()
