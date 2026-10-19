"""probe52_playercomps.py - find live player pawn, its component list, the
alt-fire component instance (subclass-aware) and InteractionManager instances.

Outputs to temp/probe52.out:
  - objects whose class chain contains AltFireComponent (name + class)
  - live pawns (class name contains PlayerCharacter, no Default__)
  - each pawn's OwnedComponents TSet (component class + name)
  - InteractionManagerComponent instances: outer/owner + selected/focused fields
"""
import ctypes
import os
import struct
import sys
import time

import hud_dynamic as h

CORE_DLL = "Returnal-Core-Win64-Shipping.dll"
BLOCKS_RVA = 0x5C2950
GUA_IAT_RVA = 0x8A15B0
OUTLOG = r"C:\Users\admin\AppData\Local\Temp\opencode\probe52.out"

_lf = open(OUTLOG, "a", encoding="utf-8")


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s.encode("cp1252", "replace").decode("cp1252"), flush=True)
    _lf.write(s + "\n")
    _lf.flush()


say("=== probe52 %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))

pid = h.find_process_id(h.GAME_EXE)
bases = h.module_bases(pid, {CORE_DLL.lower(), h.GAME_DLL.lower()})
core = bases.get(CORE_DLL.lower())
game = bases.get(h.GAME_DLL.lower())
say("pid=%d core=0x%X game=0x%X" % (pid, core or 0, game or 0))
if not (core and game):
    sys.exit(1)

k32 = ctypes.windll.kernel32
k32.OpenProcess.restype = ctypes.c_void_p
k32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
H = k32.OpenProcess(0x0410, 0, pid)
assert H, "OpenProcess failed"
_RB = ctypes.create_string_buffer(0x10000)
_BIG = ctypes.create_string_buffer(4 << 20)


def rpm(a, n):
    buf = _BIG if n > 0x10000 else _RB
    got = ctypes.c_size_t(0)
    if (not k32.ReadProcessMemory(H, ctypes.c_void_p(a), buf, n,
                                  ctypes.byref(got)) or got.value != n):
        raise OSError("rpm fail 0x%X n=%d" % (a, n))
    return buf.raw[:n]


def u8(a):
    return rpm(a, 1)[0]


def u32(a):
    return struct.unpack("<I", rpm(a, 4))[0]


def u64(a):
    return struct.unpack("<Q", rpm(a, 8))[0]


def f32(a):
    return struct.unpack("<f", rpm(a, 4))[0]


def okp(p):
    return 0x10000 <= p < 0x7FFFFFFFFFFF


def fstr(p):
    try:
        data, num, mx = struct.unpack("<QII", rpm(p, 16))
    except OSError:
        return None
    if num > 0x400 or mx > 0x1000 or num > mx or not okp(data):
        return None
    if num == 0:
        return ""
    try:
        return rpm(data, 2 * num).decode("utf-16-le", "replace").split("\x00")[0]
    except OSError:
        return None


# ---- GNames ----
BLOCKS0 = core + BLOCKS_RVA
CB = u32(BLOCKS0 - 8)
CUR = u32(BLOCKS0 - 4)
IDS = {}
for B in range(CB + 1):
    blk = u64(BLOCKS0 + 8 * B)
    if blk < 0x10000:
        continue
    size = 0x20000 if B != CB else min(CUR, 0x20000)
    try:
        data = rpm(blk, size)
    except OSError:
        continue
    off = 0
    while off + 2 <= size:
        hdr = struct.unpack_from("<H", data, off)[0]
        ln = hdr >> 6
        if ln == 0 or ln > 1023:
            break
        wide = hdr & 1
        nb = ln * (2 if wide else 1)
        if off + 2 + nb > size:
            break
        raw = data[off + 2: off + 2 + nb]
        nm = (raw.decode("utf-16-le", "replace") if wide
              else raw.decode("latin-1", "replace")).split("\x00")[0]
        IDS[(B << 16) | (off >> 1)] = nm
        off += (2 + nb + 1) & ~1
say("names: %d" % len(IDS))


def oname(o):
    try:
        return IDS.get(u32(o + 0x18), "?")
    except OSError:
        return "?"


def supers(c, limit=14):
    chain = []
    cur = c
    for _ in range(limit):
        if not okp(cur):
            break
        chain.append((cur, oname(cur)))
        try:
            cur = u64(cur + 0x40)
        except OSError:
            break
    return chain


def class_props(cls):
    out = []
    for c, cn in supers(cls):
        try:
            cp = u64(c + 0x50)
        except OSError:
            continue
        guard = 0
        while okp(cp) and guard < 400:
            try:
                nm = IDS.get(u32(cp + 0x28), "?")
                off = u32(cp + 0x4C)
            except OSError:
                break
            out.append((nm, off, cn))
            try:
                cp = u64(cp + 0x20)
            except OSError:
                break
            guard += 1
    return out


# ---- GObjects scan ----
gua = u64(game + GUA_IAT_RVA)
ctab = u64(gua + 0x10)
cnt = u32(gua + 0x24)
say("GUA 0x%X cnt=%d" % (gua, cnt))
cls_cache = {}
altfire_hits = []
pawns = []
imc = []
buf = None
cur_ch = -1
for i in range(cnt):
    ch = i >> 16
    if ch != cur_ch:
        cur_ch = ch
        cbase = u64(ctab + 8 * ch)
        buf = None
        if okp(cbase):
            try:
                buf = rpm(cbase, 65536 * 24)
            except OSError:
                buf = None
    if buf is None:
        continue
    off = (i & 0xFFFF) * 24
    flags = struct.unpack_from("<I", buf, off + 8)[0]
    if flags & 0x20000000:
        continue
    obj = struct.unpack_from("<Q", buf, off)[0]
    if not okp(obj):
        continue
    try:
        nm = IDS.get(u32(obj + 0x18))
        if not nm:
            continue
        c = u64(obj + 0x10)
        cn = IDS.get(u32(c + 0x18), "?") if okp(c) else "?"
    except OSError:
        continue
    key = c
    if key not in cls_cache:
        chain = supers(c)
        names = {x[1] for x in chain}
        cls_cache[key] = names
    names = cls_cache[key]
    if "AltFireComponent" in names:
        altfire_hits.append((obj, nm, cn))
    if "InteractionManagerComponent" in names and not nm.startswith("Default__"):
        imc.append((obj, nm, cn))
    if ("BasePlayerCharacter" in names or "PlayerCharacter" in cn) \
            and not nm.startswith("Default__") and "Character" in cn:
        pawns.append((obj, nm, cn))
say("altfire_hits=%d pawns=%d imc=%d" % (len(altfire_hits), len(pawns), len(imc)))
for obj, nm, cn in altfire_hits[:12]:
    say("  AF obj=0x%X name=%s class=%s" % (obj, nm, cn))
for obj, nm, cn in imc[:12]:
    try:
        outer = u64(obj + 0x20)
        own = fstr(obj + 0x118)
        say("  IMC obj=0x%X name=%s class=%s outer=0x%X(%s) 118=%r"
            % (obj, nm, cn, outer, oname(outer), own and own[:60]))
    except OSError as e:
        say("  IMC 0x%X read fail %s" % (obj, e))
for obj, nm, cn in pawns[:6]:
    say("  PAWN obj=0x%X name=%s class=%s" % (obj, nm, cn))
    try:
        pl = class_props(u64(obj + 0x10))
        oc = [(n, o) for n, o, c in pl if n == "OwnedComponents"]
        say("    props=%d OwnedComponents=%s" % (len(pl), oc))
        if oc:
            off = oc[0][1]
            data = u64(obj + off)
            num = u32(obj + off + 8)
            say("    OwnedComponents data=0x%X num=%d" % (data, num))
            for k in range(min(num, 40)):
                cp = u64(data + 16 * k)
                if not okp(cp):
                    continue
                ccn = oname(u64(cp + 0x10)) if okp(u64(cp + 0x10)) else "?"
                say("      comp[%02d] 0x%X %s (%s)" % (k, cp, oname(cp), ccn))
    except OSError as e:
        say("    pawn read fail %s" % e)
say("done")
