#!/usr/bin/env python3
"""ida_kmi_check.py — read module_layout CRC out of what IDA has open.

Run inside IDA (File -> Script file…, or `idat -Sida_kmi_check.py <binary>`).
It answers one question: would the modules in this directory load on this kernel?

  * ELF (vmlinux or a .ko) — the authoritative answer comes from the symbol table
    and __versions, so IDA opens the file and we read those bytes.
  * raw arm64 Image — no section headers survive objcopy; the only handle is the
    4-byte CRC that Module.symvers computed for module_layout, which we look for
    byte-wise (same method the 2026-11-13 audit used).

Usage in IDA:
    ida_kmi_check.py [--symvers Module.symvers] [--modules DIR] [--image FILE]

Without arguments it inspects the currently loaded database and prints a report
to the output window. Exit code (headless) is 0 for aligned, 1 for misaligned.
"""
import argparse
import os
import struct
import sys

LAYOUT = "module_layout"
ENTRY = 64
NAME_LEN = 56


def read_symvers(path):
    table = {}
    with open(path, errors="replace") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].startswith("0x"):
                table[p[1]] = int(p[0], 16)
    return table


def elf_sections(path):
    with open(path, "rb") as f:
        ident = f.read(16)
        if ident[:4] != b"\x7fELF" or ident[4] != 2:
            return {}
        f.seek(0)
        hdr = f.read(64)
        shoff, = struct.unpack_from("<Q", hdr, 0x28)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", hdr, 0x3A)
        if not shoff or not shnum:
            return {}
        f.seek(shoff)
        raw = f.read(shentsize * shnum)

        def sh(i):
            o = i * shentsize
            name, typ = struct.unpack_from("<II", raw, o)
            off, size = struct.unpack_from("<QQ", raw, o + 0x18)
            return name, typ, off, size

        _, _, stroff, strsize = sh(shstrndx)
        f.seek(stroff)
        strtab = f.read(strsize)
        out = {}
        for i in range(shnum):
            name_off, typ, off, size = sh(i)
            if typ == 8:
                continue
            end = strtab.find(b"\0", name_off)
            name = strtab[name_off:end].decode("ascii", "replace")
            f.seek(off)
            out[name] = f.read(size)
        return out


def versions_crc(path):
    data = elf_sections(path).get("__versions")
    if not data:
        return None
    for off in range(0, len(data) - ENTRY + 1, ENTRY):
        crc, = struct.unpack_from("<Q", data, off)
        name = data[off + 8:off + 8 + NAME_LEN].split(b"\0", 1)[0]
        if name == LAYOUT.encode():
            return crc
    return None


def ida_read_symbol(name):
    """Symbol value via IDA, if a database is open."""
    try:
        import idc  # noqa
        ea = idc.get_name_ea_simple(name)
        if ea != idc.BADADDR:
            return ea
    except Exception:
        pass
    return None


def scan_image(path, crc):
    data = open(path, "rb").read()
    return data.count(struct.pack("<I", crc))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symvers")
    ap.add_argument("--modules")
    ap.add_argument("--image")
    a = ap.parse_args(argv)

    lines = []
    ok = True

    loaded = None
    try:
        import idaapi  # noqa
        loaded = idaapi.get_input_file_path()
    except Exception:
        pass

    kernel_crc = None
    if a.symvers:
        table = read_symvers(a.symvers)
        kernel_crc = table.get(LAYOUT)
        lines.append(f"symvers {LAYOUT} = 0x{kernel_crc:08x}" if kernel_crc else
                     f"symvers has no {LAYOUT}")
        if kernel_crc is None:
            ok = False

    target = loaded or (a.image if a.image else None)
    if target and os.path.isfile(target):
        crc = versions_crc(target)
        if crc is not None:
            lines.append(f"{os.path.basename(target)}: own {LAYOUT} = 0x{crc:08x} (__versions)")
            if kernel_crc is not None and crc != kernel_crc:
                lines.append("  -> this file disagrees with the symvers")
                ok = False
        elif kernel_crc is not None:
            n = scan_image(target, kernel_crc)
            lines.append(f"{os.path.basename(target)}: raw scan of 0x{kernel_crc:08x} -> {n} hit(s)")
            if n == 0:
                lines.append("  -> kernel does not embed this CRC; modules will be rejected")
                ok = False

    if a.modules and os.path.isdir(a.modules):
        bad = []
        files = sorted(f for f in os.listdir(a.modules) if f.endswith(".ko"))
        for name in files:
            crc = versions_crc(os.path.join(a.modules, name))
            if kernel_crc is not None and crc != kernel_crc:
                bad.append((name, crc))
        lines.append(f"modules {len(files)}: {len(files) - len(bad)} match, {len(bad)} mismatch")
        for name, crc in bad[:5]:
            lines.append(f"  {name} = {'0x%08x' % crc if crc else '?'}")
        ok = ok and not bad

    report = "\n".join(lines) if lines else "nothing to check (give --symvers/--modules)"
    print(report)
    try:
        import ida_kernwin  # noqa
        ida_kernwin.msg(report + "\n")
    except Exception:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
