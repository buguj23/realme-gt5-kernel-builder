#!/usr/bin/env python3
"""kmi.py — prove an Image and a set of .ko come from one build.

With CONFIG_MODVERSIONS=y the kernel rejects any module whose __versions entry
for an imported symbol disagrees with the kernel's own CRC. The first casualty is
`module_layout` (struct module), then every EXPORT_SYMBOL the module imports.
Vermagic strings do NOT gate this: same_magic() ignores the version prefix.

Sources of truth:
  * kernel side  — Module.symvers produced by the same build as the Image
  * module side  — ELF section __versions, 64 entries of {u64 crc; char name[56]}

usage:
  kmi.py symvers  Module.symvers                       # print module_layout CRC
  kmi.py modules  DIR                                  # CRC census of *.ko
  kmi.py image    Image --crc 0x0222dd63               # occurrence count in Image
  kmi.py verify   --symvers S --modules DIR [--image I] # exit 1 on any mismatch
  kmi.py manifest --package DIR --out DIR/manifest.json

exit: 0 aligned, 1 misaligned, 2 usage/IO error
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter

VERSIONS_ENTRY = 64          # u64 crc + char name[56], arm64 + x86_64
MODULE_NAME_LEN = 56
LAYOUT = "module_layout"


# ---------------------------------------------------------------- ELF helpers
def elf_sections(path):
    """Yield (name, data, sh_type) without pyelftools when possible."""
    with open(path, "rb") as f:
        ident = f.read(16)
        if ident[:4] != b"\x7fELF" or ident[4] != 2:
            return
        f.seek(0)
        hdr = f.read(64)
        e_shoff, = struct.unpack_from("<Q", hdr, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", hdr, 0x3A)
        if not e_shoff or not e_shnum:
            return
        f.seek(e_shoff)
        raw = f.read(e_shentsize * e_shnum)

        def sh(i):
            o = i * e_shentsize
            name, typ = struct.unpack_from("<II", raw, o)
            offset, size = struct.unpack_from("<QQ", raw, o + 0x18)
            return name, typ, offset, size

        _, _, str_off, str_size = sh(e_shstrndx)
        f.seek(str_off)
        strtab = f.read(str_size)
        for i in range(e_shnum):
            name_off, typ, off, size = sh(i)
            end = strtab.find(b"\0", name_off)
            name = strtab[name_off:end].decode("ascii", "replace")
            if typ != 8:      # SHT_NOBITS has no file data
                f.seek(off)
                yield name, f.read(size), typ


def versions_map(path):
    """{symbol: crc} from __versions, or None when the section is absent."""
    try:
        for name, data, _ in elf_sections(path):
            if name != "__versions":
                continue
            out = {}
            for off in range(0, len(data) - VERSIONS_ENTRY + 1, VERSIONS_ENTRY):
                crc, = struct.unpack_from("<Q", data, off)
                sym = data[off + 8:off + 8 + MODULE_NAME_LEN].split(b"\0", 1)[0]
                if sym:
                    out[sym.decode("ascii", "replace")] = crc
            return out
    except FileNotFoundError:
        raise
    return None


def fallback_versions(path):
    """modprobe --dump-modversions when the ELF walk finds nothing."""
    import subprocess
    try:
        res = subprocess.run(["modprobe", "--dump-modversions", path],
                             capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    out = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("0x"):
            out[parts[1]] = int(parts[0], 16)
    return out or None


def module_versions(path):
    return versions_map(path) or fallback_versions(path)


# ------------------------------------------------------------------ symvers
def read_symvers(path):
    """{symbol: crc} for every exported symbol in Module.symvers."""
    table = {}
    with open(path, "r", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].startswith("0x"):
                table[parts[1]] = int(parts[0], 16)
    return table


# --------------------------------------------------------------------- verbs
def cmd_symvers(args):
    table = read_symvers(args.symvers)
    if LAYOUT not in table:
        print(f"FAIL {args.symvers}: no {LAYOUT} row (CONFIG_MODVERSIONS off?)")
        return 1
    print(f"0x{table[LAYOUT]:08x} {LAYOUT}  ({args.symvers})")
    return 0


def cmd_modules(args):
    files = sorted(f for f in os.listdir(args.modules) if f.endswith(".ko"))
    if not files:
        print(f"FAIL {args.modules}: no .ko")
        return 2
    census = Counter()
    for name in files:
        vers = module_versions(os.path.join(args.modules, name))
        if not vers:
            census["<no __versions>"] += 1
            continue
        crc = vers.get(LAYOUT)
        census[f"0x{crc:08x}" if crc is not None else "<no module_layout>"] += 1
    print(f"{len(files)} modules in {args.modules}")
    for crc, n in census.most_common():
        print(f"  {n:4d}  {crc}")
    return 0 if len(census) == 1 and "<no __versions>" not in census else 1


def cmd_image(args):
    want = int(args.crc, 0)
    data = open(args.image, "rb").read()
    needle = struct.pack("<I", want)
    n = data.count(needle)
    print(f"{args.image}: {needle.hex()} appears {n} time(s)")
    # A kernel Image is one long blob; a match proves the CRC is embedded but
    # absence proves incompatibility only when the module set is known.
    return 0 if n else 1


def cmd_verify(args):
    if not os.path.isfile(args.symvers):
        print(f"FAIL missing {args.symvers}")
        return 2
    table = read_symvers(args.symvers)
    kernel_layout = table.get(LAYOUT)
    if kernel_layout is None:
        print(f"FAIL {args.symvers} has no {LAYOUT}")
        return 1

    files = sorted(f for f in os.listdir(args.modules) if f.endswith(".ko"))
    if not files:
        print(f"FAIL {args.modules}: no .ko")
        return 2

    bad_layout = []
    mismatched = {}
    no_versions = []
    for name in files:
        vers = module_versions(os.path.join(args.modules, name))
        if not vers:
            no_versions.append(name)
            continue
        if vers.get(LAYOUT) != kernel_layout:
            bad_layout.append((name, vers.get(LAYOUT)))
        diff = sum(1 for sym, crc in vers.items() if sym in table and table[sym] != crc)
        if diff:
            mismatched[name] = diff

    print(f"kernel {LAYOUT} = 0x{kernel_layout:08x}  ({len(table)} symbols in symvers)")
    print(f"modules: {len(files)}  layout-match: {len(files) - len(bad_layout) - len(no_versions)}")
    if no_versions:
        print(f"  no __versions (unsigned/none): {len(no_versions)} e.g. {no_versions[:3]}")
    if bad_layout:
        shown = ", ".join(f"{n}=0x{c:08x}" if c else f"{n}=?" for n, c in bad_layout[:5])
        print(f"  LAYOUT MISMATCH: {len(bad_layout)} e.g. {shown}")
    if mismatched:
        worst = sorted(mismatched.items(), key=lambda kv: -kv[1])[:5]
        print(f"  SYMBOL MISMATCH: {len(mismatched)} module(s), worst {worst}")

    ok = not bad_layout and not mismatched
    if args.image:
        ok = cmd_image(argparse.Namespace(image=args.image,
                                          crc=f"0x{kernel_layout:08x}")) == 0 and ok
    print("KMI ALIGNED" if ok else "KMI MISALIGNED")
    return 0 if ok else 1


def cmd_manifest(args):
    """Describe a kernel package so the ROM tree can prove what it consumed."""
    pkg = args.package
    symvers = os.path.join(pkg, "Module.symvers")
    mods = os.path.join(pkg, "modules")
    table = read_symvers(symvers) if os.path.isfile(symvers) else {}
    files = sorted(f for f in os.listdir(mods) if f.endswith(".ko")) if os.path.isdir(mods) else []
    data = {
        "package": os.path.basename(pkg.rstrip("/")),
        "module_layout_crc": f"0x{table[LAYOUT]:08x}" if LAYOUT in table else None,
        "symvers_symbols": len(table),
        "modules": len(files),
        "image": os.path.isfile(os.path.join(pkg, "Image")),
        "dtbo": os.path.isfile(os.path.join(pkg, "dtbo.img")),
        "module_names": files,
    }
    with open(args.out, "w") as f:
        json.dump(data, f, indent=1)
    print(f"{args.out}: {data['modules']} modules, layout {data['module_layout_crc']}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("symvers"); p.add_argument("symvers"); p.set_defaults(fn=cmd_symvers)
    p = sub.add_parser("modules"); p.add_argument("modules"); p.set_defaults(fn=cmd_modules)
    p = sub.add_parser("image"); p.add_argument("image"); p.add_argument("--crc", required=True)
    p.set_defaults(fn=cmd_image)
    p = sub.add_parser("verify")
    p.add_argument("--symvers", required=True); p.add_argument("--modules", required=True)
    p.add_argument("--image"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("manifest")
    p.add_argument("--package", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_manifest)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
